"""Validated public Optiland inputs; no changes to installed optical code."""
import math

VERSION='optiland-native-inputs-v2'
def normalize(p):
    legacy=p.get('optiland_input_version')!=VERSION
    defaults=dict(optiland_solver='trf',optiland_tol=.001,optiland_x_scale='default',
                  optiland_spot_reference='monochromatic' if legacy else 'polychromatic',
                  optiland_aiming='iterative',optiland_aiming_iters=12,optiland_aiming_tol=1e-7,
                  optiland_geometry_mode='v7_compat' if legacy else 'native',
                  optiland_glass_mode='fixed',optiland_glass_neighbours=3,
                  optiland_edge_weight=10.,optiland_target_weight=10.)
    for k,v in defaults.items():
        if p.get(k) in (None,''):p[k]=v
    for k,allowed in dict(optiland_solver=('trf','dogbox'),optiland_x_scale=('default','jac'),
                          optiland_spot_reference=('monochromatic','polychromatic'),
                          optiland_aiming=('paraxial','iterative','robust'),
                          optiland_geometry_mode=('native','v7_compat'),optiland_glass_mode=('fixed','expert')).items():
        if p[k] not in allowed:raise ValueError('Optiland输入不受支持：'+k)
    for k,lo,hi in [('optiland_tol',1e-12,.1),('optiland_aiming_tol',1e-12,.01),
                    ('optiland_aiming_iters',1,100),('optiland_glass_neighbours',2,32),
                    ('optiland_edge_weight',.000001,1e6),('optiland_target_weight',.000001,1e6)]:
        v=float(p[k])
        if not math.isfinite(v) or not lo<=v<=hi:raise ValueError(k+'超出有效范围')
        if k.endswith(('iters','neighbours')):
            if not v.is_integer():raise ValueError(k+'需为整数')
            v=int(v)
        p[k]=v
    if p['optiland_geometry_mode']=='native' and any(p.get(k) not in (None,'') for k in ('fixed_stop_z_mm','fixed_ttl_mm')):
        raise ValueError('固定光阑坐标/固定总长请明确选择V7固定几何兼容模式；原生模式不做逐步间隔投影')
    if p['optiland_glass_mode']=='expert' and p.get('fixed_glasses'):
        raise ValueError('自动换玻璃与固定主片牌号冲突，请选择其中一种')
    if int(p.get('num_ring') or 5) not in range(1,33):raise ValueError('Optiland光瞳环数需为1～32')
    for k,default in [('w_cra',1.),('w_dist',10.)]:
        v=float(p.get(k) if p.get(k) not in (None,'') else default)
        if not math.isfinite(v) or v<0:raise ValueError(k+'需为非负有限数')
        p[k]=v
    for k in ('cra_cap','distortion_max'):
        if p.get(k) not in (None,''):
            v=float(p[k])
            if not math.isfinite(v) or v<0 or k=='cra_cap' and v>=90:raise ValueError(k+'超出有效范围')
            p[k]=v
    p['optiland_input_version']=VERSION
    p['optiland_material_model']='agf-formula-v1'
    return p

def configure_model(model,p):
    model.ray_tracer.set_aiming(p['optiland_aiming'],max_iter=p['optiland_aiming_iters'],tol=p['optiland_aiming_tol'])

def compatible_geometry(p):return p.get('optiland_geometry_mode','v7_compat')=='v7_compat'
