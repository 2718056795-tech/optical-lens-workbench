"""Isolated native IO, display metadata and explicitly selected legacy compositions."""
import hashlib,json,os,subprocess,sys,threading,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parent
LOCK=threading.RLock()
def run(request,folder):
 folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);request=dict(request,result=str(folder/'result.json'))
 file=folder/'request.json';file.write_text(json.dumps(request),encoding='utf-8')
 with (folder/'worker.log').open('w',encoding='utf-8') as log:
  proc=subprocess.run([sys.executable,'-B',str(ROOT/'model_io_worker.py'),'--request',str(file)],cwd=ROOT,env=dict(os.environ,PYTHONIOENCODING='utf-8'),stdout=log,stderr=subprocess.STDOUT,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 result=json.loads((folder/'result.json').read_text(encoding='utf-8')) if (folder/'result.json').exists() else {}
 if proc.returncode or not result:raise ValueError('原生模型处理失败：'+result.get('error',(folder/'worker.log').read_text(encoding='utf-8',errors='replace'))[-700:])
 return result
def scene(run_dir,source,digest):
 from prescription_store import freeze
 folder=ROOT/'runtime_cache/model_scenes'/digest[:24]
 with LOCK:
  frozen=freeze(run_dir,source,folder/'source_snapshot.json',digest)
  saved=folder/'scene.json'
  if saved.exists():return json.loads(saved.read_text(encoding='utf-8'))
  result=run(dict(action='scene',source=frozen['source']),folder);saved.write_text(json.dumps(result),encoding='utf-8');return result
def inspect_file(raw,filename,configuration=1):
 folder=ROOT/'runtime_cache/import_jobs'/uuid.uuid4().hex;folder.mkdir(parents=True)
 source=folder/'source.bin';source.write_bytes(raw)
 return run(dict(action='inspect',source=str(source),filename=filename,configuration=configuration),folder)
