"""Application configuration using native variables/operands, no solver replacement."""
import math
import numpy as np

def build_problem(model,data,p,contract,full,audit,control=None):
    from optiland.optimization import OptimizationProblem
    from optiland.optimization.operand import operand_registry
    problem=OptimizationProblem(batching=False)
    count=len(data['surfaces']);primary=p['spectrum']['primary_um'];waves=p['spectrum']['wavelengths_um']
    def thickness(optic,surface_number):return optic.surfaces[surface_number].thickness
    def cra(optic,Hx,Hy,wavelength):
        ray=optic.trace_generic(Hx,Hy,0.,0.,wavelength)
        if not np.isfinite(ray.N).all() or not (np.asarray(ray.i)>0).all():return float('nan')
        return math.degrees(math.acos(np.clip(float(np.asarray(ray.N).reshape(-1)[0]),-1,1)))
    def distortion(optic,Hx,Hy,wavelength):
        near=optic.trace_generic(0.,.001,0.,0.,wavelength)
        nh=math.hypot(float(np.asarray(near.x).reshape(-1)[0]),float(np.asarray(near.y).reshape(-1)[0]))
        ray=optic.trace_generic(Hx,Hy,0.,0.,wavelength)
        if not np.isfinite(ray.x).all() or not (np.asarray(ray.i)>0).all():return float('nan')
        height=math.hypot(float(np.asarray(ray.x).reshape(-1)[0]),float(np.asarray(ray.y).reshape(-1)[0]))
        scale=float(optic.fields.max_field)
        factor=math.hypot(math.tan(math.radians(Hx*scale)),math.tan(math.radians(Hy*scale)))/math.tan(math.radians(.001*scale)) if contract.req['object_at_infinity'] else math.hypot(Hx,Hy)/.001
        return abs(height/max(nh*factor,1e-12)-1)
    for name,fn in [('workbench_thickness',thickness),('workbench_cra',cra),('workbench_distortion',distortion)]:
        if name not in operand_registry:operand_registry.register(name,fn)
    def add(name,weight=1.,**kw):
        fn=operand_registry.get(name);alias='application_scalar_'+name
        if alias not in operand_registry:
            def scalar(_fn=fn,**inputs):
                guard=inputs.pop('__workbench_control',None)
                if guard:guard()
                v=np.asarray(_fn(**inputs))
                if v.size!=1:raise ValueError('光学操作数必须返回单值')
                return float(v.item())
            operand_registry.register(alias,scalar)
        public_inputs=dict(kw.get('input_data',{}))
        if control:kw['input_data']=dict(public_inputs,__workbench_control=lambda _name=name:control(_name))
        problem.add_operand(alias,weight=weight,**kw)
        audit['operands'].append(dict(stage='refine' if full else 'initial',native=name,adapter=alias,
              origin='workbench extra' if name.startswith('workbench_') else 'native',weight=weight,
              target=kw.get('target'),min=kw.get('min_val'),max=kw.get('max_val'),input={k:v for k,v in public_inputs.items() if k!='optic'}))
    add('f2',target=float(p['foclen']),weight=1/(.01*float(p['foclen'])),input_data=dict(optic=model))
    add('EPD',target=float(p['foclen'])/float(p['fnum']),weight=1/(.03*float(p['foclen'])/float(p['fnum'])),input_data=dict(optic=model))
    for i,s in enumerate(data['surfaces']):
        if s['type']!='Spheric' or i in contract.plane_indices:continue
        bound=.999/max(float(s['r']),.001)
        problem.add_variable(model,'reciprocal_radius',surface_number=i+1,min_val=-bound,max_val=bound)
    if full:
        for i,s in enumerate(data['surfaces']):
            if contract.cover and i>=contract.cover['front_index']:continue
            prefix='bfl' if i==count-1 else 'thick_center' if s.get('mat2','air').lower()!='air' else 'air_center'
            problem.add_variable(model,'thickness',surface_number=i+1,min_val=float(p[prefix+'_min']),max_val=float(p[prefix+'_max']))
        scale=float(model.fields.max_field) or 1.
        for f in contract.req['fields']:
            if f['weight']<=0:continue  # User-selected zero merit weight; field stays in the model/analysis.
            fx,fy=((f['x'],f['y']) if contract.req['object_at_infinity'] else (f['object_x_mm'],f['object_y_mm']))
            fx/=scale;fy/=scale;ray=dict(optic=model,surface_number=-1,Hx=fx,Hy=fy,Px=0.,Py=0.,wavelength=primary)
            if p['optiland_spot_reference']=='polychromatic':
                add('rms_spot_size',target=0.,weight=math.sqrt(f['weight']),input_data=dict(optic=model,surface_number=-1,Hx=fx,Hy=fy,num_rays=int(p['num_ring']),wavelength='all',distribution='hexapolar'))
            else:
                for wi,w in enumerate(waves):add('rms_spot_size',target=0.,weight=math.sqrt(f['weight']*p['spectrum']['weights'][wi]),input_data=dict(optic=model,surface_number=-1,Hx=fx,Hy=fy,num_rays=int(p['num_ring']),wavelength=w,distribution='hexapolar'))
            if f.get('explicit_target'):
                for axis in ('x','y'):add('real_'+axis+'_intercept',target=f['target_'+axis+'_mm'],weight=p['optiland_target_weight']*math.sqrt(f['weight']),input_data=ray)
            if fx or fy:
                if p.get('cra_cap') not in (None,'') and p['w_cra']>0:add('workbench_cra',max_val=float(p['cra_cap']),weight=math.sqrt(p['w_cra'])/5,input_data=dict(optic=model,Hx=fx,Hy=fy,wavelength=primary))
                if p.get('distortion_max') not in (None,'') and p['w_dist']>0:add('workbench_distortion',max_val=float(p['distortion_max']),weight=p['w_dist'],input_data=dict(optic=model,Hx=fx,Hy=fy,wavelength=primary))
        add('total_track',min_val=float(p['ttl_min']),max_val=float(p['ttl_max']),weight=10.,input_data=dict(optic=model))
        add('workbench_thickness',min_val=float(p['bfl_min']),max_val=float(p['bfl_max']),weight=10.,input_data=dict(optic=model,surface_number=count))
    else:
        for number in range(1,6):add('seidel',target=0.,weight=1.,input_data=dict(optic=model,seidel_number=number))
    # Native edge-thickness operands are active in both stages.
    for i,s in enumerate(data['surfaces'][:-1]):
        if contract.cover and i>=contract.cover['front_index']:continue
        prefix='thick_edge' if s.get('mat2','air').lower()!='air' else 'air_edge'
        add('edge_thickness',min_val=float(p[prefix+'_min']),max_val=float(p[prefix+'_max']),weight=p['optiland_edge_weight'],input_data=dict(optic=model,surface_number=i+1))
    return problem
