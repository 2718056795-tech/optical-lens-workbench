"""User-requested original interactive viewer; no optimizer or modified renderer."""
import argparse,hashlib,json
from pathlib import Path
def main():
 p=argparse.ArgumentParser();p.add_argument('--request',required=True);a=p.parse_args();req=json.loads(Path(a.request).read_text(encoding='utf-8'))
 raw=Path(req['source']).read_bytes()
 if hashlib.sha256(raw).hexdigest()!=req['source_sha256']:raise ValueError('交互3D来源已变化')
 data=json.loads(raw);engine=req['engine']
 from analysis_isolation import install
 install(engine)
 if engine=='optiland':
  from native_sources import configure_optiland_runtime
  configure_optiland_runtime()
  from optiland_bridge import prescription_to_optiland
  model,_=prescription_to_optiland(req['source'],preserve_apertures=True);waves=data['wvln_ls']
 else:
  from native_sources import configure_paths,configure_analysis_runtime
  configure_paths();configure_analysis_runtime()
  from glass_selection import catalog_data
  import deeplens.material.materials as materials
  if data.get('glass_catalog'):materials.MATERIAL_data.update(catalog_data(data['glass_catalog'],data.get('glass_catalog_revision'))['dispersion'])
  from deeplens import GeoLens
  import torch
  model=GeoLens(filename=req['source'],device=torch.device('cpu'));waves=[float(data['wvln_primary'])]
 from native_3d import make_renderer
 make_renderer(model,engine,data,waves,interactive=True,ignore_object=req.get('ignore_object',True))
if __name__=='__main__':main()
