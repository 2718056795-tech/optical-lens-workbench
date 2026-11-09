# -*- coding: utf-8 -*-
"""V7 local optical workbench server (Python stdlib HTTP server).

Serves the web UI and a small JSON API. The optimization itself runs in a
separate child process (optimizer_runner.py) so the UI stays responsive and
progress can be polled in real time.

Usage:
    python app.py            # serve and open the browser
    python app.py --port N
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote, parse_qs
from engine_routing import worker_for, engine_error, apply_route
from glass_selection import resolve_selection
from parameter_rules import check_and_resolve

V2_ROOT = Path(__file__).resolve().parent
WEB_DIR = V2_ROOT / "web"
RUNS_DIR = V2_ROOT / "runs"
PY_EXE = sys.executable

JOB = {"run_id": None, "proc": None, "run_dir": None, "params": None,
       "started_at": None}
JOB_LOCK = threading.Lock()
SERVER_CLOSING=False
ACTIVE_FILE_OPERATIONS=0

def analysis_running():
    service=sys.modules.get('analysis_service')
    if service is None:return False
    with service.LOCK:return any(j['proc'].poll() is None for j in service.JOBS.values())


def json_body(handler, max_len=65536):
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0 or length > max_len:
        return None
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def job_state():
    """Snapshot of current/previous job for the UI."""
    if JOB["run_id"] is None:
        return {"has_job": False,"running":False,"analysis_running":analysis_running(),"file_operation_running":ACTIVE_FILE_OPERATIONS>0}
    run_dir = Path(JOB["run_dir"])
    st = {"has_job": True, "run_id": JOB["run_id"],
          "started_at": JOB["started_at"], "params": JOB["params"]}
    proc = JOB["proc"]
    if proc is not None and proc.poll() is None:
        st["running"] = True
        st["exit_code"] = None
    else:
        st["running"] = False
        st["exit_code"] = proc.poll() if proc is not None else None
    pj = run_dir / "progress.json"
    if pj.is_file():
        try:
            st["progress"] = json.loads(pj.read_text(encoding="utf-8"))
        except Exception:
            st["progress_error"] = "progress.json unreadable (writing...)"
    if not st["running"] and st.get("progress",{}).get("status") in ("starting","init","running"):
        progress=st["progress"]
        progress["status"]="failed" if st["exit_code"] not in (None,0) else "interrupted"
        progress["error"]=progress.get("error") or f"工作进程已退出（退出码 {st['exit_code']}），未保存正常结束状态，请查看 worker.log"
    st['stopping']=st['running'] and (run_dir/'stop.flag').exists()
    if (run_dir/'stop_request.json').is_file():
        try:st['stop_request']=json.loads((run_dir/'stop_request.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):pass
    st['analysis_running']=analysis_running()
    st['file_operation_running']=ACTIVE_FILE_OPERATIONS>0
    return st


def validate_params(p):
    """Basic sanity checks; returns error string or None."""
    if not isinstance(p,dict):return "请求参数必须是JSON对象"
    if (p.get('route') or p.get('engine','autolens'))=='autolens':
        try:
            if p.get('resume_lens'):return '续算仅接受已保存处方引用，不接受任意文件路径'
            p['resume_phase']=p.get('resume_reference',{}).get('phase') if isinstance(p.get('resume_reference'),dict) else None
            error=apply_route(p)
            if error:return error
            from official_autolens import normalize
            normalize(p)
            return None
        except (ValueError,TypeError,KeyError,OverflowError) as exc:return str(exc)
    if p.get('seeds') not in (None,'',[]) or p.get('candidate_count') is not None or p.get('_single_pipeline'):
        return 'V7只运行一次所选内核，已取消候选数量与初筛；请刷新页面'
    if p.get('refinement_mode') not in (None,'','direct') or p.get('polish_refine_iters') not in (None,'',0,'0'):
        return 'V7已取消人工选择与追加精修，请使用两条直接优化路线'
    p['workflow_mode']='direct-v1' 
    error = apply_route(p) or check_and_resolve(p) or engine_error(p)
    if error: return error
    try:
        p["glass_selection"] = resolve_selection(p)
        p["glass_policy"] = p["glass_selection"]["policy"]
        p["glass_catalog_revision"] = p["glass_selection"]["revision"]
        if p["glass_policy"] == "custom":
            p["allowed_glasses"] = p["glass_selection"]["allowed_glasses"]
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return str(exc)
    if p.get("refine_engine") == "optiland":
        future = dict(p, optim_mat=False, prune=False, device="cpu")
        error = engine_error(future, "optiland")
        if error: return "精修路线：" + error
    def num(k, lo, hi, default=None):
        v = p.get(k, default)
        if v in (None, ""):
            return default if default is not None else f"missing {k}"
        try:
            v = float(v)
        except (TypeError, ValueError):
            return f"{k} 不是数字"
        if not (lo <= v <= hi):
            return f"{k} 需在 {lo}~{hi} 之间"
        return None

    for k, lo, hi in [("foclen", 0.5, 500), ("fov", .001 if p.get('requirements') else 2, 150),
                      ("fnum", 0.7, 22), ("bfl", 0.01, 200),
                      ("curriculum_iters", 0, 20000),
                      ("refine_iters", 0, 20000)]:
        err = num(k, lo, hi, default={"curriculum_iters": 600,
                                      "refine_iters": 300}.get(k))
        if isinstance(err, str):
            return err
    t = p.get("thickness")
    if t not in (None, ""):
        try:
            if not (2 <= float(t) <= 1000):
                return "thickness 需在 2~1000 mm"
        except (TypeError, ValueError):
            return "thickness 不是数字"
    if not 1<=int(p.get("elements",4))<=16:
        return "elements 需在 1~16"
    sp = p.get("stop_pos", "middle")
    if sp not in ("front", "middle", "back"):
        try:
            k = int(sp)
            if k < 0 or k > int(p.get('elements',4)):
                return "stop_pos 非法"
        except (TypeError, ValueError):
            return "stop_pos 非法"
    if p.get("device", "auto") not in ("auto", "cpu", "cuda"):
        return "device 非法"
    # ---- 新增可选参数（留空跳过）----
    opt_ranges = {
        "imgh": (0.1, 100), "obj_depth": (0.1, 1e9),
        "wvln_b": (0.3, 1.2), "wvln_g": (0.3, 1.2), "wvln_r": (0.3, 1.2),
        "cra_cap": (0.2, 89), "distortion_max": (0.001, 1.0),
        "bfl_min": (0.01, 500), "bfl_max": (0.01, 500),
        "ttl_min": (0.1, 2000), "ttl_max": (0.1, 2000),
        "air_edge_min": (0.001, 100), "air_edge_max": (0.001, 200),
        "air_center_min": (0.001, 100), "air_center_max": (0.001, 200),
        "thick_edge_min": (0.01, 100), "thick_edge_max": (0.01, 200),
        "thick_center_min": (0.01, 100), "thick_center_max": (0.01, 200),
        "sag2diam_max": (0.01, 2.0), "diam2thick_max": (1, 100),
        "tmax2tmin_max": (1, 100), "surf_angle_max": (1, 89),
        "bend_angle_max": (1, 89),
        "w_dist": (0, 100), "scale_pupil": (0.5, 2.0),
        "num_ring": (1, 32), "spp": (4, 4096),
        "w_cra": (0, 100), "w_ray_bend": (0, 100), "w_clearance": (0, 100),
        "w_envelope": (0, 100), "w_profile": (0, 100),
    }
    for k, (lo, hi) in opt_ranges.items():
        v = p.get(k)
        if v in (None, ""):
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return f"{k} 不是数字"
        if not (lo <= fv <= hi):
            return f"{k} 需在 {lo}~{hi} 之间"
    if p.get("centroid", "auto") not in ("auto", "centroid", "pinhole"):
        return "centroid 非法"
    if p.get('engine','autolens')=='autolens':
        if p.get('scale_pupil') not in (None,'') and abs(float(p['scale_pupil'])-1.05)>1e-12:
            return '原生AutoLens课程光瞳采样裕量固定为1.05；本版不覆盖官方课程参数'
        budget=float(p.get('curriculum_iters') or 0)
        if 0<budget<4:return '原生AutoLens课程学习预算需为0或至少4'
        weights=[f['weight'] for f in p.get('requirements',{}).get('fields',[])]
        if weights and max(weights)-min(weights)>1e-12:return 'AutoLens保留原生自适应视场权重；指定非等权视场请使用Optiland'
    if p.get("glass_table", "CDGM") not in ("CDGM", "SCHOTT", "OHARA"):
        return "glass_table 非法"
    if p.get("by_imgh") in (True, "1", "true") and p.get("imgh") in (None, ""):
        return "选择按像高设计时必须填写像高"
    if p.get("resume_lens"):
        return "续算处方请通过导入SEQ/ZMX并选择沿用原结构，不接受任意文件路径"
    try:
        seed=str(p.get("seed",42)).strip()
        if not seed.isdecimal() or not 0<=int(seed)<2**32:return "内部随机状态非法"
        if int(p.get('curriculum_iters') or 0)+int(p.get('refine_iters') or 0)<1 and not (isinstance(p.get('resume_reference'),dict) and p['resume_reference'].get('phase')=='finalize'):
            return '至少设置一个优化阶段的预算；原结构续算可将初始阶段设为0'
    except (ValueError,TypeError):return "预算格式非法"
    return None


def spawn_job(p, worker):
    with JOB_LOCK:
        if SERVER_CLOSING:raise RuntimeError('程序正在退出，未启动任务')
        if JOB["proc"] is not None and JOB["proc"].poll() is None:
            raise RuntimeError("已有优化任务在运行，请先停止")
        run_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")+"_"+str(os.getpid())
        run_dir = RUNS_DIR/run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        params_path = run_dir/"params.json"
        p['_workflow_worker']=worker
        params_path.write_text(json.dumps(p,ensure_ascii=False,indent=1),encoding="utf-8")
        with (run_dir/"worker.log").open("w",encoding="utf-8") as log:
            proc = subprocess.Popen(
                [PY_EXE,"-B",str(V2_ROOT/'workflow_runner.py'),"--params",str(params_path),"--run-dir",str(run_dir)],
                cwd=str(V2_ROOT),env=dict(os.environ,PYTHONDONTWRITEBYTECODE="1"),
                stdout=log,stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        JOB.update(run_id=run_id,proc=proc,run_dir=str(run_dir),params=p,
                   started_at=dt.datetime.now().astimezone().isoformat())
        return {"run_id":run_id,"run_dir":str(run_dir)}


def safe_run_dir(reference):
    if not isinstance(reference,str) or not reference or ".." in reference or "\\" in reference:
        raise ValueError("运行路径非法")
    p=(RUNS_DIR/reference).resolve()
    if RUNS_DIR.resolve() not in p.parents:
        raise ValueError("运行路径非法")
    return p


class Handler(BaseHTTPRequestHandler):
    server_version = "V7Workbench/1.0"

    def log_message(self, fmt, *args):  # quiet console
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def do_GET(self):
        url = urlparse(self.path)
        path = unquote(url.path)
        if path in ("/", "/index.html"):
            f = WEB_DIR / "index.html"
            if f.is_file():
                self._send(200, f.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(404, "index.html missing")
            return
        if path in ("/web/workbench.css", "/web/glass.css", "/web/light-results.css", "/web/analysis-suite.css", "/web/analysis-suite.js", "/web/seq-import.js", "/web/seq-import.css", "/web/controls.js", "/web/workbench.js", "/web/glass-ui.js", "/web/viewer3d.js", "/web/requirements.css", "/web/requirements-ui.js", "/web/design-import.js", "/web/desktop-theme.css", "/web/desktop-toolbar.js"):
            f = WEB_DIR / path.rsplit("/", 1)[-1]
            ctype = "text/css; charset=utf-8" if f.suffix == ".css" else "text/javascript; charset=utf-8"
            self._send(200, f.read_bytes(), ctype)
            return
        if path == "/api/analysis-catalog":
            from analysis_catalog import catalog_payload
            self._send_json(200,catalog_payload())
            return
        if path == "/api/analysis-protocol":
            self._send_json(200,dict(protocol='analysis-engines-v2',engine_field=True,pipeline_engine_selection=True,object_view_toggle=True,stop_continue=True,official_autolens=True,native_cra_input=True,native_optiland_inputs=True,workbench_version='10.0.0',backend_pid=os.getpid(),safe_exit=True))
            return
        if path == "/api/analysis-state":
            try:
                import analysis_service
                self._send_json(200,analysis_service.state(parse_qs(url.query).get('job_id',[''])[0]))
            except (ValueError,OSError) as exc:self._send_json(400,{'error':str(exc)})
            return
        if path == "/api/library":
            import workspace_api
            try:
                query=parse_qs(url.query);limit=query.get('limit',[None])[0]
                self._send_json(200, {"runs": workspace_api.library(query.get('offset',[0])[0],limit)})
            except (ValueError,OSError) as exc:self._send_json(400,dict(error=str(exc)))
            return
        if path == "/api/glasses":
            try:
                from glass_selection import public_catalog
                query = parse_qs(url.query)
                catalog = query.get("catalog", ["CDGM"])[0]
                self._send_json(200, public_catalog(catalog,query.get("revision",[None])[0]))
            except (ValueError, OSError) as exc:
                self._send_json(400, {"error":str(exc)})
            return
        if path in ("/api/record", "/api/lens", "/api/log"):
            try:
                ref = parse_qs(url.query).get("run", [""])[0]
                run_dir = safe_run_dir(ref)
                if not run_dir.is_dir():
                    raise FileNotFoundError("运行不存在")
                import workspace_api
                if path == "/api/record":
                    if ref == JOB["run_id"]:
                        result = job_state()
                    else:
                        result = workspace_api.run_record(run_dir, ref)
                elif path == "/api/lens":
                    from lens_scene import build_scene
                    from prescription_store import resolve,list_snapshots
                    selected,data,digest=resolve(run_dir,parse_qs(url.query).get('source',[None])[0])
                    if data.get('optiland_native_source'):
                        from model_io_service import scene
                        result=scene(run_dir,selected.relative_to(run_dir.resolve()).as_posix(),digest)
                    else:result = build_scene(selected)
                    result['source']=selected.relative_to(run_dir.resolve()).as_posix()
                    result['source_sha256']=digest;result['snapshots']=list_snapshots(run_dir)
                    from saved_metrics import for_scene
                    result['saved_metrics']=for_scene(run_dir,result['source'],data,digest)
                    progress_file=run_dir/'progress.json'
                    try:recorded=json.loads(progress_file.read_text(encoding='utf-8'))
                    except (OSError,ValueError):recorded={}
                    bound=recorded.get('metrics_source') or {}
                    if bound.get('source_file')==result['source'] and bound.get('source_sha256')==digest:
                        measured=recorded.get('metrics_final') or recorded.get('metrics_current')
                        if measured:result['saved_metrics']=dict(measured,source_file=result['source'],source_sha256=digest,display_kind='independently_recorded')
                    from snapshot_display import describe
                    result['snapshot_layout']=describe(run_dir,result['source'],digest)
                    from result_comparison import compare
                    try:original_params=json.loads((run_dir/'params.json').read_text(encoding='utf-8'))
                    except (OSError,ValueError):original_params={}
                    result['comparison']=compare(original_params,result['saved_metrics'],result['source'],digest)
                    result['analysis_engines']=['optiland'] if data.get('optiland_native_source') else ['autolens','optiland']
                    result['native_import']=bool(data.get('optiland_native_source'))
                    result["run_id"] = ref
                else:
                    f = run_dir/"worker.log"
                    if f.is_file():
                        with f.open("rb") as stream:
                            stream.seek(max(0, f.stat().st_size-24000))
                            log = stream.read().decode("utf-8", errors="replace")
                    else:
                        log = "尚无运行日志"
                    result = {"run_id":ref, "text":"\n".join(log.splitlines()[-120:])}
                self._send_json(200, result)
            except FileNotFoundError as exc:
                self._send_json(404, {"error":str(exc)})
            except (ValueError, OSError, KeyError, TypeError) as exc:
                self._send_json(400, {"error":str(exc)})
            return
        if path == "/api/state":
            self._send_json(200, job_state())
            return
        if path == "/api/capabilities":
            import torch  # noqa: F401  (deferred so UI works w/o torch too)
            self._send_json(200, {
                "cuda_available": torch.cuda.is_available(),
                "gpu_name": torch.cuda.get_device_name(0)
                if torch.cuda.is_available() else None,
                "python": sys.version.split()[0],
                "optimization_engines": ["autolens", "optiland"],
                "optiland_device": "cpu",
            })
            return
        if path == "/api/export":
            q = parse_qs(url.query)
            run_id = q.get("run", [""])[0]
            fmt = q.get("fmt", [""])[0]
            if fmt not in ("zmx", "seq") or not run_id or ".." in run_id:
                self._send_json(400, {"error": "参数非法"})
                return
            try:
                run_dir = safe_run_dir(run_id)
            except ValueError:
                self._send_json(400, {"error":"运行路径非法"})
                return
            try:
                from export_service import export
                from urllib.parse import quote
                data,name,sha=export(run_dir,fmt,q.get('source',[None])[0],q.get('sha256',[None])[0])
                self.send_response(200)
                self.send_header("Content-Type","application/octet-stream")
                self.send_header("Content-Disposition", "attachment; filename=\"lens."+fmt+"\"; filename*=UTF-8''"+quote(name))
                self.send_header("X-Prescription-SHA256",sha)
                self.send_header("Content-Length",str(len(data)));self.end_headers();self.wfile.write(data)
            except (ValueError,OSError,subprocess.TimeoutExpired) as exc:self._send_json(400,dict(error=str(exc)))
            return
        if path.startswith("/runs/"):
            rel = path[len("/runs/"):]
            parts = rel.split("/", 1)
            if len(parts) == 2 and parts[0] and ".." not in parts:
                try:
                    f = safe_run_dir(rel)
                except ValueError:
                    self._send_json(400, {"error":"文件路径非法"})
                    return
                if f.is_file() and f.suffix.lower() in (
                        ".png", ".json", ".txt", ".csv", ".npz", ".log", ".seq", ".zmx", ".agf"):
                    ctype = "image/png" if f.suffix.lower() == ".png" \
                        else "application/json; charset=utf-8" if f.suffix.lower()=='.json' else "application/octet-stream" if f.suffix.lower() in ('.npz','.csv') else "text/plain; charset=utf-8"
                    self._send(200, f.read_bytes(), ctype)
                    return
            self._send_json(404, {"error": "not found"})
            return
        self._send_json(404, {"error": "unknown route"})

    def do_POST(self):
        global SERVER_CLOSING,ACTIVE_FILE_OPERATIONS
        url = urlparse(self.path)
        if SERVER_CLOSING and url.path not in ('/api/host-exit','/api/stop'):
            self._send_json(409,dict(error='程序正在退出，请稍后重开'));return
        if url.path=='/api/host-cancel-analysis':
            json_body(self)
            service=sys.modules.get('analysis_service')
            if service is not None:service.close_workers()
            self._send_json(200,dict(ok=True));return
        if url.path=='/api/host-exit':
            body=json_body(self) or {}
            if body.get('backend_pid')!=os.getpid():self._send_json(409,dict(error='退出来源与本后台不一致'));return
            with JOB_LOCK:
                if JOB['proc'] is not None and JOB['proc'].poll() is None:
                    self._send_json(409,dict(error='任务仍在运行，须安全停止并保存后再退出'));return
                if ACTIVE_FILE_OPERATIONS:
                    self._send_json(409,dict(error='档案读写尚未完成，请等待后再退出'));return
                SERVER_CLOSING=True
            service=sys.modules.get('analysis_service')
            if service is not None:service.close_workers()
            self._send_json(200,dict(ok=True))
            threading.Thread(target=self.server.shutdown,daemon=True).start()
            return
        if url.path=='/api/results-open':
            with JOB_LOCK:
                if SERVER_CLOSING:
                    self._send_json(409,dict(error='程序正在退出，未读取档案'));return
                ACTIVE_FILE_OPERATIONS+=1
            try:
                body=json_body(self) or {}
                from result_archive import restore
                self._send_json(200,restore(body.get('folder'),RUNS_DIR))
            except (ValueError,OSError,KeyError,TypeError) as exc:self._send_json(400,dict(error=str(exc)))
            finally:
                with JOB_LOCK:ACTIVE_FILE_OPERATIONS-=1
            return
        if url.path=='/api/results-save':
            with JOB_LOCK:
                if SERVER_CLOSING:
                    self._send_json(409,dict(error='程序正在退出，未开始保存'));return
                ACTIVE_FILE_OPERATIONS+=1
            try:
                body=json_body(self) or {}
                folder=safe_run_dir(body.get('run_id',''))
                if not folder.is_dir():raise ValueError('运行记录不存在')
                from result_save import save_run
                self._send_json(200,save_run(folder,body.get('destination','')))
            except (ValueError,OSError) as exc:self._send_json(400,dict(error=str(exc)))
            finally:
                with JOB_LOCK:ACTIVE_FILE_OPERATIONS-=1
            return
        if url.path=='/api/requirements-inspect':
            body=json_body(self)
            error=validate_params(body)
            if error:self._send_json(400,dict(error=error))
            else:self._send_json(200,dict(requirements=body.get('requirements'),normalized_params=body,
                                        note='校核条件完整性与可建模性，不代表像质已经达标'))
            return
        if url.path in ('/api/design-import/inspect','/api/design-import/apply'):
            try:
                import base64,binascii
                import design_import
                body=json_body(self,max_len=3000000)
                if not isinstance(body,dict):raise ValueError('请求需为JSON对象')
                if url.path.endswith('/inspect'):
                    raw=base64.b64decode(body.get('data',''),validate=True)
                    from model_io_service import inspect_file
                    result=inspect_file(raw,str(body.get('filename','lens.seq')),int(body.get('configuration',1)))
                else:result=design_import.selected_patch(body.get('import_id'),body.get('sections',[]),body.get('mode'))
                self._send_json(200,result)
            except (ValueError,TypeError,OSError,IndexError,KeyError,OverflowError,binascii.Error) as exc:self._send_json(400,dict(error=str(exc)))
            return
        if url.path=='/api/seq-inspect':
            try:
                import base64,binascii
                from codev_import import inspect_seq
                body=json_body(self,max_len=1500000)
                if not isinstance(body,dict) or not isinstance(body.get('data'),str):raise ValueError('需要SEQ文件的base64内容')
                raw=base64.b64decode(body['data'],validate=True)
                self._send_json(200,inspect_seq(raw,str(body.get('filename','lens.seq'))))
            except (ValueError,TypeError,binascii.Error) as exc:self._send_json(400,{'error':str(exc)})
            return
        if url.path in ('/api/analysis-start','/api/analysis-cancel'):
            try:
                body=json_body(self,max_len=3000000) or {}
                if not isinstance(body,dict):raise ValueError('请求需为JSON对象')
                import analysis_service
                if url.path.endswith('cancel'):result=analysis_service.cancel(body.get('job_id',''))
                else:
                    run_id=body.get('run_id','')
                    result=analysis_service.start(safe_run_dir(run_id),run_id,body.get('analysis_id'),body.get('options'),body.get('image'),bool(body.get('force')),engine=body.get('engine','optiland'),source=body.get('source_file'),source_sha256=body.get('source_sha256'))
                self._send_json(200,result)
            except RuntimeError as exc:self._send_json(409,{'error':str(exc)})
            except (ValueError,OSError,TypeError) as exc:self._send_json(400,{'error':str(exc)})
            return
        if url.path == "/api/import-v3":
            body = json_body(self) or {}
            try:
                import workspace_api
                self._send_json(200, {"run_id":workspace_api.import_v3(body.get("run_id"))})
            except (ValueError, OSError, TypeError) as exc:
                self._send_json(400, {"error":str(exc)})
            return
        if url.path == "/api/refine":
            json_body(self)
            self._send_json(410,dict(error='V7已取消候选选择/追加精修。请导入处方并直接选择内核运行。'))
            return
        if url.path == '/api/native3d/open':
            try:
                body=json_body(self) or {}
                from native_3d_service import launch
                self._send_json(200,launch(safe_run_dir(body.get('run_id','')),body.get('engine'),body.get('source_file'),body.get('source_sha256'),body.get('ignore_object',True)))
            except (ValueError,OSError,TypeError) as exc:self._send_json(400,dict(error=str(exc)))
            return
        if url.path == '/api/design-import/analyze':
            try:
                body=json_body(self) or {}
                from design_import import create_analysis_record
                self._send_json(200,create_analysis_record(body.get('import_id'),RUNS_DIR))
            except (ValueError,OSError,TypeError,KeyError) as exc:self._send_json(400,dict(error=str(exc)))
            return
        if url.path == '/api/resume-prepare':
            try:
                body=json_body(self) or {}
                ref=body.get('run_id','');folder=safe_run_dir(ref)
                if JOB['run_id']==ref and JOB['proc'] is not None and JOB['proc'].poll() is None:raise ValueError('请先停止此任务再准备继续优化')
                from snapshot_resume import prepare
                self._send_json(200,prepare(folder,ref,body.get('source_file'),body.get('source_sha256')))
            except (ValueError,OSError,TypeError) as exc:self._send_json(400,dict(error=str(exc)))
            return
        if url.path == "/api/start":
            if SERVER_CLOSING:self._send_json(409,dict(error='程序正在退出，未启动任务'));return
            if JOB["proc"] is not None and JOB["proc"].poll() is None:
                self._send_json(409, {"error": "已有优化任务在运行，请先停止"})
                return
            p = json_body(self)
            if not p:
                self._send_json(400, {"error": "请求体不是合法 JSON"})
                return
            err = validate_params(p)
            if err:
                self._send_json(400, {"error": err})
                return
            try:
                from design_import import prepare_start
                prepare_start(p)
                from snapshot_resume import apply as apply_snapshot_resume
                apply_snapshot_resume(p,RUNS_DIR)
            except (ValueError,OSError) as exc:
                self._send_json(400,dict(error=str(exc)));return
            worker = worker_for(p)
            try:
                self._send_json(200, spawn_job(p,worker))
            except RuntimeError as exc:
                self._send_json(409, {"error":str(exc)})
            return
        if url.path == "/api/stop":
            body=json_body(self) or {}
            if body.get('run_id') and body['run_id']!=JOB['run_id']:
                self._send_json(409,dict(error='任务已变化，未停止其他任务'));return
            if JOB["run_dir"] and JOB['proc'] is not None and JOB['proc'].poll() is None:
                flag = Path(JOB["run_dir"]) / "stop.flag"
                flag.write_text("stop", encoding="utf-8")
                from engine_io import write_json
                request=dict(run_id=JOB['run_id'],requested_at=dt.datetime.now().astimezone().isoformat(),status='stopping')
                write_json(Path(JOB['run_dir'])/'stop_request.json',request)
                self._send_json(200, dict(ok=True,**request))
            else:
                self._send_json(400, {"error": "没有运行中的任务"})
            return
        if url.path == "/api/analysis":
            p = json_body(self)
            run_id = (p or {}).get("run_id", "")
            force = bool((p or {}).get("force"))
            try:
                run_dir = safe_run_dir(run_id)
            except ValueError:
                self._send_json(400, {"error": "run_id 非法"})
                return
            try:
                if (p or {}).get('engine','optiland')!='optiland':raise ValueError('旧版外层组合图仅属于Optiland；AutoLens请使用对应原生分析入口')
                from prescription_store import resolve,freeze
                chosen,_,digest=resolve(run_dir,(p or {}).get('source_file'),(p or {}).get('source_sha256'))
                source_name=chosen.relative_to(run_dir.resolve()).as_posix()
                ana_dir=run_dir/'analysis'/'legacy'/digest[:20]
                frozen=freeze(run_dir,source_name,ana_dir/'source_snapshot.json',digest)
                src=Path(frozen['source'])
            except (ValueError,OSError) as exc:self._send_json(400,dict(error=str(exc)));return
            cache = ana_dir / "analysis.json"
            if cache.is_file() and not force:
                try:
                    cached = json.loads(cache.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    cached = {}
                if cached.get("analysis_version") == 5 and cached.get("source_sha256")==digest:
                    cached["source_file"]=source_name
                    self._send_json(200, cached)
                    return
            try:
                from model_io_service import run as run_model_io
                result=run_model_io(dict(action='legacy',source=str(src),out_dir=str(ana_dir)),ana_dir/'worker_io')
                result.update(run_id=run_id,engine="optiland",source_file=source_name,source_sha256=digest,relative_dir=ana_dir.relative_to(run_dir).as_posix(),presentation="application legacy composition")
                payload = json.dumps(result, ensure_ascii=False)
                cache.write_text(payload, encoding="utf-8")
                self._send(200, payload)
            except Exception as e:
                self._send_json(500, {"error": f"分析失败: {type(e).__name__}: {e}"})
            return
        self._send_json(404, {"error": "unknown route"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8682)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    actual_port = httpd.server_address[1]
    url = f"http://127.0.0.1:{actual_port}/"
    print(f"V10 工作台已启动: {url}", flush=True)
    print("关闭本窗口即停止服务。", flush=True)
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if JOB["proc"] is not None and JOB["proc"].poll() is None:
            try:
                (Path(JOB["run_dir"]) / "stop.flag").write_text("stop")
                JOB["proc"].wait(timeout=10)
            except Exception:
                JOB["proc"].kill()
        httpd.server_close()


if __name__ == "__main__":
    main()
