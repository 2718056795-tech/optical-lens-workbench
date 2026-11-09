"""Restore a saved run into an independent local copy; never optimize on open."""
import datetime,hashlib,json,shutil,stat,uuid
from pathlib import Path
from prescription_store import list_snapshots

def read(path):
    try:value=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError) as exc:raise ValueError('档案JSON不可读取：'+path.name) from exc
    if not isinstance(value,dict):raise ValueError('档案数据格式不正确：'+path.name)
    return value

def inventory(root):
    for entry in sorted(root.iterdir()):
        info=entry.lstat()
        if entry.is_symlink() or getattr(info,'st_file_attributes',0)&stat.FILE_ATTRIBUTE_REPARSE_POINT:raise ValueError('档案含链接，请选择完整保存的普通文件夹：'+entry.name)
        if stat.S_ISDIR(info.st_mode):yield from inventory(entry)
        elif stat.S_ISREG(info.st_mode):yield entry

def fingerprint(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()

def restore(folder,runs_dir):
    if not isinstance(folder,str) or not Path(folder).is_absolute():raise ValueError('请选择完整的档案文件夹路径')
    source=Path(folder).resolve(strict=True);runs=Path(runs_dir).resolve();runs.mkdir(parents=True,exist_ok=True)
    if not source.is_dir() or source==runs or runs.is_relative_to(source):raise ValueError('请选择一个具体的结果档案子文件夹')
    if not (source/'params.json').is_file() or not list_snapshots(source):raise ValueError('此文件夹没有完整的任务参数和保存处方，请选择“光学优化结果_…”文件夹')
    params=read(source/'params.json')
    if params.get('engine') not in ('autolens','optiland','reference'):raise ValueError('此档案的优化内核不受支持')
    files=list(inventory(source));original={p.relative_to(source).as_posix():fingerprint(p) for p in files}
    candidates=list(source.glob('_保存信息*/保存清单.json'));manifest=None;warnings=[]
    if candidates:
        manifest_path=max(candidates,key=lambda p:p.stat().st_mtime_ns);manifest=read(manifest_path)
        if not isinstance(manifest.get('files'),list):raise ValueError('保存清单缺少文件列表')
        for item in manifest['files']:
            name=item.get('file') if isinstance(item,dict) else None
            if not isinstance(name,str) or not name or '\\' in name or ':' in name or Path(name).is_absolute() or '..' in Path(name).parts:raise ValueError('保存清单含非法文件路径')
            if original.get(name)!=item.get('sha256'):raise ValueError('档案文件缺失或已改变：'+name+'；未载入档案')
        if manifest.get('status')=='partial':warnings.append('此档案保存时不完整，请核对保存说明中的未复制文件')
        old_id=manifest.get('run_id','')
    else:
        warnings.append('旧版档案没有保存清单，已校核基本结构，但无法核对保存时的指纹')
        old_id=read(source/'progress.json').get('run_id','') if (source/'progress.json').exists() else ''
    if not isinstance(old_id,str):raise ValueError('档案任务标识格式不正确')
    if not old_id and (source/'analysis_summary.json').exists():old_id=read(source/'analysis_summary.json').get('run_id','')
    stamp=datetime.datetime.now().astimezone();run_id='archive_'+stamp.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
    staging=runs/('.importing_'+uuid.uuid4().hex);staging.mkdir();target=runs/run_id;changed=[]
    for entry in files:
        relative=entry.relative_to(source);copy=staging/relative;copy.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(entry,copy)
        if fingerprint(copy)!=original[relative.as_posix()] or fingerprint(entry)!=original[relative.as_posix()]:raise ValueError('档案在读取过程中发生变化，请保存完成后再载入')
    # Only UI/analysis bookkeeping is rebound. Native prescriptions remain byte exact.
    def rebind(value):
        if isinstance(value,dict):return {key:run_id if key=='run_id' and item==old_id else rebind(item) for key,item in value.items()}
        if isinstance(value,list):return [rebind(item) for item in value]
        return value
    metadata=[staging/'analysis_summary.json',*staging.glob('analysis/analysis*.json'),*staging.glob('analysis/**/result.json')]
    for path in metadata:
        if path.is_file():
            data=read(path);adapted=rebind(data)
            if adapted!=data:path.write_text(json.dumps(adapted,ensure_ascii=False,indent=2),encoding='utf-8');changed.append(path.relative_to(staging).as_posix())
    progress=read(staging/'progress.json') if (staging/'progress.json').is_file() else {}
    if progress.get('status') in ('running','starting','init','stopping','finalizing'):
        progress['status']='stopped';progress['archive_interrupted']=True
        (staging/'progress.json').write_text(json.dumps(progress,ensure_ascii=False,indent=2),encoding='utf-8');changed.append('progress.json')
        warnings.append('档案来自进行中的任务，已按停止快照载入；没有恢复或启动旧进程')
    origin=dict(source_directory=str(source),original_run_id=old_id,restored_at=stamp.isoformat(timespec='seconds'),source_files_sha256=original,
        adapted_metadata=changed,manifest_checked=manifest is not None,warnings=warnings,optimization_started=False)
    (staging/'archive_origin.json').write_text(json.dumps(origin,ensure_ascii=False,indent=2),encoding='utf-8')
    staging.rename(target)
    view_engine=params.get('analysis_engine') or params.get('engine')
    return dict(run_id=run_id,file_count=len(files),manifest_checked=manifest is not None,warnings=warnings,optimization_started=False,
        analysis_engine=view_engine if view_engine in ('autolens','optiland') else 'optiland')
