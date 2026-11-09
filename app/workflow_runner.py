"""Finish one EXE task without an online agent: optimize, check, plot, export."""
import argparse,json,os,shutil,subprocess,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parent
os.environ.update(NUMBA_CACHE_DIR=str(ROOT/'runtime_cache/numba'),MPLCONFIGDIR=str(ROOT/'runtime_cache/matplotlib'),MPLBACKEND='Agg',OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2')
from engine_io import write_json


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--params',required=True);ap.add_argument('--run-dir',required=True);args=ap.parse_args()
    out=Path(args.run_dir);p=json.loads(Path(args.params).read_text(encoding='utf-8'));state={}
    try:
        if p.get('engine')=='optiland':
            from engine_isolation import install
            install()
        worker=p['_workflow_worker']
        if worker not in ('optimizer_runner.py','optiland_runner.py'):raise ValueError('未知优化工作进程')
        if p.get('resume_phase')=='finalize':
            if not p.get('resume_lens') or not p.get('resume_reference'):raise ValueError('缺少已验证的分析续跑来源')
            shutil.copy2(p['resume_lens'],out/'final_lens.json')
            state=dict(status='finished',engine=p['engine'],params=p,history=p.get('resume_history',[]),target=p.get('resume_target',{}),metrics_final=p.get('resume_metrics',{}),metrics_current=p.get('resume_metrics',{}),files=['final_lens.json'],optimization_skipped=True)
            write_json(out/'progress.json',state);write_json(out/'source_execution.json',dict(optimization_skipped=True,reason='continue analysis/export only',source_reference=p['resume_reference']))
            child_code=0
        else:
            child=subprocess.run([sys.executable,'-B',str(ROOT/worker),'--params',args.params,'--run-dir',str(out)],cwd=ROOT);child_code=child.returncode
            state=json.loads((out/'progress.json').read_text(encoding='utf-8'))
        if child_code or state.get('status') not in ('finished','stopped'):
            state.update(status='failed',error=state.get('error') or '优化进程未正常完成')
            write_json(out/'progress.json',state);write_json(out/'completion.json',dict(status='failed',error=state['error']));return 1
        if state['status']=='stopped':write_json(out/'completion.json',dict(status='stopped'));return 0
        if (out/'stop.flag').exists():
            state['status']='stopped';write_json(out/'progress.json',state);write_json(out/'completion.json',dict(status='stopped'));return 0
        if not (out/'final_lens.json').exists():raise RuntimeError('未找到最终保存处方')
        # Provenance and comparison only. No recalculation or optimizer change.
        from snapshot_output import record_comparison
        record_comparison(state,p,out)
        state.update(status='running',stage='verification');write_json(out/'progress.json',state)
        from design_contract import load
        contract=None if p.get('autolens_protocol')=='autolens-official-main-v1' else load(p)
        if contract:write_json(out/'requirements_validation.json',contract.verify(json.loads((out/'final_lens.json').read_text(encoding='utf-8'))))
        state['stage']='analysis';write_json(out/'progress.json',state)
        from optiland_bridge import export_lens
        from analysis_batch import compute_selected
        analysis_engine=p.get('analysis_engine','optiland')
        def analysis_progress(message):
            state.update(analysis_engine=analysis_engine,analysis_message=message);write_json(out/'progress.json',state)
        analysis=compute_selected(out,analysis_engine,progress=analysis_progress)
        write_json(out/'analysis_summary.json',analysis)
        if analysis.get('errors'):raise RuntimeError('分析出图未完整完成：'+json.dumps(analysis['errors'],ensure_ascii=False))
        if len(analysis.get('images',[]))<5:raise RuntimeError('基础分析图未齐全')
        if (out/'stop.flag').exists():
            state['status']='stopped';write_json(out/'progress.json',state);write_json(out/'completion.json',dict(status='stopped'));return 0
        state['stage']='export';write_json(out/'progress.json',state)
        for fmt in ('seq','zmx'):export_lens(out/'final_lens.json',fmt,out/('final_lens.'+fmt))
        catalog_file=None
        if contract:
            from glass_selection import catalog_data
            selection=contract.req['glass_selection'];catalog_file=selection['catalog']+selection['revision']+'.AGF'
            shutil.copy2(catalog_data(selection['catalog'],selection['revision'])['source_file'],out/catalog_file)
        elif p.get('autolens_protocol')=='autolens-official-main-v1':
            from optiland_bridge import native_cdgm_catalog
            from glass_selection import catalog_data
            identified=native_cdgm_catalog(json.loads((out/'final_lens.json').read_text(encoding='utf-8')))
            if identified:
                catalog_file='CDGM.AGF';shutil.copy2(catalog_data(*identified)['source_file'],out/catalog_file)
        status='finished'
        complete=dict(status=status,workflow_mode='direct-v1',route=p.get('route',p.get('engine')),route_completed=True,
                      optimization_finished=True,requirements_verified=bool(contract),analysis_finished=True,analysis_engine=analysis_engine,
                      exports=['final_lens.json','final_lens.seq','final_lens.zmx'],waiting_for_user=False,
                      optical_acceptance=None,note='所选优化内核求解、独立选择的分析内核出图与格式导出已结束；没有候选筛选或追加精修，不代表光学指标全部达标')
        if p.get('engine')=='optiland':
            from engine_isolation import report
            complete['engine_isolation']=report()
        if catalog_file:complete['exports'].append(catalog_file)
        state.update(status=status,stage='complete',completion=complete)
        state['files']=[f.name for f in out.iterdir() if f.is_file()]
        write_json(out/'completion.json',complete);write_json(out/'progress.json',state)
        return 0
    except InterruptedError:
        state.update(status='stopped',stage='analysis');write_json(out/'progress.json',state);write_json(out/'completion.json',dict(status='stopped'));return 0
    except BaseException:
        state.update(status='finalization_failed',error=traceback.format_exc())
        write_json(out/'progress.json',state);write_json(out/'completion.json',dict(status='finalization_failed',error=state['error']));print(state['error'],flush=True);return 1

if __name__=='__main__':raise SystemExit(main())
