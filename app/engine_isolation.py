"""Runtime guard for the independent Optiland process."""
import importlib.abc,sys
FORBIDDEN=('deeplens','optimizer_runner','native_autolens_runner','native_autolens_extensions','common_metrics')
def forbidden_loaded():return sorted(name for name in sys.modules if any(name==root or name.startswith(root+'.') for root in FORBIDDEN))
class OptilandOnly(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if any(fullname==root or fullname.startswith(root+'.') for root in FORBIDDEN):
            raise ImportError('Optiland独立线路禁止导入另一内核: '+fullname)
        return None
def install():
    if forbidden_loaded():raise RuntimeError('Optiland进程已混入其他内核: '+str(forbidden_loaded()))
    if not any(isinstance(f,OptilandOnly) for f in sys.meta_path):sys.meta_path.insert(0,OptilandOnly())
def report():
    loaded=forbidden_loaded()
    if loaded:raise RuntimeError('跨内核导入: '+str(loaded))
    return dict(other_engine_imports=loaded,guard_active=any(isinstance(f,OptilandOnly) for f in sys.meta_path))
