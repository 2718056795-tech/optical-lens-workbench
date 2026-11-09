"""Post-optimization analysis using the separately selected analysis engine."""
import json,time
from pathlib import Path
from engine_io import write_json

def compute_selected(run_dir,engine='optiland',progress=lambda *a,**k:None):
    out=Path(run_dir)
    if engine not in ('autolens','optiland'):raise ValueError('未知分析内核')
    # Both engines use their selected native analysis jobs in isolated children.
    import analysis_service
    results=[];errors={}
    source=json.loads((out/'final_lens.json').read_text(encoding='utf-8'))
    auto_spot='spot_fields' if source.get('design_fields') else 'spot_radial'
    for key in (('layout',auto_spot,'native_mtf','curvature','grid_distortion') if engine=='autolens' else ('layout','native_spot','native_geometric_mtf','native_curvature','native_grid')):
        if (out/'stop.flag').exists():raise InterruptedError('用户停止分析')
        progress(engine+' 原生分析：'+key)
        job=analysis_service.start(out,out.name,key,engine=engine)
        while job['status']=='running':
            if (out/'stop.flag').exists():analysis_service.cancel(job['job_id']);raise InterruptedError('用户停止分析')
            time.sleep(.25);job=analysis_service.state(job['job_id'])
        if job['status']=='finished':results.append(job['result'])
        else:errors[key]=job.get('error','原生分析未完成')
    result=dict(engine=engine,run_id=out.name,analysis_version='native-selected-v2',results=results,errors=errors,
                images=[dict(file=r['relative_dir']+'/'+i['file'],label=i['label']) for r in results for i in r['images']])
    write_json(out/('analysis/analysis_'+engine+'.json'),result);return result
