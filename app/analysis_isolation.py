"""Analysis processes never fall back to the other calculation engine."""
import importlib.abc,sys
def roots(engine):return ('optiland',) if engine=='autolens' else ('deeplens','autolens_analysis','optimizer_runner','native_autolens_runner','common_metrics')
def loaded(engine):return sorted(n for n in sys.modules if any(n==r or n.startswith(r+'.') for r in roots(engine)))
class Guard(importlib.abc.MetaPathFinder):
    def __init__(self,engine):self.engine=engine
    def find_spec(self,fullname,path=None,target=None):
        if any(fullname==r or fullname.startswith(r+'.') for r in roots(self.engine)):
            raise ImportError(self.engine+'分析禁止跨内核调用：'+fullname)
def install(engine):
    if loaded(engine):raise RuntimeError('分析进程已混入其他内核')
    sys.meta_path.insert(0,Guard(engine))
def report(engine):
    cross=loaded(engine)
    if cross:raise RuntimeError('分析跨内核导入：'+str(cross))
    return dict(engine=engine,other_engine_imports=cross,guard_active=any(isinstance(g,Guard) and g.engine==engine for g in sys.meta_path))
