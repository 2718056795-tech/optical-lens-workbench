"""External starting-value recipe, built through official Optiland APIs only.

This is a documented parameter initialization rule, not an Optiland-provided
arbitrary-spec automatic lens design algorithm. No AutoLens code is imported.
"""
import copy,math
from pathlib import Path
from engine_io import write_json

def initialize(params,out):
    from design_contract import load
    from glass_selection import catalog_data,resolve_selection,stamp_json
    from spectrum import stamp_spectrum
    from optiland_bridge import prescription_to_optiland
    contract=load(params)
    if contract is None:raise ValueError('Optiland独立初始化要求完整技术条件，请通过工作台提交')
    req=contract.req;selection=resolve_selection(params);params['glass_selection']=selection
    catalog=catalog_data(selection['catalog'],selection['revision'])['dispersion']
    allowed=selection['allowed_glasses']
    # A reproducible catalog crown starting value. These are initialization
    # values only; the current Optiland route keeps real glasses fixed.
    crown=min(allowed,key=lambda n:((catalog[n.lower()]['nd']-1.52)/.1)**2+((catalog[n.lower()]['vd']-64.)/20.)**2).lower()
    types=[kind for group in req['surf_list'] for kind in group]
    count=len(types);glass_indices=req['glass_indices'];cover=req['cover']
    names={i:crown for i in glass_indices}
    for i,name in zip(glass_indices,req['fixed_glasses']):names[i]=name
    if cover:names[cover['front_index']]=cover['material']
    total=float(req['fixed_ttl_mm'] or req['ttl_cap_mm'])
    gaps=list(req['minimum_gaps_mm']);locked=set()
    if cover:locked.update((count-2,count-1))
    else:
        gaps[-1]=max(gaps[-1],float(params['bfl']));locked.add(count-1)
    spare=total-sum(gaps)
    if spare< -1e-8:raise ValueError('初始BFL、片厚与总长没有可用空间')
    free=[i for i in range(count) if i not in locked]
    if not free:raise ValueError('没有可分配的镜片/空气间隔')
    for i in free:gaps[i]+=max(0.,spare)/len(free)
    gaps=contract.project_gaps(gaps)
    zs=[];z=0.
    for gap in gaps:zs.append(z);z+=float(gap)
    stop=req['stop_index'];stop_r=float(req['fixed_stop_radius_mm'] or req['focal_length_mm']/(2*req['fnum']))
    slope=max(math.hypot(f['object_x_mm'],f['object_y_mm'])/req['object_distance_mm'] for f in req['fields'])
    radii=[max(stop_r+abs(zi-zs[stop])*slope,req['sensor_radius_mm']+stop_r)*1.1+.1 for zi in zs]
    radii[stop]=stop_r
    curves=[0.]*count;cursor=0;main_count=int(params['elements'])
    for group in req['surf_list']:
        if group==['Aperture']:cursor+=1;continue
        indices=list(range(cursor,cursor+len(group)));cursor+=len(group)
        if cover and indices[0]==cover['front_index']:continue
        n_glass=len(group)-1
        power=n_glass/(main_count*req['focal_length_mm'])
        for i,sign,material in [(indices[0],1,names[indices[0]]),(indices[-1],-1,names[indices[-2]])]:
            nd=float(catalog[material.lower()]['nd'])
            curves[i]=sign*min(power/(2*(nd-1)),.8/radii[i])
    surfaces=[]
    for i,(kind,gap) in enumerate(zip(types,gaps)):
        c=curves[i]
        surfaces.append(dict(type=kind,r=float(radii[i]),roc=1/c if c else 1e14,
                             **{'(c)':c,'(d)':zs[i]},d_next=float(gap),mat2=names.get(i,'air')))
    data=dict(surfaces=surfaces,**{'(d_sensor)':z},foclen=req['focal_length_mm'],fnum=req['fnum'],r_sensor=req['sensor_radius_mm'],
              obj_depth=-req['object_distance_mm'],object_at_infinity=req['object_at_infinity'],
              design_fields=copy.deepcopy(req['fields']),design_requirements=copy.deepcopy(req))
    audit=dict(engine='optiland',api='Optic + SurfaceGroup.add',recipe='equal-positive-group-power-v1',
               rule='equal positive group thin-lens powers; neutral cemented interfaces; projected positive thicknesses; catalog crown or specified glasses',
               default_catalog_glass=crown,source='external starting-value adapter, not an official automatic design algorithm',
               autolens_used=False,random_candidates=0)
    data['initialization']=audit
    data['optiland_material_model']='agf-formula-v1'
    path=Path(out)/'initial_prescription.json';write_json(path,data);stamp_json(path,selection);stamp_spectrum(path,params)
    import json
    data=json.loads(path.read_text(encoding='utf-8'));contract.verify(data)
    model,meta=prescription_to_optiland(path,preserve_apertures=True)
    audit['native_surface_count']=len(model.surfaces);audit['model_type']=type(model).__module__+'.'+type(model).__name__
    write_json(Path(out)/'initialization.json',audit)
    return data,model,audit
