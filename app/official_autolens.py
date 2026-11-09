"""Execute the upstream workflow, with optional native input setup. No method replacement."""
import ast,copy,hashlib,math
from native_sources import AUTO_DIR
PROTOCOL='autolens-official-main-v1'
CFG_KEYS={'foclen','fov','fnum','bfl','thickness','surf_list','lrs','curriculum_iters','refine_iters','seed'}

def upstream_program():
    path=AUTO_DIR/'1_autolens.py';tree=ast.parse(path.read_text(encoding='utf-8'),filename=str(path))
    main=next(n for n in tree.body if isinstance(n,ast.If) and ast.unparse(n.test)=="__name__ == '__main__'")
    return path,main.body

def config_from_params(p):
    if p.get('autolens_config'):
        cfg=copy.deepcopy(p['autolens_config'])
        if set(cfg)!=CFG_KEYS:raise ValueError('AutoLens官方配置字段不完整或含额外字段')
    else:
        raw_count=p.get('elements',4);number=float(raw_count)
        if isinstance(raw_count,bool) or not math.isfinite(number) or not number.is_integer() or not 1<=number<=16:raise ValueError('镜片个数需为1～16的整数')
        n=int(number);stop=str(p.get('stop_pos','middle'))
        if stop in ('front','middle','back'):stop=0 if stop=='front' else n if stop=='back' else n//2
        else:
            index=float(stop)
            if not math.isfinite(index) or not index.is_integer() or not 0<=index<=n:raise ValueError('光阑位置需为第0～N片后的整数')
            stop=int(index)
        sizes=p.get('lens_group_sizes') or [1]*n
        if isinstance(sizes,str):sizes=[int(v.strip()) for v in sizes.split(',') if v.strip()]
        if sum(sizes)!=n or any(v not in (1,2) for v in sizes):raise ValueError('胶合分组须由1/2组成且合计等于片数')
        groups=[];count=0;kind='Aspheric' if p.get('aspheric') else 'Spheric'
        for size in sizes:
            if count==stop:groups.append(['Aperture'])
            groups.append([kind]*(size+1));count+=size
        if stop==n:groups.append(['Aperture'])
        if sum(g==['Aperture'] for g in groups)!=1:raise ValueError('光阑不能位于胶合组内部')
        cfg=dict(foclen=float(p['foclen']),fov=float(p['fov']),fnum=float(p['fnum']),bfl=float(p['bfl']),
                 thickness=float(p.get('thickness') or float(p['foclen'])+float(p['bfl'])),surf_list=groups,
                 lrs=[1e-3,1e-3,1e-2,1e-4],curriculum_iters=int(p.get('curriculum_iters',2000)),
                 refine_iters=int(p.get('refine_iters',3000)),seed=int(p.get('seed',42)))
    for key in ('foclen','fov','fnum','bfl','thickness'):
        if isinstance(cfg[key],bool) or not isinstance(cfg[key],(int,float)) or not math.isfinite(cfg[key]) or cfg[key]<=0:raise ValueError('无效官方输入：'+key)
        cfg[key]=float(cfg[key])
    if not 0<cfg['fov']<150 or cfg['thickness']<=cfg['bfl']:raise ValueError('视场或初始总长/BFL无效')
    if len(cfg['lrs'])!=4 or any(not math.isfinite(float(v)) or v<=0 for v in cfg['lrs']):raise ValueError('官方学习率需4个正数')
    if not isinstance(cfg['seed'],int) or not 0<=cfg['seed']<2**32:raise ValueError('随机状态非法')
    if any(not isinstance(cfg[k],int) or not 0<=cfg[k]<=20000 for k in ('curriculum_iters','refine_iters')):raise ValueError('官方阶段预算需为整数')
    phase=p.get('resume_phase')
    if phase!='finalize' and cfg['refine_iters']<1:raise ValueError('官方完整流程的精调预算至少1轮')
    if phase not in ('refine','finalize') and cfg['curriculum_iters']<4:raise ValueError('官方课程预算至少4轮')
    allowed={'Spheric','Aspheric','Aperture'}
    if not cfg['surf_list'] or any(not isinstance(g,list) or any(s not in allowed for s in g) for g in cfg['surf_list']):raise ValueError('无效官方surf_list')
    if sum(g==['Aperture'] for g in cfg['surf_list'])!=1 or not 1<=sum(len(g)-1 for g in cfg['surf_list'] if g!=['Aperture'])<=16:raise ValueError('官方结构需1个独立光阑及1～16片玻璃')
    if any(g!=['Aperture'] and (not 2<=len(g)<=3 or 'Aperture' in g) for g in cfg['surf_list']):raise ValueError('无效原生镜片分组')
    if p.get('device','auto') not in ('auto','cuda'):raise ValueError('此固定版官方create_lens初始化直接访问CUDA；严格原版入口请用自动/GPU，CPU优化可选Optiland')
    return cfg

def cra_input(p):
    raw=p.get('cra_cap')
    if raw in (None,''):return None
    if isinstance(raw,bool):raise ValueError('CRA上限需为角度数值')
    value=float(raw)
    if not math.isfinite(value) or not 0<=value<90:raise ValueError('CRA上限需为0～90°之间（不含90°）')
    return value

def apply_native_cra(lens,cap):
    """Input only: native public attribute and native FOV setter; no loss replacement."""
    lens.sensor_cra_cap=float(cap)
    lens.set_fov(float(lens.rfov_eff))
    return dict(requested_sensor_cra_cap_deg=float(cap),effective_chief_ray_angle_max_deg=float(lens.chief_ray_angle_max),
                native_rule='min(half field angle, sensor_cra_cap)',soft_constraint=True)

def normalize(p):
    if p.get('design_import_mode')=='resume':raise ValueError('AutoLens官方直跑暂不接受转换后的SEQ/ZMX起点；可直接分析或使用Optiland沿用结构')
    cap=cra_input(p)
    if cap is None:p.pop('cra_cap',None)
    else:p['cra_cap']=cap
    for key in ('fixed_stop_z_mm','fixed_stop_radius_mm','fixed_ttl_mm','fixed_glasses','distortion_max',
                'bfl_min','bfl_max','ttl_min','ttl_max','air_edge_min','air_edge_max','air_center_min','air_center_max',
                'thick_edge_min','thick_edge_max','thick_center_min','thick_center_max','sag2diam_max','diam2thick_max',
                'tmax2tmin_max','surf_angle_max','bend_angle_max','w_cra','w_ray_bend','w_clearance','w_envelope','w_profile','w_dist'):
        if p.get(key) not in (None,'',[]):raise ValueError('官方AutoLens入口未使用此额外约束：'+key)
    if p.get('cover_glass') or p.get('object_at_infinity') or p.get('field_mode')=='manual':raise ValueError('本路线按官方main输入运行，不接保护片/真无限远/手动XY视场约束')
    if p.get('requirements') or p.get('requirements_version'):raise ValueError('AutoLens官方入口不接额外统一约束，请使用官方配置输入；自定义条件可选择Optiland')
    if p.get('obj_depth') not in (None,'',20000,'20000'):raise ValueError('此官方main入口采用原生物距-20000mm，不覆盖物距')
    if p.get('num_ring') not in (None,'',8,'8') or p.get('centroid') not in (None,'','auto'):raise ValueError('不覆盖官方main的采样网格或质心策略')
    if p.get('glass_policy') not in (None,'','native'):raise ValueError('官方main使用内置CDGM匹配，不启用MA/A等外层玻璃池')
    if p.get('spp') not in (None,'',512,'512'):raise ValueError('官方默认课程512/精调1024光线，不接受外层采样覆盖')
    cfg=config_from_params(p);p['autolens_config']=cfg;p['autolens_protocol']=PROTOCOL
    for k in ('foclen','fov','fnum','bfl','thickness','curriculum_iters','refine_iters','seed'):p[k]=cfg[k]
    for key in ('requirements','requirements_version','spec_contract','spectrum','glass_selection','design_import_id','design_import_mode'):p.pop(key,None)
    p.update(glass_table='CDGM',optim_mat=True,prune=False,glass_policy='native',glass_catalog_revision='upstream',spp=512,centroid='auto',num_ring=8,wavelength_min_nm=486,wavelength_max_nm=656)
    return cfg

def program_for(p,split=False):
    path,body=upstream_program();original=ast.dump(ast.Module(body=body,type_ignores=[]),include_attributes=False)
    phase=p.get('resume_phase');modified=copy.deepcopy(body);resume=p.get('resume_lens')
    if resume:
        kept=[];skip_course=False
        for node in modified:
            text=ast.unparse(node)
            if text.startswith('lens = create_lens('):node=ast.parse('lens = GeoLens(filename=__resume_path)').body[0]
            elif text.startswith('lens.set_target_fov_fnum('):continue
            elif phase=='refine' and text.startswith("curriculum_iters = cfg["):skip_course=True;continue
            elif phase=='refine' and skip_course:
                if text.startswith('use_centroid ='):skip_course=False
                else:continue
            elif phase=='refine' and text.startswith('lens = GeoLens('):continue
            elif text.startswith('create_video_from_images('):continue
            kept.append(node)
        modified=kept
    cap=cra_input(p)
    if cap is not None:
        with_inputs=[]
        for node in modified:
            text=ast.unparse(node)
            if text.startswith('lens.curriculum_design(') or text.startswith('lens.optimize('):
                stage='curriculum' if text.startswith('lens.curriculum_design(') else 'refine'
                with_inputs.append(ast.parse(f'__apply_native_cra(lens, {stage!r})').body[0])
            with_inputs.append(node)
            if text=='lens.post_computation()':with_inputs.append(ast.parse("__apply_native_cra(lens, 'final')").body[0])
        modified=with_inputs
    program=ast.fix_missing_locations(ast.Module(body=modified,type_ignores=[]))
    compiled=[(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),str(path),'exec'),ast.unparse(node)) for node in program.body] if split else compile(program,str(path),'exec')
    return compiled,dict(protocol=PROTOCOL,upstream_main_ast_sha256=hashlib.sha256(original.encode()).hexdigest(),
        executed_ast_sha256=hashlib.sha256(ast.dump(program,include_attributes=False).encode()).hexdigest(),main_ast_unchanged=not bool(resume) and cap is None,
        input_binding='MOBILE_CONFIG plus native sensor_cra_cap/set_fov setup' if cap is not None else 'MOBILE_CONFIG dictionary only',output_binding='unchanged upstream results directory under private run cwd',resume_entry=phase if resume else None,
        optical_methods_replaced=[],native_input_additions={'sensor_cra_cap':cap} if cap is not None else {},resume_output_omissions=['video only: resume can contain mixed image dimensions'] if resume else [],default_sampling=dict(curriculum=dict(spp=512,num_ring=8,num_arm=1),refine=dict(spp=1024,num_ring=8,num_arm=2)),
        default_spectrum=dict(wavelengths_um=[.656,.587,.486],primary_um=.587),native_catalog='upstream CDGM')
