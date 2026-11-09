/* Read-only strict SEQ preflight. Never substitutes this report for an import. */
(()=>{
  const byId=id=>document.getElementById(id);let report=null;
  const button=document.createElement('button');button.id='inspectSeq';button.type='button';button.textContent='SEQ 校核';button.title='读取并核对全部视场；未支持条件会明确阻止导入分析';
  document.querySelector('#moreActions .toolmenu-panel').prepend(button);
  const input=document.createElement('input');input.type='file';input.accept='.seq';input.hidden=true;input.id='seqFileInput';document.body.append(input);
  const dialog=document.createElement('dialog');dialog.id='seqImportDialog';dialog.className='seq-import-dialog';
  dialog.innerHTML='<div class="dialogtools"><strong>SEQ 导入前校核</strong><button id="closeSeqDialog" type="button">关闭 ×</button></div><p id="seqFileSummary" class="seq-summary"></p><p id="seqImportStatus" class="seq-status" role="status"></p><div class="seq-config"><label for="seqConfiguration">配置</label><select id="seqConfiguration" aria-label="SEQ配置"></select><span id="seqFieldCount"></span></div><div class="seq-field-table"><table><thead><tr><th>原视场编号</th><th id="seqXLabel">X</th><th id="seqYLabel">Y</th><th>原权重 WTF</th></tr></thead><tbody id="seqFieldRows"></tbody></table></div><details class="seq-blockers"><summary>未支持条件与分析限制</summary><ul id="seqBlockerList"></ul></details><p class="seq-footnote">仅校核原文件数据，尚未创建镜头分析运行。视场数量、定义、坐标或权重不一致时必须拒绝，不能默认成轴上场。原文件不会执行或修改。</p>';
  document.body.append(dialog);byId('closeSeqDialog').onclick=()=>dialog.close();
  function fields(){
    if(!report)return;const contract=report.field_contract,index=Number(byId('seqConfiguration').value)-1,config=contract.configurations[index],body=byId('seqFieldRows');body.replaceChildren();
    for(const field of config.fields){const row=document.createElement('tr');for(const value of ['F'+field.index,field.x,field.y,field.weight]){const cell=document.createElement('td');cell.textContent=String(value);row.append(cell);}body.append(row);}
    byId('seqFieldCount').textContent=`${contract.count} / ${contract.count} 个视场 · 原顺序全部保留`;
  }
  async function inspect(data,filename){
    report=null;byId('seqFileSummary').textContent=filename;byId('seqImportStatus').textContent='正在读取全部视场和配置…';byId('seqFieldRows').replaceChildren();byId('seqBlockerList').replaceChildren();byId('seqConfiguration').replaceChildren();byId('seqFieldCount').textContent='';if(!dialog.open)dialog.showModal();
    try{
      const response=await fetch('/api/seq-inspect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({data,filename})});const value=await response.json();if(!response.ok)throw Error(value.error||'校核失败');report=value;const c=report.field_contract;
      byId('seqFileSummary').textContent=`${report.filename} · ${c.label} (${c.unit}) · ${c.configuration_count} 个配置 × ${c.count} 个视场`;
      byId('seqImportStatus').textContent=report.message;byId('seqImportStatus').classList.toggle('blocked',!report.can_analyze);
      byId('seqXLabel').textContent='原 X ('+c.unit+')';byId('seqYLabel').textContent='原 Y ('+c.unit+')';
      for(const config of c.configurations)byId('seqConfiguration').append(new Option(`Z${config.index} · ${config.title}`,config.index));
      for(const item of report.blockers){const li=document.createElement('li');li.textContent=`第${item.line}行 ${item.command}：${item.reason}`;byId('seqBlockerList').append(li);}fields();
    }catch(error){byId('seqImportStatus').textContent='校核失败，已阻止分析：'+error.message;byId('seqImportStatus').classList.add('blocked');}
  }
  byId('seqConfiguration').onchange=fields;button.onclick=()=>input.click();input.onchange=async()=>{const file=input.files[0];if(!file)return;try{if(file.size>1024*1024)throw Error('文件超过1MB');const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',',2)[1]);reader.onerror=reject;reader.readAsDataURL(file);});await inspect(data,file.name);}catch(error){notify('SEQ校核失败：'+error.message,true);}finally{input.value='';}};
  window.seqImport={inspect,get report(){return report;}};
})();
