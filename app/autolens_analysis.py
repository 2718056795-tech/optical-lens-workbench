"""Read-only adapters for pinned AutoLens analysis, never Optiland calculations.

Native drawing methods are called without monkey-patching them. The profile
observer only exports returned numerical data and records the native calls.
Plots for numerical-only interfaces are labelled as application presentation.
"""
import base64,hashlib,io,json,math,os,sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from native_sources import AUTO_DIR,configure_paths,verify_autolens
from analysis_catalog import AUTO_CATALOG

def arrays(value,prefix,depth=0):
    if depth>5:return {}
    if hasattr(value,'detach'):value=value.detach().cpu().numpy()
    if isinstance(value,np.ndarray):
        return {prefix:value} if value.dtype.kind in 'biufc' and 0<value.size<=4000000 else {}
    if isinstance(value,(int,float,np.number)):return {prefix:np.asarray(value)}
    if isinstance(value,dict):items=value.items()
    elif isinstance(value,(list,tuple)):items=enumerate(value)
    else:return {}
    result={}
    for key,item in items:result.update(arrays(item,f'{prefix}.{key}',depth+1))
    return result

class Observer:
    methods={'spot_points','calc_distortion_map','psf','psf2mtf','rms_map','vignetting','wavefront_error',
             'seidel_coefficients','tolerancing_sensitivity','tolerancing_monte_carlo','render'}
    def __init__(self,r):self.r=r;self.calls={};self.counts={};self.layout=None;self.origins=None;self.layout_lines=[];self.line_start=0
    def __call__(self,frame,event,result):
        if not frame.f_code.co_filename.startswith(str(AUTO_DIR)):return
        name=frame.f_code.co_name
        if event=='call':
            self.calls[name]=self.calls.get(name,0)+1
            if name=='draw_ray_2d':self.line_start=len(frame.f_locals['ax'].lines)
        elif event=='return':
            if name=='sample_point_source_2D' and result is not None:self.origins=result.o.detach().cpu().numpy().copy()
            if name=='draw_ray_2d' and self.origins is not None:
                self.layout_lines.extend(zip(frame.f_locals['ax'].lines[self.line_start:],self.origins.copy()))
            if name=='draw_layout':self.layout=(frame.f_locals.get('ax'),frame.f_locals.get('fig'))
            if name in self.methods:
                idx=self.counts.get(name,0);self.counts[name]=idx+1
                if idx<64:
                    if name=='spot_points' and result is not None:
                        counts=result.is_valid.detach().sum(dim=-1).cpu().numpy()
                        self.r.summary['fully_blocked_ray_groups']=self.r.summary.get('fully_blocked_ray_groups',0)+int((counts==0).sum())
                        result={'o':result.o,'is_valid':result.is_valid}
                    self.r.arrays.update(arrays(result,f'native.{name}.{idx}'))
            if name=='draw_field_curvature':
                for key in ('rfov_samples','delta_z_tan'):
                    if key in frame.f_locals:self.r.arrays.update(arrays(frame.f_locals[key],key))

def run_analysis(req,progress=lambda *a,**k:None):
    src=Path(req['source']);raw=src.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=req['source_sha256']:raise ValueError('处方在分析启动前已变化')
    data=json.loads(raw);key=req['analysis_id'];o=req['options']
    if data.get('optiland_native_source'):raise ValueError('此导入记录保留原生Optiland模型，请选择Optiland直接分析；尚未验证其到AutoLens的完全等价转换，不以转换后的近似模型冒充原文件。')
    if key not in AUTO_CATALOG:raise ValueError('AutoLens没有该原生分析接口')
    if AUTO_CATALOG[key].get('available') is False:raise ValueError(AUTO_CATALOG[key]['reason'])
    source=verify_autolens();configure_paths()
    import torch
    from deeplens import GeoLens
    from glass_selection import catalog_data
    import deeplens.material.materials as materials
    if data.get('glass_catalog'):
        materials.MATERIAL_data.update(catalog_data(data['glass_catalog'],data.get('glass_catalog_revision'))['dispersion'])
    # Report has no eager import of either optical core.
    from extended_analysis import Report
    r=Report(req,progress);r.allwaves=list(map(float,data['wvln_ls']));r.primary=float(data['wvln_primary'])
    r.waves=r.allwaves if o['wave']=='all' else [r.primary] if o['wave']=='primary' else [float(o['wave'])/1000]
    if any(not any(abs(w-v)<1e-9 for v in r.allwaves) for w in r.waves):raise ValueError('仅能选择保存处方的实际采样波长')
    torch.set_num_threads(2);torch.manual_seed(o['seed']);np.random.seed(o['seed'])
    device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    progress('AutoLens：读取独立处方',device=str(device))
    lens=GeoLens(filename=str(src),device=device)
    depth=float(lens.obj_depth)
    if not math.isfinite(depth) and key not in ('layout','native_3d'):
        raise ValueError('AutoLens此分析接口使用有限物点；当前处方为无限远。为保持源码不自动换成有限物距近似，请改用Optiland分析。')
    n=o['ray_count'];grid=o['grid_points'];ks=o['samples'];radial=o['radial_fields']
    torch.set_grad_enabled(key=='sensitivity')
    r.notes+=['计算来源：固定AutoLens e58db32。官方源码、追迹及分析方法未替换；本项目只做输入、任务隔离、数值导出和界面展示。',
              '原生径向/网格接口使用自身采样规则，不等同保存的全部离散XY视场；“完整设计视场点列”逐一使用保存的XY物点。',
              '几何PSF、相干PSF、Huygens和几何MTF的定义不同，不应直接比较曲线高低。分波长显示不是多色OTF综合。']
    r.summary.update(device=str(device),native_source=source,design_field_count=len(data.get('design_fields',[])),
                     native_sampling=dict(grid_points=grid,ray_count=n,radial_fields=radial,kernel_size=ks))
    if data.get('object_at_infinity') and math.isfinite(depth):r.notes+=[f'处方标记无限远，AutoLens此接口实际按保存的obj_depth={depth:g} mm计算实用无限远；未改物距。Optiland真无限远定义可能不同。']
    def native_plot(label,method,**kw):
        file=f'plot_{len(r.images)+1:02d}.png';path=r.out/file
        method(**kw,show=False)
        if not path.is_file():raise ValueError('原生分析未保存图像')
        r.images.append(dict(file=file,label=label))
    observer=Observer(r);previous=sys.getprofile();sys.setprofile(observer)
    try:
        progress('AutoLens：计算 '+AUTO_CATALOG[key]['label'])
        if key=='native_3d':
            from native_3d import render
            r.waves=[r.primary];render(lens,'autolens',data,r)
        elif key=='layout':
            path=str(r.out/'plot_01.png')
            native_plot('AutoLens 原生 2D 光路',lens.draw_layout,filename=path,depth=depth,wvln_list=r.waves,
                        lens_title='AutoLens native analysis',num_views=radial,num_rays_viz=7,spot_num_rays=n)
            ax,fig=observer.layout
            for i,line in enumerate(ax.lines):r.arrays[f'layout.native.line.{i}']=np.asarray(line.get_xydata()).copy()
            # Original draw_layout propagates rays to z=-1 before tracing. Keep
            # that trace untouched; show its native sampled object origins only
            # by prepending display segments afterwards, never resampling rays.
            for i,(line,origin) in enumerate(observer.layout_lines):
                r.arrays[f'layout.object_origin.{i}']=origin.copy()
                xy=np.vstack(([origin[2],origin[0]],line.get_xydata()));line.set_data(xy[:,0],xy[:,1])
            from view_framing import frame_2d
            positions=[float(s.d) for s in lens.surfaces]+[float(lens.d_sensor)]
            radius=max([float(s.r) for s in lens.surfaces]+[float(lens.r_sensor)])
            r.summary['view_framing']=frame_2d(ax,(min(positions),max(positions)),radius,o.get('ignore_object',True))
            fig.savefig(path,format='png',dpi=300);plt.close(fig)
            r.notes+=['“忽略物面”只切换显示范围；完整物方显示将原生sample_point_source_2D返回的物点与原生绘图光线首点连接，未改物距、采样或追迹。无限远没有有限物面。']
            r.arrays['surface_radius_mm']=np.asarray([float(s.r) for s in lens.surfaces])
        elif key=='spot_fields':
            fields=data.get('design_fields')
            if not fields:raise ValueError('保存处方没有完整设计视场，不能用默认三场冒充；请选择原生径向点列')
            if any(f.get('object_x_mm') is None or f.get('object_y_mm') is None for f in fields):raise ValueError('设计视场缺少有限物点坐标')
            points=torch.tensor([[f['object_x_mm'],f['object_y_mm'],depth] for f in fields],device=device,dtype=lens.dtype)
            cols=min(4,len(fields));rows=math.ceil(len(fields)/cols)
            fig,axs=plt.subplots(rows,cols,figsize=(cols*3.1,rows*3),squeeze=False)
            for w in r.waves:
                ray=lens.spot_points(points,num_rays=n,wvln=w)
                hits=ray.o.detach().cpu().numpy();valid=ray.is_valid.detach().cpu().numpy()>0
                r.arrays.update({f'{w:g}.hits_mm':hits,f'{w:g}.valid':valid})
                for i,f in enumerate(fields):
                    ax=axs.flat[i];mask=valid[i]&np.isfinite(hits[i]).all(axis=-1)
                    ax.scatter(hits[i,mask,0]*1000,hits[i,mask,1]*1000,s=2,label=f'{w*1000:g} nm ({mask.sum()}/{n})')
            for i,f in enumerate(fields):
                ax=axs.flat[i];ax.set(title=f"#{i+1} X={f['x']:g}, Y={f['y']:g}, w={f['weight']:g}",xlabel='Image x (µm)',ylabel='Image y (µm)');ax.set_aspect('equal',adjustable='datalim');ax.legend(fontsize=6)
            for ax in list(axs.flat)[len(fields):]:ax.axis('off')
            fig.tight_layout();r.figure('完整设计XY视场 · 原生 spot_points / 展示适配',fig)
            r.notes+=['所有设计视场保留顺序、重复项和权重；不把权重当点数，图例括号为有效/发射光线数。坐标为实际像面位置，不强制各波长分别居中。']
        elif key=='spot_radial':
            native_plot('AutoLens 原生径向点列',lens.draw_spot_radial,save_name=str(r.out/'plot_01.png'),num_fov=radial,depth=depth,num_rays=n,wvln_list=r.waves)
        elif key=='spot_map':
            native_plot('AutoLens 原生二维点列',lens.draw_spot_map,save_name=str(r.out/'plot_01.png'),num_grid=grid,depth=depth,num_rays=n,wvln_list=r.waves)
        elif key=='native_mtf':
            native_plot('AutoLens 原生几何 MTF · 各波长 Tan',lens.draw_mtf,save_name=str(r.out/'plot_01.png'),relative_fov_list=np.linspace(0,1,radial).tolist(),depth_list=[depth],wvln_list=r.waves,psf_ks=ks)
            r.notes+=['直接调用draw_mtf：原生默认几何PSF、仅Tan曲线；使用接口内部默认16384条光线/PSF。不是衍射MTF或多色OTF综合。']
        elif key=='curvature':
            native_plot('AutoLens 原生子午最佳焦面场曲',lens.draw_field_curvature,save_name=str(r.out/'plot_01.png'),num_points=o['field_points'],z_span=o['z_span_mm'],z_steps=o['z_steps'],wvln_list=r.waves,spp=n)
            r.notes+=['原生子午光束扫描最佳RMS焦面；不是Optiland的T/S场曲。命中扫描边界时需增大离焦范围，不能视为真实最佳焦面。']
        elif key in ('grid_distortion','vignetting','opd','seidel','rms_map'):
            for w in r.waves:
                progress('AutoLens：逐波长计算',wavelength_nm=w*1000);path=str(r.out/f'plot_{len(r.images)+1:02d}.png');label=f'AutoLens · {w*1000:g} nm'
                if key=='grid_distortion':native_plot(label+' · 原生畸变网格',lens.draw_distortion_map,save_name=path,num_grid=grid,depth=depth,wvln=w)
                elif key=='vignetting':native_plot(label+' · 原生渐晕',lens.draw_vignetting,filename=path,depth=depth,num_grid=grid,num_rays=n,wvln=w)
                elif key=='opd':native_plot(label+' · 原生波前',lens.draw_wavefront_error,save_name=path,num_fov=radial,depth=depth,wvln=w,num_rays=n,ks=ks)
                elif key=='seidel':native_plot(label+' · 原生 Seidel/CL/CT',lens.aberration_histogram,save_name=path,wvln=w,include_chromatic=len(r.allwaves)>1)
                else:
                    rms,centroid=lens.rms_map(num_grid=grid,depth=depth,wvln=w)
                    fig,ax=plt.subplots();im=ax.imshow(rms.detach().cpu().numpy()*1000,origin='lower');fig.colorbar(im,ax=ax,label='RMS (µm)');ax.set_title(label+' · native rms_map');r.figure(label+' · RMS图（展示适配）',fig)
            if key=='grid_distortion':r.notes+=['原生二维质心位移网格，不是F-tan畸变百分比曲线；本固定版本没有原生径向曲线绘图入口。']
            if key=='vignetting':r.notes+=['数值为发射光线存活比例，不是包含cos⁴/镀膜/传感器响应的绝对照度。']
            if key=='seidel':r.notes+=['CL/CT是原生近轴色差系数，不是实光线横向/轴向色差曲线。']
        elif key.endswith('_psf'):
            model={'geometric_psf':'geometric','coherent_psf':'coherent','huygens_psf':'huygens'}[key]
            if model!='geometric':torch.set_default_dtype(torch.float64);lens.astype(torch.float64)
            for w in r.waves:
                progress('AutoLens：PSF',wavelength_nm=w*1000)
                # Same normalized meridional point convention used by native draw_mtf.
                theta=o['field']*float(lens.rfov);norm=-math.tan(theta)/(lens.sensor_size[1]/(2*float(lens.foclen)))
                psf=lens.psf(points=[0,norm,depth],ks=ks,wvln=w,spp=o['coherent_rays'] if model=='coherent' else n,model=model)
                a=psf.detach().cpu().numpy();r.arrays[f'{w:g}.psf']=a
                if not np.isfinite(a).all() or a.sum()<=0:raise ValueError('原生PSF没有有效光能，不能展示成合格结果')
                fig,ax=plt.subplots();im=ax.imshow(a,origin='lower');fig.colorbar(im,ax=ax,label='Native normalized intensity');ax.set_title(f'AutoLens {model} PSF · {w*1000:g} nm · H={o["field"]:g}');r.figure(f'{model} PSF · {w*1000:g} nm（展示适配）',fig)
            if model=='coherent':r.notes+=[f"按原生要求使用float64和至少一百万条相干光线；本次每波长{o['coherent_rays']}条。不是低采样几何PSF。"]
        elif key=='sensitivity':
            if len(r.allwaves)!=3:raise ValueError('原生敏感度内部loss_rms要求三个设计波长')
            # Bind input sampling only; the original loss and sensitivity bodies execute unchanged.
            from functools import partial
            original_loss=lens.loss_rms
            try:
                lens.loss_rms=partial(original_loss,num_grid=grid,num_rays=n,wvln_list=r.allwaves)
                result=lens.tolerancing_sensitivity()
            finally:lens.loss_rms=original_loss
            r.arrays.update(arrays(result,'sensitivity'))
            names=[k for k in result if k.endswith('_score')];values=[float(result[k]) for k in names]
            fig,ax=plt.subplots(figsize=(10,5));ax.bar(np.arange(len(names)),values);ax.set_xticks(np.arange(len(names)),names,rotation=90,fontsize=6);ax.set_ylabel('Native sensitivity score');fig.tight_layout();r.figure('AutoLens 原生梯度敏感度（展示适配）',fig)
            r.notes+=[f'使用原生默认公差和三设计波长。外层仅将原生loss_rms采样参数绑定为{grid}×{grid}场/{n}光线，避免其内部默认16×16场/16384光线耗尽显存；原生损失、梯度和敏感度公式未替换。不使用Optiland的半径/厚度扫值设置。']
            r.summary['sampling_adapter']='functools.partial(native loss_rms, num_grid, num_rays, wvln_list); native sensitivity body unchanged'
        elif key=='monte_carlo':
            # Upstream saves a fixed relative filename: contain it in the job directory.
            old=os.getcwd()
            try:
                os.chdir(r.out);result=lens.tolerancing_monte_carlo(trials=o['trials'],spp=n)
            finally:os.chdir(old)
            r.arrays.update(arrays(result,'monte_carlo'));r.summary.update(result)
            p=r.out/'Monte_Carlo_Tolerance.png'
            if not p.is_file():raise ValueError('原生蒙特卡洛没有生成图像')
            r.images.append(dict(file=p.name,label='AutoLens 原生蒙特卡洛公差'))
            r.notes+=['使用原生默认公差、内部0/0.5/1三个场和主波长MTF指标，含原生像面补偿；与Optiland公差模型不同。不能由此认定生产良率。']
        elif key=='image_simulation':
            from PIL import Image
            if req.get('image'):
                image=Image.open(io.BytesIO(base64.b64decode(req['image'].split(',',1)[-1]))).convert('RGB');image.thumbnail((128,128));a=np.asarray(image)
            else:
                t=np.indices((64,64)).sum(axis=0)//8%2;a=np.repeat((t*255).astype(np.uint8)[...,None],3,axis=2)
            tensor=torch.as_tensor(np.array(a,copy=True),device=device,dtype=lens.dtype).permute(2,0,1).unsqueeze(0)/255
            lens.set_sensor_res(sensor_res=tensor.shape[-2:])
            out=lens.render(tensor,depth=depth,spp=min(n,64),method='ray_tracing')
            b=out.detach().cpu().squeeze(0).permute(1,2,0).numpy();r.arrays['render']=b
            fig,axs=plt.subplots(1,2,figsize=(10,5));axs[0].imshow(a);axs[0].set_title('Input');axs[1].imshow(np.clip(b,0,1));axs[1].set_title('AutoLens native ray tracing');r.figure('AutoLens 原生光线图像模拟（展示适配）',fig)
            r.notes+=['RGB通道按保存三设计波长，直接调用原生render(ray_tracing)；外层组织输入、展示和导出，不计算PSNR/SSIM，不依赖torchvision。输入最长边128像素，spp最多64。不是Optiland灰度空间变PSF算法。']
        else:raise ValueError('尚未接入该原生分析')
    finally:sys.setprofile(previous);plt.close('all')
    if hashlib.sha256(src.read_bytes()).hexdigest()!=req['source_sha256']:raise RuntimeError('分析改变了来源处方')
    r.summary['native_calls']=observer.calls
    if r.summary.get('fully_blocked_ray_groups'):r.notes+=['警告：原生采样中存在整束失效视场；即使原生图中出现零值，也不能视为零像差或合格。请查看数值valid掩码和通光情况。']
    # Keep actual design metadata and requested wavelengths auditable even for native plots returning None.
    r.arrays['requested_wavelengths_um']=np.asarray(r.waves)
    r.arrays['design_fields_xy']=np.asarray([[f['x'],f['y']] for f in data.get('design_fields',[])])
    result=r.done();result['optical_model']='AutoLens native GeoLens; saved prescription; original physical apertures'
    return result
