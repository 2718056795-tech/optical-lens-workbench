/* Local manufacturer catalog and explicit allowed-glass pool. */
window.glassUI=(()=>{
  const catalogs=new Map();let data=null,customNames=[],working=new Set(),shown=[],loadVersion=0;
  const catalogEl=$("glass_table"),policyEl=$("glass_policy"),revisionEl=$("glass_catalog_revision");
  const versions={CDGM:["202609","202409"],SCHOTT:["202412"]};
  function setVersions(preferred){revisionEl.replaceChildren(...versions[catalogEl.value].map(v=>new Option(v.slice(0,4)+"-"+v.slice(4)+" 目录",v)));revisionEl.value=versions[catalogEl.value].includes(preferred)?preferred:versions[catalogEl.value][0];}
  function message(text){$("glassSelectionNote").textContent=text;}
  function store(){try{localStorage.setItem("lens-v4-glass-selection",JSON.stringify({catalog:catalogEl.value,revision:revisionEl.value,policy:policyEl.value,names:customNames}));}catch(e){}}
  function namesForPolicy(){return policyEl.value==="custom"?customNames:(data?.profiles?.[policyEl.value]||[]);}
  function summary(){
    if(!data){message("读取本地玻璃目录…");return;}
    const count=namesForPolicy().length;
    message(`${data.label} · 允许 ${count} 个牌号 · ${data.source_header}。MA/A/B 来自厂家分级，不保证当前库存。`);
  }
  async function load(preservePolicy=false){
    const version=++loadVersion,catalog=catalogEl.value,key=catalog+":"+revisionEl.value;data=null;summary();
    try{
      if(!catalogs.has(key)){const r=await fetch("/api/glasses?catalog="+encodeURIComponent(catalog)+"&revision="+encodeURIComponent(revisionEl.value)),d=await r.json();if(!r.ok||d.error)throw new Error(d.error||"目录读取失败");catalogs.set(key,d);}
      if(version!==loadVersion)return;
      data=catalogs.get(key);
      if(preservePolicy){const names=new Map(data.rows.map(r=>[r.name.toLowerCase(),r.name]));customNames=customNames.map(n=>names.get(n.toLowerCase())||n);}
      for(const o of policyEl.options)if(o.value!=="custom")o.disabled=!(data.profiles[o.value]?.length);
      if(policyEl.value!=="custom"&&!data.profiles[policyEl.value]?.length)policyEl.value="all";
      if(!preservePolicy)customNames=[];
      summary();store();
    }catch(e){if(version===loadVersion)message(e.message);}
  }
  catalogEl.addEventListener("change",()=>{setVersions();policyEl.value=catalogEl.value==="CDGM"?"frequent_12":"all";load();});
  revisionEl.addEventListener("change",()=>load());
  policyEl.addEventListener("change",()=>{summary();store();if(policyEl.value==="custom")open();});
  function count(){ $("glassCount").textContent=`已选 ${working.size} 个 · 当前显示 ${shown.length} 个`;
    $("applyGlass").disabled=working.size===0;
  }
  function render(){
    if(!data)return;const search=$("glassSearch").value.trim().toLowerCase(),frequency=$("glassFrequencyFilter").value;
    shown=data.rows.filter(r=>r.name.toLowerCase().includes(search)&&(frequency==="all"||(r.melt_grade||"unknown")===frequency));
    $("glassRows").replaceChildren();
    for(const r of shown){const tr=document.createElement("tr"),checkCell=document.createElement("td"),box=document.createElement("input");box.type="checkbox";box.checked=working.has(r.name);box.disabled=!r.selectable;box.setAttribute("aria-label","允许使用 "+r.name);
      box.onchange=()=>{box.checked?working.add(r.name):working.delete(r.name);count();};checkCell.append(box);tr.append(checkCell);
      const state=r.source_conflict?"Excel/AGF数据冲突":r.status===2?"已停用":r.exclude_substitution?"排除替换":!r.selectable?"公式未支持":({0:"标准",1:"优选",3:"特殊",4:"熔次"}[r.status]||"未知");
      for(const value of [r.name,r.nd.toFixed(6),r.vd.toFixed(3),r.melt_grade||"未知",r.relative_cost==null?"—":r.relative_cost.toFixed(2),state]){const td=document.createElement("td");td.textContent=value;tr.append(td);}
      if(!r.selectable)tr.className="unavailable";$("glassRows").append(tr);
    }count();
  }
  function readPresets(){try{return JSON.parse(localStorage.getItem("lens-v4-glass-pools")||"[]");}catch(e){return[];}}
  function refreshPresets(){const select=$("savedGlassPools");select.replaceChildren(new Option("保存的自定义清单",""));readPresets().forEach((p,i)=>{if(p.catalog===catalogEl.value&&p.revision===revisionEl.value)select.append(new Option(p.name+" · "+p.names.length+" 个",String(i)));});}
  async function open(){
    if(!data)await load(true);if(!data)return;
    working=new Set(namesForPolicy());$("glassSearch").value="";$("glassFrequencyFilter").value="all";
    $("glassDialogTitle").textContent=data.label+" · 可用玻璃池";$("glassCatalogSource").textContent=data.source_header+" · "+data.rows.length+" 个目录记录";
    $("glassDialogNote").textContent=data.frequency_note+" "+data.cost_note;refreshPresets();render();$("glassDialog").showModal();
  }
  $("manageGlasses").onclick=open;$("glassSearch").addEventListener("input",render);$("glassFrequencyFilter").addEventListener("change",render);
  $("glassSelectVisible").onclick=()=>{shown.filter(r=>r.selectable).forEach(r=>working.add(r.name));render();};
  $("glassClear").onclick=()=>{working.clear();render();};
  $("closeGlass").onclick=()=>$("glassDialog").close();
  $("glassDialog").onclick=e=>{if(e.target===$("glassDialog"))$("glassDialog").close();};
  $("applyGlass").onclick=()=>{if(!working.size)return;customNames=data.rows.filter(r=>working.has(r.name)&&r.selectable).map(r=>r.name);policyEl.value="custom";summary();store();$("glassDialog").close();};
  $("glassSavePreset").onclick=()=>{
    const name=$("glassPoolName").value.trim();if(!name||!working.size){$("glassCount").textContent="请填写清单名称并至少勾选一个牌号";return;}
    const presets=readPresets().filter(p=>!(p.catalog===catalogEl.value&&p.revision===revisionEl.value&&p.name===name));presets.push({name,catalog:catalogEl.value,revision:revisionEl.value,names:[...working]});
    try{localStorage.setItem("lens-v4-glass-pools",JSON.stringify(presets));refreshPresets();$("glassCount").textContent="已保存清单："+name;}catch(e){$("glassCount").textContent="保存失败："+e.message;}
  };
  $("glassLoadPreset").onclick=()=>{const value=$("savedGlassPools").value;if(value==="")return;const p=readPresets()[Number(value)];if(!p||p.catalog!==catalogEl.value||p.revision!==revisionEl.value)return;const valid=new Set(data.rows.filter(r=>r.selectable).map(r=>r.name));working=new Set(p.names.filter(n=>valid.has(n)));$("glassPoolName").value=p.name;render();};
  function refill(params){catalogEl.value=params.glass_table||"CDGM";setVersions(params.glass_catalog_revision||(catalogEl.value==="CDGM"?"202409":"202412"));policyEl.value=params.glass_policy||"legacy_common";customNames=params.allowed_glasses||params.glass_selection?.allowed_glasses||[];return load(true);}
  function collect(params){params.glass_catalog_revision=revisionEl.value;params.glass_policy=policyEl.value;if(params.glass_policy==="custom"){if(!customNames.length)throw new Error("请先勾选自定义玻璃可用清单");params.allowed_glasses=[...customNames];}}
  setVersions();
  try{const saved=JSON.parse(localStorage.getItem("lens-v4-glass-selection")||"null");if(saved&&["CDGM","SCHOTT"].includes(saved.catalog)){catalogEl.value=saved.catalog;setVersions(saved.revision);policyEl.value=saved.policy;customNames=saved.names||[];}}catch(e){}
  load(true);return{refill,collect,open};
})();
