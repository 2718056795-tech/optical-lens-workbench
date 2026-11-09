"""Contain native exporter errors in a child process and preserve original files."""
import os,subprocess,sys,threading
from pathlib import Path
from prescription_store import resolve,freeze
ROOT=Path(__file__).resolve().parent
LOCK=threading.Lock()
def export(run_dir,fmt,source=None,expected_sha=None):
 if fmt not in ('seq','zmx'):raise ValueError('仅支持SEQ/ZMX导出')
 path,_,sha=resolve(run_dir,source,expected_sha);name=path.stem
 folder=Path(run_dir)/'exports'/sha[:20];target=folder/(name+'.'+fmt)
 with LOCK:
  frozen=freeze(run_dir,path.relative_to(Path(run_dir).resolve()).as_posix(),folder/'source_snapshot.json',sha)
  with (folder/'export.log').open('w',encoding='utf-8') as log:
   proc=subprocess.run([sys.executable,'-B',str(ROOT/'export_worker.py'),'--source',frozen['source'],'--format',fmt,'--output',str(target)],
       cwd=ROOT,env=dict(os.environ,PYTHONIOENCODING='utf-8',MPLBACKEND='Agg'),stdout=log,stderr=subprocess.STDOUT,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  if proc.returncode or not target.is_file():
   text=(folder/'export.log').read_text(encoding='utf-8',errors='replace');raise ValueError('原生导出未成功：'+text.strip().splitlines()[-1][:350])
  return target.read_bytes(),target.name,sha
