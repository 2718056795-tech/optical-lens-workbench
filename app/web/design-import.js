(()=>{
  const $=id=>document.getElementById(id);let report=null,source=null;
  const labels={optics:'焦距 / F数 / 视场 / 物距',fields:'完整视场表',spectrum:'波长 / 主波长 / 权重',structure:'片数 / 胶合关系 / 总长 / 保护片',stop:'光阑位置与孔径',materials:'制造商 / 原玻璃牌号',bounds:'兼容原结构的起始边界（推导值，可在B区修改）'};
  const file=document.createElement('input');file.type='file';file.accept='.seq,.zmx,.zos';file.hidden=true;document.body.append(file);
  const dialog=document.createElement('dialog');dialog.id='designImportDialog';dialog.className='requirements-dialog';
  dialog.innerHTML='<div class="dialogtools"><strong>导入设计文件</strong><button id="closeDesignImport" type="button">取消 ×</button></div><p id="designFileSummary"></p><label>配置 <select id="designConfiguration"></select></label><p id="designImportStatus" role="status"></p><div class="fields" id="designImportSections"></div><div class="requirements-table"><table><thead><tr><th>#</th><th>原X</th><th>原Y</th><th>权重</th></tr></thead><tbody id="designImportFields"></tbody></table></div><details open><summary>未支持或需注意的条件</summary><ul id="designImportBlockers"></ul></details><label>接下来的操作<select id="designImportMode"><option value="reset">按选中的技术参数重新生成</option><option value="resume">沿用原结构继续优化</option></select></label><label class="chk" id="designImportAckLabel"><input id="designImportAck" type="checkbox">我已确认未支持条件；重新设计只采用选中的技术目标</label><p class="small">原文件只读。续算保留实际结构、材料和光阑；重新生成不加载原曲率/间隔。直接使用左侧所选内核完成优化、分析与导出。</p><div class="dialogtools"><span id="designImportError" role="alert"></span><button id="analyzeDesignImport" type="button">载入镜头直接分析</button><button id="applyDesignImport" type="button">回填左侧条件</button></div>';
  document.body.append(dialog);$('closeDesignImport').onclick=()=>dialog.close();
  const parameters=document.createElement('div');parameters.id='designImportParameters';dialog.insertBefore(parameters,$('designImportSections'));
  dialog.insertBefore($('designImportMode').closest('label'),parameters);
  function render(){
    const typeName={angle:'角度（°）',object_height:'物高（mm）',real_image_height:'实际像高（mm）',paraxial_image_height:'一阶像高（mm）'}[report.field_definition]||report.field_definition;
    $('designFileSummary').textContent=report.filename+' · '+typeName+' · '+report.raw_fields.length+'个视场，全部保留';
    $('designConfiguration').closest('label').hidden=report.configuration_count===1;
    parameters.replaceChildren();const facts=document.createElement('table');
    const patch=report.patch,values=[['焦距 EFL (mm)',patch.foclen],['F数',patch.fnum],['物距 (mm)',patch.object_at_infinity?'无穷远':patch.obj_depth],['全视场角 (°)',patch.fov],['总长 (mm)',patch.thickness],['视场点数',patch.field_count??report.raw_fields.length],['波长 (nm)',patch.spectral_samples_um?.map(w=>Number((w*1000).toPrecision(12))).join(' / ')],['主波长 (nm)',patch.wvln_primary==null?undefined:patch.wvln_primary*1000],['玻璃目录',patch.glass_table?patch.glass_table+' '+patch.glass_catalog_revision:undefined]];
    for(const [label,value]of values){const row=document.createElement('tr');for(const v of[label,value??'未能确认，保留左侧当前输入并请校核']){const cell=document.createElement('td');cell.textContent=String(v);row.append(cell);}facts.append(row);}parameters.append(facts);
    $('designImportStatus').textContent=report.can_resume?'原结构通过当前支持范围预检；请选择回填内容和操作。':'原结构续算被阻止；已识别的技术条件仍可选择回填后重新设计。';
    if(patch.spectral_samples_um?.length){const lo=Math.min(...patch.spectral_samples_um)*1000,hi=Math.max(...patch.spectral_samples_um)*1000;$('designImportStatus').textContent+=` 新优化取 ${Number(lo.toPrecision(12))} / ${Number(((lo+hi)/2).toPrecision(12))} / ${Number(hi.toPrecision(12))} nm；下表波长保留源文件记录。`;}
    $('designImportStatus').style.color=report.can_resume?'#256a52':'#b52d3d';
    $('designImportFields').replaceChildren();for(const f of report.raw_fields){const tr=document.createElement('tr');for(const value of[f.index,f.x,f.y,f.weight]){const td=document.createElement('td');td.textContent=String(value);tr.append(td);} $('designImportFields').append(tr);}
    $('designImportBlockers').replaceChildren();for(const b of report.blockers){const li=document.createElement('li');li.textContent=(b.line?'第'+b.line+'行 ':'')+b.command+'：'+b.reason;$('designImportBlockers').append(li);}if(!report.blockers.length){const li=document.createElement('li');li.textContent='无已识别的未支持条件；启动前还会校核当前目标及交接模型。';$('designImportBlockers').append(li);}
    $('designImportSections').replaceChildren();for(const key of report.available_sections){const label=document.createElement('label');label.className='chk';const check=document.createElement('input');check.type='checkbox';check.value=key;check.checked=true;const text=document.createElement('span');text.textContent=key==='fields'&&!report.patch.field_rows?'视场点数 / 最大像高（原坐标仅展示，请另设物方视场）':labels[key];label.append(check,text);$('designImportSections').append(label);}
    $('analyzeDesignImport').disabled=!report.can_analyze;const resume=$('designImportMode').querySelector('[value="resume"]');resume.disabled=!report.can_resume;$('designImportMode').value='reset';$('designImportAck').checked=false;mode();
  }
  function mode(){const resume=$('designImportMode').value==='resume';$('designImportAckLabel').hidden=resume||!report?.blockers.length;for(const check of $('designImportSections').querySelectorAll('input')){const mandatory=resume&&['structure','materials','stop','bounds'].includes(check.value);if(mandatory)check.checked=true;check.disabled=mandatory;}}
  $('designImportMode').onchange=mode;
  async function inspect(data,name,configuration=1){
    report=null;$('applyDesignImport').disabled=true;
    $('designImportError').textContent='';$('designImportStatus').textContent='正在读取和校核…';if(!dialog.open)dialog.showModal();
    const response=await fetch('/api/design-import/inspect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({data,filename:name,configuration})});const value=await response.json();if(!response.ok)throw Error(value.error||'导入校核失败');report=value;
    $('designConfiguration').replaceChildren();for(let i=1;i<=report.configuration_count;i++)$('designConfiguration').append(new Option('配置 '+i,i));$('designConfiguration').value=configuration;render();$('applyDesignImport').disabled=false;return report;
  }
  let currentFile=null;
  $('designConfiguration').onchange=()=>{if(currentFile)inspect(currentFile.data,currentFile.name,Number($('designConfiguration').value)).catch(e=>$('designImportError').textContent=e.message);};
  $('importDesign').onclick=()=>file.click();file.onchange=async()=>{const f=file.files[0];if(!f)return;try{if(f.size>2*1024*1024)throw Error('文件超过2MB');const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',',2)[1]);reader.onerror=reject;reader.readAsDataURL(f);});currentFile={data,name:f.name};await inspect(data,f.name);}catch(e){$('designImportError').textContent=e.message;if(!dialog.open)dialog.showModal();}finally{file.value='';}};
  $('applyDesignImport').onclick=async()=>{try{
    const selected=[...$('designImportSections').querySelectorAll('input:checked')].map(i=>i.value),action=$('designImportMode').value;
    if(action==='reset'&&report.blockers.length&&!$('designImportAck').checked)throw Error('请先确认未支持条件，或取消回填');
    const response=await fetch('/api/design-import/apply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({import_id:report.import_id,sections:selected,mode:action})});const p=await response.json();if(!response.ok)throw Error(p.error||'无法应用');
    for(const [key,value] of Object.entries(p)){const el=$(key);if(!el)continue;if(el.type==='checkbox')el.checked=!!value;else if(typeof value!=='object')el.value=String(value);}
    if(p.elements!=null){rebuildStopOptions();$('stop_pos').value=String(p.stop_pos??$('stop_pos').value);}
    if(p.glass_table)await window.glassUI.refill(p);
    window.requirementsUI.refill(p);
    refillResumeReference(null);source={id:report.import_id,mode:action,name:report.filename,ack:$('designImportAck').checked};updateStartMode();
    $('designImportSource').textContent=report.filename+' · '+(action==='resume'?'沿用原结构继续优化':'仅采用选中的指标，重新生成');$('clearDesignImport').hidden=false;
    dialog.close();
  }catch(e){$('designImportError').textContent=e.message;}};
  $('clearDesignImport').onclick=()=>{source=null;updateStartMode();$('clearDesignImport').hidden=true;$('designImportSource').textContent='文件来源已取消；当前左侧填写的技术要求保留。';};
  $('analyzeDesignImport').onclick=async()=>{try{if(!report?.can_analyze)throw Error('文件未通过完整原生模型校核，请查看原因');const d=await postJson('/api/design-import/analyze',{import_id:report.import_id});refillResumeReference(null);dialog.close();followActive=false;selectRun(d.run_id);await refreshLibrary();await viewLens(d.run_id,false,true);showTab('layout');notify('已原样载入用于分析，未启动优化；原文件只读。');}catch(e){$('designImportError').textContent=e.message;}};
  window.designImport={inspect,get report(){return report;},collect(p){if(source){p.design_import_id=source.id;p.design_import_mode=source.mode;p.import_unknowns_ack=source.ack;}},get source(){return source;},refill(p){
    source=p.design_import_id?{id:p.design_import_id,mode:p.design_import_mode,name:p.source_design?.filename||'已保存的设计文件',ack:p.import_unknowns_ack}:null;
    updateStartMode();$('clearDesignImport').hidden=!source;
    $('designImportSource').textContent=source?source.name+' · '+(source.mode==='resume'?'沿用原结构继续优化':'按选定指标重新生成'):'';
  }};
})();
