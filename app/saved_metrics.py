"""Display saved values without tracing or touching a live optimization model."""
import json,math
from pathlib import Path

def from_json(data,source=None,digest=None):
    f=data.get('foclen');r=data.get('r_sensor')
    field=math.degrees(2*math.atan2(r,f)) if isinstance(f,(int,float)) and f>0 and isinstance(r,(int,float)) else None
    return dict(efl_mm=f,fnum=data.get('fnum'),full_fov_deg=field,wavelengths_um=data.get('wvln_ls',[]),source_file=source,source_sha256=digest,
                evaluation_protocol='native saved JSON values; FOV inferred from sensor radius/focal length',display_kind='saved',rms_spot_mm=None)

def for_scene(root,source,data,digest):
    fallback=from_json(data,source,digest)
    for file,key in [('display_metrics.json',None),('native_preview.json',None),('progress.json','native_preview')]:
        try:
            record=json.loads((Path(root)/file).read_text(encoding='utf-8'))
            if key:record=record.get(key,{})
            if record.get('source_file')==source and record.get('source_sha256')==digest:return dict(fallback,**record)
        except (ValueError,OSError,TypeError):pass
    return fallback
