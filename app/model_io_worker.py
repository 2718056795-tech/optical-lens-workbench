"""Keep native model and plotting-library imports out of HTTP request threads."""
import argparse,json,os,traceback
from pathlib import Path
os.environ.update(MPLBACKEND='Agg',OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2')
def main():
 p=argparse.ArgumentParser();p.add_argument('--request',required=True);a=p.parse_args();req=json.loads(Path(a.request).read_text(encoding='utf-8'))
 from native_sources import configure_optiland_runtime
 configure_optiland_runtime()
 try:
  if req['action']=='scene':
   from lens_scene import build_scene
   result=build_scene(req['source'])
  elif req['action']=='legacy':
   from optiland_bridge import compute_analysis
   result=compute_analysis(req['source'],req['out_dir'])
  else:
   from design_import import inspect
   result=inspect(Path(req['source']).read_bytes(),req['filename'],req['configuration'])
  Path(req['result']).write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8');return 0
 except Exception:
  Path(req['result']).write_text(json.dumps(dict(error=traceback.format_exc())),encoding='utf-8');return 1
if __name__=='__main__':raise SystemExit(main())
