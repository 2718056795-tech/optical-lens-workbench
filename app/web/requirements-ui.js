/* The form builds one requirement object; neither engine invents its own fields. */
(()=>{
  const VERSION='lens-requirements-v1';let manual=[];
  const ids=['field_mode','field_definition','field_count','field_distribution','spectrum_mode','discrete_wavelengths_nm','discrete_primary_nm','discrete_weights','fixed_stop_z_mm','fixed_stop_radius_mm','fixed_ttl_mm','lens_group_sizes','fixed_glasses','cover_material','cover_thickness_mm','cover_gap_mm'];
  const parse=(text,name)=>{
    const parts=String(text).split(/[,，;；\s]+/).filter(Boolean);
    const result=parts.map(Number);if(!result.length||result.some(v=>!Number.isFinite(v)))throw new Error(name+'需为数值列表');return result;
  };
  const get=id=>document.getElementById(id);
  function summary(){
    get('workflowModeHint').textContent='直接运行所选内核，结束后自动分析与导出。';
    get('aspheric').disabled=true;get('aspheric').title='当前工作台的统一条件与文件适配只验证了球面';
    get('prune').disabled=true;get('prune').checked=true;get('prune').title='调用原生correct_shape/prune_surf修整有效口径；始终执行，不删镜片';
    if(get('route').value==='autolens'){get('w_dist').value='.1';get('w_dist').disabled=true;get('w_dist').title='原生AutoLens总损失的系数保留0.1';}
    else{get('w_dist').disabled=false;get('w_dist').title='工作台畸变操作数的权重';}
    get('spectrum_mode').value='range';get('spectrum_mode').disabled=true;
    if(get('fixed_glasses').value.trim()||get('route').value==='optiland'){get('optim_mat').checked=false;get('optim_mat').disabled=true;}
    else get('optim_mat').disabled=false;
    get('num_ring').disabled=get('route').value==='autolens';
    const isManual=get('field_mode').value==='manual',discrete=get('spectrum_mode').value==='discrete';
    get('field_count').disabled=isManual;get('field_distribution').disabled=isManual;
    get('fov').disabled=isManual;get('imgh').disabled=isManual;
    if(isManual&&manual.length){
      const depth=Number(get('obj_depth').value)||20000,focal=Number(get('foclen').value),angles=get('field_definition').value==='angle';
      const extent=Math.max(...manual.map(f=>Math.atan(angles?Math.hypot(Math.tan(f.x*Math.PI/180),Math.tan(f.y*Math.PI/180)):Math.hypot(f.x,f.y)/depth)*360/Math.PI));
      if(extent>0)get('fov').value=Number(extent.toPrecision(12));
      const radius=Math.max(...manual.map(f=>f.target_x_mm!=null&&f.target_y_mm!=null?Math.hypot(f.target_x_mm,f.target_y_mm):angles?focal*Math.hypot(Math.tan(f.x*Math.PI/180),Math.tan(f.y*Math.PI/180)):focal*Math.hypot(f.x,f.y)/depth));
      if(radius>0)get('imgh').value=Number(radius.toPrecision(12));
    }
    get('fieldSummary').textContent=isManual?`${manual.length}个手动视场，按原顺序使用（${get('field_definition').value==='angle'?'角度 °':'物高 mm'}）`:`自动${get('field_count').value}个视场；1个表示仅轴上，多个包含轴上和最大视场。`;
    document.querySelectorAll('.req-discrete').forEach(e=>e.hidden=!discrete);
    get('coverParameters').hidden=!get('cover_glass').checked;
    get('bfl').disabled=get('cover_glass').checked;if(get('cover_glass').checked)get('bfl').value=get('cover_gap_mm').value;
    const fixedLength=Number(get('fixed_ttl_mm').value),automaticLength=Number(get('foclen').value)+(Number(get('bfl').value)||8);
    get('thickness').placeholder=get('fixed_ttl_mm').value!==''?`跟随固定总长 ${fixedLength}`:String(Number(automaticLength.toPrecision(8)));
    get('obj_depth').disabled=get('object_at_infinity').checked;
    get('wavelength_min_nm').disabled=discrete;get('wavelength_max_nm').disabled=discrete;
    if(discrete)get('spectrumHint').textContent='使用下方离散列表、主波长和权重；保持输入顺序。';else updateSpectrumHint();
    linkImghFov();
    if(window.applyOfficialMode)window.applyOfficialMode();
  }
  function automatic(){
    const n=Math.max(1,Math.min(32,Number(get('field_count').value)||5)),depth=Number(get('obj_depth').value)||20000,max=Number(get('fov').value)*Math.PI/360;
    return Array.from({length:n},(_,i)=>{const frac=n>1?i/(n-1):0,angle=get('field_distribution').value==='image_height'?Math.atan(Math.tan(max)*frac):max*frac;return {x:0,y:get('field_definition').value==='angle'?angle*180/Math.PI:-depth*Math.tan(angle),weight:1};});
  }
  function addRow(row={x:0,y:0,weight:1}){
    const tr=document.createElement('tr');
    const num=document.createElement('td');num.textContent=get('fieldRows').children.length+1;tr.append(num);
    for(const key of ['x','y','weight','target_x_mm','target_y_mm']){const td=document.createElement('td'),input=document.createElement('input');input.type='number';input.step='any';input.dataset.key=key;input.value=row[key]??'';input.setAttribute('aria-label',key);if(key==='weight')input.min=0;td.append(input);tr.append(td);}
    const td=document.createElement('td'),button=document.createElement('button');button.type='button';button.textContent='删除';button.onclick=()=>tr.remove();td.append(button);tr.append(td);get('fieldRows').append(tr);
  }
  get('editFields').onclick=()=>{get('fieldRows').replaceChildren();(get('field_mode').value==='manual'?manual:automatic()).forEach(addRow);get('fieldsError').textContent='';get('fieldsUnitNote').textContent=get('field_definition').value==='angle'?'物方 X/Y 角度，单位 °；支持正负方向。':'物方 X/Y 坐标，单位 mm；物平面由工作距离确定。';get('fieldsDialog').showModal();};
  get('addField').onclick=()=>{if(get('fieldRows').children.length<32)addRow();};
  get('closeFields').onclick=()=>get('fieldsDialog').close();
  get('applyFields').onclick=()=>{try{
    const rows=[...get('fieldRows').children].map(tr=>{const row={};tr.querySelectorAll('input').forEach(input=>{if(input.value.trim()!=='')row[input.dataset.key]=Number(input.value);});if(!Number.isFinite(row.x)||!Number.isFinite(row.y)||!Number.isFinite(row.weight)||row.weight<0)throw new Error('每行X、Y和非负权重必须填写');if(('target_x_mm'in row)!==('target_y_mm'in row))throw new Error('目标像高X/Y需同时填写或同时留空');return row;});
    if(!rows.length||!rows.some(r=>r.weight>0))throw new Error('至少一行且至少一个权重大于0');manual=rows;get('field_mode').value='manual';get('field_count').value=rows.length;summary();get('fieldsDialog').close();
  }catch(e){get('fieldsError').textContent=e.message;}};
  for(const id of ids)get(id).addEventListener('change',summary);
  get('cover_glass').addEventListener('change',summary);
  get('object_at_infinity').addEventListener('change',summary);
  get('route').addEventListener('change',summary);
  get('foclen').addEventListener('input',summary);
  get('glass_table').addEventListener('change',()=>{if(['h-k9l','n-bk7'].includes(get('cover_material').value.toLowerCase()))get('cover_material').value=get('glass_table').value==='SCHOTT'?'n-bk7':'h-k9l';});
  get('closeRequirements').onclick=()=>get('requirementsDialog').close();
  get('inspectRequirements').onclick=async()=>{get('requirementsStatus').textContent='正在校核…';try{
    const response=await fetch('/api/requirements-inspect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(collectParams())}),result=await response.json();if(!response.ok)throw new Error(result.error||'校核失败');
    const r=result.requirements;if(!r)throw new Error('统一条件未生成');const box=get('requirementsReport');box.replaceChildren();
    const facts=[['视场数',r.fields.length],['波长 (nm)',r.spectrum.wavelengths_um.map(w=>Number((w*1000).toPrecision(12))).join(' / ')],['主波长 (nm)',r.spectrum.primary_um*1000],['物距 (mm)',r.object_at_infinity?'无穷远（平行入射）':r.object_distance_mm],['表面数',r.surface_count],['光阑面',r.stop_index+1],['固定光阑坐标',r.fixed_stop_z_mm??'可移动'],['固定光阑半径',r.fixed_stop_radius_mm??'按F数设置'],['固定总长',r.fixed_ttl_mm??'仅限制上限'],['保护片',r.cover?`${r.cover.material} · 厚${r.cover.thickness_mm}mm · 像面间距${r.cover.gap_mm}mm`:'无'],['玻璃池',r.glass_selection.catalog+' '+r.glass_selection.revision+' / '+r.glass_selection.count+'种']];
    const table=document.createElement('table');for(const [key,value]of facts){const tr=document.createElement('tr');for(const v of[key,value]){const td=document.createElement('td');td.textContent=String(v);tr.append(td);}table.append(tr);}box.append(table);
    const fieldTable=document.createElement('table');let header=document.createElement('tr');for(const label of['#',r.object_at_infinity?'X角 (°)':'物方X (mm)',r.object_at_infinity?'Y角 (°)':'物方Y (mm)','权重','目标X (mm)','目标Y (mm)']){const th=document.createElement('th');th.textContent=label;header.append(th);}fieldTable.append(header);for(const f of r.fields){const tr=document.createElement('tr');for(const value of[f.index,r.object_at_infinity?f.x:f.object_x_mm,r.object_at_infinity?f.y:f.object_y_mm,f.weight,f.target_x_mm,f.target_y_mm]){const td=document.createElement('td');td.textContent=String(value);tr.append(td);}fieldTable.append(tr);}box.append(fieldTable);
    const note=document.createElement('p');note.className='small';note.textContent=result.note;box.append(note);get('requirementsStatus').textContent='条件校核通过；可开始优化。';get('requirementsDialog').showModal();
  }catch(e){get('requirementsStatus').textContent=e.message;}};
  window.requirementsUI={
    collect(p){
      p.requirements_version=VERSION;for(const id of ids)p[id]=get(id).value;
      p.object_at_infinity=get('object_at_infinity').checked;
      p.field_rows=get('field_mode').value==='manual'?structuredClone(manual):undefined;
      if(p.field_mode==='manual'&&!manual.length)throw new Error('请先编辑手动视场表');
      p.spectrum_mode='range';
      if(p.cover_glass)p.bfl=p.cover_gap_mm;
      return p;
    },
    refill(p){
      for(const id of ids)if(p[id]!=null)get(id).value=p[id];
      if('object_at_infinity'in p)get('object_at_infinity').checked=!!p.object_at_infinity;
      if(p.spectral_samples_um){get('wavelength_min_nm').value=Math.min(...p.spectral_samples_um)*1000;get('wavelength_max_nm').value=Math.max(...p.spectral_samples_um)*1000;get('spectrum_mode').value='range';}
      if('field_rows'in p)manual=structuredClone(p.field_rows||[]);refillImageGeometry(p);summary();
    },
    getFields:()=>structuredClone(manual),setFields(rows,definition='angle'){manual=structuredClone(rows);get('field_mode').value='manual';get('field_definition').value=definition;get('field_count').value=rows.length;summary();},summary
  };
  summary();
})();
