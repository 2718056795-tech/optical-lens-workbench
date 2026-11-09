"""On-demand Optiland adapters. Each job owns its independent optical model.

All plots retain their calculation settings and numeric arrays. No installed
library or source prescription is modified. Units: lens mm, wavelength um.
"""
import base64,hashlib,inspect,io,json,math
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from analysis_catalog import CATALOG,VERSION,engine_catalog
from optiland_bridge import autolens_json_to_optiland


def chief(optic,field,wave):
    ray=optic.trace_generic(Hx=0,Hy=float(field),Px=0,Py=0,wavelength=float(wave))
    y=float(np.asarray(ray.y).ravel()[0]);x=float(np.asarray(ray.x).ravel()[0])
    if not np.isfinite([x,y]).all() or float(np.asarray(ray.i).ravel()[0])<=0:
        raise ValueError(f'主光线无效: field={field}, wavelength={wave}um')
    return x,y


def tolerance_ray_metrics(optic,Hy,wavelength):
    """Do not let finite coordinates of blocked rays improve a tolerance score."""
    ray=optic.trace(0.,Hy,wavelength,num_rays=6,distribution='hexapolar')
    x,y,i=(np.asarray(v,dtype=float).ravel() for v in (ray.x,ray.y,ray.i))
    good=np.isfinite(x)&np.isfinite(y)&np.isfinite(i)&(i>0)
    fraction=float(good.mean())
    if not good.any():return float('nan'),fraction
    x=x[good];y=y[good];i=i[good];i=i/i.sum()
    rms=float(np.sqrt(np.sum(i*((x-np.sum(x*i))**2+(y-np.sum(y*i))**2))))
    return rms,fraction


def encircled_curve(x,y,intensity):
    x,y,i=(np.asarray(v,dtype=float).ravel() for v in (x,y,intensity))
    valid=np.isfinite(x)&np.isfinite(y)&np.isfinite(i)&(i>0)
    if not valid.any():raise ValueError('包围能量无有效光线')
    x=x[valid];y=y[valid];i=i[valid];cx=np.average(x,weights=i);cy=np.average(y,weights=i)
    radii=np.hypot(x-cx,y-cy);order=np.argsort(radii);radii=radii[order];cumulative=np.r_[0,np.cumsum(i[order])/i.sum()]
    radius=np.linspace(0,max(float(radii[-1])*1.05,1e-10),256)
    energy=cumulative[np.searchsorted(radii,radius,side='right')]
    return radius,energy,np.array([cx,cy])


def numeric_tree(obj,path='data',depth=0,seen=None):
    """Export native numerical results without serializing the optical context."""
    if seen is None:seen=set()
    if depth>5 or id(obj) in seen:return {}
    if isinstance(obj,np.ndarray):
        return {path:obj} if obj.dtype.kind in 'biufc' and obj.size else {}
    if isinstance(obj,(int,float,np.number)) and not isinstance(obj,bool):return {path:np.asarray(obj)}
    seen.add(id(obj));out={}
    if isinstance(obj,(list,tuple)):items=enumerate(obj)
    elif isinstance(obj,dict):items=obj.items()
    elif hasattr(obj,'__dict__'):items=((k,v) for k,v in vars(obj).items() if k not in ('optic','surfaces','_optic','context') and not k.startswith('__'))
    else:return out
    for k,v in items:out.update(numeric_tree(v,f'{path}.{k}',depth+1,seen))
    return out


class Report:
    def __init__(self,req,progress):
        self.req=req;self.progress=progress;self.out=Path(req['out_dir']);self.out.mkdir(parents=True,exist_ok=True)
        self.images=[];self.arrays={};self.notes=[];self.summary={}
    def save(self,label,obj=None,view=None,**kwargs):
        if view is None:view=obj.view
        if 'show' in inspect.signature(view).parameters:kwargs['show']=False
        result=view(**kwargs)
        if isinstance(result,tuple):fig=result[0]
        else:fig=result
        if fig is None or not hasattr(fig,'savefig'):fig=plt.gcf()
        self.figure(label,fig)
        if obj is not None:self.arrays.update(numeric_tree(obj,label))
    def figure(self,label,fig):
        name=f'plot_{len(self.images)+1:02d}.png'
        fig.savefig(self.out/name,dpi=140,bbox_inches='tight',facecolor='white');plt.close(fig)
        self.images.append(dict(file=name,label=label))
    def done(self):
        if not self.images:raise ValueError('分析未产生图像')
        if not self.arrays:raise ValueError('分析未产生可审计数值')
        np.savez_compressed(self.out/'numeric.npz',**self.arrays)
        shapes={k:dict(shape=list(v.shape),dtype=str(v.dtype),finite=int(np.isfinite(v).sum()),count=int(v.size)) for k,v in self.arrays.items()}
        (self.out/'numeric_index.json').write_text(json.dumps(shapes,ensure_ascii=False,indent=2),encoding='utf-8')
        entry=engine_catalog(self.req.get('engine','optiland'))[self.req['analysis_id']]
        return dict(ok=True,version=VERSION,engine=self.req.get('engine','optiland'),analysis_id=self.req['analysis_id'],label=entry['label'],method=entry['method'],
                    source_sha256=self.req['source_sha256'],run_id=self.req['run_id'],options=self.req['options'],wavelengths_um=self.waves,
                    primary_um=self.primary,images=self.images,notes=self.notes,summary=self.summary,
                    source_file=self.req.get('source_file',Path(self.req['source']).name),
                    relative_dir='analysis/extended/'+self.out.name,files=['numeric.npz','numeric_index.json','request.json','analysis.log'],
                    optical_model='saved spherical surfaces / physical circular apertures; scalar unless Jones')


def color_analysis(key,optic,data,o,r):
    waves=r.waves;ref=r.primary if o['reference_wave']=='primary' else float(o['reference_wave'])/1000;n=o['field_points']
    if not any(abs(ref-w)<1e-9 for w in r.allwaves):raise ValueError('参考波长须为处方实际采样波长')
    if key=='lateral_color':
        from scipy.optimize import brentq
        refheight=chief(optic,1,ref)[1];heights=np.linspace(0,refheight,n)
        fields=np.array([0 if i==0 else 1 if i==n-1 else brentq(lambda h:chief(optic,h,ref)[1]-target,0,1) for i,target in enumerate(heights)])
        ys=np.array([[chief(optic,h,w)[1] for h in fields] for w in waves]);refs=np.array([chief(optic,h,ref)[1] for h in fields])
        delta=(ys-refs)*1000
        fig,ax=plt.subplots(figsize=(12,5))
        for w,d in zip(waves,delta):ax.plot(d,heights,label=f'{w*1000:g} nm')
        pixel=o['pixel_pitch_um'];ax.axvline(pixel,c='grey',ls=':',label='±1 pixel');ax.axvline(-pixel,c='grey',ls=':');ax.axvline(0,c='grey',lw=.7)
        ax.set(xlabel='Chief-ray lateral color (µm)',ylabel='Reference real image height (mm)',title=f'Lateral color · reference {ref*1000:g} nm');ax.grid(alpha=.2);ax.legend()
        r.figure('横向色差 · 主光线相对参考波长',fig)
        r.arrays.update(field_normalized=fields,real_image_height_mm=heights,wavelength_um=np.array(waves),chief_y_mm=ys,lateral_color_um=delta,endpoint_color_um=(ys[0]-ys[-1])*1000)
        idx=np.unravel_index(np.argmax(np.abs(delta)),delta.shape)
        r.summary.update(max_abs_um=float(abs(delta[idx])),worst_field=float(fields[idx[1]]),worst_wavelength_nm=float(waves[idx[0]]*1000),max_pixels=float(abs(delta[idx])/pixel),reference_nm=ref*1000)
        r.notes+=['参考用户CODE V宏的R1主光线定义；按参考波长实际像高等距取点，再在相同物方视场比较各波长。保留物理口径，不执行宏中的清口径/重设渐晕。','±1像素仅为参考线，图轴自动适配；像素尺寸由分析参数指定。未与CODE V数值交叉验收。']
        np.savetxt(r.out/'lateral_color.csv',np.column_stack((fields,heights,delta.T)),delimiter=',',header='normalized_field,reference_height_mm,'+','.join(f'delta_{w*1000:g}nm_um' for w in waves),comments='');r.summary['csv']='lateral_color.csv'
    elif key=='axial_color':
        # Trace a unit-height parallel paraxial ray at each actual wavelength.
        zstart=optic.surfaces.build_paraxial_path().axial_positions.reshape(-1,1)[1]-1
        def focus(w):
            y,u=optic.paraxial.trace_generic(1.,0.,zstart,w)
            return float(np.asarray(-y[-1]/u[-1]).ravel()[0])
        vals=np.array([focus(w) for w in waves]);delta=(vals-focus(ref))*1000
        fig,ax=plt.subplots(figsize=(8,5));ax.plot(np.array(waves)*1000,delta,'o-');ax.axhline(0,c='grey',lw=.7);ax.set(xlabel='Wavelength (nm)',ylabel='Paraxial axial focus shift (µm)',title=f'Axial color · reference {ref*1000:g} nm');ax.grid(alpha=.2);r.figure('近轴轴向色差',fig)
        r.arrays.update(wavelength_um=np.array(waves),focus_from_image_mm=vals,axial_shift_um=delta);r.notes+=['近轴平行光焦点相对参考波长的轴向位移；不是最佳MTF焦点，也不是有限物距最佳焦点。仅绘制保存/选择的离散波长。']
    else:
        rho=np.linspace(.03,1,n);fig,ax=plt.subplots(figsize=(8,5));values=[]
        for w in waves:
            z=[]
            for p in rho:
                ray=optic.trace_generic(Hx=0,Hy=0,Px=0,Py=float(p),wavelength=w)
                valid=float(np.asarray(ray.i).ravel()[0])>0
                y=float(np.asarray(ray.y).ravel()[0]);m=float(np.asarray(ray.M).ravel()[0]);nn=float(np.asarray(ray.N).ravel()[0])
                z.append(-y*nn/m if valid and abs(m)>1e-14 else np.nan)
            values.append(z);ax.plot(np.array(z)*1000,rho,label=f'{w*1000:g} nm')
        r.arrays.update(pupil_fraction=rho,longitudinal_from_image_mm=np.array(values));ax.set(xlabel='Axis intercept relative to saved image (µm)',ylabel='Normalized pupil radius',title='Longitudinal spherical aberration / spherochromatism');ax.legend();ax.grid(alpha=.2);r.figure('球差随波长',fig);r.notes+=['实光线与光轴交点相对当前像面；被挡/不能求交光线记NaN，不作零值。']


def diffraction_mtf(key,optic,o,r):
    from optiland.mtf import ScalarFFTMTF,ScalarHuygensMTF
    cls=ScalarFFTMTF if key=='fft_mtf' else ScalarHuygensMTF
    series=[];fields=[(0.,0.),(0.,.7),(0.,1.)]
    # Native wavefront reference centres the chief ray. Restore its wavelength
    # displacement before adding complex OTFs in a common physical image frame.
    for w in r.waves:
        r.progress('计算衍射PSF / OTF',wavelength_nm=w*1000)
        kw=dict(fields=fields,wavelength=w,num_rays=o['samples'])
        if key=='fft_mtf':kw['grid_size']=o['samples']*2
        else:kw['image_size']=o['samples']*2
        obj=cls(optic,**kw);psfs=obj.psf if key=='fft_mtf' else obj.psf_data
        rec=[]
        for j,p in enumerate(psfs):
            p=np.asarray(p);h=p.shape[0]//2;otf=np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(p)));otf/=otf[h,h]
            ft=np.asarray(obj.freq_tang[j]);fs=np.asarray(obj.freq_sag[j]);t=otf[h:,h][:h];s=otf[h,h:][:h]
            # Store native mono magnitude for a direct numerical regression.
            r.arrays.update({f'{w:g}.psf.{j}':p,f'{w:g}.otf_t.{j}':t,f'{w:g}.otf_s.{j}':s,f'{w:g}.freq_t.{j}':ft,f'{w:g}.freq_s.{j}':fs})
            if key=='huygens_mtf':
                instance=obj.psf_instances[j]
                # Native Huygens grids are centred on the ray centroid, NOT
                # the chief ray. Even linspace grids place index N/2 half a
                # sample beyond that centre. Restore that actual origin.
                halfsample=float(instance.pixel_pitch)*p.shape[0]/(2*(p.shape[0]-1))
                origin=(float(instance.cx)+halfsample,float(instance.cy)+halfsample)
            else:origin=chief(optic,fields[j][1],w)
            ray=optic.trace(0.,fields[j][1],w,num_rays=24,distribution='hexapolar')
            intensity=np.asarray(ray.i,dtype=float);throughput=float(np.where(np.isfinite(intensity)&(intensity>0),intensity,0).mean())
            if throughput<=0:raise ValueError('该视场/波长无有效光能')
            r.arrays[f'{w:g}.native_mtf.{j}']=np.asarray(obj.mtf[j]);r.arrays[f'{w:g}.throughput.{j}']=np.asarray(throughput)
            rec.append((ft,fs,t,s,origin,throughput))
        series.append(rec)
    weights=np.array([r.weights[r.allwaves.index(w)] for w in r.waves]);weights/=weights.sum()
    fig,axes=plt.subplots(1,3,figsize=(13,4),sharey=True)
    for j,(_,f) in enumerate(fields):
        maxfreq=min(max(float(rec[j][0][-1]),float(rec[j][1][-1])) for rec in series);freq=np.linspace(0,min(maxfreq,5000),300)
        sums=[np.zeros(freq.shape,complex),np.zeros(freq.shape,complex)]
        for wi,(w,rec) in enumerate(zip(r.waves,series)):
            ft,fs,t,s,origin,throughput=rec[j];dx,dy=np.subtract(origin,chief(optic,f,r.primary))
            for k,(axis,val,shift) in enumerate(((ft,t,dy),(fs,s,dx))):
                v=np.interp(freq,axis,val.real,left=val.real[0],right=0)+1j*np.interp(freq,axis,val.imag,left=val.imag[0],right=0)
                sums[k]+=weights[wi]*throughput*v*np.exp(-2j*np.pi*freq*shift)
        total=sum(weights[wi]*rec[j][5] for wi,rec in enumerate(series))
        sums=[value/total for value in sums]
        for k,label in enumerate(('T','S')):
            mtf=np.abs(sums[k]);axes[j].plot(freq,mtf,'-' if k==0 else '--',label=label);r.arrays[f'combined.{j}.{label}']=mtf
        r.arrays[f'combined.{j}.frequency']=freq;axes[j].set(title=f'Field {f:g}',xlabel='Frequency (cycles/mm)',ylim=(0,1.02));axes[j].grid(alpha=.2);axes[j].legend()
    axes[0].set_ylabel('MTF');fig.suptitle(f'{"FFT" if key=="fft_mtf" else "Huygens"} scalar diffraction MTF · {len(r.waves)} wavelength(s)');r.figure('全选波长复OTF综合 · 衍射MTF',fig)
    r.notes+=['标量衍射波前PSF；各波长复OTF按原生物理频率轴插值，恢复PSF实际坐标原点后叠加（FFT为主光线，Huygens为原生质心网格）。按保存谱权与实光线透过能量加权，不含传感器QE/镀膜光谱。','FFT与Huygens为不同离散算法；默认32采样适合预览。离轴/强像差可能发生窗口截断或混叠，增加采样并检查收敛后才能作定量验收。']


def tolerance_analysis(key,optic,data,o,r):
    from optiland.tolerancing import Tolerancing,RangeSampler,DistributionSampler,SensitivityAnalysis
    from optiland.tolerancing.monte_carlo import MonteCarlo
    from optiland.optimization.operand import operand_registry
    if 'v4_valid_rms' not in operand_registry:
        operand_registry.register('v4_valid_rms',lambda optic,Hy,wavelength:tolerance_ray_metrics(optic,Hy,wavelength)[0])
        operand_registry.register('v4_valid_fraction',lambda optic,Hy,wavelength:tolerance_ray_metrics(optic,Hy,wavelength)[1])
    tol=Tolerancing(optic)
    tol.add_operand('f2',input_data={'optic':optic})
    tol.add_operand('v4_valid_rms',input_data=dict(optic=optic,Hy=o['field'],wavelength=r.primary))
    tol.add_operand('v4_valid_fraction',input_data=dict(optic=optic,Hy=o['field'],wavelength=r.primary))
    nominal=tol.evaluate();variables=[]
    for i,s in enumerate(data['surfaces'],1):
        if s['type']=='Spheric' and np.isfinite(float(s.get('roc',np.inf))) and o['radius_tol_mm']:
            variables.append(('radius',i,float(s['roc']),o['radius_tol_mm']))
        if float(s['d_next'])>o['thickness_tol_mm'] and s['type']!='Aperture' and o['thickness_tol_mm']:
            variables.append(('thickness',i,float(s['d_next']),o['thickness_tol_mm']))
    if not variables:raise ValueError('无可扰动参数，请设置非零公差')
    for j,(typ,i,v,d) in enumerate(variables):
        sampler=RangeSampler(v-d,v+d,5) if key=='sensitivity' else DistributionSampler('uniform',seed=o['seed']+j,low=v-d,high=v+d)
        tol.add_perturbation(typ,sampler,surface_number=i)
    try:
        if key=='sensitivity':
            # Native plotting caps each study at six perturbations. Run disjoint
            # blocks against the SAME nominal model; every variable is covered.
            import pandas as pd
            allpert=tol.perturbations;frames=[]
            for start in range(0,len(allpert),6):
                tol.perturbations=allpert[start:start+6];obj=SensitivityAnalysis(tol);obj.run();frames.append(obj.get_results());r.save(f'公差敏感度 · 参数{start+1}~{min(start+6,len(allpert))}',obj)
            tol.perturbations=allpert;frame=pd.concat(frames,ignore_index=True)
        else:
            obj=MonteCarlo(tol);obj.run(o['trials']);frame=obj.get_results()
        frame.to_csv(r.out/'tolerance_results.csv',index=False,encoding='utf-8-sig')
        for col in frame.select_dtypes(include='number'):r.arrays[col]=frame[col].to_numpy()
        if key!='sensitivity':
            r.save('公差分布',obj,view=obj.view_histogram,kde=False);r.save('累计概率',obj,view=obj.view_cdf);r.save('参数与指标相关性',obj,view=obj.view_heatmap)
    finally:tol.reset()
    r.summary.update(nominal_metrics=nominal,variables=[dict(type=t,surface=i,nominal=v,half_width_mm=d) for t,i,v,d in variables],csv='tolerance_results.csv')
    r.notes+=['独立均匀半宽：曲率半径/轴向间隔；末片到像面的间隔也参与扰动，无自动调焦补偿器。敏感度逐项5点；Monte Carlo所有变量同时抽样。','指标为近轴EFL(mm)、所选视场/主波长有效能量加权几何RMS(mm)及有效光线比例(0~1)。排除强度≤0的被挡光线；无有效光线时RMS为NaN。未设验收阈值，不输出制造良率；未覆盖偏心、倾斜、折射率、温度及装调补偿。']


def simulation(optic,o,r):
    from optiland.analysis.image_simulation import ImageSimulationEngine
    from PIL import Image
    image=r.req.get('image')
    if image:
        payload=image.split(',',1)[-1];im=Image.open(io.BytesIO(base64.b64decode(payload,validate=True)))
        if im.width*im.height>16000000:raise ValueError('图像像素超过1600万')
        im=im.convert('L');original=im.size;im.thumbnail((256,256));source=np.asarray(im)/255.;r.summary.update(input_original_size=list(original),input_used_size=list(im.size))
    else:
        y,x=np.indices((128,128));source=((x//8+y//8)%2).astype(float);source[48:80,48:80]=.5;r.summary['input']='built-in 128x128 checkerboard'
    results=[]
    for w in r.waves:
        r.progress('空间变PSF成像模拟',wavelength_nm=w*1000)
        engine=ImageSimulationEngine(optic,dict(wavelengths=[w],psf_grid_shape=(3,3),psf_size=o['samples']*2,num_rays=o['samples'],n_components=3,padding=16))
        result=np.asarray(engine.run(source))[0,0];results.append(result);r.arrays[f'image_{w:g}um']=result
    weights=np.array([r.weights[r.allwaves.index(w)] for w in r.waves]);weights/=weights.sum();combined=np.tensordot(weights,np.asarray(results),axes=1)
    fig,axes=plt.subplots(1,2,figsize=(10,5));axes[0].imshow(source,cmap='gray',vmin=0,vmax=1);axes[0].set_title('Source');axes[1].imshow(combined,cmap='gray',vmin=0,vmax=1);axes[1].set_title('Spectrally weighted simulation')
    for ax in axes:ax.axis('off')
    r.figure('空间变PSF + 畸变 · 灰度成像',fig);r.arrays.update(source=source,combined=combined)
    r.notes+=['输入转灰度并等权逐波长计算（支持1/3/5点），按整个设计视场映射测试图；9个视场PSF、3个EigenPSF。未引入真实传感器像素/QE/噪声/照明，不作为实拍预测。上传图像最长边缩至256像素。']


def run_analysis(req,progress=lambda *a,**k:None):
    # Verify the worker reads exactly the prescription fingerprint requested.
    src=Path(req['source']);raw=src.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=req['source_sha256']:raise ValueError('处方在分析启动前已变化，请重新计算')
    data=json.loads(raw);optic,meta=autolens_json_to_optiland(src,preserve_apertures=True)
    matplotlib.rcParams['font.sans-serif']=['Microsoft YaHei','DejaVu Sans'];matplotlib.rcParams['axes.unicode_minus']=False
    r=Report(req,progress);o=req['options'];key=req['analysis_id'];r.primary=float(data['wvln_primary']);r.allwaves=list(map(float,data['wvln_ls']));r.weights=list(map(float,data.get('spectral_weights',[1]*len(r.allwaves))))
    r.waves=r.allwaves if o['wave']=='all' else [r.primary] if o['wave']=='primary' else [float(o['wave'])/1000]
    if any(not any(abs(w-v)<1e-9 for v in r.allwaves) for w in r.waves):raise ValueError('仅能选择保存处方实际采样波长；修改设计波长范围后重新设计')
    progress('计算 '+CATALOG[key]['label']);field=(0.,o['field']);n=o['samples'];wave=r.waves[0];np.random.seed(o['seed'])
    if key=='native_3d':
        from native_3d import render
        render(optic,'optiland',data,r)
    elif key in ('native_spot','native_geometric_mtf','native_curvature','native_grid','native_ray_fan'):
        import optiland.analysis as native
        from optiland.mtf import GeometricMTF
        cls={'native_spot':native.SpotDiagram,'native_geometric_mtf':GeometricMTF,'native_curvature':native.FieldCurvature,'native_grid':native.GridDistortion,'native_ray_fan':native.RayFan}[key]
        if 'wavelength' in inspect.signature(cls).parameters:
            for w in r.waves:r.save(f'Optiland 原生 {CATALOG[key]["label"]} · {w*1000:g} nm',cls(optic,wavelength=w))
        else:r.save('Optiland 原生 · '+CATALOG[key]['label'],cls(optic,wavelengths=r.waves))
        r.notes+=['直接使用对应原生分析类和原生view；未经过工作台多色OTF或色差重组。原生各分析的采样/单色多色定义以图例和numeric.npz为准。']
    elif key=='layout':
        fig,ax=optic.draw(fields='all',wavelengths=r.waves,num_rays=7,hide_vignetted=False,show=False,
                          title='Optiland native analysis',figsize=(11,5))
        heights=[abs(float(s['r'])) for s in data['surfaces']]+[float(data['r_sensor'])]
        for i,line in enumerate(ax.lines):
            xy=line.get_xydata();r.arrays[f'layout.line.{i}']=np.asarray(xy)
        from view_framing import frame_2d
        positions=np.asarray(optic.surfaces.global_z_positions).ravel()[1:]
        r.summary['view_framing']=frame_2d(ax,(positions.min(),positions.max()),max(heights),o.get('ignore_object',True))
        r.figure('Optiland 原生 2D 光路',fig)
        r.notes+=['直接调用Optic.draw，保留物理口径及原生逐场光阑瞄准。“忽略物面”只调整绘图显示范围，未改物距或追迹；关闭后显示完整原生物方光路。']
    elif key in ('lateral_color','axial_color','spherochromatic'):color_analysis(key,optic,data,o,r)
    elif key in ('fft_mtf','huygens_mtf'):diffraction_mtf(key,optic,o,r)
    elif key in ('sensitivity','monte_carlo'):tolerance_analysis(key,optic,data,o,r)
    elif key=='image_simulation':simulation(optic,o,r)
    elif key=='seidel':
        fig,axes=plt.subplots(2,1,figsize=(10,8),layout='constrained');s=np.asarray(optic.aberrations.seidels()).ravel();r.arrays['seidel_sums']=s
        axes[0].bar(['SI','SII','SIII','SIV','SV'],s);axes[0].set(title='Native Seidel sums',ylabel='Native coefficient')
        for name in ('LchC','TchC','TAchC'):
            a=np.asarray(getattr(optic.aberrations,name)());r.arrays[name]=a;axes[1].plot(a.ravel(),label=name)
        axes[1].legend();axes[1].set(title='First-order chromatic contributions',xlabel='Surface term index (first refracting surface = 0)',ylabel='mm (native convention)');r.figure('Seidel总和 / 一阶色差逐面贡献',fig);r.notes+=['上图为原生Seidel总和SI~SV，下图为一阶色差逐面项；不是实光线色差验收。一阶色差使用保存处方最短/最长波长，独立于本页单色选择；单波长时色差项为零。']
    else:
        import optiland.analysis as ana
        from optiland import wavefront as wf,psf,mtf
        multi=r.waves
        if key=='mtf_field':r.save('MTF 随视场',ana.MTFvsField(optic,o['frequencies'],num_fields=o['field_points'],wavelengths=multi,num_rays=n,override_limits=True))
        elif key=='through_spot':r.save('离焦点列阵列',ana.ThroughFocusSpotDiagram(optic,delta_focus=o['focus_step_mm'],num_steps=o['focus_steps'],wavelengths=multi,num_rings=6))
        elif key=='rms_field':r.save('点列RMS随视场',ana.RmsSpotSizeVsField(optic,num_fields=o['field_points'],wavelengths=multi,num_rings=6))
        elif key=='distortion':
            obj=ana.Distortion(optic,wavelengths=multi,num_points=o['field_points'],distortion_type='f-tan')
            fig,ax=obj.view(show=False,figsize=(11,5.2))
            kind=type(optic.fields.field_definition).__name__
            field_unit='mm' if 'Height' in kind else 'deg'
            ax.set_ylabel({'ObjectHeightField':'Object height (mm)','RealImageHeightField':'Real image height (mm)','ParaxialImageHeightField':'Paraxial image height (mm)'}.get(kind,'Field height (mm)') if field_unit=='mm' else 'Field angle (deg)')
            ax.set_title('Optiland native F-tan distortion')
            for line,w in zip(ax.lines[1:],r.waves):line.set_label(f'{w*1000:g} nm')
            ax.legend(bbox_to_anchor=(1.02,.5),loc='center left');fig.tight_layout()
            r.arrays.update(numeric_tree(obj,'distortion'));r.figure('畸变曲线 · 原生 F-tan',fig)
            r.summary.update(field_unit=field_unit,field_definition=kind)
            r.notes+=['使用原生Distortion默认paraxial参考与f-tan定义，横轴百分比；正值枕形，负值桶形。','这是原生Hx=0、Hy从0到1的连续子午扫描，不是逐个设计XY视场；有限物距纵轴为物高mm，不能标成视场角。未修改参考模型或追迹算法。']
        elif key=='best_fan':r.save('最佳拟合光扇',ana.BestFitRayFan(optic,wavelengths=multi,num_points=n))
        elif key=='opd_fan':r.save('OPD光扇',wf.OPDFan(optic,wavelengths=multi,num_rays=n))
        elif key=='wavefront_field':r.save('波前RMS随视场',ana.RmsWavefrontErrorVsField(optic,num_fields=o['field_points'],wavelengths=multi,num_rays=n))
        elif key=='pupil':r.save('光瞳像差',ana.PupilAberration(optic,wavelengths=multi,num_points=n))
        elif key in ('irradiance','intensity'):
            from optiland.physical_apertures import RadialAperture
            optic.surfaces[-1].aperture=RadialAperture(r_max=float(data['r_sensor']))
            kw=dict(fields='all',wavelengths=multi,num_rays=4096,distribution='random')
            np.random.seed(o['seed'])
            if key=='irradiance':obj=ana.IncoherentIrradiance(optic,**kw,res=(128,128));r.save('归一化像面辐照度',obj,normalize=True)
            else:obj=ana.RadiantIntensity(optic,**kw,use_absolute_units=False,num_angular_bins_X=65,num_angular_bins_Y=65);r.save('相对辐射强度',obj,normalize=True)
            r.notes+=['无绝对光源功率标定：显示归一化分布。离散视场等权、波长入射等权、均匀瞳孔随机采样；像面口径取传感器半对角。不是连续扩展光源的相对照度/渐晕验收。']
        else:
            for w in r.waves:
                label=f'{w*1000:g} nm';progress('计算 '+label)
                if key=='through_mtf':r.save(label,ana.ThroughFocusMTF(optic,o['frequency'],delta_focus=o['focus_step_mm'],num_steps=o['focus_steps'],wavelength=w,num_rays=n))
                elif key in ('fft_psf','huygens_psf'):
                    cls=psf.ScalarFFTPSF if key=='fft_psf' else psf.ScalarHuygensPSF
                    kw=dict(field=field,wavelength=w,num_rays=n)
                    kw['grid_size' if key=='fft_psf' else 'image_size']=n*2
                    obj=cls(optic,**kw);r.save(label,obj,projection=o['projection']);r.summary[label+'_Strehl']=float(obj.strehl_ratio())
                elif key=='encircled':
                    fig,ax=plt.subplots(figsize=(10,4.5))
                    for f in (0.,.7,1.):
                        ray=optic.trace(0.,f,w,num_rays=4096,distribution='random')
                        radius,energy,center=encircled_curve(ray.x,ray.y,ray.i)
                        ax.plot(radius*1000,energy,label=f'Field {f:g}');r.arrays.update({f'{label}.{f}.radius_mm':radius,f'{label}.{f}.encircled_fraction':energy,f'{label}.{f}.centroid_mm':center})
                    ax.set(xlabel='Radius about monochromatic energy centroid (µm)',ylabel='Fraction of transmitted energy',ylim=(0,1.02),title=label+' Geometric encircled energy');ax.legend();ax.grid(alpha=.2);r.figure(label+' 几何包围能量',fig)
                    r.notes+=['包围能量以各单色的有效能量质心为圆心，按透过总能量归一化；4096随机瞳孔光线，排除被挡/非有限光线。是几何包围能量，不是衍射PSF能量积分。']
                elif key=='opd':r.save(label,wf.OPD(optic,field=field,wavelength=w,num_rays=n),projection=o['projection'])
                elif key=='zernike':
                    obj=wf.ZernikeOPD(optic,field=field,wavelength=w,num_rings=10,num_terms=37)
                    r.save(label+' 拟合波前',obj,projection=o['projection']);r.save(label+' 拟合残差',obj,view=obj.view_residual)
                    fig,ax=plt.subplots(figsize=(10,4));coeff=np.asarray(obj.coeffs);ax.bar(np.arange(1,len(coeff)+1),coeff);ax.set(xlabel='Fringe term (1 based)',ylabel='Coefficient (waves)',title=label+' Zernike coefficients');r.figure(label+' Fringe系数',fig);r.arrays[label+'.coefficients']=coeff
                elif key=='field_angle':r.save(label,ana.FieldIncidentAngleVsHeight(optic,wavelength=w,num_points=o['field_points']))
                elif key=='pupil_angle':r.save(label,ana.PupilIncidentAngleVsHeight(optic,wavelength=w,field=field,num_points=n))
                elif key=='yybar':r.save(label,ana.YYbar(optic,wavelength=w))
                elif key=='jones':r.save(label,ana.JonesPupil(optic,field=field,wavelengths=[w],grid_size=33))
                else:raise ValueError('尚未实现分析 '+key)
    if key not in ('through_mtf','through_spot','sensitivity','monte_carlo'):r.notes+=['使用保存的当前固定像面，非重新优化。']
    r.notes+=['波长“全部”指保存的有限采样点；单色原生接口逐波长输出，不把各单色结果冒充综合结果。']
    result=r.done()
    if meta.get('native_import'):
        result['optical_model']='Original Optiland imported model; canonical data used for labels only'
        result['notes'].append('直接载入严格校核后保存的原生Optiland模型，保留原光阑/孔径定义、视场与波长；没有用优化初始结构重新构造模型。')
    return result
