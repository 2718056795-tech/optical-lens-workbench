"""Locate an existing layout for one explicit saved prescription; never trace rays."""
import hashlib,json
from pathlib import Path

def _digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def describe(run_dir,source_file,source_sha256):
    root=Path(run_dir).resolve()
    result=dict(source_file=source_file,source_sha256=source_sha256,image_file=None,image_sha256=None,available=False,
                message='当前快照没有已保存的同源光路图，可选择本快照计算光路分析。')
    if not isinstance(source_file,str) or not isinstance(source_sha256,str):return result
    source=(root/source_file).resolve()
    if not source.is_relative_to(root) or not source.is_file() or _digest(source)!=source_sha256:
        return dict(result,message='快照已更新，请重新载入后查看光路。')
    relative=Path(source_file);candidates=[relative.with_suffix('.png'),Path(str(relative.with_suffix('.png'))+'.png')]
    if source_file=='final_lens.json':candidates.append(Path('layout_final.png'))
    # Accepted-step Optiland snapshots use their native callback index in the file name.
    if relative.parent.name in ('optiland_initial','optiland_refine') and relative.stem.startswith('iter'):
        try:candidates.append(Path('layout_'+relative.parent.name+'_'+str(int(relative.stem[4:])).zfill(5)+'.png'))
        except ValueError:pass
    def found(candidate,binding,expected_image_sha=None):
        path=(root/candidate).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower()!='.png' or path.stat().st_size==0:return None
        digest=_digest(path)
        if expected_image_sha and digest!=expected_image_sha:return None
        if binding=='same-prescription filename' and path.stat().st_mtime_ns<source.stat().st_mtime_ns:return None
        return dict(result,available=True,image_file=path.relative_to(root).as_posix(),image_sha256=digest,binding=binding,message='')
    try:bindings=json.loads((root/'layout_bindings.json').read_text(encoding='utf-8'))
    except (ValueError,OSError):bindings={}
    if isinstance(bindings,dict):
        images=bindings.get('images',bindings)
        for image_name,record in images.items() if isinstance(images,dict) else []:
            if not isinstance(image_name,str) or not isinstance(record,dict) or not isinstance(record.get('image_sha256'),str) or record.get('source_file')!=source_file or record.get('source_sha256')!=source_sha256:continue
            image=found(Path(image_name),'explicit source SHA256',record.get('image_sha256'))
            if image:return image
    for candidate in candidates:
        image=found(candidate,'same-prescription filename')
        if image:return image
    # A calculated layout can be reused only when its recorded source and hash match.
    for path in sorted((root/'analysis').glob('**/result.json')):
        try:record=json.loads(path.read_text(encoding='utf-8'))
        except (ValueError,OSError):continue
        if not isinstance(record,dict) or not record.get('ok') or record.get('analysis_id')!='layout' or record.get('source_file')!=source_file or record.get('source_sha256')!=source_sha256:continue
        for image in record.get('images',[]) if isinstance(record.get('images',[]),list) else []:
            if not isinstance(image,dict) or not isinstance(image.get('file'),str):continue
            candidate=Path(record.get('relative_dir',''))/image['file'];matched=found(candidate,'analysis source SHA256')
            if matched:return matched
    return result
