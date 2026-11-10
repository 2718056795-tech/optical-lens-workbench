"""Secondary analysis navigation and validated, versioned calculation settings."""
import math

VERSION=5
ENGINES={'optiland':'Optiland 0.6.3','autolens':'AutoLens e58db32'}
GROUPS={'mtf':'MTF','spot':'点像分析','aberration':'场曲 / 畸变 / 色差','fan':'光扇 / 像差','tolerance':'公差'}
# Keep the established slot ID for the tolerance tab.
SLOTS={'mtf':'mtf','spot':'spot','aberration':'aberration','fan':'fan','tolerance':'advanced'}
ROWS=[
 ('fft_mtf','mtf','FFT 衍射 MTF','scalar FFT wavefront PSF / complex OTF'),
 ('huygens_mtf','mtf','Huygens 衍射 MTF','scalar Huygens-Fresnel PSF / complex OTF'),
 ('mtf_field','mtf','MTF 随视场','Optiland SampledMTF, per wavelength'),
 ('through_mtf','mtf','离焦 MTF','Optiland ThroughFocusMTF, per wavelength'),
 ('fft_psf','spot','FFT PSF','scalar FFT PSF'),('huygens_psf','spot','Huygens PSF','scalar Huygens PSF'),
 ('encircled','spot','包围能量','Optiland valid-ray encircled energy about monochromatic energy centroid'),
 ('through_spot','spot','离焦点列阵列','Optiland ThroughFocusSpotDiagram'),
 ('rms_field','spot','点列 RMS 随视场','Optiland RmsSpotSizeVsField'),
 ('distortion','aberration','畸变曲线','Optiland Distortion f-tan'),
 ('lateral_color','aberration','横向色差','real chief-ray intercept difference; user CODE V macro reference'),
 ('axial_color','aberration','近轴轴向色差','paraxial BFL shift over wavelengths'),
 ('spherochromatic','aberration','球差随波长','real on-axis longitudinal ray intercept'),
 ('best_fan','fan','最佳拟合光扇','Optiland BestFitRayFan'),
 ('seidel','fan','Seidel / 一阶色差贡献','native Seidel and chromatic coefficients; V4 plots'),
 ('sensitivity','tolerance','公差敏感度','Optiland SensitivityAnalysis; nominal absolute parameter sweeps'),
 ('monte_carlo','tolerance','蒙特卡洛公差','Optiland MonteCarlo; uniform independent absolute parameter samples'),
]
CATALOG={key:dict(id=key,group=group,slot=SLOTS[group],label=label,method=method) for key,group,label,method in ROWS}
CATALOG['layout']=dict(id='layout',group='layout',slot='layout',label='原生 2D 光路',method='Optic.draw / optical-train display bounds')
for key,group,slot,label,method in [
 ('native_3d','three','three','原生 3D · 含追迹光线','OpticViewer3D / native Rays3D + OpticalSystem / VTK'),
 ('native_spot','spot','spot','原生点列图','Optiland SpotDiagram.view'),
 ('native_geometric_mtf','mtf','mtf','原生几何 MTF','Optiland GeometricMTF.view'),
 ('native_curvature','aberration','aberration','原生 T/S 场曲','Optiland FieldCurvature.view'),
 ('native_grid','aberration','aberration','原生网格畸变','Optiland GridDistortion.view'),
 ('native_ray_fan','fan','fan','原生光线像差扇图','Optiland RayFan.view')]:CATALOG[key]=dict(id=key,group=group,slot=slot,label=label,method=method)
AUTO_ROWS=[
 ('layout','layout','原生 2D 光路','GeoLens.draw_layout'),
 ('spot_fields','spot','完整设计视场点列','GeoLens.spot_points / display adapter'),
 ('spot_radial','spot','原生径向点列','GeoLens.draw_spot_radial'),
 ('spot_map','spot','原生二维点列阵列','GeoLens.draw_spot_map'),
 ('rms_map','spot','RMS 分布','GeoLens.rms_map / display adapter'),
 ('geometric_psf','spot','几何 PSF','GeoLens.psf(model=geometric)'),
 ('coherent_psf','spot','相干出口瞳传播 PSF','GeoLens.psf(model=coherent)'),
 ('huygens_psf','spot','Huygens PSF','GeoLens.psf(model=huygens)'),
 ('native_mtf','mtf','原生 MTF · 各波长 Tan','GeoLens.draw_mtf / geometric PSF'),
 ('curvature','aberration','原生子午最佳焦面场曲','GeoLens.draw_field_curvature'),
 ('grid_distortion','aberration','原生畸变网格','GeoLens.draw_distortion_map'),
 ('seidel','fan','原生 Seidel / CL / CT','GeoLens.aberration_histogram'),
 ('sensitivity','tolerance','原生 RMS 梯度公差敏感度','GeoLens.tolerancing_sensitivity'),
 ('monte_carlo','tolerance','原生蒙特卡洛公差','GeoLens.tolerancing_monte_carlo'),
]
AUTO_CATALOG={key:dict(id=key,group=group,slot='layout' if group=='layout' else SLOTS[group],label=label,method=method) for key,group,label,method in AUTO_ROWS}
AUTO_CATALOG['native_3d']=dict(id='native_3d',group='three',slot='three',label='原生 3D · 含平行追迹光线',method='GeoLens.draw_lens_3d / PyVista / VTK, primary wavelength')
AUTO_CATALOG['coherent_psf'].update(available=False,reason='固定版原生psf_pupil_prop引用缺失的AngularSpectrumMethod，实际运行NameError；保持源码，未启用。')

def engine_catalog(engine='optiland'):
    if engine not in ENGINES:raise ValueError('未知分析内核：'+str(engine))
    return AUTO_CATALOG if engine=='autolens' else CATALOG


def normalize_options(raw=None):
    raw=raw or {}
    if not isinstance(raw,dict):raise ValueError('分析参数必须为JSON对象')
    def num(key,default,low,high,integer=False):
        v=raw.get(key,default)
        if v in (None,''):v=default
        if isinstance(v,bool):raise ValueError(key+'需为数值')
        v=float(v)
        if not math.isfinite(v) or not low<=v<=high or integer and not v.is_integer():raise ValueError(f'{key}需在{low}~{high}'+('整数' if integer else ''))
        return int(v) if integer else v
    wave=raw.get('wave','all')
    if wave not in ('all','primary'):
        wave=float(wave)
        if not math.isfinite(wave) or not 300<=wave<=1200:raise ValueError('所选波长需为300~1200nm')
    projection=raw.get('projection','2d')
    if projection not in ('2d','3d'):raise ValueError('投影需为2d/3d')
    reference=raw.get('reference_wave','primary')
    if reference!='primary':
        reference=float(reference)
        if not math.isfinite(reference) or not 300<=reference<=1200:raise ValueError('参考波长需为300~1200nm')
    values=raw.get('frequencies','30,50,100')
    frequencies=[float(v) for v in values] if isinstance(values,list) else [float(v.strip()) for v in str(values).split(',') if v.strip()]
    if not 1<=len(frequencies)<=5 or any(not math.isfinite(v) or not 0<v<=5000 for v in frequencies):raise ValueError('频率需为1~5个0~5000 cycles/mm正数')
    extra={}
    if 'ignore_object' in raw:
        flag=raw['ignore_object']
        if not isinstance(flag,bool):raise ValueError('忽略物面需为布尔值')
        extra['ignore_object']=flag
    return dict(**extra,wave=wave,reference_wave=reference,field=num('field',.7,0,1),samples=num('samples',32,32,128,True),
                field_points=num('field_points',21,3,65,True),frequency=num('frequency',50,.1,5000),frequencies=frequencies,
                focus_step_mm=num('focus_step_mm',.05,.0001,10),focus_steps=num('focus_steps',5,3,15,True),
                projection=projection,pixel_pitch_um=num('pixel_pitch_um',5.4,.01,1000),
                radius_tol_mm=num('radius_tol_mm',.02,0,1),thickness_tol_mm=num('thickness_tol_mm',.01,0,1),
                trials=num('trials',32,8,500,True),seed=num('seed',42,0,2**32-1,True),
                grid_points=num('grid_points',5,3,17,True),ray_count=num('ray_count',1024,32,65536,True),coherent_rays=num('coherent_rays',1000000,1000000,8388608,True),
                radial_fields=num('radial_fields',3,2,12,True),z_span_mm=num('z_span_mm',1,.001,20),z_steps=num('z_steps',101,5,401,True))


def catalog_payload():return dict(version=VERSION,engines=ENGINES,groups=dict(layout='光路布局',three='原生3D',**GROUPS),analyses=list(CATALOG.values()),
                                 by_engine={engine:list(engine_catalog(engine).values()) for engine in ENGINES},defaults=normalize_options(),
                                 external_analyses=[dict(id='mtf_yield',group='tolerance',slot='advanced',label='MTF 良率（导入 TXT）',method='V6 蒙特卡罗报告统计')],
                                 unsupported={'autolens':['原生 F-tan 畸变曲线','专用 RayFan','包围能量'], 'optiland':[]})
