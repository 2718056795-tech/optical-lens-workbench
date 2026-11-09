/* Secondary analysis navigation. Calculations are explicit, cached and cancellable. */
(()=>{
  let catalog,job=null,lastLens=null,image=null,engine='optiland',ready=false,pending=false,objectViewReady=false,stopContinueReady=false;const panels=new Map(),results=new Map();
  const sourceToken=()=>{const r=selectedPrescription();return (r.source_file||'')+'|'+(r.source_sha256||'');};
  const cacheKey=(run,id,e=engine,token=sourceToken())=>e+'|'+run+'|'+token+'|'+id;
  const matchesSource=result=>{const r=selectedPrescription();return (!result.source_file||result.source_file===r.source_file)&&(!r.source_sha256||result.source_sha256===r.source_sha256);};
  let ignoreObject=true;try{ignoreObject=localStorage.getItem('lens-workbench-ignore-object')!=='false';}catch(e){}
  const viewMatches=(panel,result)=>!objectViewReady||!['layout','native_3d'].includes(result.analysis_id)||result.options.ignore_object===panel.ignore.checked;
  const el=(tag,cls,text)=>{const x=document.createElement(tag);if(cls)x.className=cls;if(text!==undefined)x.textContent=text;return x;};
  const taskInfo=el('details','task-details'),taskBody=el('div','task-details-body');
  taskInfo.append(el('summary','','任务信息'),taskBody);taskBody.append(document.querySelector('.workhead'),$('runinfo'));document.querySelector('.resulttools').append(taskInfo);
  // Keep native controls and keyboard behavior; size their selected text, then
  // expose a wrapping readout only if a narrow container still cannot fit it.
  const labelCanvas=document.createElement('canvas'),labelContext=labelCanvas.getContext('2d');let labelTick=false,labelSequence=0;
  function fitNativeLabels(){
    labelTick=false;
    for(const select of document.querySelectorAll('select')){
      if(!select.checkVisibility()||select.closest('.sr-only'))continue;
      const option=select.selectedOptions[0],text=option?.textContent||'',style=getComputedStyle(select);
      labelContext.font=style.font;const width=labelContext.measureText(text).width,extra=parseFloat(style.paddingLeft)+parseFloat(style.paddingRight)+34,needed=Math.ceil(width+extra);
      const label=select.closest('.parameters label');
      if(label){const budget=label.classList.contains('selhalf')?label.parentElement.clientWidth/2-6:label.parentElement.clientWidth;label.classList.toggle('select-expanded',needed>budget);}
      if(select.matches('.suite-nav>.suite-select')){select.style.flexBasis=Math.max(220,needed)+'px';select.style.minWidth=Math.min(needed,220)+'px';}
      else if(select.id==='snapshotSelect')select.style.width=Math.max(245,needed)+'px';
      else if(select.matches('.suite-perspective'))select.style.setProperty('width',Math.max(260,needed)+'px','important');
      else if(select.id==='analysisEngine')select.style.setProperty('width',Math.max(112,needed)+'px','important');
      if(select._labelOriginalTitle===undefined)select._labelOriginalTitle=select.title;select.title=[text,select._labelOriginalTitle].filter(Boolean).join('\n');
      const available=select.getBoundingClientRect().width-extra,overflow=width>available+1;
      let note=select._fullLabel;
      if(overflow&&!note){note=el('span','select-full-label');note.id='select-full-label-'+(++labelSequence);select.after(note);select._fullLabel=note;select.setAttribute('aria-describedby',((select.getAttribute('aria-describedby')||'')+' '+note.id).trim());}
      if(note){if(note.textContent!==text)note.textContent=text;note.hidden=!overflow;}
    }
  }
  function queueLabelFit(){if(labelTick)return;labelTick=true;requestAnimationFrame(fitNativeLabels);}
  new MutationObserver(queueLabelFit).observe(document.body,{childList:true,subtree:true,characterData:true});
  document.addEventListener('change',queueLabelFit);document.addEventListener('toggle',queueLabelFit,true);document.addEventListener('focusin',queueLabelFit);window.addEventListener('resize',queueLabelFit);queueLabelFit();
  const names={layout:'流程保存光路',mtf:'几何综合 MTF',spot:'多色点列',aberration:'场曲 / 网格畸变',fan:'实际光扇'};
  const config={
    field:['归一化视场','number','.7','0','1','.05'],samples:['瞳孔采样','select',[32,64,128]],
    wave:['波长','wave'],reference_wave:['色差参考波长','reference'],projection:['绘图投影','select',['2d','3d']],field_points:['视场 / 瞳孔点数','number','21','3','65','1'],
    frequencies:['频率组 cycles/mm','text','30,50,100'],frequency:['频率 cycles/mm','number','50','.1','5000','1'],
    focus_step_mm:['离焦步距 mm','number','.05','.0001','10','.01'],focus_steps:['离焦步数（奇数）','number','5','3','15','2'],
    pixel_pitch_um:['像素尺寸 µm','number','5.4','.01','1000','.1'],radius_tol_mm:['半径公差 ±mm','number','.02','0','1','.001'],thickness_tol_mm:['间隔公差 ±mm','number','.01','0','1','.001'],
    trials:['蒙特卡洛次数','number','32','8','500','1'],seed:['随机种子','number','42','0','4294967295','1'],
    coherent_rays:['相干光线数（原生≥百万）','number','1000000','1000000','8388608','100000'],grid_points:['二维网格边长','number','5','3','17','1'],ray_count:['光线数 / 原生spp','number','1024','32','65536','1'],radial_fields:['径向视场数','number','3','2','12','1'],
    z_span_mm:['场曲离焦半范围 mm','number','1','.001','20','.1'],z_steps:['场曲离焦步数','number','101','5','401','2']
  };
  const relevant={mtf_field:['frequencies','field_points','samples','wave'],through_mtf:['frequency','focus_step_mm','focus_steps','samples','wave'],fft_mtf:['samples','wave'],huygens_mtf:['samples','wave'],fft_psf:['field','samples','projection','wave'],huygens_psf:['field','samples','projection','wave'],encircled:['wave'],through_spot:['focus_step_mm','focus_steps','wave'],rms_field:['field_points','wave'],distortion:['field_points','wave'],lateral_color:['field_points','pixel_pitch_um','wave'],axial_color:['wave'],spherochromatic:['field_points','wave'],best_fan:['samples','wave'],seidel:[],opd:['field','samples','projection','wave'],opd_fan:['samples','wave'],zernike:['field','projection','wave'],wavefront_field:['field_points','samples','wave'],pupil:['samples','wave'],field_angle:['field_points','wave'],pupil_angle:['field','samples','wave'],yybar:['wave'],irradiance:['wave','seed'],intensity:['wave','seed'],jones:['field','wave'],image_simulation:['samples','wave'],sensitivity:['field','radius_tol_mm','thickness_tol_mm'],monte_carlo:['field','radius_tol_mm','thickness_tol_mm','trials','seed']};
  relevant.layout=['wave'];for(const id of ['native_3d','native_spot','native_geometric_mtf','native_curvature','native_grid','native_ray_fan'])relevant[id]=['wave'];
  const autoRelevant={native_3d:[],layout:['radial_fields','ray_count','wave'],spot_fields:['ray_count','wave'],spot_radial:['radial_fields','ray_count','wave'],spot_map:['grid_points','ray_count','wave'],rms_map:['grid_points','wave'],geometric_psf:['field','samples','ray_count','wave'],coherent_psf:['field','samples','coherent_rays','wave'],huygens_psf:['field','samples','ray_count','wave'],native_mtf:['radial_fields','samples','wave'],curvature:['field_points','z_span_mm','z_steps','ray_count','wave'],grid_distortion:['grid_points','wave'],vignetting:['grid_points','ray_count','wave'],opd:['radial_fields','samples','ray_count','wave'],seidel:['wave'],sensitivity:['grid_points','ray_count','seed'],monte_carlo:['trials','ray_count','seed'],image_simulation:['ray_count']};
  function input(key){
    const [title,type,a,min,max,step]=config[key],label=el('label','suite-field'),span=el('span','',title);let x;
    if(type==='select'||type==='wave'||type==='reference'){x=el('select');if(type==='select')for(const v of a)x.append(new Option(v,v));else {fillWaves(x);if(type==='reference'){x.options[0].remove();x.value='primary';}}}
    else{x=el('input');x.type=type;x.value=a;if(min!==undefined){x.min=min;x.max=max;x.step=step;}}
    x.dataset.option=key;label.append(span,x);return label;
  }
  function fillWaves(select){const prev=select.value;select.replaceChildren(new Option('全部采样波长','all'),new Option('主波长','primary'));for(const w of currentScene?.wavelengths||[])select.append(new Option(`${(w*1000).toFixed(2).replace(/\.?0+$/,'')} nm`,w*1000));if(select.dataset.option==='reference_wave'){select.options[0].remove();select.value='primary';}if([...select.options].some(o=>o.value===prev))select.value=prev;}
  function message(panel,text,error=false){panel.status.textContent=text;panel.status.classList.toggle('error',error);panel.status.classList.toggle('complete',!error&&text.startsWith('计算完成'));}
  function refresh(panel){
    const id=panel.select.value,basic=id==='basic';panel.basic&&(panel.basic.hidden=!basic);panel.extra.hidden=basic;panel.advanced.hidden=basic;panel.tools.hidden=basic;
    panel.ignoreLabel.hidden=!['layout','native_3d'].includes(id);
    if(basic){panel.advanced.open=false;return;}
    for(const b of panel.groups.children)b.classList.toggle('active',b.dataset.analysis===id||(b.dataset.analysis==='basic'&&basic));
    panel.form.replaceChildren();for(const key of (engine==='autolens'?autoRelevant:relevant)[id]||[])panel.form.append(input(key));if(engine==='optiland'&&['lateral_color','axial_color'].includes(id))panel.form.append(input('reference_wave'));
    panel.form.onchange=()=>{panel.output.replaceChildren();message(panel,'参数已更改，请计算分析；当前设置尚未计算。');};panel.nativeOpen.hidden=id!=='native_3d';panel.imageLabel.hidden=id!=='image_simulation';panel.description.textContent=(catalog.by_engine[engine].find(a=>a.id===id)?.method||'')+' · '+catalog.engines[engine];
    panel.output.replaceChildren();message(panel,'选择有效保存处方后，点击「计算分析」。');
    const saved=results.get(cacheKey(currentLens||'',id));if(saved&&viewMatches(panel,saved)){for(const x of panel.form.querySelectorAll('[data-option]')){const value=saved.options[x.dataset.option];if(value!==undefined)x.value=Array.isArray(value)?value.join(','):value;}paint(panel,saved);}
  }
  function paint(panel,result){
    if(result.engine!==engine||result.run_id!==currentLens||!matchesSource(result)||panel.select.value!==result.analysis_id||!viewMatches(panel,result))return;
    panel.output.replaceChildren();panel.output.classList.toggle('suite-single',result.images.length===1||result.analysis_id==='native_3d');const header=el('div','suite-result-head');header.append(el('b','',catalog.engines[engine]+' · '+result.label));
    const details=el('span','',`波长 ${result.wavelengths_um.map(w=>(w*1000).toFixed(2)).join(' / ')} nm · ${result.source_file||'保存处方'} · ${result.source_sha256.slice(0,10)}`);header.append(details);
    const base=result.relative_dir+'/',links=el('div','suite-downloads');for(const file of [...result.files,...(result.summary.csv?[result.summary.csv]:[])]){const a=el('a','',file==='numeric.npz'?'数值 NPZ':file==='request.json'?'计算条件':file==='numeric_index.json'?'数值索引':file);a.href=runPath(result.run_id,base+file);a.target='_blank';a.rel='noopener';a.download=file;links.append(a);}
    if(result.analysis_id==='lateral_color'){const s=result.summary;panel.output.append(el('p','suite-color-summary',`最大绝对横向色差 ${s.max_abs_um.toFixed(3)} µm（${s.max_pixels.toFixed(3)} 像素） · 最差归一化视场 ${s.worst_field.toFixed(3)} · 参考 ${s.reference_nm.toFixed(2)} nm`));}
    const strehls=Object.entries(result.summary).filter(([key])=>key.endsWith('_Strehl'));if(strehls.length)panel.output.append(el('p','suite-color-summary','Strehl：'+strehls.map(([key,value])=>key.replace('_Strehl','')+' = '+value.toFixed(4)).join(' · ')));
    const grid=el('div','suite-images');const viewSelect=result.analysis_id==='native_3d'?el('select','suite-select suite-perspective'):null;if(viewSelect){viewSelect.setAttribute('aria-label','3D视角');for(const [i,im] of result.images.entries())viewSelect.append(new Option(im.label,i));panel.output.append(viewSelect);viewSelect.onchange=()=>[...grid.children].forEach((c,i)=>c.hidden=i!==Number(viewSelect.value));}
    for(const plot of result.images){const card=el('article','plotcard'),host=el('div','analysisplot');if(result.analysis_id==='layout')host.dataset.layoutImage='true';plotImage(host,runPath(result.run_id,base+plot.file),plot.label,true);card.append(el('h3','suite-plot-title',plot.label),host);if(viewSelect&&grid.children.length)card.hidden=true;grid.append(card);}panel.output.append(grid);
    const notes=el('details','suite-notes');notes.append(el('summary','','说明与数据'),header,links);for(const note of result.notes)notes.append(el('p','',note));panel.output.append(notes);message(panel,'计算完成 · '+result.run_id);
    preview(result);
  }
  function preview(result){if(result.engine===engine&&currentLens===result.run_id&&matchesSource(result)&&result.analysis_id==='layout'){loadGeometry(currentLens,result.source_file);return;}if(result.engine===engine&&currentLens===result.run_id&&matchesSource(result)&&['spot_fields','spot_radial','native_mtf','native_spot','native_geometric_mtf'].includes(result.analysis_id)){
      const host=['spot_fields','spot_radial','native_spot'].includes(result.analysis_id)?$('overviewSpot'):$('overviewMtf');
      plotImage(host,runPath(result.run_id,result.relative_dir+'/'+result.images[0].file),engine+' · '+result.label,true);
    }
  }
  function updateBusy(){if(ready)$('btnAnalysis').disabled=!!job||pending||!hasSavedPrescription();for(const p of panels.values()){p.start.disabled=!!job||pending;p.cancel.hidden=!job;p.cancel.disabled=!job;p.ignore.disabled=!objectViewReady||!!job||pending;}}
  async function run(panel){
    if(!ready)return;
    if(job||pending){message(panel,'已有分析正在计算，请等待或取消。');return;}
    if(panel.select.value==='basic'){if(panel.slot==='layout'){message(panel,'流程保存光路可直接查看；选择具体分析后计算。');return;}return runAnalysis(currentLens,true);}
    if(!hasSavedPrescription()){message(panel,'请先载入有效保存处方；停止后的阶段结构也可以分析。',true);return;}
    freezeSourceView();const id=panel.select.value,run=currentLens,selectedEngine=engine,token=sourceToken(),ref=selectedPrescription(),options={};for(const x of panel.form.querySelectorAll('[data-option]'))options[x.dataset.option]=x.value;
    if(objectViewReady&&['layout','native_3d'].includes(id))options.ignore_object=panel.ignore.checked;
    message(panel,'准备分析…');pending=true;updateBusy();
    try{const d=await postJson('/api/analysis-start',{run_id:run,engine:selectedEngine,analysis_id:id,options,image:id==='image_simulation'?image:null,force:panel.force.checked,...ref});
      if(d.status==='finished'){if(d.result.engine!==selectedEngine)throw Error('后端未支持所选内核，请关闭工作台后重新打开。');results.set(cacheKey(run,id,selectedEngine,token),d.result);if(engine===selectedEngine&&panel.select.value===id)paint(panel,d.result);return;}
      job={id:d.job_id,panel,run,analysis:id,engine:selectedEngine,sourceToken:token};updateBusy();await monitor();
    }catch(e){message(panel,e.message,true);}finally{pending=false;updateBusy();}
  }
  async function monitor(){
    if(!job)return;const active=job;
    try{const response=await fetch('/api/analysis-state?job_id='+encodeURIComponent(active.id)),d=await response.json();if(!response.ok)throw Error(d.error||'任务查询失败');if(job!==active)return;
      if(d.status==='finished'){if(d.result.engine!==active.engine)throw Error('分析结果内核不符；拒绝显示，请重新打开新版工作台。');results.set(cacheKey(active.run,active.analysis,active.engine,active.sourceToken),d.result);if(engine===active.engine&&currentLens===active.run&&sourceToken()===active.sourceToken&&active.panel.select.value===active.analysis)paint(active.panel,d.result);else notify(active.engine+'分析完成：'+d.result.label+' · '+active.run);job=null;updateBusy();}
      else if(d.status==='failed'||d.status==='cancelled'){if(engine===active.engine&&currentLens===active.run&&sourceToken()===active.sourceToken&&active.panel.select.value===active.analysis)message(active.panel,d.error||'分析已取消',d.status==='failed');job=null;updateBusy();}
      else{if(engine===active.engine&&active.panel.select.value===active.analysis)message(active.panel,`${active.engine} · ${d.message||'分析中'} · ${Math.floor(d.elapsed_seconds||0)}秒${d.wavelength_nm?' · '+d.wavelength_nm+' nm':''}`);setTimeout(monitor,800);}
    }catch(e){message(active.panel,'查询失败：'+e.message,true);job=null;updateBusy();}
  }
  function mount(slot){
    const view=$('view-'+slot),basic=slot==='advanced'?null:el('div','suite-basic');
    if(basic){while(view.firstChild)basic.append(view.firstChild);view.append(basic);}
    if(basic){const notes=[...basic.children].filter(x=>x.classList.contains('viewnote'));if(notes.length){const info=el('details','suite-basic-notes');info.append(el('summary','','说明'),...notes);basic.append(info);}}
    view.classList.add('suite-view');const nav=el('div','suite-nav'),groups=el('div','suite-groups'),select=el('select','suite-select');select.setAttribute('aria-label','分析类型');
    const extra=el('div','suite-extra'),tools=el('div','suite-tools'),description=el('p','suite-description'),form=el('div','suite-form'),advanced=el('details','suite-settings');advanced.append(el('summary','','分析参数'),form,description);
    const start=el('button','suite-start','计算分析'),cancel=el('button','','取消分析'),status=el('p','suite-status',''),forceLabel=el('label','chk'),force=el('input');force.type='checkbox';forceLabel.append(force,document.createTextNode('重新计算'));
    const imageLabel=el('label','suite-upload','测试图（可选，≤2MB；转灰度）'),upload=el('input');upload.type='file';upload.accept='image/png,image/jpeg,image/bmp';imageLabel.append(upload);upload.onchange=async()=>{const f=upload.files[0];if(!f){image=null;return;}if(f.size>2*1024*1024){message(panel,'图像超过2MB',true);upload.value='';image=null;return;}image=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(f);});};
    const nativeOpen=el('button','','打开原生交互窗口 ↗');nativeOpen.hidden=true;nativeOpen.onclick=async()=>{try{if(!hasSavedPrescription())throw Error('请先载入保存处方');await postJson('/api/native3d/open',{run_id:currentLens,engine,ignore_object:panel.ignore.checked,...selectedPrescription()});notify('已请求打开'+engine+'原生3D窗口，首次载入需要等待；可在原生窗口拖动缩放。');}catch(e){message(panel,e.message,true);}};
    const ignoreLabel=el('label','chk suite-ignore-object'),ignore=el('input');ignore.type='checkbox';ignore.checked=ignoreObject;ignoreLabel.title='仅调整显示，不改变实际物距和追迹；AutoLens原生3D保持平行光约定';ignoreLabel.append(ignore,document.createTextNode('忽略物面'));
    if(!objectViewReady){ignore.checked=false;ignoreLabel.title='此开关需要关闭并重新打开V10.0.0，以加载新后台；刷新页面无法更新后台';ignoreLabel.append(el('small','','需重开'));}
    tools.append(start,cancel,nativeOpen,forceLabel);advanced.append(imageLabel);extra.append(status);const output=el('div','suite-output');extra.append(output);nav.append(groups,select,advanced,ignoreLabel,tools);view.prepend(nav);view.append(extra);
    const capability=el('p','suite-capability');advanced.append(capability);
    const panel={slot,basic,extra,select,form,start,cancel,status,description,imageLabel,output,force,advanced,tools,groups,nativeOpen,ignore,ignoreLabel};panels.set(slot,panel);start.onclick=()=>run(panel);cancel.onclick=async()=>{if(!job)return;try{await postJson('/api/analysis-cancel',{job_id:job.id});}catch(e){message(panel,e.message,true);}};
    ignore.onchange=()=>{ignoreObject=ignore.checked;try{localStorage.setItem('lens-workbench-ignore-object',String(ignoreObject));}catch(e){}const hadOutput=!!panel.output.querySelector('img');for(const p of panels.values()){p.ignore.checked=ignoreObject;if(['layout','native_3d'].includes(p.select.value)){p.output.replaceChildren();message(p,'视图已切换，点击计算分析；实际物距未改变。');}}if(hadOutput&&!job&&!pending)run(panel);};
    function group(key){select.replaceChildren();if(basic&&engine==='optiland'&&slot!=='three')select.append(new Option('外层组合图（旧版 '+names[slot]+'）','basic'));for(const a of catalog.by_engine[engine].filter(a=>a.group===key)){const option=new Option(a.label+(a.available===false?' · 未启用':''),a.id);option.disabled=a.available===false;option.title=a.reason||a.method;select.append(option);}
      const defaults=engine==='optiland'?{layout:'layout',three:'native_3d',spot:'native_spot',mtf:'native_geometric_mtf',aberration:'distortion',fan:'native_ray_fan'}:{layout:'layout',three:'native_3d'};if(defaults[slot])select.value=defaults[slot];
      for(const b of groups.children)b.classList.toggle('active',b.dataset.group===key);refresh(panel);}
    panel.rebuild=()=>{groups.replaceChildren();
      const keys=(slot==='advanced'?['wavefront','pupil','energy','simulation','tolerance']:[slot]).filter(k=>catalog.by_engine[engine].some(a=>a.group===k)||(engine==='optiland'&&basic));
      for(const key of keys){const b=el('button','',slot==='aberration'?(engine==='optiland'?'原生 T/S 场曲':'子午场曲'):catalog.groups[key]);b.dataset.group=key;if(slot==='aberration')b.dataset.analysis=engine==='optiland'?'native_curvature':'curvature';b.onclick=()=>{group(key);if(slot==='aberration'){select.value=engine==='optiland'?'native_curvature':'curvature';refresh(panel);}};groups.append(b);}
      if(slot==='aberration')for(const [id,title] of engine==='optiland'?[['distortion','畸变曲线'],['native_grid','原生网格'],['lateral_color','横向色差（外层）']]:[['grid_distortion','畸变网格']]){
        const b=el('button','suite-quick',title);b.dataset.analysis=id;b.onclick=()=>{select.value=id;refresh(panel);};groups.append(b);
      }
      capability.textContent=engine==='autolens'?(slot==='three'?'AutoLens原生3D：主波长、各保存视场方向的平行光视图；有限物距也采用原生平行采样，不代表有限物距通光验收。':slot==='fan'?'AutoLens 此版本没有专用光扇图入口；本页提供原生赛德尔与色差系数。':slot==='aberration'?'AutoLens：原生子午最佳焦面场曲、畸变网格；无现成 F-tan 曲线。实光线色差曲线请切换 Optiland。':'AutoLens 原生分析；相干传播PSF因本固定版缺失AngularSpectrumMethod未启用，其余项目按接口自身采样定义。3D使用所选内核原生几何、光线及VTK渲染。'):(slot==='three'?'Optiland原生OpticViewer3D组件与VTK渲染；页面三视角，原生交互窗口支持拖动缩放。':'默认直接调用Optiland原生分析类；“外层组合图”及横向色差等外层分析单独标注。');
      group(keys[0]);updateBusy();};select.onchange=()=>refresh(panel);panel.rebuild();
  }
  function changeEngine(){
    engine=$('analysisEngine').value;try{localStorage.setItem('lens-workbench-analysis-engine',engine);}catch(e){}
    $('analysisSource').textContent=catalog.engines[engine]+' · 独立于优化路线';
    $('overviewMtfTitle').textContent=engine==='autolens'?'AutoLens 几何 MTF · 分波长 Tan':'Optiland 原生几何 MTF（逐波长）';$('overviewSpotTitle').textContent=engine==='autolens'?'AutoLens 完整视场点列':'Optiland 点列图';
    resetAnalysis();for(const p of panels.values())p.rebuild();
    
    if(engine==='autolens')for(const id of ['spot_fields','native_mtf']){const saved=results.get(cacheKey(currentLens,id));if(saved)paint(panels.get(id==='spot_fields'?'spot':'mtf'),saved);}
    $('anaStatus').textContent=catalog.engines[engine]+' · 选择分析项目后计算；切换内核不会重新优化。';
    lastLens=null;sourceChanged();
  }
  const savedBatches=new Map();
  async function loadSaved(id){if(!id||selectedPrescription().source_file!=='final_lens.json')return;
    const requestedEngine=engine,token=sourceToken(),batchKey=engine+'|'+id;
    try{let d=savedBatches.get(batchKey);if(!d){const response=await fetch(runPath(id,'analysis/analysis_'+requestedEngine+'.json'));if(!response.ok)return;d=await response.json();if(d.engine!==requestedEngine||d.run_id!==id)return;savedBatches.set(batchKey,d);}
      if(engine!==requestedEngine||currentLens!==id||sourceToken()!==token)return;
      for(const result of d.results||[]){if(result.engine!==requestedEngine||result.run_id!==id||!matchesSource(result))continue;results.set(cacheKey(id,result.analysis_id,requestedEngine,token),result);
        const slot=catalog.by_engine[requestedEngine].find(a=>a.id===result.analysis_id)?.slot,p=panels.get(slot);if(p&&p.select.value===result.analysis_id)paint(p,result);preview(result);}
    }catch(e){notify('读取所选内核分析失败：'+e.message,true);}
  }
  function sourceChanged(){const allowed=currentScene?.analysis_engines||['autolens','optiland'];for(const option of $('analysisEngine').options)option.disabled=!allowed.includes(option.value);if(!allowed.includes(engine)){notify('该导入记录保留原文件的Optiland模型，已选择Optiland直接分析；不使用未验证的跨内核转换。');$('analysisEngine').value=allowed[0];changeEngine();return;}const key=currentLens+'|'+sourceToken();if(lastLens===key)return;lastLens=key;resetAnalysis();
    if(engine==='autolens'&&currentScene?.has_explicit_fields===false){const p=panels.get('spot');p.select.value='spot_radial';refresh(p);$('overviewSpotTitle').textContent='AutoLens 原生径向点列';}
    for(const p of panels.values()){for(const s of p.form.querySelectorAll('[data-option="wave"],[data-option="reference_wave"]'))fillWaves(s);if(p.select.value!=='basic'){p.output.replaceChildren();message(p,'已选择 '+(selectedPrescription().source_file||'尚无处方')+'；点击计算分析。');const saved=results.get(cacheKey(currentLens||'',p.select.value));if(saved)paint(p,saved);}}
    for(const id of ['overviewMtf','overviewSpot'])makeEmpty($(id),'等待当前快照的原生分析','选择分析项目并计算；不会用另一快照的图代替。');
    for(const id of ['native_spot','native_geometric_mtf','spot_fields','spot_radial','native_mtf']){const result=results.get(cacheKey(currentLens,id));if(result)preview(result);}loadSaved(currentLens);updateBusy();
  }
  async function runCurrent(){let slot=['layout','three','spot','mtf','aberration','fan','advanced'].includes(activeTab)?activeTab:'spot';if(slot!==activeTab)showTab(slot);const p=panels.get(slot);if(p)return run(p);}
  async function init(){try{const protocol=await requestJson('/api/analysis-protocol').catch(()=>null);if(protocol?.protocol!=='analysis-engines-v2')throw Error('后台仍是旧版，请先结束任务、关闭旧版，再打开V10.0.0。');catalog=await requestJson('/api/analysis-catalog');if(!catalog.by_engine)throw Error('后端仍是旧版，请关闭工作台后重新打开以加载分析内核选择。');
    try{const saved=localStorage.getItem('lens-workbench-analysis-engine');if(saved in catalog.engines)$('analysisEngine').value=saved;}catch(e){}
    objectViewReady=protocol.object_view_toggle===true;stopContinueReady=protocol.stop_continue===true;window.nativeCraReady=protocol.native_cra_input===true;window.nativeOptilandReady=protocol.native_optiland_inputs===true;if(window.applyOfficialMode)window.applyOfficialMode();engine=$('analysisEngine').value;for(const slot of ['layout','three','mtf','spot','aberration','fan','advanced'])mount(slot);ready=true;$('analysisEngine').onchange=changeEngine;changeEngine();
    setInterval(sourceChanged,500);

  }catch(e){$('analysisEngine').disabled=true;$('analysisSource').textContent=e.message;notify('扩展分析初始化失败：'+e.message,true);}}
  window.analysisSuite={get engine(){return engine;},get stopContinueReady(){return stopContinueReady;},get legacy(){return engine==='optiland'&&[...panels.values()].some(p=>p.select.value==='basic');},get job(){return job;},get busy(){return !!job||pending;},get panels(){return panels;},get ready(){return ready;},runCurrent,loadSaved,sourceChanged};init();
})();

