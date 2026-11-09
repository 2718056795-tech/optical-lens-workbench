"""Run library helpers. V3 is read only; imports are independent V4 copies."""
import json
import shutil
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IMPORT_LOCK = threading.Lock()


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return default


def run_record(run_dir, run_id):
    p = read_json(run_dir / "progress.json", {})
    params = read_json(run_dir / "params.json", {})
    if (run_dir/'archive_origin.json').is_file():
        params=dict(params)
        for key in ('resume_reference','resume_lens'):params.pop(key,None)
        p=dict(p,params=params)
    if not p:
        summary = read_json(run_dir / "summary.json", {})
        p = dict(summary, status="finished" if (run_dir/"final_lens.json").is_file() else "unknown")
    else:
        p = dict(p)
    p["files"] = sorted(f.name for f in run_dir.iterdir() if f.is_file())
    batch = read_json(run_dir / "screening.json")
    if batch:
        p["batch"] = batch
    if p.get("status") in ("starting", "running", "init"):
        p["status"] = "interrupted"
    return {"has_job": True, "run_id": run_id, "running": False,
            "params": params, "progress": p}


def library(offset=0,limit=None):
    result = []
    for source, base in (("v7", ROOT/"runs"),):
        if not base.is_dir():
            continue
        def updated(p):
            return max([p.stat().st_mtime]+[f.stat().st_mtime for f in (p/'progress.json',p/'params.json') if f.is_file()])
        directories = sorted((p for p in base.iterdir() if p.is_dir() and not p.name.startswith('.') and (p/'params.json').is_file()),key=lambda p:(updated(p),p.name),reverse=True)
        for p in directories:
            if p.name.startswith('.'):continue
            if not (p/"params.json").is_file():
                continue
            params = read_json(p/"params.json", {})
            progress = read_json(p/"progress.json", {})
            archive=read_json(p/'archive_origin.json',{})
            result.append({"run_id": p.name, "source": source,
                           "foclen": params.get("foclen"), "fnum": params.get("fnum"),
                           "fov": params.get("fov"), "engine": params.get("engine", "autolens"),
                           "status": progress.get("status", "unknown"),
                           "reference": bool(params.get("reference")), "label": ('档案 · '+(archive.get('original_run_id') or p.name)) if archive else params.get("label"),
                           "has_final": (p/"final_lens.json").is_file(),
                           "multiseed": bool(params.get("seeds"))})
    offset=int(offset)
    if offset<0:raise ValueError('历史偏移不能为负数')
    if limit is not None:
        limit=int(limit)
        if not 1<=limit<=1000:raise ValueError('每页历史数量须为1～1000')
    return result[offset:] if limit is None else result[offset:offset+limit]


def import_v3(run_id):
    if not isinstance(run_id, str) or not run_id or any(c in run_id for c in ("/", "\\", ":", "..")):
        raise ValueError("运行路径非法")
    base = (ROOT.parent/"V3"/"runs").resolve()
    src = (base/run_id).resolve()
    if src.parent != base or not src.is_dir() or not (src/"params.json").is_file():
        raise ValueError("V3 运行不存在")
    # Do not copy an active/incomplete record, symlinks or control flags.
    progress = read_json(src/"progress.json", {})
    if progress.get("status") not in ("finished", "failed", "stopped"):
        raise ValueError("仅能导入已完成、失败或停止的 V3 运行")
    dst = ROOT/"runs"/("v3_"+run_id)
    with IMPORT_LOCK:
        if not dst.exists():
            tmp = dst.with_name(dst.name+".importing")
            if tmp.exists():
                raise ValueError("存在未完成的导入，请检查 .importing 目录")
            def ignore(directory, names):
                return [n for n in names if n in ("stop.flag", "__pycache__") or (Path(directory)/n).is_symlink()]
            shutil.copytree(src, tmp, ignore=ignore)
            (tmp/"import_origin.json").write_text(json.dumps({"source":"V3", "run_id":run_id}, ensure_ascii=False), encoding="utf-8")
            tmp.rename(dst)
    return dst.name


def prescription_file(run_dir,source=None):
    from prescription_store import resolve
    return resolve(run_dir,source)[0]
