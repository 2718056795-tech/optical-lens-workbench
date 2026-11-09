"""Read-only metrics through an independent native Optiland model, no AutoLens."""
import json,math
from pathlib import Path
import numpy as np

def scalar(value):
    v=float(np.asarray(value).item())
    return v if math.isfinite(v) else None

def valid_rays(ray):
    x=np.asarray(ray.x).reshape(-1);y=np.asarray(ray.y).reshape(-1)
    intensity=np.asarray(ray.i).reshape(-1)
    valid=np.isfinite(x)&np.isfinite(y)&np.isfinite(intensity)&(intensity>0)
    return x,y,valid

def evaluate_snapshot(path,params):
    from optiland_bridge import prescription_to_optiland
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    model,_=prescription_to_optiland(path,preserve_apertures=True)
    req=data['design_requirements'];scale=float(model.fields.max_field) or 1.
    waves=req['spectrum']['wavelengths_um'];weights=req['spectrum']['weights'];primary=req['spectrum']['primary_um']
    rings=int(params.get('num_ring') or 5)
    def normalized(f):return ((f['x'],f['y']) if req['object_at_infinity'] else (f['object_x_mm'],f['object_y_mm']))
    rows=[];rms_values=[];rms_weights=[];fractions=[]
    for wi,wave in enumerate(waves):
        for f in req['fields']:
            hx,hy=normalized(f);weight=f['weight']*weights[wi];failure=None
            try:
                ray=model.trace(hx/scale,hy/scale,wave,num_rays=rings,distribution='hexapolar')
                x,y,valid=valid_rays(ray);fraction=float(valid.mean()) if valid.size else 0.
                xy=np.column_stack((x[valid],y[valid]))
                value=float(np.sqrt(np.mean(np.sum((xy-xy.mean(0))**2,axis=1)))) if len(xy)>=2 else None
            except Exception as exc:fraction=0.;value=None;failure=str(exc)
            fractions.append(fraction)
            if value is not None:rms_values.append(value);rms_weights.append(weight)
            rows.append(dict(field_index=f['index'],wavelength_um=wave,weight=weight,rms_mm=value,valid_fraction=fraction,error=failure))
    def chief(hx,hy):
        try:
            ray=model.trace_generic(Hx=hx,Hy=hy,Px=0.,Py=0.,wavelength=primary)
            x,y,valid=valid_rays(ray)
            if not valid.size or not valid[0]:return None
            n=scalar(np.asarray(ray.N).reshape(-1)[0])
            return (float(x[0]),float(y[0]),n)
        except Exception:return None
    cra=[];dist=[];target_error=[];near=chief(0.,.001)
    for f in req['fields']:
        hx,hy=normalized(f);hx/=scale;hy/=scale;out=chief(hx,hy)
        if out is None:continue
        if out[2] is not None:cra.append(math.degrees(math.acos(np.clip(out[2],-1.,1.))))
        if near is not None and (hx or hy):
            factor=math.hypot(math.tan(math.radians(hx*scale)),math.tan(math.radians(hy*scale)))/math.tan(math.radians(.001*scale)) if req['object_at_infinity'] else math.hypot(hx,hy)/.001
            expected=math.hypot(near[0],near[1])*factor
            if expected>1e-12:dist.append(abs(math.hypot(out[0],out[1])/expected-1)*100)
        target=np.array([f['target_x_mm'],f['target_y_mm']]);height=float(np.linalg.norm(target))
        if height>1e-12:target_error.append(float(np.linalg.norm(np.array(out[:2])-target))/height*100)
    efl=scalar(model.paraxial.f2());epd=scalar(model.paraxial.EPD());fnum=scalar(model.paraxial.FNO())
    rms=sum(v*w for v,w in zip(rms_values,rms_weights))/sum(rms_weights) if rms_values and sum(rms_weights)>0 else None
    polychromatic=params.get('optiland_spot_reference')=='polychromatic'
    if polychromatic:
        from optiland.optimization.operand import RayOperand
        values=[]
        for f in req['fields']:
            if f['weight']<=0:continue
            hx,hy=normalized(f)
            try:value=scalar(RayOperand.rms_spot_size(model,-1,hx/scale,hy/scale,rings,'all',distribution='hexapolar'))
            except Exception:value=None
            values.append((value,f['weight']))
        rms=sum(v*w for v,w in values)/sum(w for v,w in values) if values and all(v is not None for v,w in values) else None
    return dict(efl_mm=efl,fnum=fnum,fnum_recorded=data.get('fnum'),entrance_pupil_diameter_mm=epd,
                full_fov_deg=math.degrees(2*math.atan2(req['sensor_radius_mm'],efl)) if efl is not None and efl>0 else None,
                full_fov_definition='2*atan(sensor_radius/native paraxial_efl); inferred, not a traced clear field',
                rms_spot_mm=rms,valid_fraction=sum(fractions)/len(fractions),valid_fraction_min=min(fractions),
                bfl_mm=float(data['surfaces'][-1]['d_next']),track_mm=float(data['(d_sensor)'])-float(data['surfaces'][0]['(d)']),
                cra_max_deg=max(cra) if cra else None,cra_mean_deg=sum(cra)/len(cra) if cra else None,distortion_max_pct=max(dist) if dist else None,
                target_image_error_max_pct=max(target_error) if target_error else None,
                evaluation_protocol='v7-optiland-native-v1: independent native model, iterative stop aiming, hexapolar pupil, complete fields/waves',
                rms_definition=(f'Weighted mean native polychromatic RMS about primary centroid, nan_policy=propagate, {len(req["fields"])} fields x {len(waves)} wavelengths' if polychromatic else f'Weighted mean of per-wavelength valid-ray centroid RMS over {len(req["fields"])} fields x {len(waves)} wavelengths'),
                distortion_definition='native aimed chief-ray paraxial f-tan distortion; target image error separate',
                design_field_count=len(req['fields']),field_results=rows,wavelengths_um=waves,primary_wavelength_um=primary,rms_samples_available=len(rms_values),
                pupil_distribution='hexapolar',pupil_rings=rings,evaluation_engine='optiland')
