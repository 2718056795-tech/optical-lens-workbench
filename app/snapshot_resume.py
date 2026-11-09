"""Prepare a new native optimization from an explicit saved prescription."""
import copy,hashlib,json,re
from pathlib import Path
from prescription_store import resolve
from engine_io import write_json
ROOT=Path(__file__).resolve().parent

COURSE_RESTART_WARNING=('此操作保留镜片处方，但会重新启动原生课程：光阑半径先变为当前保存半径的一半，再渐进到当前保存半径；'
                        '同时重建求解器和调度器。它不恢复停止时的课程进度。是否仍要继续？')

def _official_structure(cfg):
 groups=copy.deepcopy(cfg['surf_list']);sizes=[];stop=None;count=0;types=[]
 for group in groups:
  if group==['Aperture']:
   if stop is not None:raise ValueError('保存的官方结构含多个光阑')
   stop=count
  else:
   sizes.append(len(group)-1);count+=len(group)-1;types.extend(group)
 if stop is None:raise ValueError('保存的官方结构缺少光阑')
 return dict(elements=count,stop_pos=stop,aspheric=any(t=='Aspheric' for t in types),lens_group_sizes=sizes,surf_list=groups)

def _integer(value,key):
 if isinstance(value,bool):raise ValueError('续算结构参数格式非法：'+key)
 try:number=float(value)
 except (ValueError,TypeError):raise ValueError('续算结构参数格式非法：'+key)
 if not number.is_integer():raise ValueError('续算结构参数需为整数：'+key)
 return int(number)

def _verify_official_structure(p,cfg):
 expected=_official_structure(cfg)
 for key in ('elements','stop_pos','aspheric','lens_group_sizes','surf_list'):
  if key not in p:continue
  actual=p[key]
  if key=='stop_pos' and actual in ('front','middle','back'):actual={'front':0,'middle':expected['elements']//2,'back':expected['elements']}[actual]
  if key in ('elements','stop_pos'):actual=_integer(actual,key)
  elif key=='aspheric':
   if actual in (None,''):actual=False
   elif isinstance(actual,bool):pass
   elif str(actual).lower() in ('true','1'):actual=True
   elif str(actual).lower() in ('false','0'):actual=False
   else:raise ValueError('续算面型参数格式非法')
  elif key=='lens_group_sizes':
   if isinstance(actual,str):actual=actual.split(',')
   if not isinstance(actual,(list,tuple)):raise ValueError('续算胶合分组格式非法')
   actual=[_integer(v,key) for v in actual]
  elif isinstance(actual,str):
   try:actual=json.loads(actual)
   except ValueError:raise ValueError('续算surf_list格式非法')
  if actual!=expected[key]:raise ValueError('续算需保留原结构，请开始新任务以更改：'+key)
 supplied=p.get('autolens_config')
 if supplied:
  for key in ('surf_list','seed','lrs'):
   if supplied.get(key)!=cfg[key]:raise ValueError('续算需保留原官方配置，请开始新任务以更改：'+key)
 if 'seed' in p and _integer(p['seed'],'seed')!=cfg['seed']:raise ValueError('续算需保留原随机状态，请开始新任务以更改seed')
 p.update(expected)

def phase_info(run_dir,path,params):
 root=Path(run_dir);rel=path.relative_to(root.resolve()).as_posix()
 progress=json.loads((root/'progress.json').read_text(encoding='utf-8')) if (root/'progress.json').is_file() else {}
 meta=json.loads((root/'snapshot_state.json').read_text(encoding='utf-8')) if path.name=='stopped_lens.json' and (root/'snapshot_state.json').is_file() else {}
 match=re.search(r'^(curriculum|refine)/iter(\d+)\.json$',rel)
 stage=match.group(1) if match else meta.get('stage') or progress.get('snapshot_stage') or progress.get('stage')
 used=int(match.group(2)) if match else int(meta.get('iteration') or progress.get('snapshot_solver_iteration') or progress.get('iter') or 0)
 if path.name=='curriculum_final.json':stage='refine';used=0
 if path.name=='final_lens.json' and progress.get('status')=='stopped':return 'finalize',0
 if stage in ('init','starting',None):stage=('curriculum' if params.get('engine')=='autolens' else 'optiland_initial') if int(params.get('curriculum_iters') or 0)>0 else 'refine'
 if stage not in ('curriculum','optiland_initial'):stage='refine'
 return stage,used
def prepare(run_dir,run_id,source=None,source_sha256=None):
 path,data,sha=resolve(run_dir,source,source_sha256)
 if data.get('optiland_native_source'):raise ValueError('此记录保留原文件的Optiland原生模型，仅用于直接分析；原结构优化请在导入对话框选择“沿用原结构继续优化”并完成兼容性校核。')
 p=json.loads((Path(run_dir)/'params.json').read_text(encoding='utf-8'))
 if p.get('autolens_protocol')=='autolens-official-main-v1':
  phase,used=phase_info(run_dir,path,p)
  cfg=p['autolens_config'];initial=max(4,int(cfg['curriculum_iters'])-used) if phase=='curriculum' else 0
  progress_path=Path(run_dir)/'progress.json'
  progress=json.loads(progress_path.read_text(encoding='utf-8')) if progress_path.is_file() else {}
  completed=path.name=='final_lens.json' and progress.get('status')=='finished'
  remaining=0 if phase=='finalize' else int(cfg['refine_iters']) if completed else max(1,int(cfg['refine_iters'])-used) if phase=='refine' else int(cfg['refine_iters'])
  p.pop('_workflow_worker',None);p.pop('resume_lens',None)
  p.pop('resume_acknowledge_course_restart',None)
  p.update(_official_structure(cfg))
  p.update(curriculum_iters=initial,refine_iters=remaining)
  p['autolens_config'].update(curriculum_iters=initial,refine_iters=remaining)
  p['resume_reference']=dict(run_id=run_id,source_file=path.relative_to(Path(run_dir).resolve()).as_posix(),source_sha256=sha,phase=phase,initial_budget=initial,source_iteration=used,additional_refinement=completed,course_restart=phase=='curriculum')
  return dict(params=p,source=p['resume_reference'],message=COURSE_RESTART_WARNING if phase=='curriculum' else '保留原生结构，按当前阶段重新建立官方求解器；不恢复旧内部状态。',
              requires_course_restart_acknowledgement=phase=='curriculum',course_restart_warning=COURSE_RESTART_WARNING if phase=='curriculum' else None)
 for key in ('_workflow_worker','resume_lens','design_import_id','design_import_mode','source_design','import_unknowns_ack','reference','label'):p.pop(key,None)
 phase,used=phase_info(run_dir,path,p);continuous=any('/' in str(s.get('mat2','air')) for s in data['surfaces'])
 if continuous and not (p.get('engine')=='autolens' and phase=='curriculum'):raise ValueError('连续MODEL材料仅能由AutoLens继续原生课程阶段，不能直接进入固定玻璃精调或另一个内核；不会重新生成结构。')
 initial=max(4,int(p.get('curriculum_iters') or 4)-used) if phase=='curriculum' else max(1,int(p.get('curriculum_iters') or 1)) if phase=='optiland_initial' else 0
 remaining=0 if phase=='finalize' else max(1,int(p.get('refine_iters') or 120)-used) if p.get('engine')=='autolens' and phase=='refine' else int(p.get('refine_iters') or 0) if phase in ('curriculum','optiland_initial') else max(1,int(p.get('refine_iters') or 120))
 p.update(curriculum_iters=initial,refine_iters=remaining,optim_mat=bool(p.get('optim_mat',True)) if phase=='curriculum' else False,design_start_mode='resume',
          resume_reference=dict(run_id=run_id,source_file=path.relative_to(Path(run_dir).resolve()).as_posix(),source_sha256=sha,phase=phase,initial_budget=initial))
 message='保留停止时的结构，重新建立原生求解器；不恢复旧动量或调度器。'
 if phase=='curriculum':message+=' 继续课程阶段后再精调；原生课程预算最低4步。'
 if phase=='finalize':message='优化结构已经完成，只继续分析和导出，不重新优化。'
 return dict(params=p,source=p['resume_reference'],message=message)
def apply(p,runs_dir):
 ref=p.get('resume_reference')
 if not ref:return
 if not isinstance(ref,dict) or not isinstance(ref.get('run_id'),str) or not re.fullmatch(r'[A-Za-z0-9_\-.]+',ref['run_id']) or ref['run_id'] in ('.','..'):raise ValueError('续算来源标识非法')
 root=Path(runs_dir).resolve();folder=(root/ref['run_id']).resolve()
 if not folder.is_relative_to(root):raise ValueError('续算来源非法')
 source,data,sha=resolve(folder,ref.get('source_file'),ref.get('source_sha256'))
 validated=prepare(folder,ref['run_id'],ref.get('source_file'),ref.get('source_sha256'));phase=validated['source']['phase']
 if validated['params'].get('autolens_protocol')=='autolens-official-main-v1':
  if p.get('engine')!='autolens':raise ValueError('官方AutoLens快照请使用原生AutoLens续算')
  from official_autolens import normalize,cra_input
  if phase=='finalize' and cra_input(p)!=cra_input(validated['params']):raise ValueError('只补分析导出需保留原CRA输入；修改CRA需继续优化')
  expected=validated['params']['autolens_config']
  _verify_official_structure(p,expected)
  if phase=='curriculum' and p.get('resume_acknowledge_course_restart') is not True:raise ValueError('请先确认原生课程将重新启动、光阑会重新渐进；未启动优化')
  for k in ('foclen','fov','fnum','bfl','thickness'):
   if float(p[k])!=float(expected[k]):raise ValueError('原生续算保留原设计目标；更改指标请开始新任务：'+k)
  p['autolens_config']=dict(expected,curriculum_iters=int(p['curriculum_iters']),refine_iters=int(p['refine_iters']))
  p['resume_phase']=phase;normalize(p)
  if phase=='finalize':
   expected=validated['params']['autolens_config'];actual=p['autolens_config']
   if any(actual[k]!=expected[k] for k in expected):raise ValueError('只补分析导出需保持原官方配置')
  elif phase=='refine' and int(p['curriculum_iters'])!=0:raise ValueError('精调续算不重新运行课程')
  target=ROOT/'imports'/('official_resume_'+sha);target.mkdir(parents=True,exist_ok=True);prepared=target/'prepared.json'
  prepared.write_bytes(source.read_bytes())
  p.update(resume_lens=str(prepared),source_design=dict(filename=source.name,sha256=sha,mode='official-snapshot-resume'),design_start_mode='resume')
  if phase=='finalize':
   progress=json.loads((folder/'progress.json').read_text(encoding='utf-8'));p.update(resume_metrics=progress.get('metrics_final',{}),resume_history=progress.get('history',[]),resume_target=progress.get('target',{}))
  return
 if phase=='curriculum' and p.get('engine')!='autolens' or phase=='optiland_initial' and p.get('engine')!='optiland':raise ValueError('当前阶段请沿用原优化内核继续；不会跨内核重建结构')
 req=p.get('requirements')
 if not req:raise ValueError('续算需要完整技术条件')
 if phase=='finalize' and req!=data.get('design_requirements'):raise ValueError('仅继续分析导出时请保持原技术条件；更改条件需要重新优化')
 initial=int(p.get('curriculum_iters') or 0)
 if phase in ('refine','finalize') and initial!=0:raise ValueError('精调续算不会重新初始化，初始预算须为0')
 if phase=='refine' and int(p.get('refine_iters') or 0)<1:raise ValueError('精调续算预算需至少1步；不会用零步优化冒充完成')
 if phase=='curriculum' and initial<4 or phase=='optiland_initial' and initial<1:raise ValueError('继续当前阶段需要有效的剩余预算')
 if phase=='finalize' and int(p.get('refine_iters') or 0)!=0:raise ValueError('此处只继续分析和导出；需要继续精调请选优化阶段快照')
 folder=ROOT/'imports'/('resume_'+hashlib.sha256((sha+req['sha256']).encode()).hexdigest());folder.mkdir(parents=True,exist_ok=True)
 path=folder/'prepared.json';data=copy.deepcopy(data)
 data.update(wvln_ls=req['spectrum']['wavelengths_um'],wvln_primary=req['spectrum']['primary_um'],spectral_weights=req['spectrum']['weights'])
 write_json(path,data)
 from glass_selection import stamp_json
 from spectrum import stamp_spectrum
 from design_contract import load
 stamp_json(path,req['glass_selection']);stamp_spectrum(path,p);load(p).stamp(path);load(p).verify(json.loads(path.read_text(encoding='utf-8')),allow_model_glass=phase=='curriculum')
 if phase=='finalize':
  progress=json.loads((source.parent/'progress.json').read_text(encoding='utf-8'))
  p['resume_metrics']=progress.get('metrics_final') or progress.get('metrics_current') or {};p['resume_history']=progress.get('history',[]);p['resume_target']=progress.get('target',{})
 p['resume_phase']=phase;p['resume_lens']=str(path);p['design_start_mode']='resume';p['source_design']=dict(filename=source.name,sha256=sha,mode='snapshot-resume',run_id=ref['run_id'],source_file=ref['source_file'])
