"""Generic condition adapter; no optimization algorithm is implemented here."""
import copy,json
from pathlib import Path


class DesignContract:
    def __init__(self,params):
        self.params=params;self.req=copy.deepcopy(params['requirements'])
        self.stop=self.req['stop_index'];self.count=self.req['surface_count']
        self.groups=self.req['surf_list'];self.cover=self.req['cover']
        self.plane_indices=[] if not self.cover else [self.cover['front_index'],self.cover['front_index']+1]
        self.points=[[f['object_x_mm'],f['object_y_mm'],f['object_z_mm']] for f in self.req['fields']]
        self.targets=[[f['target_x_mm'],f['target_y_mm']] for f in self.req['fields']]
        self.field_weights=[f['weight'] for f in self.req['fields']]

    def attach(self,lens):
        lens.design_fields=self.req['fields'];lens.design_requirements=self.req

    def restore_materials(self,lens):
        from deeplens.material import Material
        for index,name in zip(self.req['glass_indices'],self.req['fixed_glasses']):
            lens.surfaces[index].mat2=Material(name,device=lens.device)
        if self.cover:lens.surfaces[self.cover['front_index']].mat2=Material(self.cover['material'],device=lens.device)

    def initialize(self,lens):
        if len(lens.surfaces)!=self.count or lens.aper_idx!=self.stop:raise ValueError('种子拓扑与设计条件不一致')
        lens.r_sensor=self.req['sensor_radius_mm'];self.restore_materials(lens)
        if self.req['fixed_stop_radius_mm'] is not None:lens.surfaces[self.stop].update_r(self.req['fixed_stop_radius_mm'])
        self.attach(lens);self.project(lens)

    def anchors(self,gaps):
        lower=self.req['minimum_gaps_mm'];total=sum(gaps)
        total=self.req['fixed_ttl_mm'] or min(self.req['ttl_cap_mm'],max(total,sum(lower)+1e-6))
        zstop=self.req['fixed_stop_z_mm']
        if zstop is not None:total=max(total,zstop+sum(lower[self.stop:])+1e-6)
        if total>self.req['ttl_cap_mm']+1e-7:raise ValueError('固定条件与总长上限发生冲突')
        anchors={0:0.,self.count:total}
        if zstop is not None:anchors[self.stop]=zstop
        if self.cover:
            front=self.cover['front_index'];gap=self.cover['gap_mm'];thick=self.cover['thickness_mm']
            anchors[front]=total-gap-thick;anchors[front+1]=total-gap
        return sorted(anchors.items())

    def project_gaps(self,gaps):
        import numpy as np
        t=np.asarray(gaps,dtype=float).copy();lower=np.array(self.req['minimum_gaps_mm'])
        anchors=self.anchors(t)
        for (a,za),(b,zb) in zip(anchors[:-1],anchors[1:]):
            budget=zb-za;floor=lower[a:b]
            if budget<floor.sum()-1e-7:raise ValueError('固定面位置造成间隔不足')
            if b-a==1:t[a]=budget;continue
            free=np.maximum(t[a:b]-floor,1e-6)
            t[a:b]=floor+free/free.sum()*max(0,budget-floor.sum())
        return t

    def project(self,lens):
        import torch
        with torch.no_grad():
            ds=[float(s.d) for s in lens.surfaces]+[float(lens.d_sensor)]
            t=self.project_gaps([b-a for a,b in zip(ds[:-1],ds[1:])]);z=0.
            for surface,gap in zip(lens.surfaces,t):surface.d.fill_(z);z+=gap
            lens.d_sensor.fill_(z)
            for i in self.plane_indices:lens.surfaces[i].c.zero_()
        self.attach(lens)

    def sample(self,lens,spp,wavelength,scale=1.):
        import torch
        if self.req['object_at_infinity']:
            from deeplens.ray import Ray
            bundles=[lens.sample_from_fov(fov_x=f['x'],fov_y=f['y'],depth=float('inf'),num_rays=spp,wvln=wavelength,scale_pupil=scale) for f in self.req['fields']]
            return Ray(torch.stack([r.o for r in bundles])[:,None],torch.stack([r.d for r in bundles])[:,None],wavelength,device=lens.device)
        points=torch.tensor(self.points,device=lens.device,dtype=lens.surfaces[0].d.dtype)[:,None,:]
        return lens.sample_from_points(points,num_rays=spp,wvln=wavelength,scale_pupil=scale)

    def para_loss(self,lens):
        base=lens.surfaces[0].d;one=base.new_ones(());zero=base.new_zeros(())
        A,B,C,D=one,zero,zero,one;n0=one;pre=None
        wavelength=self.req['spectrum']['primary_um']
        for i,s in enumerate(lens.surfaces):
            n=s.mat2.refractive_index(wavelength);curve=getattr(s,'c',zero)
            if getattr(s,'ai2',None) is not None:curve=curve+2*s.ai2
            power=(n-n0)*curve;C,D=C-power*A,D-power*B
            if i==self.stop:pre=A
            if i+1<len(lens.surfaces):
                t=(lens.surfaces[i+1].d-s.d)/n;A,B=A+t*C,B+t*D
            n0=n
        t=lens.d_sensor-lens.surfaces[-1].d;A,B=A+t*C,B+t*D
        focal=self.req['focal_length_mm'];diameter=2*float(lens.surfaces[self.stop].r)
        target_pre=diameter/(focal/self.req['fnum'])
        focus=A/.01 if self.req['object_at_infinity'] else (A*self.req['object_distance_mm']+B)/5
        return ((C*focal+1)/.01).square().mean()+((pre-target_pre)/.02).square().mean()+focus.square().mean()

    def distortion_loss(self,lens):
        import math,torch
        cap=self.params.get('distortion_max')
        if cap in (None,''):return lens.d_sensor.new_zeros(())
        primary=self.req['spectrum']['primary_um'];infinity=self.req['object_at_infinity'];angle=1e-3
        with torch.no_grad():
            near=lens.sample_from_fov(fov_x=0.,fov_y=angle,depth=float('inf') if infinity else -self.req['object_distance_mm'],num_rays=1,wvln=primary,scale_pupil=1e-6)
            fields=self.sample(lens,1,primary,1e-6)
        n=lens.trace2sensor(near);r=lens.trace2sensor(fields)
        plate=n.o.reshape(-1,3)[0,:2].norm()/math.tan(math.radians(angle))
        tangent=[math.hypot(math.tan(math.radians(f['x'])),math.tan(math.radians(f['y']))) if infinity else math.hypot(f['object_x_mm'],f['object_y_mm'])/self.req['object_distance_mm'] for f in self.req['fields']]
        t=plate.new_tensor(tangent);actual=r.o.reshape(len(tangent),3)[:,:2].norm(dim=-1);ideal=plate*t
        distortion=(actual/ideal.clamp_min(1e-8)-1).abs()
        penalty=((distortion-float(cap))/float(cap)).clamp_min(0)
        valid=r.is_valid.reshape(-1).bool() & n.is_valid.reshape(-1)[0].bool()
        penalty=torch.where(valid,penalty,torch.full_like(penalty,10.))
        weights=plate.new_tensor(self.field_weights)*(t>1e-8)
        return (penalty*weights).sum()/weights.sum().clamp_min(1e-8)

    def stamp(self,path,lens=None):
        p=Path(path);d=json.loads(p.read_text(encoding='utf-8'))
        if lens is not None:
            d['(d_sensor)']=float(lens.d_sensor.detach())
            for i,(saved,surface) in enumerate(zip(d['surfaces'],lens.surfaces)):
                saved['(d)']=float(surface.d.detach());saved['r']=float(surface.r)
                end=lens.surfaces[i+1].d if i+1<len(lens.surfaces) else lens.d_sensor
                saved['d_next']=float((end-surface.d).detach())
                if hasattr(surface,'c'):
                    c=float(surface.c.detach());saved['(c)']=c;saved['roc']=1/c if abs(c)>1e-14 else 1e14
                if hasattr(surface,'k'):
                    saved['k']=float(surface.k.detach())
                    saved['ai']=([float(surface.ai2.detach())] if surface.ai2 is not None else [])+[float(getattr(surface,f'_ai{2*(j+2)}').detach()) for j in range(surface.ai_degree)]
                    saved['use_ai2']=surface.ai2 is not None
        d['design_requirements']=self.req;d['design_fields']=self.req['fields'];d['object_at_infinity']=self.req['object_at_infinity']
        # V1's preserved JSON reader uses the Windows system encoding. ASCII
        # escapes keep Chinese metadata lossless without editing that library.
        p.write_text(json.dumps(d,ensure_ascii=True,indent=1,allow_nan=False),encoding='utf-8')

    def verify(self,data,allow_model_glass=False):
        from exchange_validation import verify_requirements
        report=verify_requirements(data,self.req,allow_model_glass=allow_model_glass)
        if not report['passed']:raise ValueError('条件核验失败：'+'；'.join(report['errors']))
        return report

    def configure_optiland(self,model):
        infinity=self.req['object_at_infinity'];model.fields.fields.clear();model.fields.set_type('angle' if infinity else 'object_height')
        for f in self.req['fields']:model.fields.add(x=f['x'] if infinity else f['object_x_mm'],y=f['y'] if infinity else f['object_y_mm'],weight=f['weight'])
        model.ray_tracer.set_aiming('iterative',max_iter=12,tol=1e-7)


def load(params):
    return DesignContract(params) if params.get('requirements') else None
