"""Launch the original interactive 3D window only on an explicit UI action."""
import json,os,subprocess,sys,threading,time
from pathlib import Path
from prescription_store import resolve,freeze
ROOT=Path(__file__).resolve().parent
LOCK=threading.Lock();SESSIONS={}
def launch(run_dir,engine,source=None,expected_sha=None,ignore_object=True):
 if engine not in ('autolens','optiland'):raise ValueError('未知3D内核')
 if not isinstance(ignore_object,bool):raise ValueError('忽略物面需为布尔值')
 path,data,sha=resolve(run_dir,source,expected_sha);key=(engine,sha,ignore_object)
 if data.get('optiland_native_source') and engine!='optiland':raise ValueError('该导入模型仅支持原生Optiland查看器')
 with LOCK:
  old=SESSIONS.get(key)
  if old is not None and old.poll() is None:return dict(opened=True,already_open=True,engine=engine)
  folder=Path(run_dir)/'native3d_sessions'/(engine+'_'+str(time.time_ns()));folder.mkdir(parents=True)
  req=freeze(run_dir,path.relative_to(Path(run_dir).resolve()).as_posix(),folder/'source_snapshot.json',sha);req.update(engine=engine,ignore_object=ignore_object)
  request=folder/'request.json';request.write_text(json.dumps(req),encoding='utf-8')
  with (folder/'native3d.log').open('w',encoding='utf-8') as log:
   proc=subprocess.Popen([sys.executable,'-B',str(ROOT/'native_3d_window.py'),'--request',str(request)],cwd=ROOT,
       env=dict(os.environ,PYTHONIOENCODING='utf-8'),stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  SESSIONS[key]=proc
  return dict(opened=True,already_open=False,engine=engine)
