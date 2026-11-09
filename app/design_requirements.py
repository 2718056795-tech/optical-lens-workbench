"""UI-independent, versioned requirements for both optimization engines.

Only modelling requirements live here. No optimizer or SEQ execution is defined.
All lengths are mm and internal wavelengths are micrometres.
"""
import hashlib
import json
import math

VERSION='lens-requirements-v1'


def number(raw,name,low=None,high=None):
    if isinstance(raw,bool):raise ValueError(name+' 必须是数值')
    try:value=float(raw)
    except (ValueError,TypeError):raise ValueError(name+' 必须是数值')
    if not math.isfinite(value) or low is not None and value<low or high is not None and value>high:
        raise ValueError(name+' 超出允许范围')
    return value


def optional(p,key,low=None,high=None):
    return None if p.get(key) in (None,'') else number(p[key],key,low,high)


def enabled(p):
    return p.get('requirements_version')==VERSION or 'requirements' in p


def prepare_fields(p):
    """Normalize manual field extent before existing first-order form checks."""
    if not enabled(p):return
    if p.get('field_mode','auto')!='manual':return
    rows=p.get('field_rows')
    if not isinstance(rows,list) or not 1<=len(rows)<=32:raise ValueError('手动视场需有1~32行')
    definition=p.get('field_definition','angle')
    if p.get('object_at_infinity') and definition!='angle':raise ValueError('无穷远物方请使用角度视场')
    depth=abs(number(p.get('obj_depth') or 20000,'物距',.1,1e9))
    extent=0.
    for row in rows:
        x=number(row.get('x',0),'视场X');y=number(row.get('y',0),'视场Y')
        if definition=='angle':
            number(x,'X角',-75,75);number(y,'Y角',-75,75)
            tangent=math.hypot(math.tan(math.radians(x)),math.tan(math.radians(y)))
        elif definition=='object_height':tangent=math.hypot(x,y)/depth
        else:raise ValueError('视场定义仅支持物方角度或物高；真实像高需给出对应物方条件')
        extent=max(extent,2*math.degrees(math.atan(tangent)))
    if extent>150:raise ValueError('手动视场径向全角不能超过150°')
    # For a single on-axis field the entered maximum is only sensor sizing.
    if extent>0:p['fov']=extent


def compile_requirements(p):
    if not enabled(p):return None
    if p.get('aspheric'):raise ValueError('统一条件、接力和文件续算当前仅验证了球面；非球面请勿启动此流程')
    from spectrum import resolve_spectrum
    from glass_selection import resolve_selection
    focal=number(p['foclen'],'焦距',.5,500)
    infinity=bool(p.get('object_at_infinity'))
    depth=abs(number(p.get('obj_depth') or 20000,'物距',.1,1e9))
    fov=number(p['fov'],'全视场',0,150)
    mode=p.get('field_mode','auto');definition=p.get('field_definition','angle')
    distribution=p.get('field_distribution','angle')
    if mode not in ('auto','manual'):raise ValueError('视场设置方式非法')
    if definition not in ('angle','object_height'):raise ValueError('不支持的视场定义')
    if infinity and definition!='angle':raise ValueError('无穷远物方请使用角度视场')
    if distribution not in ('angle','image_height'):raise ValueError('视场分布非法')
    rows=p.get('field_rows') if mode=='manual' else None
    if mode=='auto':
        count=number(p.get('field_count',5),'视场点数',1,32)
        if not count.is_integer():raise ValueError('视场点数必须为整数')
        rows=[]
        for i in range(int(count)):
            frac=i/(count-1) if count>1 else 0.
            angle=math.radians(fov/2)*frac if distribution=='angle' else math.atan(math.tan(math.radians(fov/2))*frac)
            y=math.degrees(angle) if definition=='angle' else -depth*math.tan(angle)
            rows.append(dict(x=0.,y=y,weight=1.))
    if not isinstance(rows,list) or not 1<=len(rows)<=32:raise ValueError('视场表需有1~32行')
    fields=[]
    for index,row in enumerate(rows):
        x=number(row.get('x',0),'视场X');y=number(row.get('y',0),'视场Y')
        weight=number(row.get('weight',1),'视场权重',0,1e6)
        if definition=='angle':
            number(x,'X角',-75,75);number(y,'Y角',-75,75)
            ox=-depth*math.tan(math.radians(x));oy=-depth*math.tan(math.radians(y))
        else:ox,oy=x,y
        tx=optional(row,'target_x_mm');ty=optional(row,'target_y_mm')
        if (tx is None)!=(ty is None):raise ValueError('目标像高X/Y需同时填写或同时留空')
        explicit_target=tx is not None
        if tx is None:tx,ty=-focal*ox/depth,-focal*oy/depth
        fields.append(dict(index=index+1,x=x,y=y,weight=weight,definition=definition,
                           object_x_mm=ox,object_y_mm=oy,object_z_mm=-depth,
                           target_x_mm=tx,target_y_mm=ty,explicit_target=explicit_target))
    if not any(f['weight']>0 for f in fields):raise ValueError('至少一个视场权重需大于0')
    if len(fields)>1 and all(f['object_x_mm']==0 and f['object_y_mm']==0 for f in fields):raise ValueError('多个完全轴上视场会被分析内核合并；请设为1个轴上视场，不会自动删减')
    elements=number(p.get('elements',4),'镜片数',1,16)
    if not elements.is_integer():raise ValueError('镜片数必须为整数')
    elements=int(elements)
    raw=p.get('lens_group_sizes')
    if raw in (None,''):groups=[1]*elements
    else:
        raw=raw.split(',') if isinstance(raw,str) else raw
        if not isinstance(raw,list):raise ValueError('胶合分组格式非法')
        groups=[]
        for value in raw:
            n=number(value,'每组玻璃片数',1,2)
            if not n.is_integer():raise ValueError('每组玻璃片数需为1或2')
            groups.append(int(n))
        if sum(groups)!=elements:raise ValueError('胶合分组片数之和必须等于镜片数量')
    stop=p.get('stop_pos','middle')
    stop=0 if stop=='front' else elements if stop=='back' else elements//2 if stop=='middle' else int(stop)
    boundaries=[0];total=0
    for n in groups:total+=n;boundaries.append(total)
    if stop not in boundaries:raise ValueError('独立光阑不能插入胶合组内部，请调整分组或光阑位置')
    surf_type='Aspheric' if p.get('aspheric') else 'Spheric'
    topology=[];glass_indices=[];stop_index=None
    for group_index,n in enumerate(groups):
        if boundaries[group_index]==stop:stop_index=sum(map(len,topology));topology.append(['Aperture'])
        start=sum(map(len,topology));glass_indices.extend(range(start,start+n));topology.append([surf_type]*(n+1))
    if stop==elements:stop_index=sum(map(len,topology));topology.append(['Aperture'])
    selection=resolve_selection(p);allowed={name.lower() for name in selection['allowed_glasses']}
    fixed=p.get('fixed_glasses') or []
    fixed=[name.strip().lower() for name in fixed.split(',')] if isinstance(fixed,str) else [str(name).lower() for name in fixed]
    if fixed and len(fixed)!=elements:raise ValueError('固定玻璃清单需与主镜片片数一致，或留空自动选材')
    if any(name not in allowed for name in fixed):raise ValueError('固定玻璃含当前可用材料池以外的牌号')
    cover=None
    if p.get('cover_glass'):
        thickness=number(p.get('cover_thickness_mm',.3),'保护片厚度',.01,50)
        gap=number(p.get('cover_gap_mm',.3),'保护片至像面间距',.01,200)
        material=str(p.get('cover_material') or ('h-k9l' if selection['catalog']=='CDGM' else 'n-bk7')).strip().lower()
        if material not in allowed:raise ValueError('保护片材料不在当前可用玻璃池，请调整牌号或材料池')
        cover=dict(front_index=sum(map(len,topology)),thickness_mm=thickness,gap_mm=gap,material=material)
        topology.append(['Spheric','Spheric']);glass_indices.append(cover['front_index'])
    if p.get('optim_mat') and fixed:raise ValueError('指定固定主镜片玻璃时，请关闭连续材料联动')
    if p.get('prune'):raise ValueError('统一条件模式暂不支持自动裁面，请关闭；不会静默更改固定结构')
    count=sum(map(len,topology))
    stop_z=optional(p,'fixed_stop_z_mm',0,1000)
    ttl=optional(p,'fixed_ttl_mm',.1,2000)
    cap=float(p.get('effective_total_length_cap_mm') or p.get('thickness') or focal+float(p['bfl']))
    if ttl is not None and ttl>cap+1e-7:raise ValueError('固定总长不能超过TTL上限')
    if stop_index==0 and stop_z not in (None,0.):raise ValueError('前置光阑为首面时固定坐标应为0')
    if stop_z is not None and stop_z>=min(cap,ttl or cap):raise ValueError('光阑固定坐标需小于总长')
    stop_radius=optional(p,'fixed_stop_radius_mm',.001,200)
    minimum=[float(p.get('thick_center_min') or .4) if i in glass_indices else float(p.get('air_center_min') or .1) for i in range(count)]
    minimum[-1]=float(p.get('bfl_min') or .05)
    if cover:minimum[-2:]=[cover['thickness_mm'],cover['gap_mm']]
    if sum(minimum)>=min(cap,ttl or cap):raise ValueError('镜片/间隔/保护片的最小厚度超过可用总长')
    if stop_z is not None:
        if sum(minimum[:stop_index])>stop_z+1e-8:raise ValueError('光阑前最小间隔超过固定光阑坐标')
        if sum(minimum[stop_index:])>min(cap,ttl or cap)-stop_z+1e-8:raise ValueError('固定光阑后空间不足')
    spectrum=resolve_spectrum(p)
    if spectrum['primary_um'] not in spectrum['wavelengths_um']:raise ValueError('统一条件要求主波长为实际采样之一，请使用离散波长列表明确设置')
    result=dict(version=VERSION,fields=fields,spectrum=spectrum,object_distance_mm=depth,
                object_at_infinity=infinity,focal_length_mm=focal,fnum=float(p['fnum']),full_fov_deg=fov,
                surf_list=topology,surface_count=count,glass_indices=glass_indices,
                fixed_glasses=fixed,stop_index=stop_index,fixed_stop_z_mm=stop_z,
                fixed_stop_radius_mm=stop_radius,fixed_ttl_mm=ttl,ttl_cap_mm=cap,
                minimum_gaps_mm=minimum,cover=cover,glass_selection=selection,
                sensor_radius_mm=max(math.hypot(f['target_x_mm'],f['target_y_mm']) for f in fields) or float(p.get('imgh') or focal*math.tan(math.radians(fov/2))))
    encoded=json.dumps(result,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')
    result['sha256']=hashlib.sha256(encoded).hexdigest()
    return result
