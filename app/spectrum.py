"""Canonical wavelength ranges in nm; engines use micrometres internally."""
import json
import math
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch


def resolve_spectrum(params):
    """New optimization tasks always use endpoints and their arithmetic midpoint."""
    from autolens_three_wavelength_input import from_range_nm,from_file_wavelengths_um
    values=[params.get('wavelength_min_nm'),params.get('wavelength_max_nm')]
    if any(v not in (None,'') for v in values):
        if any(v in (None,'') for v in values):raise ValueError('请同时填写两个波长端点，单位nm')
        result=from_range_nm(*values)
    elif params.get('spectral_samples_um') is not None:
        result=from_file_wavelengths_um(params['spectral_samples_um'],params.get('wvln_primary'),params.get('spectral_sample_weights'))
    else:
        waves=[params.get(k) if params.get(k) not in (None,'') else d for k,d in [('wvln_b',.486),('wvln_g',.587),('wvln_r',.656)]]
        result=from_file_wavelengths_um(waves,params.get('wvln_primary'))
    if params.get('source_spectrum') is not None:result['source_spectrum']=params['source_spectrum']
    return dict(result,mode='native-three-v1')

def stamp_spectrum(path,params):
    spectrum=resolve_spectrum(params);p=Path(path);data=json.loads(p.read_text(encoding='utf-8'))
    data.update(wvln_ls=spectrum['wavelengths_um'],wvln_primary=spectrum['primary_um'],
                spectral_weights=spectrum['weights'],spectral_model=spectrum['mode'])
    if math.isinf(float(data.get('obj_depth',0))):
        data['object_at_infinity']=True
        data['obj_depth']=-abs(float(params.get('requirements',{}).get('object_distance_mm') or params.get('obj_depth') or 20000))
    data['wavelength_range_nm']=spectrum['input_range_nm'];data['wavelength_sampling_policy']=spectrum['policy']
    if 'source_spectrum' in spectrum:data['source_spectrum']=spectrum['source_spectrum']
    p.write_text(json.dumps(data,ensure_ascii=True,indent=2,allow_nan=False),encoding='utf-8')


@contextmanager
def primary_ray_context(primary):
    """Set omitted pupil-ray wavelengths locally without editing the V1 snapshot."""
    import deeplens.geolens as module
    original=module.Ray
    def ray(*args,**kwargs):
        if len(args)<3 and 'wvln' not in kwargs:kwargs['wvln']=float(primary)
        return original(*args,**kwargs)
    with patch.object(module,'Ray',ray):yield


def spectral_rms_loss(*args,**kwargs):
    raise RuntimeError('V6禁止调用旧自编光谱损失；使用未修改的AutoLens原生三波长RMS')
