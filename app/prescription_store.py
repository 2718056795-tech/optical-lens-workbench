"""One explicit saved-prescription reference for viewing, analysis, export and resume."""
import hashlib,json,math,re
from pathlib import Path
ALLOWED_DIRS={'curriculum','refine','optiland_initial','optiland_refine'}
def read(path):
    data=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data,dict) or not isinstance(data.get('surfaces'),list) or not data['surfaces']:
        raise ValueError('所选文件不是有效的保存处方')
    if not all(isinstance(s,dict) and s.get('type') and s.get('r') is not None for s in data['surfaces']):raise ValueError('处方表面数据不完整')
    return data
def resolve(run_dir,source=None,expected_sha=None):
    root=Path(run_dir).resolve()
    if source in (None,'','latest'):
        choices=list_snapshots(root)
        if not choices:raise FileNotFoundError('尚无有效保存处方')
        source=choices[0]['file']
    if not isinstance(source,str) or '\\' in source or ':' in source or '..' in source.split('/'):
        raise ValueError('处方文件路径非法')
    relative=Path(source)
    if relative.is_absolute() or relative.suffix.lower()!='.json' or len(relative.parts)>2 or len(relative.parts)==2 and relative.parts[0] not in ALLOWED_DIRS:
        raise ValueError('仅能选择当前运行目录中的保存处方')
    path=(root/relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():raise FileNotFoundError('保存处方不存在')
    data=read(path);raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    if expected_sha and digest!=expected_sha:raise ValueError('该快照已更新，请重新载入后再操作；不会分析或导出未显示的新结构')
    return path,data,digest
def list_snapshots(run_dir):
    root=Path(run_dir);paths=list(root.glob('*.json'))
    for folder in ALLOWED_DIRS:
        if (root/folder).is_dir():paths.extend((root/folder).glob('*.json'))
    rows=[]
    for path in paths:
        try:
            data=read(path);stat=path.stat();rel=path.relative_to(root).as_posix()
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):continue
            rows.append(dict(file=rel,saved_at=stat.st_mtime,bytes=stat.st_size,surfaces=len(data['surfaces']),
                             sha256=hashlib.sha256(path.read_bytes()).hexdigest(),final=rel=='final_lens.json'))
        except (ValueError,OSError,TypeError,KeyError):continue
    return sorted(rows,key=lambda r:(r['final'],r['saved_at'],int(re.search(r'iter(\d+)',r['file']).group(1)) if re.search(r'iter(\d+)',r['file']) else -1),reverse=True)
def freeze(run_dir,source,target,expected_sha=None):
    path,data,digest=resolve(run_dir,source,expected_sha);raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('快照在复制时更新，请重试')
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    for key,sha_key,allowed in [('optiland_native_source','native_model_sha256',{'native_optic.json'}),('source_original_file','source_original_sha256',{'original.seq','original.zmx'})]:
        if data.get(key):
            name=data[key]
            if name not in allowed:raise ValueError('原生模型伴随文件路径非法')
            payload=(path.parent/name).read_bytes()
            if hashlib.sha256(payload).hexdigest()!=data.get(sha_key):raise ValueError('原生模型伴随文件已变化，请重新导入')
            (target.parent/name).write_bytes(payload)
    return dict(source_file=path.relative_to(Path(run_dir).resolve()).as_posix(),source_sha256=digest,source=str(target))
