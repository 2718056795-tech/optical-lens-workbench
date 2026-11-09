"""Copy one run's existing files into a new user-selected result folder."""
import datetime,hashlib,json,os,stat
from pathlib import Path

def read_json(path):
    try:return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}

def save_run(source,parent):
    if not isinstance(parent,(str,Path)) or not str(parent):raise ValueError('请选择目标文件夹')
    source=Path(source).resolve(strict=True);parent=Path(parent)
    if not source.is_dir():raise ValueError('运行记录目录不存在')
    if not parent.is_absolute():raise ValueError('请选择完整的目标文件夹路径')
    parent=parent.resolve(strict=True)
    if not parent.is_dir():raise ValueError('目标必须是已存在的文件夹')
    if parent.is_relative_to(source.parent):raise ValueError('请选运行记录目录以外的位置，避免把结果重复保存到运行记录中')
    stamp=datetime.datetime.now().astimezone();base='光学优化结果_'+source.name+'_'+stamp.strftime('%Y%m%d_%H%M%S')
    for index in range(10000):
        target=parent/(base+(f'_{index}' if index else ''))
        try:target.mkdir();break
        except FileExistsError:continue
    else:raise OSError('无法建立唯一的结果文件夹')
    records=[];errors=[];progress=read_json(source/'progress.json');status=progress.get('status','unknown')
    def inventory(folder):
        for entry in sorted(folder.iterdir()):
            info=entry.lstat()
            if entry.is_symlink() or getattr(info,'st_file_attributes',0)&stat.FILE_ATTRIBUTE_REPARSE_POINT:
                errors.append(dict(file=entry.relative_to(source).as_posix(),error='链接文件/目录未复制'));continue
            if stat.S_ISDIR(info.st_mode):yield from inventory(entry)
            elif stat.S_ISREG(info.st_mode):yield entry,entry.relative_to(source)
    files=list(inventory(source))
    # Include the independent F-number report when it belongs to this run.
    tracking=source.parent.parent/'validation/fnum_tracking'/source.name
    tracking_relative=Path('附加记录/F数跟踪');index=0
    while (source/tracking_relative).exists():index+=1;tracking_relative=Path('附加F数跟踪_'+str(index))
    for name in ('F数跟踪.md','F数跟踪.csv','measurements.json'):
        path=tracking/name
        if path.is_file() and not path.is_symlink():files.append((path,tracking_relative/name))
    for path,relative in files:
        destination=target/relative
        try:
            destination.parent.mkdir(parents=True,exist_ok=True)
            for attempt in range(3):
                before=path.stat();digest=hashlib.sha256();size=0
                with path.open('rb') as incoming,destination.open('wb') as outgoing:
                    for chunk in iter(lambda:incoming.read(1024*1024),b''):
                        outgoing.write(chunk);digest.update(chunk);size+=len(chunk)
                after=path.stat()
                if (before.st_mtime_ns,before.st_size)==(after.st_mtime_ns,after.st_size) and size==before.st_size:break
            else:raise OSError('文件持续更新，未能取得稳定副本；请稍后再次保存')
            os.utime(destination,ns=(after.st_atime_ns,after.st_mtime_ns))
            records.append(dict(file=relative.as_posix(),bytes=size,sha256=digest.hexdigest()))
        except OSError as exc:
            if destination.is_file() and destination.resolve().is_relative_to(target):destination.unlink()
            errors.append(dict(file=relative.as_posix(),error=str(exc)))
    metadata=target/'_保存信息';index=0
    while metadata.exists():index+=1;metadata=target/('_保存信息_'+str(index))
    metadata.mkdir()
    result=dict(status='saved' if not errors else 'partial',run_id=source.name,source_directory=str(source),destination=str(target),
        saved_at=stamp.isoformat(timespec='seconds'),run_status_at_start=status,live_snapshot=status not in ('finished','stopped','failed'),
        file_count=len(records),total_bytes=sum(r['bytes'] for r in records),files=records,errors=errors,
        scope='保存开始时已有文件及可用F数跟踪记录；不重算、不修改源文件，不包含之后产生的文件；运行中副本不是同一时刻的原子快照')
    (metadata/'保存清单.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['光学优化结果保存说明',f'任务：{source.name}',f'保存时间：{result["saved_at"]}',f'保存时任务状态：{status}',
        f'已复制：{len(records)} 个文件；未复制：{len(errors)} 个',result['scope'],
        '保留原有目录层级，文件清单附SHA256。优化完成不代表光学指标达标。已有处方/分析/日志原样保存，未生成尚未计算的分析或导出。']
    params=progress.get('params') or read_json(source/'params.json');metrics=progress.get('metrics_final') or progress.get('metrics_current') or {}
    lines.extend(['',f'输入目标：焦距 {params.get("foclen","未记录")} mm；F数 {params.get("fnum","未记录")}；全视场 {params.get("fov","未记录")}°',
        f'已记录独立评价：焦距 {metrics.get("efl_mm","尚未评价")} mm；F数 {metrics.get("fnum","尚未评价")}；近轴全视场 {metrics.get("full_fov_deg","尚未评价")}°',
        '上述评价来自已有指标文件，保存操作没有重新计算；是否满足指标请结合目标、完整分析及验收条件核对。'])
    lines.extend(f'未复制 {e["file"]}：{e["error"]}' for e in errors)
    (metadata/'保存说明.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8-sig')
    return {k:v for k,v in result.items() if k!='files'}
