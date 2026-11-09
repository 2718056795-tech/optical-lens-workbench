"""Load pinned upstream source. This module never edits an upstream file."""
import hashlib,importlib.util,json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
COMMIT='e58db32f3a0b07f25861b5839a45970f77b5c947'
AUTO_DIR=ROOT/'vendor'/('AutoLens-'+COMMIT)
RUNTIME=ROOT/'vendor/native_runtime'
ANALYSIS_RUNTIME=ROOT/'vendor/analysis_runtime'
def configure_analysis_runtime():
    value=str(ANALYSIS_RUNTIME)
    if value not in sys.path:sys.path.insert(0,value)

def configure_paths():
    for path in (RUNTIME,AUTO_DIR):
        value=str(path)
        if value in sys.path:sys.path.remove(value)
        sys.path.insert(0,value)

def verify_autolens():
    manifest=json.loads((ROOT/'vendor/autolens_upstream_manifest.json').read_text(encoding='utf-8'))
    errors=[name for name,digest in manifest['files'].items() if not (ROOT/'vendor'/name).is_file() or hashlib.sha256((ROOT/'vendor'/name).read_bytes()).hexdigest()!=digest]
    if errors:raise RuntimeError('官方AutoLens源码完整性校验失败：'+', '.join(errors[:5]))
    return dict(commit=COMMIT,files=len(manifest['files']),source_files_modified=0,archive_sha256=manifest['archive_sha256'])

def load_autolens():
    configure_paths();verify_autolens()
    loaded=sys.modules.get('deeplens')
    if loaded and not Path(loaded.__file__).resolve().is_relative_to(AUTO_DIR):
        raise RuntimeError('当前进程已载入其他DeepLens；原生优化必须使用独立工作进程')
    spec=importlib.util.spec_from_file_location('upstream_autolens_entry',AUTO_DIR/'1_autolens.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def verify_optiland():
    import base64,importlib.metadata
    dist=importlib.metadata.distribution('optiland');checked=0;errors=[]
    for item in dist.files or []:
        if item.suffix!='.py' or not item.hash or item.hash.mode!='sha256':continue
        path=Path(dist.locate_file(item))
        actual=base64.urlsafe_b64encode(hashlib.sha256(path.read_bytes()).digest()).decode().rstrip('=')
        if actual!=item.hash.value:errors.append(str(item))
        checked+=1
    if errors:raise RuntimeError('Optiland安装源码与原始wheel记录不符：'+', '.join(errors[:5]))
    return dict(version=dist.version,source_files_checked=checked,source_files_modified=0)


def configure_optiland_runtime():
    """Add private SciPy only; never add an AutoLens source path."""
    value=str(RUNTIME)
    if value in sys.path:sys.path.remove(value)
    sys.path.insert(0,value)
