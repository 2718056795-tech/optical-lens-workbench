"""Independent cached worker jobs for expensive analysis, separate from optimization."""
import atexit,hashlib,json,os,subprocess,sys,threading,time
from pathlib import Path
from analysis_catalog import engine_catalog,VERSION,normalize_options

ROOT=Path(__file__).resolve().parent
LOCK=threading.RLock();JOBS={}


def start(run_dir,run_id,analysis_id,options=None,image=None,force=False,engine='optiland',source=None,source_sha256=None):
    if analysis_id not in engine_catalog(engine):raise ValueError('该分析内核不支持此项目：'+str(analysis_id))
    entry=engine_catalog(engine)[analysis_id]
    if entry.get('available') is False:raise ValueError(entry['reason'])
    from prescription_store import resolve,freeze
    src,source_data,digest_source=resolve(run_dir,source,source_sha256)
    if engine=='optiland' and any('/' in str(s.get('mat2','air')) for s in source_data['surfaces']):raise ValueError('该阶段仍是连续MODEL材料；请用AutoLens分析，或选择匹配目录玻璃后的保存点。')
    if source_data.get('optiland_native_source') and engine!='optiland':raise ValueError('此记录保留原文件的Optiland原生模型，仅支持Optiland直接分析；未验证的跨内核转换已阻止。')
    source_file=src.relative_to(Path(run_dir).resolve()).as_posix()
    opts=normalize_options(options)
    if analysis_id in ('layout','native_3d'):opts.update(ignore_object=opts.get('ignore_object',True),view_version='object-frame-v1')
    if engine=='autolens' and analysis_id=='native_3d':opts['wave']='primary'
    if opts['focus_steps']%2==0:raise ValueError('离焦步数需为奇数')
    if image is not None and (not isinstance(image,str) or len(image)>2800000):raise ValueError('图像需小于2MB')
    body=dict(run_id=run_id,engine=engine,analysis_id=analysis_id,options=opts,source_file=source_file,source_sha256=digest_source,version=VERSION)
    image_hash=hashlib.sha256((image or '').encode()).hexdigest()
    digest=hashlib.sha256(json.dumps(dict(body,image_sha256=image_hash),sort_keys=True).encode()).hexdigest()[:20]
    target=Path(run_dir)/'analysis'/'extended'/digest
    key=run_id+'|'+digest
    with LOCK:
        if key in JOBS and JOBS[key]['proc'].poll() is None:return state(key)
        if (target/'result.json').is_file() and not force:
            result=json.loads((target/'result.json').read_text(encoding='utf-8'))
            if result.get('engine')!=engine:raise ValueError('缓存内核不符，请重新计算')
            return dict(job_id=key,status='finished',cached=True,result=result)
        for job in JOBS.values():
            if job['proc'].poll() is None:raise RuntimeError('已有分析正在计算，请等待或取消当前分析')
        target.mkdir(parents=True,exist_ok=True)
        frozen=freeze(run_dir,source_file,target/'source_snapshot.json',digest_source)
        request=dict(body,source=frozen['source'],out_dir=str(target),image=image)
        path=target/'request.json';path.write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding='utf-8')
        # A cancelled/failed attempt shares the same content key. Clear its
        # terminal status BEFORE launching a new process for that key.
        from engine_io import write_json
        write_json(target/'progress.json',dict(status='running',message='准备独立分析进程'))
        flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
        with (target/'analysis.log').open('w',encoding='utf-8') as log:
            env=dict(os.environ,PYTHONIOENCODING='utf-8',MPLBACKEND='Agg',OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',NUMBA_CACHE_DIR=str(ROOT/'runtime_cache/numba'),MPLCONFIGDIR=str(ROOT/'runtime_cache/matplotlib'))
            proc=subprocess.Popen([sys.executable,str(ROOT/'analysis_worker.py'),'--request',str(path)],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
        JOBS[key]=dict(proc=proc,target=target,started=time.time())
        return dict(job_id=key,status='running',cached=False)


def state(key):
    with LOCK:
        job=JOBS.get(key)
        if not job:raise ValueError('分析任务不存在，请重新计算或读取缓存')
        target=job['target'];proc=job['proc'];running=proc.poll() is None
        payload=dict(job_id=key,status='running' if running else 'failed',elapsed_seconds=time.time()-job['started'])
        if (target/'progress.json').is_file():
            try:payload.update(json.loads((target/'progress.json').read_text(encoding='utf-8')))
            except (OSError,ValueError):pass
        if running:payload['status']='running'
        elif (target/'result.json').is_file() and proc.returncode==0:
            payload.update(status='finished',result=json.loads((target/'result.json').read_text(encoding='utf-8')))
        elif payload.get('status') not in ('cancelled','failed'):
            payload.update(status='failed',error=f'分析进程退出码{proc.returncode}，请查看analysis.log')
        return payload


def cancel(key):
    with LOCK:
        job=JOBS.get(key)
        if job and job['proc'].poll() is None:
            job['proc'].terminate();job['proc'].wait(timeout=10)
            (job['target']/'progress.json').write_text(json.dumps(dict(status='cancelled',error='用户取消分析')),encoding='utf-8')
    return dict(status='cancelled',job_id=key)


@atexit.register
def close_workers():
    for key in list(JOBS):
        try:cancel(key)
        except (OSError,subprocess.TimeoutExpired):pass
