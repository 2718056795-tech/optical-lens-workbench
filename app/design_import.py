"""Read-only SEQ/ZMX preflight, selectable requirements and safe warm starts.

Files are parsed as data; no macro or external program is executed. Unsupported
conditions prevent warm starts while known requirements remain available.
"""
import copy,hashlib,json,math,re,warnings
from pathlib import Path
ROOT=Path(__file__).resolve().parent;IMPORTS=ROOT/'imports'


def decode(raw):
    encodings=['utf-16','utf-8-sig','gb18030'] if raw[:2] in (b'\xff\xfe',b'\xfe\xff') else ['utf-8-sig','gb18030']
    for encoding in encodings:
        try:return raw.decode(encoding)
        except UnicodeError:pass
    raise ValueError('无法识别文本编码；ZOS二进制请先另存为ZMX文本')


def _number(v):
    value=float(v)
    if not math.isfinite(value):raise ValueError('需要有限数值')
    return value


def _zmx_preflight(text):
    tokens=[(i,line.split()) for i,line in enumerate(text.splitlines(),1) if line.strip()]
    allowed={'VERS','MODE','NAME','NOTE','UNIT','ENPD','FNUM','PFIL','OBNA','FLOA','FTYP','XFLN','YFLN','XFLD','YFLD','WAVM','WAVL','PWAV','FWGN','SURF','TYPE','CURV','DISZ','GLAS','STOP','DIAM','CONI','GCAT','PARM','VDXN','VDYN','VCXN','VCYN','VANN','CLAP','FLAP','HIDE','MIRR','SLAB'}
    blockers=[];columns={};declared=None;kind='angle';patch={};waves=[];weights=[];primary=0;surface_index=None;unit=None;mode=None;surface_ids=[];raw_materials={}
    for line,t in tokens:
        cmd=t[0].upper();reason=None
        if cmd=='SURF':surface_index=int(t[1]);surface_ids.append(surface_index)
        if cmd=='UNIT' and len(t)>1:unit=t[1].upper()
        if cmd=='GLAS' and surface_index is not None:raw_materials[surface_index-1]=t[1].lower()
        if cmd=='MODE' and len(t)>1:mode=t[1].upper()
        if cmd=='DISZ' and surface_index==0:
            if t[1].upper()=='INFINITY':patch.update(object_at_infinity=True,obj_depth=20000.)
            else:
                distance=_number(t[1])
                if distance>0:patch.update(object_at_infinity=False,obj_depth=distance)
                else:reason='零或虚物距尚不能原样续算'
        if cmd not in allowed:reason='尚未验证此指令，不能保证原结构完整续算'
        elif cmd=='MODE' and t[1:]!=['SEQ']:reason='仅支持顺序系统'
        elif cmd=='UNIT' and (len(t)<2 or t[1].upper()!='MM'):reason='当前仅支持毫米单位'
        elif cmd=='TYPE' and (len(t)<2 or t[1].upper()!='STANDARD'):reason='当前续算支持居中球面与独立平面光阑'
        elif cmd=='CONI' and _number(t[1])!=0:reason='圆锥面尚未纳入续算支持'
        elif cmd=='PARM' and len(t)>2 and _number(t[2])!=0:reason='非零特殊面参数尚未支持'
        elif cmd=='CLAP' and len(t)>2 and _number(t[1])!=0:reason='中心遮挡尚不能原样续算'
        elif cmd=='GLAS' and len(t)>1 and t[1].upper() in ('MODEL','MIRROR','___BLANK'):reason='模型玻璃/反射面不能按真实目录玻璃原样续算'
        elif cmd in ('VDXN','VDYN','VCXN','VCYN','VANN') and any(_number(v)!=0 for v in t[1:]):reason='非零渐晕/瞳孔偏移尚未完整重放'
        elif cmd=='FTYP':
            if len(t)<5:reason='缺少明确的视场和波长数量'
            else:
                declared=int(t[3]);kind={0:'angle',1:'object_height',2:'paraxial_image_height',3:'real_image_height'}.get(int(t[1]),'unsupported')
                if kind=='unsupported' or int(t[2])!=0 or len(t)>7 and int(t[7])!=0:reason='此视场/远心/无焦模式尚未验证'
        if cmd in ('XFLN','XFLD'):columns['x']=[_number(v) for v in t[1:]]
        elif cmd in ('YFLN','YFLD'):columns['y']=[_number(v) for v in t[1:]]
        elif cmd=='FWGN':columns['weight']=[_number(v) for v in t[1:]]
        elif cmd in ('FNUM','PFIL'):patch['fnum']=_number(t[1])
        elif cmd in ('WAVM','WAVL'):
            if len(t)<4:reason='波长记录缺少权重'
            else:waves.append(_number(t[2]));weights.append(_number(t[3]))
        elif cmd=='PWAV':primary=int(t[1])-1
        if reason:blockers.append(dict(line=line,command=cmd,reason=reason))
    if declared is None or not 1<=declared<=32 or any(len(columns.get(k,[]))<declared for k in ('x','y')):
        blockers.append(dict(command='FIELDS',line=0,reason='缺少明确的完整视场表，或超过32个有效视场'));fields=[]
    else:
        if 'weight'in columns and len(columns['weight'])<declared:raise ValueError('视场权重数量小于有效视场数')
        fields=[dict(index=i+1,x=columns['x'][i],y=columns['y'][i],weight=columns.get('weight',[1.]*declared)[i]) for i in range(declared)]
        if any(f['weight']<0 for f in fields) or not any(f['weight']>0 for f in fields):blockers.append(dict(line=0,command='FWGN',reason='视场权重无效'))
    if waves and 0<=primary<len(waves):patch.update(spectral_samples_um=waves,spectral_sample_weights=weights,wvln_primary=waves[primary])
    if unit!='MM':blockers.append(dict(line=0,command='UNIT',reason='未明确声明毫米单位'))
    if mode!='SEQ':blockers.append(dict(line=0,command='MODE',reason='未明确声明顺序系统'))
    if surface_ids!=list(range(len(surface_ids))):blockers.append(dict(line=0,command='SURF',reason='表面编号重复/遗漏/次序不连续'))
    if fields:
        patch['field_count']=len(fields)
        if kind=='angle' or kind=='object_height' and unit=='MM':patch.update(field_mode='manual',field_definition=kind,field_rows=[{k:f[k] for k in ('x','y','weight')} for f in fields])
        elif kind in ('paraxial_image_height','real_image_height') and unit=='MM':patch['imgh']=max(math.hypot(f['x'],f['y']) for f in fields)
    return dict(blockers=blockers,raw_fields=fields,raw_materials=raw_materials,field_definition=kind,patch=patch,configuration_count=1)


def _seq_preflight(raw,configuration):
    from codev_import import commands,decode_seq,inspect_seq
    text,_=decode_seq(raw);rows=commands(text);patch={}
    for row in rows:
        t=row['tokens']
        if t[0]=='FNO' and len(t)==2:patch['fnum']=_number(t[1])
        elif t[0]=='WL':patch['spectral_samples_um']=[_number(v)/1000 for v in t[1:]]
        elif t[0]=='WTW':patch['spectral_sample_weights']=[_number(v) for v in t[1:]]
        elif t[0]=='REF':patch['_primary_index']=int(t[1])-1
        elif t[0]=='SO' and len(t)>2:
            try:
                distance=_number(t[2])
                if distance>=1e10:patch.update(object_at_infinity=True,obj_depth=20000.)
                elif distance>0:patch.update(object_at_infinity=False,obj_depth=distance)
            except ValueError:pass
    waves=patch.get('spectral_samples_um',[]);index=patch.pop('_primary_index',0)
    if waves and 0<=index<len(waves):patch['wvln_primary']=waves[index]
    report=inspect_seq(raw)
    contract=report['field_contract']
    if not 1<=configuration<=contract['configuration_count']:raise ValueError('配置编号无效')
    if contract['dimension']!='M':patch.pop('obj_depth',None)
    fields=contract['configurations'][configuration-1]['fields'];patch['field_count']=len(fields)
    if contract['type'] in ('angle','object_height') and contract['unit'] in ('deg','mm'):
        patch.update(field_mode='manual',field_definition=contract['type'],field_rows=[{k:f[k] for k in ('x','y','weight')} for f in fields])
    elif contract['type'] in ('real_image_height','paraxial_image_height') and contract['unit']=='mm':patch['imgh']=max(math.hypot(f['x'],f['y']) for f in fields)
    raw_materials={};index=0
    for row in rows:
        t=row['tokens']
        if t[0]=='S' and len(t)>=3:
            name=t[3].lower() if len(t)>3 else 'air'
            for suffix in ('_cdgm','_schott'):
                if name.endswith(suffix):name=name[:-len(suffix)]
            raw_materials[index]=name;index+=1
    return dict(blockers=report['blockers'],raw_fields=fields,field_unit=contract['unit'],raw_materials=raw_materials,
                field_definition=contract['type'],patch=patch,configuration_count=contract['configuration_count'])


def _canonical(optic):
    import numpy as np
    from glass_selection import catalog_data
    native=list(optic.surfaces);physical=native[1:-1]
    if not physical:raise ValueError('文件中没有物理表面')
    stop=next(i for i,s in enumerate(physical) if s.is_stop)
    if not math.isinf(float(np.asarray(physical[stop].geometry.radius).item())):raise ValueError('曲面上的光阑尚不能原样转换为独立平面光阑')
    def material(surface):
        name=str(getattr(surface.material_post,'name','air')).lower()
        for suffix in ('_cdgm','_schott'):
            if name.endswith(suffix):name=name[:-len(suffix)]
        return name
    names=[material(s) for s in physical]
    if names[stop]!='air' or stop>0 and names[stop-1]!='air':raise ValueError('独立光阑必须位于空气中')
    glass_names=sorted(set(names)-{'air'})
    catalog=None
    for manufacturer,revision in [('CDGM','202609'),('SCHOTT','202412')]:
        rows=catalog_data(manufacturer,revision)['rows'];available={r['name'].lower() for r in rows if r['selectable']}
        if set(glass_names)<=available:catalog=(manufacturer,revision);break
    if catalog is None:raise ValueError('含模型玻璃、未知玻璃或跨制造商材料，尚不能完整原样续算')
    efl=float(np.asarray(optic.paraxial.f2()).item());fnum=float(np.asarray(optic.paraxial.FNO()).item())
    if not 0<efl<=500 or not .7<=fnum<=22:raise ValueError('源结构焦距/F数超出当前工作台范围')
    y,_=optic.paraxial.marginal_ray();stop_radius=abs(float(np.asarray(y).reshape(-1)[stop+1]))
    clear=getattr(getattr(physical[stop],'aperture',None),'r_max',None)
    if clear is not None:stop_radius=min(stop_radius,float(clear))
    if not math.isfinite(stop_radius) or stop_radius<=0:raise ValueError('无法建立有效的物理光阑')
    rows=[];z=0.
    for i,s in enumerate(physical):
        radius=float(np.asarray(s.geometry.radius).item());thick=float(np.asarray(s.thickness).item())
        if not math.isfinite(thick) or thick<=0:raise ValueError('零/负间隔或非有限像面间隔尚不支持原样续算')
        ap=getattr(s,'aperture',None);r=getattr(ap,'r_max',None)
        if r is None:r=getattr(s,'semi_aperture',None)
        if i==stop:r=stop_radius
        if r is None or not math.isfinite(float(r)) or float(r)<=0:raise ValueError(f'第{i+1}面缺少可验证的有效口径，不能自动猜测')
        rows.append(dict(idx=i,type='Aperture' if i==stop else 'Spheric',roc=radius if math.isfinite(radius) else 1e14,r=float(r),mat2=names[i],d_next=thick,**{'(d)':z,'(c)':1/radius if math.isfinite(radius) else 0.}))
        z+=thick
    cover=None;end=len(rows)
    if len(rows)>=2 and rows[-2]['mat2']!='air' and rows[-1]['mat2']=='air' and abs(rows[-2]['(c)'])<1e-12 and abs(rows[-1]['(c)'])<1e-12:
        cover=dict(cover_glass=True,cover_material=rows[-2]['mat2'],cover_thickness_mm=rows[-2]['d_next'],cover_gap_mm=rows[-1]['d_next']);end-=2
    groups=[];glasses=[];open_count=0;stop_after=None
    for i,s in enumerate(rows[:end]):
        if s['type']=='Aperture':
            if open_count:raise ValueError('光阑位于玻璃组内部')
            stop_after=len(glasses);continue
        if s['mat2']!='air':open_count+=1;glasses.append(s['mat2'])
        else:
            if open_count not in (1,2):raise ValueError('当前支持单片与双胶合组，源文件拓扑超出范围')
            groups.append(open_count);open_count=0
    if open_count or stop_after is None:raise ValueError('源结构空气/玻璃拓扑不完整')
    distance=float(np.asarray(native[0].thickness).item());infinity=math.isinf(distance)
    if not infinity and distance<=0:raise ValueError('零/虚物距尚未纳入原样续算支持')
    native_fields=optic.fields.fields;kind=type(optic.fields.field_definition).__name__
    if not 1<=len(native_fields)<=32:raise ValueError('源文件有效视场数超出1~32')
    scale=float(optic.fields.max_field) or 1.;fields=[]
    for f in native_fields:
        if infinity:
            if kind!='AngleField':raise ValueError('无穷远像高视场转换尚未完整验证，请使用角度定义文件')
            fields.append(dict(x=float(f.x),y=float(f.y),weight=float(f.weight)))
        else:
            x,y,zz=optic.fields.field_definition.get_ray_origins(optic,float(f.x)/scale,float(f.y)/scale,0.,0.,0.,0.)
            row=dict(x=float(np.asarray(x).reshape(-1)[0]),y=float(np.asarray(y).reshape(-1)[0]),weight=float(f.weight))
            if not all(math.isfinite(row[k]) for k in ('x','y','weight')):raise ValueError('源模型不能为全部视场建立有限物方坐标')
            if kind in ('RealImageHeightField','ParaxialImageHeightField'):row.update(target_x_mm=float(f.x),target_y_mm=float(f.y))
            fields.append(row)
    wavelengths=[float(w) for w in optic.wavelengths.get_wavelengths()];weights=list(map(float,optic.wavelengths.weights));primary=float(optic.wavelengths.primary_wavelength.value)
    patch=dict(foclen=efl,fnum=fnum,thickness=z,fixed_ttl_mm=z,bfl=rows[-1]['d_next'],
               obj_depth=20000. if infinity else abs(distance),object_at_infinity=infinity,
               elements=len(glasses),lens_group_sizes=','.join(map(str,groups)),stop_pos=stop_after,
               fixed_stop_z_mm=rows[stop]['(d)'],fixed_stop_radius_mm=stop_radius,
               cover_glass=bool(cover),glass_table=catalog[0],glass_catalog_revision=catalog[1],
               glass_policy='custom',allowed_glasses=glass_names,fixed_glasses=','.join(glasses),
               field_mode='manual',field_definition='angle' if infinity else 'object_height',field_rows=fields,field_count=len(fields),
               spectral_samples_um=wavelengths,spectral_sample_weights=weights,wvln_primary=primary,
               optim_mat=False,prune=False,aspheric=False)
    if cover:patch.update(cover)
    glass_gaps=[s['d_next'] for s in rows[:end] if s['mat2']!='air'];air_gaps=[s['d_next'] for s in rows[:end-1] if s['mat2']=='air']
    patch.update(ttl_min=.1,ttl_max=z,bfl_min=.01,bfl_max=max(2*rows[-1]['d_next'],rows[-1]['d_next']+.1),
                 thick_center_min=max(.01,min(.4,min(glass_gaps)/2)),thick_center_max=max(20.,max(glass_gaps)*2),
                 air_center_min=max(.001,min(.1,min(air_gaps)/2 if air_gaps else .1)),air_center_max=max(50.,max(air_gaps)*2 if air_gaps else 50.))
    maximum=max(math.hypot(math.tan(math.radians(f['x'])),math.tan(math.radians(f['y']))) if infinity else math.hypot(f['x'],f['y'])/distance for f in fields)
    patch['fov']=2*math.degrees(math.atan(maximum)) or 2.
    return dict(surfaces=rows,**{'(d_sensor)':z},foclen=efl,fnum=fnum,object_at_infinity=infinity),patch


def inspect(raw,filename,configuration=1):
    if not isinstance(raw,bytes) or not 0<len(raw)<=2*1024*1024:raise ValueError('设计文件需为2MB以内的非空文件')
    suffix=Path(filename).suffix.lower()
    if suffix not in ('.seq','.zmx'):raise ValueError('支持SEQ和ZMX文本；ZOS二进制请在Zemax中另存为ZMX')
    if suffix=='.zmx' and configuration!=1:raise ValueError('当前ZMX仅支持单配置')
    digest=hashlib.sha256(raw).hexdigest();token=hashlib.sha256((digest+':'+str(configuration)).encode()).hexdigest()
    folder=IMPORTS/token;folder.mkdir(parents=True,exist_ok=True);source=folder/('source'+suffix)
    if not source.exists() or source.read_bytes()!=raw:source.write_bytes(raw)
    report=_seq_preflight(raw,configuration) if suffix=='.seq' else _zmx_preflight(decode(raw))
    report.update(import_id=token,filename=Path(filename).name,sha256=digest,configuration=configuration,can_resume=False,notes=[])
    data=None
    if not report['blockers']:
        try:
            if suffix=='.seq':
                from codev_import import load_for_analysis
                optic,_=load_for_analysis(source)
            else:
                from optiland.fileio import load_zemax_file
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter('always');optic=load_zemax_file(str(source))
                errors=[str(w.message) for w in caught if not issubclass(w.category,DeprecationWarning)]
                if errors:raise ValueError('读取器警告：'+'；'.join(errors))
                # The pinned native converter does not carry FWGN reliably.
                # Rebuild from the explicitly validated original coordinate table.
                optic.fields.fields.clear();optic.fields.set_type(report['field_definition'])
                for f in report['raw_fields']:optic.fields.add(x=f['x'],y=f['y'],weight=f['weight'])
                fields=optic.fields.fields
                if len(fields)!=len(report['raw_fields']) or any(float(a.x)!=b['x'] or float(a.y)!=b['y'] or float(a.weight)!=b['weight'] for a,b in zip(fields,report['raw_fields'])):
                    raise ValueError('导入前后视场坐标/数量/权重不一致')
                if len(optic.fields.get_field_coords())!=len(fields):raise ValueError('原生分析接口将合并视场，拒绝丢失原始行')
            if report['patch'].get('spectral_samples_um'):
                waves=report['patch']['spectral_samples_um'];original=optic.wavelengths.get_wavelengths()
                if len(waves)!=len(original) or any(abs(a-b)>1e-12 for a,b in zip(waves,original)):raise ValueError('原生读取改变了波长列表/顺序')
                weights=report['patch'].get('spectral_sample_weights',[1.]*len(waves))
                if len(weights)!=len(waves) or any(w<0 for w in weights) or sum(weights)<=0:raise ValueError('原波长权重无效')
                for w,weight in zip(optic.wavelengths.wavelengths,weights):w.weight=weight
                optic.wavelengths.primary_index=waves.index(report['patch']['wvln_primary'])
            data,patch=_canonical(optic)
            for i,name in report.get('raw_materials',{}).items():
                index=int(i)
                if index>=len(data['surfaces']) or data['surfaces'][index]['mat2'].lower()!=name:raise ValueError('读取器玻璃牌号与原始文件不一致，拒绝替换材料')
            report['patch'].update(patch);report['can_resume']=True
            from optiland.fileio import save_optiland_file
            save_optiland_file(optic,str(folder/'native_optic.json'))
            report['native_model_sha256']=hashlib.sha256((folder/'native_optic.json').read_bytes()).hexdigest()
        except Exception as exc:report['blockers'].append(dict(line=0,command='MODEL',reason=str(exc)))
    from engine_io import write_json
    report['available_sections']=[name for name,keys in SECTIONS.items() if any(key in report['patch'] for key in keys)]
    if data:
        write_json(folder/'geometry.json',data);report['geometry_sha256']=hashlib.sha256((folder/'geometry.json').read_bytes()).hexdigest()
    report['can_analyze']=bool(data and report.get('native_model_sha256') and not report['blockers'])
    write_json(folder/'report.json',report)
    return report


SECTIONS={
 'optics':['foclen','fnum','fov','obj_depth','object_at_infinity'],
 'fields':['field_mode','field_definition','field_rows','field_count','imgh'],
 'spectrum':['spectral_samples_um','spectral_sample_weights','wvln_primary'],
 'structure':['elements','lens_group_sizes','stop_pos','thickness','fixed_ttl_mm','bfl','cover_glass','cover_material','cover_thickness_mm','cover_gap_mm'],
 'stop':['fixed_stop_z_mm','fixed_stop_radius_mm'],
 'materials':['glass_table','glass_catalog_revision','glass_policy','allowed_glasses','fixed_glasses']}
SECTIONS['bounds']=['ttl_min','ttl_max','bfl_min','bfl_max','air_center_min','air_center_max','thick_center_min','thick_center_max']


def get_report(token):
    if not isinstance(token,str) or not re.fullmatch('[a-f0-9]{64}',token):raise ValueError('导入标识无效')
    path=IMPORTS/token/'report.json'
    if not path.is_file():raise ValueError('导入记录不存在，请重新选择文件')
    return json.loads(path.read_text(encoding='utf-8'))


def selected_patch(token,sections,mode):
    report=get_report(token)
    if mode not in ('resume','reset'):raise ValueError('请选择续算或重新生成')
    if mode=='resume' and not report['can_resume']:raise ValueError('源结构含未支持条件，禁止不完整续算；可选择已识别技术要求重新设计')
    if not isinstance(sections,list) or any(s not in SECTIONS for s in sections):raise ValueError('回填条件选择无效')
    chosen=set(sections)
    if mode=='resume':chosen.update(('structure','materials','stop','bounds'))
    patch={key:copy.deepcopy(report['patch'][key]) for section in chosen for key in SECTIONS[section] if key in report['patch']}
    if 'spectrum' in chosen and patch.get('spectral_samples_um'):
        from autolens_three_wavelength_input import from_file_wavelengths_um
        spectrum=from_file_wavelengths_um(patch['spectral_samples_um'],patch.get('wvln_primary'),patch.get('spectral_sample_weights'))
        patch.update(wavelength_min_nm=spectrum['input_range_nm'][0],wavelength_max_nm=spectrum['input_range_nm'][1],source_spectrum=spectrum['source_spectrum'],spectrum_mode='range')
        for key in ('spectral_samples_um','spectral_sample_weights','wvln_primary'):patch.pop(key,None)
    patch.update(design_import_id=token,design_import_mode=mode)
    return patch


def prepare_start(p):
    token=p.get('design_import_id')
    if not token:return p
    report=get_report(token)
    p['source_design']=dict(filename=report['filename'],sha256=report['sha256'],mode=p.get('design_import_mode'))
    if p.get('design_import_mode')!='resume':
        if report['blockers'] and p.get('import_unknowns_ack') is not True:raise ValueError('请先确认导入报告中的未支持条件；重新设计仅使用你已选择回填的目标')
        return p
    if not report['can_resume']:raise ValueError('文件未通过完整续算预检')
    if p.get('seeds') not in (None,'',[]):raise ValueError('原结构续算使用单一源结构；多种子请选重新生成')
    from engine_io import write_json
    from glass_selection import stamp_json
    from spectrum import stamp_spectrum
    from design_contract import load
    geometry=IMPORTS/token/'geometry.json'
    if hashlib.sha256(geometry.read_bytes()).hexdigest()!=report.get('geometry_sha256'):raise ValueError('导入结构缓存已变化，请重新选择原文件')
    data=json.loads(geometry.read_text(encoding='utf-8'))
    req=p['requirements']
    if data['object_at_infinity']!=req['object_at_infinity']:raise ValueError('续算时物方类型变化，请选择重新生成或保留文件的物方条件')
    data.update(r_sensor=req['sensor_radius_mm'],obj_depth=-req['object_distance_mm'],wvln_ls=req['spectrum']['wavelengths_um'],wvln_primary=req['spectrum']['primary_um'],spectral_weights=req['spectrum']['weights'])
    file=IMPORTS/token/('prepared_'+req['sha256']+'.json');write_json(file,data)
    stamp_json(file,req['glass_selection']);stamp_spectrum(file,p);load(p).stamp(file)
    load(p).verify(json.loads(file.read_text(encoding='utf-8')))
    p['resume_lens']=str(file);p['design_start_mode']='resume'
    return p


def create_analysis_record(token,runs_dir):
    import datetime as dt,shutil
    report=get_report(token)
    if not report.get('can_resume') or not report.get('geometry_sha256'):raise ValueError('文件未通过完整模型校核，不能静默遗漏条件后分析；请查看导入报告')
    folder=IMPORTS/token;geometry=folder/'geometry.json'
    if hashlib.sha256(geometry.read_bytes()).hexdigest()!=report['geometry_sha256']:raise ValueError('导入缓存已变化，请重新选择文件')
    p=copy.deepcopy(report['patch']);data=json.loads(geometry.read_text(encoding='utf-8'))
    # Keep original spectral list/weights. Three-point range resampling is optimization input only.
    p.update(spec_contract='v4-explicit-v1',requirements_version='lens-requirements-v1',workflow_mode='direct-v1',engine='imported',reference=True,label=report['filename'],curriculum_iters=0,refine_iters=0,design_start_mode='analysis-only')
    from design_requirements import compile_requirements
    from design_contract import load
    from glass_selection import stamp_json,resolve_selection
    from engine_io import write_json
    p['requirements']=compile_requirements(p);p['glass_selection']=resolve_selection(p)
    original=dict(mode='imported-analysis-v1',wavelengths_um=list(p['spectral_samples_um']),primary_um=p['wvln_primary'],weights=list(p['spectral_sample_weights']),
                  input_range_nm=[min(p['spectral_samples_um'])*1000,max(p['spectral_samples_um'])*1000],policy='original source wavelengths and weights; analysis only, no resampling')
    p['requirements']['spectrum']=original;p['requirements'].pop('sha256',None)
    p['requirements']['sha256']=hashlib.sha256(json.dumps(p['requirements'],sort_keys=True,ensure_ascii=True,separators=(',',':')).encode()).hexdigest()
    data.update(r_sensor=p['requirements']['sensor_radius_mm'],obj_depth=-p['requirements']['object_distance_mm'],wvln_ls=p['spectral_samples_um'],wvln_primary=p['wvln_primary'],spectral_weights=p['spectral_sample_weights'])
    native=folder/'native_optic.json'
    if not native.is_file() or hashlib.sha256(native.read_bytes()).hexdigest()!=report.get('native_model_sha256'):raise ValueError('原生导入模型缺失或变化，请重新导入')
    data.update(optiland_native_source='native_optic.json',native_model_sha256=report['native_model_sha256'],
                source_original_file='original'+Path(report['filename']).suffix.lower(),source_original_sha256=report['sha256'])
    # compile_requirements preserves supplied original spectral samples here.
    ref=dt.datetime.now().strftime('imported_%Y%m%d_%H%M%S_%f');out=Path(runs_dir)/ref;out.mkdir(parents=True,exist_ok=False)
    dest=out/'imported_lens.json';write_json(dest,data);stamp_json(dest,p['glass_selection']);load(p).stamp(dest)
    shutil.copy2(native,out/'native_optic.json')
    shutil.copy2(folder/('source'+Path(report['filename']).suffix.lower()),out/('original'+Path(report['filename']).suffix.lower()))
    write_json(out/'params.json',p);write_json(out/'import_report.json',report)
    write_json(out/'progress.json',dict(status='imported',stage='import',engine='imported',params=p,files=['imported_lens.json'],source_design=report['filename']))
    return dict(run_id=ref,source_file='imported_lens.json',status='imported',optimization_started=False)
