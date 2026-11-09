"""Read-only requirement and physical-prescription handoff verification."""
import math


def _finite(x):return isinstance(x,(float,int)) and not isinstance(x,bool) and math.isfinite(x)
def _near(a,b,tol=2e-5):return _finite(a) and _finite(b) and abs(a-b)<=tol
def _curve(s):
    r=s.get('roc')
    return 1/float(r) if r is not None and math.isfinite(float(r)) and float(r)!=0 else 0.


def verify_requirements(data,req,allow_model_glass=False):
    checks=[]
    def check(name,passed,expected=None,actual=None):checks.append(dict(name=name,passed=bool(passed),expected=expected,actual=actual))
    surfaces=data.get('surfaces',[]);count=req['surface_count']
    check('表面数量',len(surfaces)==count,count,len(surfaces))
    check('统一条件版本/内容',data.get('design_requirements')==req,req.get('sha256'),data.get('design_requirements',{}).get('sha256'))
    check('完整视场/次序/权重/目标',data.get('design_fields')==req['fields'],req['fields'],data.get('design_fields'))
    spectrum=req['spectrum']
    check('波长列表及顺序',data.get('wvln_ls')==spectrum['wavelengths_um'],spectrum['wavelengths_um'],data.get('wvln_ls'))
    check('主波长',_near(data.get('wvln_primary'),spectrum['primary_um'],1e-12),spectrum['primary_um'],data.get('wvln_primary'))
    check('波长权重',data.get('spectral_weights')==spectrum['weights'],spectrum['weights'],data.get('spectral_weights'))
    check('物距',_near(abs(data.get('obj_depth',float('nan'))),req['object_distance_mm']),req['object_distance_mm'],data.get('obj_depth'))
    check('有限/无穷远物方',data.get('object_at_infinity',False)==req['object_at_infinity'],req['object_at_infinity'],data.get('object_at_infinity',False))
    check('传感器半径',_near(data.get('r_sensor'),req['sensor_radius_mm']),req['sensor_radius_mm'],data.get('r_sensor'))
    if len(surfaces)==count:
        types=[t for group in req['surf_list'] for t in group]
        check('表面类型及拓扑',[s.get('type') for s in surfaces]==types,types,[s.get('type') for s in surfaces])
        zs=[s.get('(d)') for s in surfaces];image=data.get('(d_sensor)')
        check('有限坐标与正口径',all(_finite(z) for z in zs) and _finite(image) and all(_finite(s.get('r')) and s['r']>0 for s in surfaces))
        if all(_finite(z) for z in zs) and _finite(image):
            check('首面坐标',_near(zs[0],0),0,zs[0])
            end=zs[1:]+[image]
            check('间隔与坐标一致',all(_near(s.get('d_next'),b-a) and b>a for s,a,b in zip(surfaces,zs,end)))
            ttl=image-zs[0]
            check('总长上限',ttl<=req['ttl_cap_mm']+2e-5,req['ttl_cap_mm'],ttl)
            if req['fixed_ttl_mm'] is not None:check('固定总长',_near(ttl,req['fixed_ttl_mm']),req['fixed_ttl_mm'],ttl)
            stop=surfaces[req['stop_index']]
            if req['fixed_stop_z_mm'] is not None:check('固定光阑坐标',_near(zs[req['stop_index']]-zs[0],req['fixed_stop_z_mm']),req['fixed_stop_z_mm'],zs[req['stop_index']]-zs[0])
            if req['fixed_stop_radius_mm'] is not None:check('固定光阑半径',_near(stop.get('r'),req['fixed_stop_radius_mm']),req['fixed_stop_radius_mm'],stop.get('r'))
            if req['cover']:
                cover=req['cover'];i=cover['front_index']
                check('保护片厚度',_near(zs[i+1]-zs[i],cover['thickness_mm']),cover['thickness_mm'],zs[i+1]-zs[i])
                check('保护片至像面间距',_near(image-zs[i+1],cover['gap_mm']),cover['gap_mm'],image-zs[i+1])
                check('保护片平面',abs(_curve(surfaces[i]))<1e-12 and abs(_curve(surfaces[i+1]))<1e-12)
                check('保护片材料',surfaces[i].get('mat2','').lower()==cover['material'],cover['material'],surfaces[i].get('mat2'))
        names=[s.get('mat2','').lower() for s in surfaces]
        glass_set=set(req['glass_indices']);allowed={n.lower() for n in req['glass_selection']['allowed_glasses']}
        def model(name):
            try:
                n,v=map(float,name.split('/'));return math.isfinite(n) and math.isfinite(v) and 1<n<4 and 0<v<1000
            except (ValueError,TypeError):return False
        check('课程中间MODEL/目录玻璃与空气拓扑' if allow_model_glass else '真实玻璃池与空气拓扑',all((name in allowed or allow_model_glass and model(name)) if i in glass_set else name=='air' for i,name in enumerate(names)))
        for i,name in zip(req['glass_indices'],req['fixed_glasses']):check(f'第{i+1}面固定玻璃',names[i]==name,name,names[i])
    for key,rkey in [('glass_catalog','catalog'),('glass_catalog_revision','revision'),('glass_catalog_sha256','source_sha256')]:
        check(key,data.get(key)==req['glass_selection'][rkey],req['glass_selection'][rkey],data.get(key))
    return dict(passed=all(c['passed'] for c in checks),checks=checks,errors=[c['name'] for c in checks if not c['passed']])


def verify_exchange(source,destination,req,allow_model_glass=False):
    report=verify_requirements(destination,req,allow_model_glass=allow_model_glass);checks=report['checks']
    def check(name,value):checks.append(dict(name=name,passed=bool(value)))
    source_report=verify_requirements(source,req,allow_model_glass=allow_model_glass)
    check('来源条件核验',source_report['passed'])
    a=source.get('surfaces',[]);b=destination.get('surfaces',[])
    same=len(a)==len(b)
    if same:
        for sa,sb in zip(a,b):
            same=same and sa.get('type')==sb.get('type') and str(sa.get('mat2')).lower()==str(sb.get('mat2')).lower()
            same=same and all(_near(sa.get(key),sb.get(key)) for key in ('(d)','d_next','r'))
            same=same and _near(_curve(sa),_curve(sb),1e-8)
            if sa.get('type')=='Aspheric':same=same and sa.get('ai')==sb.get('ai') and sa.get('k')==sb.get('k') and sa.get('use_ai2')==sb.get('use_ai2')
    check('交接前后完整物理处方相同（浮点容差）',same)
    check('交接前后像面与传感器相同',_near(source.get('(d_sensor)'),destination.get('(d_sensor)')) and _near(source.get('r_sensor'),destination.get('r_sensor')))
    report.update(passed=all(c['passed'] for c in checks),errors=[c['name'] for c in checks if not c['passed']],length_tolerance_mm=2e-5,curvature_tolerance_per_mm=1e-8)
    return report


def verify_native(data,model,req):
    """Verify the actual Optiland model, in addition to its exchange JSON."""
    import numpy as np
    from optiland_bridge import glass_ior
    checks=[]
    def check(name,passed):checks.append(dict(name=name,passed=bool(passed)))
    fields=model.fields.fields
    infinity=req['object_at_infinity']
    check('实际内核视场表',len(fields)==len(req['fields']) and all(_near(float(a.x),b['x'] if infinity else b['object_x_mm'],1e-10) and _near(float(a.y),b['y'] if infinity else b['object_y_mm'],1e-10) and _near(float(a.weight),b['weight'],1e-12) for a,b in zip(fields,req['fields'])))
    waves=model.wavelengths.get_wavelengths()
    check('实际内核波长表',np.allclose(waves,req['spectrum']['wavelengths_um'],rtol=0,atol=1e-12) if len(waves)==len(req['spectrum']['wavelengths_um']) else False)
    check('实际内核主波长',_near(float(model.wavelengths.primary_wavelength.value),req['spectrum']['primary_um'],1e-12))
    check('实际内核波长权重',np.allclose(model.wavelengths.weights,req['spectrum']['weights'],rtol=0,atol=1e-12))
    check('实际内核表面数',len(model.surfaces)==len(data['surfaces'])+2)
    if len(model.surfaces)==len(data['surfaces'])+2:
        for i,s in enumerate(data['surfaces']):
            actual=model.surfaces[i+1]
            check(f'实际面{i+1}厚度',_near(float(np.asarray(actual.thickness).item()),s['d_next']))
            actual_radius=float(np.asarray(actual.geometry.radius).item())
            check(f'实际面{i+1}曲率',_near(0. if not math.isfinite(actual_radius) else 1/actual_radius,_curve(s),1e-10))
            if s.get('mat2','air').lower()!='air':
                check(f'实际面{i+1}玻璃色散',all(_near(float(np.asarray(actual.material_post.n(w)).item()),glass_ior(s['mat2'],w,data['glass_catalog'],data['glass_catalog_revision']),1e-8) for w in req['spectrum']['wavelengths_um']))
        obj=float(np.asarray(model.surfaces[0].thickness).item())
        check('实际内核物距',math.isinf(obj) if infinity else _near(obj,req['object_distance_mm']))
        stop=model.surfaces[req['stop_index']+1]
        check('实际内核物理光阑',hasattr(stop.aperture,'r_max') and _near(float(stop.aperture.r_max),data['surfaces'][req['stop_index']]['r']))
    return dict(passed=all(c['passed'] for c in checks),checks=checks,errors=[c['name'] for c in checks if not c['passed']])
