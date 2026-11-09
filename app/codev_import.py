"""Strict SEQ field contract and preflight. Never execute a SEQ as a macro.

The native reader silently ignores XRI/YRI and configuration commands. All
analysis import paths must use load_for_analysis(), which rejects incomplete
models instead of defaulting to an on-axis field. Inspection remains available
for unsupported files, including every configuration's original field values.
"""
import copy,hashlib,math,re,shlex,warnings
from pathlib import Path

FIELD_TYPES={'XRI':('real_image_height','x','mm'),'YRI':('real_image_height','y','mm'),
             'XAN':('angle','x','deg'),'YAN':('angle','y','deg'),
             'XOB':('object_height','x','mm'),'YOB':('object_height','y','mm'),
             'XIM':('paraxial_image_height','x','mm'),'YIM':('paraxial_image_height','y','mm')}
NAMES={'real_image_height':'实际像高 RIH','angle':'物方角度','object_height':'物高','paraxial_image_height':'近轴像高'}


class SeqImportError(ValueError):pass


def decode_seq(raw):
    if not isinstance(raw,bytes) or not 0<len(raw)<=1024*1024:raise SeqImportError('SEQ文件须为1MB以内的非空文件')
    for encoding in ('utf-8-sig','gb18030'):
        try:return raw.decode(encoding),encoding
        except UnicodeDecodeError:pass
    raise SeqImportError('无法识别SEQ字符编码')


def commands(text):
    """Quote-aware comments/semicolons and ampersand continuation, with lines."""
    logical='';first=0;rows=[]
    for line_number,line in enumerate(text.splitlines(),1):
        quote=None;clean=[]
        for char in line:
            if quote:
                clean.append(char)
                if char==quote:quote=None
            elif char in ('"',"'"):quote=char;clean.append(char)
            elif char=='!':break
            else:clean.append(char)
        line=''.join(clean).strip()
        if not line:continue
        if not logical:first=line_number
        continuation=line.endswith('&');logical+=' '+(line[:-1] if continuation else line)
        if continuation:continue
        lexer=shlex.shlex(logical,posix=True,punctuation_chars=';');lexer.whitespace_split=True;lexer.commenters=''
        part=[]
        try:
            for token in lexer:
                if token==';':
                    if part:rows.append(dict(line=first,tokens=[part[0].upper(),*part[1:]]));part=[]
                else:part.append(token)
        except ValueError as exc:raise SeqImportError(f'第{first}行引号不完整：{exc}') from exc
        if part:rows.append(dict(line=first,tokens=[part[0].upper(),*part[1:]]))
        logical=''
    if logical:raise SeqImportError(f'第{first}行续行符后缺少内容')
    return rows


def numbers(values,line):
    try:result=[float(v) for v in values]
    except (TypeError,ValueError) as exc:raise SeqImportError(f'第{line}行需要明确数值，不能解析表达式/变量') from exc
    if not result or not all(math.isfinite(v) for v in result):raise SeqImportError(f'第{line}行存在空数组或非有限值')
    return result


def field_contract(rows):
    arrays={};weights=None;kind=None;unit=None;count=1;titles={};changes=[]
    dimensions=[row['tokens'][1].upper() for row in rows if row['tokens'][0]=='DIM' and len(row['tokens'])==2]
    if len(dimensions)>1:raise SeqImportError('重复定义长度单位，拒绝推测')
    dimension=dimensions[0] if dimensions else None
    for row in rows:
        t=row['tokens'];cmd=t[0];line=row['line']
        if cmd in FIELD_TYPES:
            typ,axis,u=FIELD_TYPES[cmd]
            if kind is not None and kind!=typ:raise SeqImportError(f'第{line}行混用不同视场定义，拒绝推测或覆盖')
            if axis in arrays:raise SeqImportError(f'第{line}行重复定义视场{axis.upper()}，拒绝静默覆盖')
            kind=typ;unit=u;arrays[axis]=numbers(t[1:],line)
        elif cmd=='WTF':
            if weights is not None:raise SeqImportError(f'第{line}行重复视场权重')
            weights=numbers(t[1:],line)
        elif cmd=='ZOO' and len(t)==2 and re.fullmatch(r'\d+',t[1]):
            count=int(t[1])
            if not 1<=count<=100:raise SeqImportError('配置数量须为1~100')
        elif cmd=='ZOO' and len(t)>1 and t[1].upper() in {*FIELD_TYPES,'WTF'}:
            changes.append(row)
        elif cmd=='TIT' and len(t)>=3 and re.fullmatch(r'Z\d+',t[1],re.I):titles[int(t[1][1:])]=' '.join(t[2:])
    if kind is None or set(arrays)!={'x','y'}:raise SeqImportError('缺少明确的X/Y视场数组，拒绝默认成轴上视场')
    n=len(arrays['x'])
    if n!=len(arrays['y']) or not 1<=n<=256:raise SeqImportError('X/Y视场数量不一致或超出1~256')
    if weights is not None and len(weights)!=n:raise SeqImportError('WTF权重数量与视场数量不一致')
    weight_source='explicit WTF' if weights is not None else 'explicitly recorded default unit weights'
    weights=weights if weights is not None else [1.]*n
    if any(w<0 for w in weights):raise SeqImportError('视场权重不能为负值')
    base=[dict(index=i+1,x=x,y=y,weight=w) for i,(x,y,w) in enumerate(zip(arrays['x'],arrays['y'],weights))]
    configs=[dict(index=i,title=titles.get(i,f'配置 {i}'),fields=copy.deepcopy(base)) for i in range(1,count+1)]
    seen=set()
    for row in changes:
        t=row['tokens'];cmd=t[1].upper();line=row['line']
        if len(t)<4 or not re.fullmatch(r'F\d+',t[2],re.I):raise SeqImportError(f'第{line}行的配置视场限定符尚不支持')
        field=int(t[2][1:]);values=numbers(t[3:],line)
        if not 1<=field<=n or len(values)!=count:raise SeqImportError(f'第{line}行配置视场数量/编号不匹配，期望{count}个配置值')
        axis='weight' if cmd=='WTF' else FIELD_TYPES[cmd][1]
        if cmd!='WTF' and FIELD_TYPES[cmd][0]!=kind:raise SeqImportError('配置与基础视场类型不一致')
        if (field,axis) in seen:raise SeqImportError('重复配置视场赋值，拒绝静默覆盖')
        seen.add((field,axis))
        for config,value in zip(configs,values):
            if axis=='weight' and value<0:raise SeqImportError('配置视场权重不能为负值')
            config['fields'][field-1][axis]=value
    if unit=='mm' and dimension!='M':unit=('DIM '+dimension+'（未换算）') if dimension else '未声明的文件长度单位'
    return dict(type=kind,label=NAMES[kind],unit=unit,dimension=dimension,count=n,configuration_count=count,base=base,configurations=configs,weight_source=weight_source)


def inspect_seq(raw,filename='lens.seq'):
    text,encoding=decode_seq(raw);rows=commands(text);contract=field_contract(rows);blockers=[]
    allowed={'RDM','LEN','TITLE','TIT','INI','DIM','FNO','EPD','WL','REF','WTW','WTF',*FIELD_TYPES,'SO','S','SI','STO','SLB','GO','CIR'}
    for row in rows:
        t=row['tokens'];cmd=t[0]
        reason=None
        if cmd=='ZOO':reason='多配置几何/状态尚未完整导入' if contract['configuration_count']>1 else '配置命令尚未完整支持'
        elif cmd in ('VUX','VLX','VUY','VLY'):reason='不对称渐晕/瞳孔偏移尚未完整导入'
        elif cmd=='PIK':reason='拾取关系尚未求值并验证'
        elif cmd in ('XDE','YDE','ZDE','ADE','BDE','CDE','DAR','BEN','REV'):reason='偏心/倾斜及坐标约定尚未完整验证'
        elif cmd not in allowed:reason='此命令尚未纳入严格导入支持清单'
        if cmd=='WTW':
            values=numbers(t[1:],row['line'])
            if any(v<0 for v in values) or sum(values)<=0:reason='波长权重需非负且至少一项大于0'
        if cmd=='CIR' and (len(t)>2 and t[1].upper()!='CLR'):reason='仅支持圆形清口径，不支持中心遮挡或其他口径语义'
        if cmd=='DIM' and [v.upper() for v in t[1:]]!=['M']:reason='仅验证了毫米DIM M单位'
        if reason and not any(b['command']==cmd and b['reason']==reason for b in blockers):blockers.append(dict(command=cmd,line=row['line'],reason=reason))
    if contract['dimension'] is None:blockers.append(dict(command='DIM',line=1,reason='未明确声明长度单位，严格导入不推测'))
    return dict(ok=True,filename=Path(filename).name,source_sha256=hashlib.sha256(raw).hexdigest(),encoding=encoding,
                field_contract=contract,field_values_preserved=True,can_analyze=not blockers,blockers=blockers,
                import_status='preflight_only',message='已按原文件完整读取视场；尚未建立分析运行。'+('存在未支持条件，禁止降级分析。' if blockers else '静态预检通过，实际导入仍须进行模型一致性校验。'))


def restore_and_verify_fields(optic,contract,configuration=1):
    if not isinstance(configuration,int) or not 1<=configuration<=contract['configuration_count']:raise SeqImportError('必须明确选择有效配置')
    fields=contract['configurations'][configuration-1]['fields']
    if contract['dimension']!='M':raise SeqImportError('长度单位未明确验证，禁止映射为毫米视场')
    optic.fields.fields=[];optic.fields.set_type(contract['type'])
    for field in fields:optic.fields.add(x=field['x'],y=field['y'],weight=field['weight'])
    verify_fields(optic,contract,configuration)
    return optic


def verify_fields(optic,contract,configuration=1):
    fields=contract['configurations'][configuration-1]['fields']
    if len(optic.fields)!=len(fields):raise SeqImportError('导入前后视场数量不一致，已阻止分析')
    for actual,expected in zip(optic.fields,fields):
        for key in ('x','y','weight'):
            if float(getattr(actual,key))!=expected[key]:raise SeqImportError(f"F{expected['index']}的{key}被改变，已阻止分析")
    if len(optic.fields.get_field_coords())!=len(fields):raise SeqImportError('分析接口会合并/遗漏视场，已阻止分析')
    expected_type={'real_image_height':'RealImageHeightField','angle':'AngleField','object_height':'ObjectHeightField','paraxial_image_height':'ParaxialImageHeightField'}[contract['type']]
    if type(optic.fields.field_definition).__name__!=expected_type:raise SeqImportError('视场定义被改变，已阻止分析')


def load_for_analysis(path):
    """Only accepted strict subset; full V39/V49 are deliberately refused."""
    source=Path(path);raw=source.read_bytes();report=inspect_seq(raw,source.name)
    if not report['can_analyze']:raise SeqImportError('SEQ未完整支持，已阻止分析：'+'；'.join(b['command']+' '+b['reason'] for b in report['blockers']))
    from optiland.fileio.codev.reader.parser import CodeVDataParser
    from optiland.fileio.codev.reader.converter import CodeVToOpticConverter
    text,_=decode_seq(raw);rows=commands(text)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always');parser=CodeVDataParser(str(source))
        # Feed the same validated, BOM/encoding-normalized tokens to this local
        # parser instance. The source cannot change between preflight and read.
        parser._load_and_preprocess=lambda:[row['tokens'] for row in rows]
        model=parser.parse()
        optic=CodeVToOpticConverter(model).convert()
    if caught:raise SeqImportError('原生读取存在警告，已阻止分析：'+'；'.join(str(w.message) for w in caught))
    restore_and_verify_fields(optic,report['field_contract'])
    return optic,report
