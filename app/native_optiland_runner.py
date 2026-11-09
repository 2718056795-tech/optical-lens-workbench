"""Application operands/constraints around Optiland's native problem and solver."""
import argparse,copy,inspect,json,math,os,sys,time,traceback
from pathlib import Path
from types import MethodType
from native_sources import configure_optiland_runtime,verify_optiland
from engine_isolation import install,report as isolation_report
configure_optiland_runtime();install()
ROOT=Path(__file__).resolve().parent
os.environ.update(MPLBACKEND='Agg',MPLCONFIGDIR=str(ROOT/'runtime_cache/matplotlib'),NUMBA_CACHE_DIR=str(ROOT/'runtime_cache/numba'))

class OptilandStopRequested(BaseException):
    """Control signal that native operand failure fallbacks must not swallow."""

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--params',required=True);ap.add_argument('--run-dir',required=True);args=ap.parse_args()
    out=Path(args.run_dir);out.mkdir(parents=True,exist_ok=True);p=json.loads(Path(args.params).read_text(encoding='utf-8'))
    from engine_io import write_json
    state=dict(status='starting',engine='optiland',stage='init',params=p,history=[],layouts=[],error=None,iter=0,total_iters=0)
    def publish():write_json(out/'progress.json',state)
    publish();last_accepted_snapshot=None;on_native_update=None;next_cancel_check=0.
    StopRequested=OptilandStopRequested
    try:
        from parameter_rules import check_and_resolve
        error=check_and_resolve(p)
        if error:raise ValueError(error)
        from engine_routing import engine_error
        error=engine_error(p,'optiland')
        if error:raise ValueError(error)
        from optiland_native_inputs import normalize,configure_model,compatible_geometry
        normalize(p)
        import numpy as np
        from spectrum import resolve_spectrum,stamp_spectrum
        from glass_selection import resolve_selection,stamp_json,verify_prescription
        from design_contract import load
        from optiland_bridge import prescription_to_optiland
        from optiland_initialization import initialize
        from optiland_metrics import evaluate_snapshot
        from optiland.optimization import OptimizationProblem,LeastSquares
        selection=resolve_selection(p);p['glass_selection']=selection;contract=load(p);spectrum=resolve_spectrum(p);waves=spectrum['wavelengths_um'];primary=spectrum['primary_um']
        if p.get('resume_lens'):
            data=json.loads(Path(p['resume_lens']).read_text(encoding='utf-8'))
            if contract:contract.verify(data)
            model,_=prescription_to_optiland(p['resume_lens'],preserve_apertures=True)
            initialization=dict(engine='optiland',api='Optic + SurfaceGroup.add',recipe='imported-prescription',autolens_used=False)
            write_json(out/'initialization.json',initialization)
        else:data,model,initialization=initialize(p,out)
        configure_model(model,p)
        from optiland_native_catalog import register_selection,material
        aliases=register_selection(selection)
        if p['optiland_glass_mode']=='expert' and len(aliases)<2:raise ValueError('原生自动换玻璃至少需要2种可用牌号')
        for i,surface in enumerate(data['surfaces']):
            if surface.get('mat2','air')!='air':model.updater.set_material(material(surface['mat2'],selection),i+1)
        model.updater.update()
        data['optiland_inputs']={k:v for k,v in p.items() if k.startswith('optiland_')}
        data['optiland_material_model']='agf-formula-v1'
        write_json(out/'initial_prescription.json',data);stamp_json(out/'initial_prescription.json',selection);stamp_spectrum(out/'initial_prescription.json',p)
        data=json.loads((out/'initial_prescription.json').read_text(encoding='utf-8'))
        surfaces=data['surfaces'];count=len(surfaces);stop=next(i for i,s in enumerate(surfaces) if s['type']=='Aperture')
        if contract:
            from exchange_validation import verify_native,verify_exchange
            native=verify_native(data,model,contract.req)
            exchange=verify_exchange(json.loads(Path(p['resume_lens']).read_text(encoding='utf-8')) if p.get('resume_lens') else data,data,contract.req)
            write_json(out/'exchange_validation.json',dict(passed=native['passed'] and exchange['passed'],native=native,exchange=exchange))
            if not native['passed'] or not exchange['passed']:raise ValueError('原生Optiland入场核验失败：'+'；'.join(native['errors']+exchange['errors']))
        audit=dict(source=verify_optiland(),initialization=initialization,engine_isolation=isolation_report(),optimizer_file=inspect.getfile(LeastSquares),problem_file=inspect.getfile(OptimizationProblem),
                   workflow_mode='direct-v1',native_solver_calls=0,native_progress_callbacks=0,custom_residual_function=False,solver_configuration={'method':p['optiland_solver'],'tol':p['optiland_tol'],'x_scale':p['optiland_x_scale'],'glass_mode':p['optiland_glass_mode']},geometry_mode=p['optiland_geometry_mode'],optical_methods_replaced=[] if not compatible_geometry(p) else ['OptimizationProblem.update_optics: V7 compatibility projection'],added_layers=['native operand configuration','V7 geometry projection only when explicitly selected','three-wavelength input','native solver callback snapshots of copied parameter vectors','native Optiland drawing on independent copies','progress/stop/save','independent native Optiland evaluation'],operands=[])
        state.update(status='running',glass_selection=selection,target=dict(efl_mm=float(p['foclen']),full_fov_deg=float(p['fov']),fnum=float(p['fnum']),bfl_mm=float(p['bfl']),track_mm=p.get('thickness'),cra_cap_deg=p.get('cra_cap'),distortion_max_pct=p.get('distortion_max')))
        import optiland
        def control_boundary(name):
            nonlocal next_cancel_check
            now=time.monotonic()
            if now>=next_cancel_check:
                next_cancel_check=now+.05
                if (out/'stop.flag').exists():raise StopRequested()
            if name=='f2' and on_native_update:on_native_update()
        audit['observer']='native operand boundary + native solver callback; no global tracing/profiling'
        last_accepted_snapshot=copy.deepcopy(data)
        state['stage']='optiland_initial' if int(p.get('curriculum_iters') or 0) else 'optiland_refine'
        def canonical():
            result=copy.deepcopy(data);z=0.
            for i,s in enumerate(result['surfaces']):
                native=model.surfaces[i+1];radius=float(np.asarray(native.geometry.radius).item());thick=float(np.asarray(native.thickness).item())
                s.update(**{'(d)':z,'d_next':thick,'roc':radius if math.isfinite(radius) else 1e14,'(c)':0. if not math.isfinite(radius) else 1/radius});z+=thick
                if s.get('mat2','air')!='air':s['mat2']=aliases.get(getattr(native.material_post,'name',''),s['mat2'])
            result.update(**{'(d_sensor)':z},foclen=float(np.asarray(model.paraxial.f2()).item()),fnum=float(np.asarray(model.paraxial.FNO()).item()))
            return result
        def measure(layout=False,snapshot=None,image_name='layout_final.png'):
            path=out/'current_lens.json';write_json(path,canonical() if snapshot is None else snapshot)
            m=evaluate_snapshot(path,p)
            if layout:
                from native_optiland_progress import render_snapshot
                render_snapshot(path,out/image_name)
            if snapshot is not None:
                snapshot.update(foclen=m['efl_mm'],fnum=m['fnum']);write_json(path,snapshot)
            from snapshot_output import record_snapshot
            record_snapshot(state,path,out,out/image_name if layout else None)
            return m
        state['metrics_initial']=measure(layout=True,image_name='layout_optiland_initial_00000.png');state['metrics_current']=state['metrics_initial'];state['layouts']=['layout_optiland_initial_00000.png'];publish()
        last_accepted_snapshot=copy.deepcopy(data)
        for stage,budget,full in [('optiland_initial',int(p.get('curriculum_iters') or 0),False),('optiland_refine',int(p.get('refine_iters') or 0),True)]:
            if not budget:continue
            from optiland_problem import build_problem
            problem=build_problem(model,data,p,contract,full,audit,control=control_boundary)
            original_update=problem.update_optics;calls=0;begin=time.perf_counter();solver_iterations=0;last_measure=0.;last_plot=0.
            stage_base=canonical()
            def update(_self):
                nonlocal calls
                if (out/'stop.flag').exists():raise StopRequested()
                original_update()
                if contract and compatible_geometry(p):
                    gaps=contract.project_gaps([float(np.asarray(model.surfaces[i+1].thickness).item()) for i in range(count)])
                    for i,gap in enumerate(gaps):model.updater.set_thickness(float(gap),i+1)
                    model.updater.update()
                calls+=1
                if calls==1 or calls%20==0:
                    state.update(stage=stage,iter=calls,residual_evaluations=calls,solver_iterations=solver_iterations,total_iters=budget,nfev_budget=budget,it_per_s=calls/max(time.perf_counter()-begin,1e-6));publish()
            if compatible_geometry(p):problem.update_optics=MethodType(update,problem)
            else:
                def record_update():
                    nonlocal calls
                    calls+=1
                    if calls==1 or calls%20==0:
                        state.update(stage=stage,iter=calls,residual_evaluations=calls,solver_iterations=solver_iterations,total_iters=budget,nfev_budget=budget,it_per_s=calls/max(time.perf_counter()-begin,1e-6));publish()
                on_native_update=record_update
            def accepted_snapshot(vector):
                from native_optiland_progress import snapshot_from_vector
                base=copy.deepcopy(stage_base)
                if aliases:
                    for row,current in zip(base['surfaces'],canonical()['surfaces']):row['mat2']=current['mat2']
                return snapshot_from_vector(base,problem.variables,vector,contract if compatible_geometry(p) else None)
            def progress_callback(vector):
                nonlocal solver_iterations,last_measure,last_plot,last_accepted_snapshot
                from native_optiland_progress import snapshot_from_vector
                last_accepted_snapshot=accepted_snapshot(vector)
                solver_iterations+=1;now=time.perf_counter()
                audit['native_progress_callbacks']+=1
                state.update(stage=stage,solver_iterations=solver_iterations,model_update_calls=calls,progress_mode='native-iteration-callback')
                if now-last_measure>=15 or solver_iterations==1:
                    try:
                        from native_optiland_progress import snapshot_from_vector
                        snapshot=accepted_snapshot(vector)
                        image_name=f'layout_{stage}_{solver_iterations:05d}.png';draw=now-last_plot>=45 or solver_iterations==1
                        metrics=measure(layout=draw,snapshot=snapshot,image_name=image_name)
                        state.update(metrics_current=metrics,loss_rms=metrics['rms_spot_mm'],snapshot_stage=stage,snapshot_solver_iteration=solver_iterations,
                                     snapshot_time=time.time(),snapshot_kind='native solver iteration vector; independent copied model')
                        state['history'].append(dict(stage=stage,iter=solver_iterations,loss_rms=metrics['rms_spot_mm'],loss_reg=None,loss_dist=None,model_update_calls=calls))
                        if draw:state['layouts']=[image_name];last_plot=now
                        last_measure=now
                        print(f'Optiland {stage}: solver_iteration={solver_iterations}, model_updates={calls}, EFL={metrics["efl_mm"]:.6g}, RMS={metrics["rms_spot_mm"]}',flush=True)
                    except Exception as exc:
                        state['progress_warning']=str(exc);print('Progress snapshot warning: '+str(exc),flush=True)
                publish()
            audit['native_solver_calls']+=1
            if full and p['optiland_glass_mode']=='expert':
                from optiland.optimization import GlassExpert
                for index in contract.req['glass_indices']:
                    if contract.cover and index==contract.cover['front_index']:continue
                    problem.add_variable(model,'material',surface_number=index+1,glass_selection=list(aliases))
                optimizer=GlassExpert(problem)
                result=optimizer.run(num_neighbours=min(p['optiland_glass_neighbours'],len(aliases)),maxiter=budget,tol=p['optiland_tol'],disp=False,callback=progress_callback,verbose=True)
                audit['glass_expert_called']=True
                audit['glass_expert_local_solver']='native GlassExpert default generic SciPy optimizer, not TRF'
            else:
                optimizer=LeastSquares(problem)
                kwargs=dict(maxiter=budget,method_choice=p['optiland_solver'],tol=p['optiland_tol'],callback=progress_callback)
                if p['optiland_x_scale']=='jac':kwargs['x_scale']='jac'
                result=optimizer.optimize(**kwargs)
            state.setdefault('solver_results',[]).append(dict(stage=stage,success=bool(result.success),nfev=int(result.nfev),message=str(result.message)))
            state['metrics_current']=measure();state['loss_rms']=state['metrics_current']['rms_spot_mm'];state['history'].append(dict(stage=stage,iter=solver_iterations,loss_rms=state['loss_rms'],loss_reg=0.,loss_dist=0.,model_update_calls=calls));state.update(stage_nfev=int(result.nfev),snapshot_time=time.time());publish()
        data_final=canonical();write_json(out/'final_lens.json',data_final);stamp_json(out/'final_lens.json',selection);stamp_spectrum(out/'final_lens.json',p)
        state['metrics_final']=measure(layout=True);state.update(status='finished',metrics_current=state['metrics_final'],layouts=['layout_final.png'])
        if contract:write_json(out/'requirements_validation.json',contract.verify(json.loads((out/'final_lens.json').read_text(encoding='utf-8'))))
        verify_prescription(json.loads((out/'final_lens.json').read_text(encoding='utf-8')),p);audit['source_after']=verify_optiland();audit['engine_isolation_after']=isolation_report()
        write_json(out/'source_execution.json',audit);state['files']=[f.name for f in out.iterdir() if f.is_file()];publish()
        write_json(out/'summary.json',dict(status='finished',engine='optiland',params=p,metrics_final=state['metrics_final'],target=state['target'],glass_selection=selection,source_execution=audit));return 0
    except (Exception,OptilandStopRequested) as exc:
        state.update(status='stopped' if isinstance(exc,StopRequested) else 'failed',error=None if isinstance(exc,StopRequested) else traceback.format_exc())
        if isinstance(exc,StopRequested) and last_accepted_snapshot is not None:
            try:
                write_json(out/'stopped_lens.json',last_accepted_snapshot)
                state['snapshot_source']='stopped_lens.json'
                write_json(out/'snapshot_state.json',dict(engine='optiland',stage=state.get('stage'),iteration=state.get('solver_iterations',0),source_file='stopped_lens.json',
                          optimizer_state_saved=False,resume_semantics='last accepted native solver vector, not finite-difference probes; restart native solver from this prescription'))
                audit['stopped_snapshot']=True;audit['engine_isolation_after']=isolation_report();write_json(out/'source_execution.json',audit)
            except Exception as save_error:state['checkpoint_error']=str(save_error)
        if state['error']:print(state['error'],flush=True)
        publish();write_json(out/'summary.json',dict(status=state['status'],error=state.get('error'),params=p));return 0 if isinstance(exc,StopRequested) else 1

if __name__=='__main__':raise SystemExit(main())
