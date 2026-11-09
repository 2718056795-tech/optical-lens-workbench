"""Approved input/configuration adapters around unchanged upstream functions.

Never replaces RMS, refraction, Adam or either native training loop.
"""
from contextlib import contextmanager
from pathlib import Path
from types import MethodType
import math

class StopRequested(Exception):pass

class LensSession:
    def __init__(self,params,contract,out,publish):
        self.params=params;self.contract=contract;self.out=Path(out);self.publish=publish
        self.counts={k:0 for k in ('optimizer_steps','correct_shape','prune_surf','analysis')}
        self.stage='init';self.iteration=0;self.lens=None;self.material_variable_surfaces=[]

    def apply_limits(self,lens):
        from optimizer_runner import MECH_KEYS,opt
        for key in MECH_KEYS:
            value=opt(self.params,key)
            if value is not None:setattr(lens,key,value)
        if self.params.get('cra_cap') not in (None,''):
            lens.sensor_cra_cap=float(self.params['cra_cap'])
            lens.chief_ray_angle_max=min(math.degrees(float(lens.rfov_eff)),lens.sensor_cra_cap)
        if self.params.get('distortion_max') not in (None,''):lens.distortion_max=float(self.params['distortion_max'])

    def attach(self,lens):
        import torch
        self.lens=lens
        contract=self.contract;params=self.params;session=self
        if contract:
            contract.attach(lens)
            weights=[f['weight'] for f in contract.req['fields']]
            if max(weights)-min(weights)>1e-12:
                raise ValueError('AutoLens原生RMS使用自适应视场权重；额外非等权视场尚未接入，不能静默忽略')
        original_get=lens.get_optimizer;original_shape=lens.correct_shape;original_prune=lens.prune_surf
        original_analysis=lens.analysis;original_write=lens.write_lens_json;original_post=lens.post_computation
        original_regularizer=lens.loss_reg
        original_sample_fov=lens.sample_from_fov
        original_reference=lens.psf_center
        def configured_regularizer(_self,*args,**kwargs):
            for name in ('cra','ray_bend','clearance','envelope','profile'):
                key='w_'+name
                if key not in kwargs and params.get(key) not in (None,''):kwargs[key]=float(params[key])
            return original_regularizer(*args,**kwargs)
        lens.loss_reg=MethodType(configured_regularizer,lens)

        def sample_fields(wavelength,count,scale):
            if not contract:raise RuntimeError('完整视场采样要求明确设计条件')
            if contract.req['object_at_infinity']:
                from deeplens.ray import Ray
                bundles=[original_sample_fov(fov_x=f['x'],fov_y=f['y'],depth=float('inf'),num_rays=count,wvln=wavelength,scale_pupil=scale) for f in contract.req['fields']]
                return Ray(torch.stack([r.o for r in bundles])[:,None],torch.stack([r.d for r in bundles])[:,None],wavelength,device=lens.device)
            points=torch.tensor(contract.points,device=lens.device,dtype=lens.surfaces[0].d.dtype)[:,None,:]
            return lens.sample_from_points(points,num_rays=count,wvln=wavelength,scale_pupil=scale)

        if contract:
            def explicit_sampler(_self,num_ring=8,num_arm=1,spp=512,depth=None,wvln=None,scale_pupil=1.,**kwargs):
                return sample_fields(lens.wvln_primary if wvln is None else wvln,spp,scale_pupil)
            lens.sample_ring_arm_rays=MethodType(explicit_sampler,lens)
            def reference_input(_self,points_obj,method='chief_ray'):
                if method=='pinhole' and points_obj.shape[0]==len(contract.targets):
                    return -points_obj.new_tensor(contract.targets)[:,None,:].expand(*points_obj.shape[:-1],2)
                return original_reference(points_obj,method=method)
            lens.psf_center=MethodType(reference_input,lens)

        def prune(_self,*args,**kwargs):
            session.counts['prune_surf']+=1
            if not contract:return original_prune(*args,**kwargs)
            # Native aperture computation/capping stays intact. Only replace its
            # hard-coded Y fan with the explicitly requested full XY field list.
            def full_field_fan(_self,*unused,**kw):
                return sample_fields(kw.get('wvln',lens.wvln_primary),int(kw.get('num_rays',512)),float(kw.get('scale_pupil',1.)))
            saved=lens.sample_from_fov;lens.sample_from_fov=MethodType(full_field_fan,lens)
            try:return original_prune(*args,**kwargs)
            finally:lens.sample_from_fov=saved
        lens.prune_surf=MethodType(prune,lens)

        def shape(_self,*args,**kwargs):
            session.counts['correct_shape']+=1
            result=original_shape(*args,**kwargs)
            if contract:contract.project(lens)
            session.apply_limits(lens);return result
        lens.correct_shape=MethodType(shape,lens)

        def get_optimizer(_self,*args,**kwargs):
            if contract and contract.cover and kwargs.get('optim_mat',False):
                # Native supported parameter: optimize main surfaces, excluding
                # the fixed plane cover and its material. Native Adam unchanged.
                allowed=kwargs.get('optim_surf_range')
                if allowed is None:allowed=lens.find_diff_surf()
                kwargs['optim_surf_range']=[i for i in allowed if i not in contract.plane_indices]
                session.material_variable_surfaces=[i for i in kwargs['optim_surf_range'] if lens.surfaces[i].mat2.name!='air']
            optimizer=original_get(*args,**kwargs)
            def after_step(_optimizer,_args,_kwargs):
                session.counts['optimizer_steps']+=1;session.iteration+=1
                if contract:contract.project(lens)
                if (session.out/'stop.flag').exists():raise StopRequested()
                session.publish(lens,session.stage,session.iteration,None)
            optimizer.register_step_post_hook(after_step)
            return optimizer
        lens.get_optimizer=MethodType(get_optimizer,lens)

        def analysis(_self,*args,**kwargs):
            session.counts['analysis']+=1
            # Plot-only sampling budget; no objective or optimizer is replaced.
            kwargs.setdefault('num_rays',int(params.get('spp') or 64));kwargs.setdefault('num_fov',3)
            result=original_analysis(*args,**kwargs)
            session.publish(lens,session.stage,session.iteration,None,measure=True)
            return result
        lens.analysis=MethodType(analysis,lens)

        def write(_self,path,*args,**kwargs):
            result=original_write(path,*args,**kwargs)
            from glass_selection import stamp_json
            from spectrum import stamp_spectrum
            stamp_json(path,params['glass_selection']);stamp_spectrum(path,params)
            if contract:contract.stamp(path,lens)
            return result
        lens.write_lens_json=MethodType(write,lens)

        def post(_self,*args,**kwargs):
            result=original_post(*args,**kwargs);session.apply_limits(lens)
            if contract:contract.attach(lens)
            return result
        lens.post_computation=MethodType(post,lens)
        self.apply_limits(lens)
        return lens

@contextmanager
def selected_catalog(params):
    """Provide a selected catalog to the unchanged native n/V matcher."""
    from glass_selection import catalog_data
    import deeplens.material.materials as materials
    selection=params['glass_selection'];data=catalog_data(selection['catalog'],selection['revision'])
    original=materials.CUSTOM_data['CDGM_GLASS']
    materials.CUSTOM_data['CDGM_GLASS']={name.lower():[data['dispersion'][name.lower()]['nd'],data['dispersion'][name.lower()]['vd']] for name in selection['allowed_glasses']}
    try:yield
    finally:materials.CUSTOM_data['CDGM_GLASS']=original
