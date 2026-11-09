"""Original AutoLens statements with native-output observation; no global tracing."""
import argparse,ast,copy,hashlib,inspect,json,math,os,re,shutil,sys,time,traceback
from pathlib import Path
from engine_io import write_json
from native_sources import load_autolens,verify_autolens
from official_autolens import normalize,program_for,cra_input,apply_native_cra
class StopRequested(BaseException):pass

class NativeOutput:
    """Forward original text, observing only completed output writes."""
    def __init__(self,stream,observe):self.stream=stream;self.observe=observe
    def write(self,text):
        value=self.stream.write(text)
        self.observe(str(text))
        return value
    def flush(self):return self.stream.flush()
    def __getattr__(self,key):return getattr(self.stream,key)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--params',required=True);ap.add_argument('--run-dir',required=True);a=ap.parse_args()
    p=json.loads(Path(a.params).read_text(encoding='utf-8'));out=Path(a.run_dir).resolve();out.mkdir(parents=True,exist_ok=True)
    os.environ.update(MPLBACKEND='Agg',MPLCONFIGDIR=str(out/'mpl_cache'))
    state=dict(engine='autolens',status='starting',params=p,stage='init',iter=0,history=[],files=[],error=None)
    cwd=Path.cwd();stdout,stderr=sys.stdout,sys.stderr;env={};audit={};native_dir=None;last=0.;start=time.monotonic();recent=[]
    calls={};arguments={};cra_events=[];cra_reports={};pending=None;last_history=None;copied={}
    def save():
        state['files']=[f.name for f in out.iterdir() if f.is_file()];write_json(out/'progress.json',state)
    def mirror(path):
        path=Path(path).resolve()
        if native_dir is None or not path.is_relative_to(native_dir) or not path.is_file():return
        rel=path.relative_to(native_dir)
        if len(rel.parts)==1 and rel.name.startswith('iter'):rel=Path('curriculum')/rel
        stat=path.stat();key=(stat.st_size,stat.st_mtime_ns)
        target=out/rel
        if copied.get(rel.as_posix())==key:return
        target.parent.mkdir(parents=True,exist_ok=True)
        if path!=target:shutil.copyfile(path,target)
        copied[rel.as_posix()]=key
        if path.suffix=='.json':
            try:
                raw=path.read_bytes();data=json.loads(raw)
                if data.get('surfaces'):
                    from saved_metrics import from_json
                    state['native_recorded']=dict(foclen=data.get('foclen'),fnum=data.get('fnum'))
                    state['native_preview']=from_json(data,rel.as_posix(),hashlib.sha256(raw).hexdigest())
            except (OSError,ValueError):pass
    def image():
        if pending:
            for suffix in ('.png','.png.png'):
                candidate=Path(str(pending.with_suffix(''))+suffix)
                if candidate.is_file():mirror(candidate)
    def configure_cra(model,stage):
        record=apply_native_cra(model,cra_input(p));record['stage']=stage;cra_events.append(record)
        write_json(out/'native_constraint_inputs.json',dict(cra_settings=cra_events,meaning='native parameter input, unchanged loss formula'))
    def observe(text):
        nonlocal native_dir,last,pending,recent,last_history
        if env.get('result_dir'):native_dir=Path(env['result_dir']).resolve()
        now=time.monotonic();safe=False
        written=re.search(r'Lens written to ([^\r\n]+\.json)',text)
        if written:
            name=written.group(1).strip();candidate=Path(name)
            if not candidate.is_file():
                match=re.search(r'results[/\\].*',name)
                candidate=out/match.group(0).replace('\\','/') if match else out/Path(name.replace('\\','/')).name
            if candidate.is_file():pending=candidate;mirror(candidate);image();safe=True
        spot=re.search(r'RMS radius:\s*FoV \(0\.0\) ([\d.eE+-]+) um, FoV \(0\.5\) ([\d.eE+-]+) um, FoV \(1\.0\) ([\d.eE+-]+) um',text)
        if spot and state.get('native_preview'):
            values=[float(v)/1000 for v in spot.groups()]
            state['native_preview'].update(rms_spot_mm=sum(values)/3,design_field_count=3,
                rms_definition='native analysis_spot log: polychromatic pooled centroid, mean of 0/.5/1 radial fields',display_kind='native_analysis')
            write_json(out/'native_preview.json',state['native_preview'])
        if re.search(r'(?:Curriculum|Progress|Optimizing|Optimization|Optimize)',text,re.I):
            iteration=re.search(r'(\d+)\s*/\s*(\d+)',text)
            if iteration:
                safe=True;number=int(iteration.group(1));state['iter']=number
                recent.append((number,now));recent=recent[-81:]
                distinct=[v for i,v in enumerate(recent) if i==0 or v[0]!=recent[i-1][0]]
                if len(distinct)>1 and distinct[-1][1]>distinct[0][1]:state['it_per_s']=(distinct[-1][0]-distinct[0][0])/(distinct[-1][1]-distinct[0][1])
                for key in ('loss_rms','loss_reg','loss_distortion'):
                    match=re.search(key+r'=([\d.eE+-]+)',text)
                    if match:state['loss_dist' if key=='loss_distortion' else key]=float(match.group(1))
                signature=(state['stage'],number)
                if number and signature!=last_history and number%max(1,int(state.get('total_iters',1))//1000)==0 and 'loss_rms' in state:
                    state['history'].append(dict(stage=state['stage'],iter=number,**{k:state.get(k) for k in ('loss_rms','loss_reg','loss_dist')}));last_history=signature
                if cra_input(p) is not None and env.get('lens') is not None:
                    model=env['lens'];cap=float(model.sensor_cra_cap)
                    if abs(cap-cra_input(p))>1e-10:raise RuntimeError('原生CRA输入被重置')
                    row=cra_reports.setdefault(state['stage'],dict(native_progress_reports=0,sensor_cra_cap_deg=cap,effective_thresholds_deg=[]))
                    row['native_progress_reports']+=1
                    threshold=float(model.chief_ray_angle_max)
                    if threshold not in row['effective_thresholds_deg']:row['effective_thresholds_deg'].append(threshold)
        if safe and env.get('lens') is not None and (out/'stop.flag').exists():raise StopRequested()
        if now-last>.5:last=now;image();save()
    try:
        cfg=normalize(p);state['params']=p;state['target']=dict(efl_mm=cfg['foclen'],full_fov_deg=cfg['fov'],fnum=cfg['fnum'],bfl_mm=cfg['bfl'],initial_track_mm=cfg['thickness'])
        if cra_input(p) is not None:state['target']['cra_cap_deg']=cra_input(p)
        save();module=load_autolens();module.MOBILE_CONFIG=copy.deepcopy(cfg);env=module.__dict__;env['__resume_path']=p.get('resume_lens');env['__apply_native_cra']=configure_cra
        statements,audit=program_for(p,split=True);audit['source']=verify_autolens();audit['config']=cfg
        audit['observer']=dict(mechanism='native stdout/stderr + completed JSON/PNG; no setprofile/settrace',counts_scope='top-level native calls and output reports, not internal optical call counts')
        sys.stdout=NativeOutput(stdout,observe);sys.stderr=NativeOutput(stderr,observe);os.chdir(out)
        for code,text in statements:
            tree=ast.parse(text).body[0];call=tree.value if isinstance(tree,(ast.Expr,ast.Assign)) else None
            if isinstance(call,ast.Call):
                name=call.func.attr if isinstance(call.func,ast.Attribute) else call.func.id if isinstance(call.func,ast.Name) else ''
                if name in ('curriculum_design','optimize'):
                    method=eval(compile(ast.Expression(call.func),'<native-call-binding>','eval'),env)
                    # Pinned main training kwargs are side-effect-free config reads.
                    kw={k.arg:eval(compile(ast.Expression(k.value),'<native-input-binding>','eval'),env) for k in call.keywords}
                    bound=inspect.signature(method).bind(**kw);bound.apply_defaults()
                    arguments[name]={k:bound.arguments[k] for k in ('iterations','spp','num_ring','num_arm','lrs','optim_mat','shape_control','centroid','sample_more_off_axis','depth','wvln_list') if k in bound.arguments}
                    state.update(status='running',stage='curriculum' if name=='curriculum_design' else 'refine',iter=0,total_iters=kw['iterations']+1,native_config_budget=kw['iterations']);recent=[];save()
                if name and not name.startswith('__'):calls[name]=calls.get(name,0)+1
            exec(code,env)
            if env.get('device') is not None:state['compute_device']=str(env['device'])
        sys.stdout,sys.stderr=stdout,stderr
        lens=env['lens'];native_dir=Path(env['result_dir']).resolve()
        for path in native_dir.rglob('*'):
            if path.is_file():mirror(path)
        audit.update(native_calls=calls,native_arguments=arguments,runtime_device=state.get('compute_device'),source=verify_autolens(),loss_function_replaced=False,optimizer_replaced=False,scheduler_replaced=False,
                     cra_input_events=cra_events,cra_progress_observations=cra_reports)
        write_json(out/'source_execution.json',audit)
        from deeplens import GeoLens
        from common_metrics import evaluate
        import torch
        independent=GeoLens(filename=str(out/'final_lens.json'),device=torch.device('cpu'))
        metrics=evaluate(independent,cfg['fov'],float(independent.obj_depth),independent.wvln_ls,independent.wvln_primary,64)
        state.update(status='finished',metrics_final=metrics,metrics_current=metrics,native_results=str(native_dir.relative_to(out)),layouts=[f.name for f in out.glob('final_lens*.png')])
        write_json(out/'requirements_validation.json',dict(passed=True,scope='native input and execution integrity only; not measured optical acceptance',official_main_unchanged=audit['main_ast_unchanged'],optical_acceptance=None))
        save();write_json(out/'summary.json',dict(params=p,status='finished',metrics_final=metrics,source_execution=audit));return 0
    except (Exception,StopRequested) as exc:
        sys.stdout,sys.stderr=stdout,stderr
        if isinstance(exc,StopRequested):
            state.update(status='stopped',error=None);lens=env.get('lens')
            if lens is not None:
                lens.write_lens_json(str(out/'stopped_lens.json'));state['snapshot_source']='stopped_lens.json'
                write_json(out/'snapshot_state.json',dict(engine='autolens',stage=state['stage'],iteration=state['iter'],optimizer_state_saved=False))
        else:state.update(status='failed',error=traceback.format_exc());print(state['error'],flush=True)
        audit.update(native_calls=calls,native_arguments=arguments,runtime_device=state.get('compute_device'),source=verify_autolens(),stopped=state['status']=='stopped',cra_input_events=cra_events,cra_progress_observations=cra_reports)
        write_json(out/'source_execution.json',audit);save();return 0 if state['status']=='stopped' else 1
    finally:sys.stdout,sys.stderr=stdout,stderr;os.chdir(cwd)
if __name__=='__main__':raise SystemExit(main())
