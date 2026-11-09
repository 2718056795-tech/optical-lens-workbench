/* Read-only view helpers; no optimizer calls or changes to running workers. */
((root)=>{
  function worker(runId,progress,viewedId){
    if(viewedId&&viewedId!==runId)return viewedId;
    const batch=progress?.batch;
    if(!batch)return runId;
    if(progress.stage==='polish')return runId+'/polish';
    const active=(batch.candidates||[]).find(c=>c.status==='running')
      ||(batch.candidates||[]).find(c=>c.seed===batch.active_seed);
    return active?.directory?runId+'/'+active.directory:runId;
  }
  function stage(progress){return progress?.batch?.active_stage||progress?.stage;}
  function latestImage(files){
    return (files||[]).filter(f=>/^iter\d+\.png$/.test(f))
      .sort((a,b)=>Number(a.slice(4,-4))-Number(b.slice(4,-4))).pop()||null;
  }
  function cleanLog(text){
    return String(text||'').replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,'')
      .replace(/\uFFFD+/g,'').replace(/\r\n?/g,'\n').split('\n').filter(l=>l.trim()).slice(-120).join('\n');
  }
  const api={worker,stage,latestImage,cleanLog};root.NativeProgress=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);

/* Display-only whitespace fitting. Saved images and optical data stay intact. */
const LayoutImage=(()=>{
  const cache=new Map();
  function compactPixels(source){
    const w=source.width,h=source.height,ctx=source.getContext('2d'),pixels=ctx.getImageData(0,0,w,h).data;
    let left=w,right=-1,top=h,bottom=-1;const rows=new Uint32Array(h),coloredRows=new Uint32Array(h);
    for(let y=0;y<h;y++)for(let x=0;x<w;x++){
      const i=(y*w+x)*4;
      if(pixels[i+3]>0&&(pixels[i]<255||pixels[i+1]<255||pixels[i+2]<255)){
        rows[y]++;if(Math.max(pixels[i],pixels[i+1],pixels[i+2])-Math.min(pixels[i],pixels[i+1],pixels[i+2])>12)coloredRows[y]++;
        left=Math.min(left,x);right=Math.max(right,x);top=Math.min(top,y);bottom=Math.max(bottom,y);
      }
    }
    if(right<left)return {canvas:source,bounds:null,bands:[[0,h]],original:[w,h],foregroundPixels:0};
    // Native AutoLens puts a title at the very top of a tall blank canvas.
    // Remove a large empty title/body gap, never rows containing plotted pixels.
    let split=null,blankStart=null,largest=0;
    for(let y=top;y<=bottom;y++){
      if(!rows[y]){if(blankStart===null)blankStart=y;}
      else if(blankStart!==null){
        const gap=y-blankStart;
        const title=top<h*.12&&blankStart-top<h*.1&&!coloredRows.slice(top,blankStart).some(n=>n>0)&&coloredRows.slice(y,bottom+1).some(n=>n>0);
        if(title&&gap>Math.max(32,h*.08)&&gap>largest){split=[blankStart,y];largest=gap;}
        blankStart=null;
      }
    }
    const bands=split?[[top,split[0]],[split[1],bottom+1]]:[[top,bottom+1]];
    const width=right-left+1,pad=Math.max(8,Math.round(width*.015)),gap=pad*2;
    const canvas=document.createElement('canvas');canvas.width=width+pad*2;
    canvas.height=bands.reduce((n,[a,b])=>n+b-a,0)+pad*2+(bands.length-1)*gap;
    if(canvas.width>=w&&canvas.height>=h)return {canvas:source,bounds:null,bands:[[0,h]],original:[w,h],foregroundPixels:rows.reduce((a,b)=>a+b,0)};
    const target=canvas.getContext('2d');target.fillStyle='#fff';target.fillRect(0,0,canvas.width,canvas.height);
    let dy=pad;
    for(const [a,b]of bands){target.drawImage(source,left,a,width,b-a,pad,dy,width,b-a);dy+=b-a+gap;}
    return {canvas,bounds:[left,top,right+1,bottom+1],bands,original:[w,h],foregroundPixels:rows.reduce((a,b)=>a+b,0)};
  }
  function fit(src){
    if(cache.has(src))return cache.get(src);
    const task=new Promise((resolve,reject)=>{
      const image=new Image();image.onload=()=>{try{
        const canvas=document.createElement('canvas');canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
        const ctx=canvas.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(image,0,0);
        const result=compactPixels(canvas);resolve({...result,src:result.canvas.toDataURL('image/png')});
      }catch(e){reject(e);}};image.onerror=()=>reject(Error('光路图读取失败'));image.src=src;
    });
    cache.set(src,task);while(cache.size>6)cache.delete(cache.keys().next().value);
    task.catch(()=>{if(cache.get(src)===task)cache.delete(src);});return task;
  }
  return {fit,compactPixels};
})();

/* Workbench view state is separate from the active optimization process. */
let selectedRun = null, followActive = false, activeJob = null;
let currentLens = null, lensFinal = false, lensMetrics = null, lensRequest = 0;
let selectedProgress = null, activeTab = "overview", pollBusy = false;
let currentScene = null, libraryRuns = [], logVisible = false, lastLogAt = 0;
let analysisShown = null;
let previewBusy=false,previewChecked=0,previewContext="",opViewCache=null;
const analysisCache = new Map(), analysisRequests = new Map();
const analysisFiles = {spot:"spot_diagram.png",mtf:"mtf_geometric.png",curvature:"field_curvature.png",distortion:"grid_distortion.png",fan:"ray_fan.png"};
const labels = {spot:"配置波长点列图",mtf:"波段综合几何 MTF",curvature:"场曲",distortion:"网格畸变",fan:"光线像差扇图"};
const statusNames = {imported:"已导入 · 仅分析",finished:"计算完成",finalization_failed:"验收/出图/导出未完整完成",failed:"失败",stopped:"已停止",running:"运行中",pending:"待运行",interrupted:"上次运行已中断",unknown:"状态未知"};
const runPath = (id, file) => "/runs/" + id.split("/").map(encodeURIComponent).join("/") + "/" + file.split("/").map(encodeURIComponent).join("/");

async function requestJson(url, options){
  const r = await fetch(url, options);
  const d = await r.json();
  if (!r.ok || d.error) throw new Error(d.error || `请求失败 ${r.status}`);
  return d;
}
function postJson(url, body){return requestJson(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});}
function notify(text, error=false){$("footerStatus").textContent=text;if(error){$("errBox").textContent=text;$("errBox").style.display="block";}}
function makeEmpty(host, title, message=""){
  host.replaceChildren();const div=document.createElement("div");div.className="empty";
  const b=document.createElement("b");b.textContent=title;div.append(b);
  if(message){const p=document.createElement("p");p.textContent=message;div.append(p);}host.append(div);
}
function showTab(name){
  if(!$("view-"+name))return;
  activeTab=name;
  document.querySelectorAll("#viewTabs [data-tab]").forEach(b=>{const selected=b.dataset.tab===name;b.classList.toggle("active",selected);b.setAttribute("aria-selected",String(selected));b.tabIndex=selected?0:-1;});
  document.querySelectorAll(".view").forEach(v=>{const selected=v.id==="view-"+name;v.hidden=!selected;v.classList.toggle("active",selected);});
  $("viewScroll").scrollTop=0;
  if(name==="three"&&!window.analysisSuite) lensViewer.draw();
  if(!window.analysisSuite&&["spot","mtf","aberration","fan"].includes(name)&&currentLens&&lensFinal&&!analysisCache.has(currentLens))runAnalysis(currentLens,false);
}
$("viewTabs").addEventListener("click",e=>{const b=e.target.closest("[data-tab]");if(b)showTab(b.dataset.tab);});
$("viewTabs").addEventListener("keydown",e=>{
  if(!["ArrowLeft","ArrowRight","Home","End"].includes(e.key))return;
  const tabs=[...document.querySelectorAll("#viewTabs [data-tab]")],i=tabs.findIndex(b=>b.dataset.tab===activeTab);
  const n=e.key==="Home"?0:e.key==="End"?tabs.length-1:(i+(e.key==="ArrowRight"?1:-1)+tabs.length)%tabs.length;
  e.preventDefault();showTab(tabs[n].dataset.tab);tabs[n].focus();tabs[n].scrollIntoView({block:"nearest",inline:"nearest"});
});
document.querySelectorAll("[data-open]").forEach(b=>b.onclick=()=>showTab(b.dataset.open));
$("focusResults").onclick=()=>{
  const focused=document.body.classList.toggle("results-focused");
  $("focusResults").setAttribute("aria-pressed",String(focused));
  $("focusResults").textContent=focused?"返回参数 ⤡":"结果专注 ⤢";
  requestAnimationFrame(()=>{drawChart(lensMetrics?.history);lensViewer.draw();});
};
$("focusStop").onclick=()=>stop();

function plotImage(host, src, title, preview=false){
  host.replaceChildren();const image=document.createElement("img");image.alt=title;image.loading="lazy";image.tabIndex=0;
  const layout=preview&&(["overviewLayout","imgwrap"].includes(host.id)||host.dataset.layoutImage==='true');
  if(layout){
    image.dataset.originalSrc=src;image.title="等比例适配 · 点击放大";
    LayoutImage.fit(src).then(result=>{if(image.isConnected){image.src=result.src;image.dataset.layoutFit=JSON.stringify({original:result.original,size:[result.canvas.width,result.canvas.height],bounds:result.bounds,bands:result.bands});}}).catch(()=>{if(image.isConnected)image.src=src;});
  }else image.src=src;
  const enlarge=()=>{ $("dialogImage").src=layout?(image.currentSrc||image.src||src):src;$("dialogImage").alt=title;$("dialogTitle").textContent=title;$("plotDialog").showModal();};
  image.onclick=enlarge;image.onkeydown=e=>{if(e.key==="Enter"){e.preventDefault();enlarge();}};
  if(preview){host.append(image);return;}
  const article=document.createElement("article");article.className="plotcard";
  const head=document.createElement("div");head.className="phead";const h=document.createElement("h3");h.textContent=title;const hint=document.createElement("small");hint.textContent="点击图像放大";head.append(h,hint);
  const figure=document.createElement("figure");figure.append(image);const cap=document.createElement("figcaption");cap.textContent="Optiland · 实际保存处方";figure.append(cap);article.append(head,figure);host.append(article);
}
$("closePlot").onclick=()=>$("plotDialog").close();
$("plotDialog").onclick=e=>{if(e.target===$("plotDialog"))$("plotDialog").close();};

async function refreshLibrary(){
  try{
    const d=await requestJson("/api/library");libraryRuns=d.runs||[];
    const select=$("runLibrary"),prev=select.value;select.replaceChildren(new Option("运行历史 · 选择已保存的设计",""));
    for(const source of ["v7"]){const group=document.createElement("optgroup");group.label=source==="v7"?"本地运行与档案":"V3 · 导入副本后查看";
      for(const r of libraryRuns.filter(r=>r.source===source))group.append(new Option(`${r.label||r.run_id} · ${r.foclen??"?"}mm F${r.fnum??"?"} · ${r.multiseed?"多候选":r.reference?"参考处方":"单次"} · ${r.engine}`,`${source}:${r.run_id}`));
      if(group.children.length)select.append(group);
    }
    if([...select.options].some(o=>o.value===prev))select.value=prev;
  }catch(e){notify("运行历史读取失败："+e.message);}
}
$("refreshLibrary").onclick=refreshLibrary;
$("loadRun").onclick=async()=>{
  const choice=$("runLibrary").value;if(!choice){notify("请先从运行历史选择一项");return;}
  $("loadRun").disabled=true;
  try{let id=choice.slice(3);if(choice.startsWith("v3:")){notify("正在创建 V3 结果副本…");id=(await postJson("/api/import-v3",{run_id:id})).run_id;await refreshLibrary();}
    followActive=false;selectRun(id);await poll();notify("已载入 "+id+" · 参数可回填后重新优化");
  }catch(e){notify("载入失败："+e.message,true);}finally{$("loadRun").disabled=false;}
};
$("followLive").onclick=()=>{followActive=true;if(activeJob?.has_job){selectRun(activeJob.run_id);if(currentLens!==selectedRun){resetLensView();lastImg="";}}poll();};

function setConsole(log){logVisible=log;$("parameterScroll").hidden=log;$("logPanel").hidden=!log;$("showLog").classList.toggle("active",log);$("showParams").classList.toggle("active",!log);if(log)loadLog();}
$("showParams").onclick=()=>setConsole(false);$("showLog").onclick=()=>setConsole(true);
async function loadLog(){
  if(!selectedRun)return;
  const selected=selectedRun,view=currentLens||selectedRun,id=NativeProgress.worker(selected,selectedProgress,view);
  try{const d=await requestJson("/api/log?run="+encodeURIComponent(id));if(selectedRun===selected&&(currentLens||selectedRun)===view){
    const text=NativeProgress.cleanLog(d.text);$("consoleLog").textContent="日志来源："+id+"\n\n"+(text||"当前进程尚未写入日志，请稍候自动更新。");lastLogAt=Date.now();
  }}catch(e){$("consoleLog").textContent="日志读取失败："+e.message;}
}

function resetLensView(){
  ++lensRequest;currentLens=null;lensMetrics=null;lensFinal=false;currentScene=null;analysisShown=null;
  lensViewer.setModel(null);$("threeEmpty").hidden=false;$("lensSource").textContent="尚未保存处方";
  $("prescriptionRows").replaceChildren();$("prescriptionMeta").textContent="";$("asphericDetails").textContent="";
  setExportLinks(null,false);resetAnalysis();
  paintEvaluation({});
}
function resetAnalysis(){
  for(const key of Object.keys(analysisFiles))makeEmpty($("plot-"+key),"等待计算分析","有保存处方后点击上方「计算分析」。");
  makeEmpty($("overviewMtf"),"等待像质分析","MTF · 全部采样波长");makeEmpty($("overviewSpot"),"等待点列分析","配置的波长");
  $("anaStatus").textContent="分析尚未计算。MTF默认综合全部采样波长。";
  $("mtfWavelength").replaceChildren(new Option("全部采样波长 · 综合MTF","all"));
}
function selectRun(id){
  if(selectedRun===id){if(currentLens&&currentLens!==id){resetLensView();lastImg="";}return;}
  sourceFollowLatest=true;lastScenePoll=0;selectedRun=id;lastRunId=id;lastImg="";screenKey="";selectedProgress=null;resetLensView();
  makeEmpty($("imgwrap"),"等待已保存的光路图");makeEmpty($("overviewLayout"),"等待已保存的光路图");$("files").replaceChildren();
  $("errBox").style.display="none";$("runinfo").hidden=false;
}
function onNewRun(id){followActive=true;selectRun(id);showTab("overview");refreshLibrary();}

function selectedPrescription(){
  const source=currentScene?.run_id===currentLens?currentScene.source:null;
  return {source_file:source,source_sha256:currentScene?.run_id===currentLens?currentScene.source_sha256:null};
}
function freezeSourceView(){sourceFollowLatest=false;const ref=selectedPrescription();if(ref.source_file)$('snapshotSelect').value=ref.source_file;}
function hasSavedPrescription(){return !!currentLens&&!!selectedPrescription().source_file;}
function setExportLinks(id,final){
  const ref=selectedPrescription(),available=!!id&&!!ref.source_file;
  for(const [key,fmt]of [["expZmx","zmx"],["expSeq","seq"]]){const a=$(key);a.classList.toggle('disabled',!available);a.href=available?`/api/export?run=${encodeURIComponent(id)}&fmt=${fmt}&source=${encodeURIComponent(ref.source_file)}${ref.source_sha256?'&sha256='+ref.source_sha256:''}`:'#';a.setAttribute('aria-disabled',String(!available));}
  $('jsonDownload').classList.toggle('disabled',!available);$('jsonDownload').href=available?runPath(id,ref.source_file):'#';
  $('jsonDownload').setAttribute('aria-disabled', String(!available));
  for (const id of ['expZmx', 'expSeq', 'jsonDownload']) $(id).tabIndex = available ? 0 : -1;
  $('btnAnalysis').disabled=!available||analysisRequests.has(id)||!!window.analysisSuite?.busy;$('btnAnalysis').textContent='计算当前分析';
  $('btnResume').title=currentScene?.native_import?'此记录用于原生直接分析；优化请在导入对话框选择沿用原结构并完成兼容性核验':'从选中保存处方继续，不重新生成';
  $('btnResume').disabled=!available||!!currentScene?.native_import||!!(activeJob?.running&&activeJob.run_id===id);
}
let resumeReference=null,sourceFollowLatest=true,lastScenePoll=0;
let saveResultsBusy=false;
let stopRequestPending=false,continuePending=false,stoppedSnapshotShown='';
function canContinueStopped(){return currentLens===selectedRun&&['stopped','finished'].includes(selectedProgress?.status)&&hasSavedPrescription()&&!currentScene?.native_import;}
function updateStopControls(){
 const running=!!activeJob?.running,stopping=running&&(stopRequestPending||activeJob?.stopping),can=canContinueStopped();
 for(const id of ['btnStop','focusStop']){const b=$(id);b.textContent=continuePending?'正在继续…':stopping?'正在停止…':running?'停止':can?'继续优化':'停止';b.disabled=continuePending||stopping||(!running&&(!can||!window.analysisSuite?.stopContinueReady));b.classList.toggle('can-continue',!running&&can);b.title=stopping?'正在安全停止并保存当前结构':!running&&can?(window.analysisSuite?.stopContinueReady?'从停止时最新保存的结构继续，不重新生成初始结构':'需关闭并重新打开V10.0.0以加载新的继续功能，不会从头生成'):'停止实际运行中的任务';}
 $('btnStart').disabled=running||startPending||continuePending;
 $('btnSaveResults').disabled=saveResultsBusy||!(currentLens||selectedRun);
}
async function prepareSavedContinuation(id,source={source_file:'latest'}){
 const d=await postJson('/api/resume-prepare',{run_id:id,...source});runParams=d.params;
 if(!['autolens','optiland'].includes(runParams.engine)){runParams.engine=$('route').value;runParams.route=$('route').value;}
 refillRunParams();refillResumeReference(d.source);$('showParams').click();return d;
}
function refillResumeReference(ref){resumeReference=ref||null;window.resumeReference=resumeReference;$('resumeSource').hidden=!ref;$('clearResume').hidden=!ref;
 if(ref)$('resumeSource').textContent=(ref.phase==='curriculum'?'课程重启来源（非完整断点恢复）：':'继续来源：')+ref.run_id+' / '+ref.source_file+' · 保留结构；本段计数从0开始';updateStartMode();}
$('clearResume').onclick=()=>{refillResumeReference(null);notify('已取消快照来源；下一次从技术条件重新生成。');};
$('btnResume').onclick=async()=>{try{const d=await prepareSavedContinuation(currentLens,selectedPrescription());notify('已准备从选定结构继续：检查左侧预算后点“开始优化”。'+d.message);}catch(e){notify(e.message,true);}};
$('snapshotSelect').onchange=async()=>{try{sourceFollowLatest=$('snapshotSelect').value==='latest';await loadGeometry(currentLens,$('snapshotSelect').value);setExportLinks(currentLens,lensFinal);window.analysisSuite?.sourceChanged();}catch(e){notify(e.message,true);}};
async function downloadExport(a){if(a.classList.contains('disabled'))return;freezeSourceView();
 try{notify('正在导出当前选中处方…');const response=await fetch(a.href);if(!response.ok){const d=await response.json();throw Error(d.error||'导出未成功');}
 const data=await response.blob(),url=URL.createObjectURL(data),link=document.createElement('a');link.href=url;
 const match=(response.headers.get('Content-Disposition')||'').match(/filename\*=UTF-8''([^;]+)/i);link.download=match?decodeURIComponent(match[1]):(a.id==='expSeq'?'lens.seq':'lens.zmx');document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);notify('文件已生成，请在保存对话框选择位置。');
 }catch(e){notify('导出失败：'+e.message,true);}}
for(const id of ['expSeq','expZmx'])$(id).onclick=e=>{e.preventDefault();downloadExport($(id));};
window.chrome?.webview?.addEventListener('message',e=>{if(e.data?.type==='download')notify(e.data.message,e.data.failed);});
function chooseResultsFolder(mode='save'){
 return new Promise((resolve,reject)=>{
  const bridge=window.chrome?.webview;if(!bridge){reject(Error('请选择V10.0.0 EXE入口打开工作台，以使用文件夹选择窗口'));return;}
  const id=Date.now().toString()+'-'+Math.random().toString(36).slice(2),cleanup=()=>{clearTimeout(timer);bridge.removeEventListener('message',receive);};
  const receive=e=>{const data=e.data;if(data?.request_id!==id)return;
   if(data.type==='results-folder-opened'){clearTimeout(timer);return;}
   if(data.type==='results-folder'){cleanup();data.error?reject(Error(data.error)):resolve(data.path||null);}
  };
  const timer=setTimeout(()=>{cleanup();reject(Error('当前窗口未提供文件夹选择功能，请关闭旧窗口并打开V10.0.0 EXE'));},8000);
  bridge.addEventListener('message',receive);bridge.postMessage('choose-results-folder|'+id+'|'+mode);
 });
}
$('btnSaveResults').onclick=async()=>{
 if(saveResultsBusy)return;const id=currentLens||selectedRun;if(!id){notify('请先载入一个运行记录',true);return;}
 saveResultsBusy=true;updateStopControls();const button=$('btnSaveResults');button.textContent='选择文件夹…';
 try{const destination=await chooseResultsFolder();if(!destination)return;button.textContent='正在保存…';
  const saved=await postJson('/api/results-save',{run_id:id,destination});
  const note=saved.status==='partial'?`；${saved.errors.length}项未复制，请查看保存说明`:saved.live_snapshot?'；仅含保存时已有文件':'';
  const message=`已保存${saved.file_count}个文件${note}：${saved.destination}`;
  notify(message,saved.status==='partial');$('footerStatus').textContent=message;button.title=message;
 }catch(error){notify('保存结果失败：'+error.message,true);}
 finally{saveResultsBusy=false;button.textContent='保存全部结果';updateStopControls();}
};
$('btnOpenResults').onclick=async()=>{
 const button=$('btnOpenResults');if(button.disabled)return;button.disabled=true;button.textContent='选择档案…';
 try{const folder=await chooseResultsFolder('open');if(!folder)return;button.textContent='正在读取…';
  const imported=await postJson('/api/results-open',{folder});
  followActive=false;selectRun(imported.run_id);await refreshLibrary();await viewLens(imported.run_id,false,true);await poll();
  $('analysisEngine').value=imported.analysis_engine;$('analysisEngine').dispatchEvent(new Event('change'));
  $('runLibrary').value='v7:'+imported.run_id;
  notify('已读取档案，未启动优化。'+(imported.warnings||[]).join('；'));$('footerStatus').textContent='已读取档案 · '+folder;
 }catch(error){notify('读取档案失败：'+error.message,true);}
 finally{button.disabled=false;button.textContent='读取档案';}
};
async function viewLens(id,final,force=false){
  const changed=currentLens!==id;if(changed){resetLensView();currentLens=id;resetAnalysis();}
  lensFinal=final;setExportLinks(id,final);
  $("lensSource").textContent="查看处方 · "+id;
  if(changed&&id!==selectedRun){
    requestJson("/api/record?run="+encodeURIComponent(id)).then(s=>{if(currentLens===id){lensMetrics=s.progress;paintEvaluation(lensMetrics);}}).catch(e=>notify(e.message));
    makeEmpty($("imgwrap"),'正在载入所选快照');makeEmpty($("overviewLayout"),'正在载入所选快照');
    $("files").replaceChildren();
  }
  if(changed||force)await loadGeometry(id);
  if(currentLens!==id)return;
  if(analysisCache.has(id))renderAnalysis(id,analysisCache.get(id));
  else if(final&&(changed||force))loadCachedAnalysis(id);
  if(!window.analysisSuite&&final&&["spot","mtf","aberration","fan"].includes(activeTab))runAnalysis(id,false);
  highlightCandidate();
}
async function loadGeometry(id,source=null){
  if(source===null&&!sourceFollowLatest&&currentScene?.run_id===id)source=currentScene.source;
  const token=++lensRequest;
  try{const d=await requestJson("/api/lens?run="+encodeURIComponent(id)+(source?"&source="+encodeURIComponent(source):""));if(token!==lensRequest||currentLens!==id)return;
    currentScene=d;paintImageHeight();if(lensMetrics)paintEvaluation(lensMetrics);updateLayout(id,lensMetrics||{});
    const options=$('snapshotSelect');options.replaceChildren(new Option('最新保存（自动跟随）','latest'));for(const row of d.snapshots||[])options.append(new Option((row.final?'最终保存 · ':'阶段保存 · ')+row.file,row.file));options.value=sourceFollowLatest?'latest':d.source;
    setExportLinks(id,lensFinal);window.analysisSuite?.sourceChanged();lensViewer.setModel(d);$("threeEmpty").hidden=true;renderPrescription(d);
    $("lensSource").textContent="查看处方 · "+id+" / "+d.source;
    $("geometryNote").textContent=d.warnings.length?d.warnings.join("；"):"工作台几何模型 · mm · 不随分析内核切换；原生光线见光路布局";
    $("jsonDownload").href=runPath(id,d.source);$("jsonDownload").classList.remove("disabled");
  }catch(e){if(token===lensRequest){currentScene=null;lastImg='';lensViewer.setModel(null);$('prescriptionRows').replaceChildren();$('prescriptionMeta').textContent='';$('asphericDetails').textContent='';$('geometryNote').textContent=e.message;paintEvaluation(lensMetrics||{});setExportLinks(id,false);window.analysisSuite?.sourceChanged();makeEmpty($('overviewLayout'),'当前快照无法载入',e.message);makeEmpty($('imgwrap'),'当前快照无法载入',e.message);$("threeEmpty").textContent=e.message;$("threeEmpty").hidden=false;}}
}
function renderPrescription(d){
  const body=$("prescriptionRows");body.replaceChildren();
  function row(values,cls=""){const tr=document.createElement("tr");tr.className=cls;for(const v of values){const td=document.createElement("td");td.textContent=v;tr.append(td);}body.append(tr);}
  row(["物面",d.object_at_infinity?"无限远":"有限物距", "—",d.object_at_infinity?"∞":fmt(Math.abs(d.object_depth),3),"—","air","1.00000","—"]);
  for(const s of d.surfaces)row([s.type==="Aperture"?s.index+" · STOP":s.index,{Spheric:"球面",Aspheric:"偶次非球面",Aperture:"光阑",Plane:"平面"}[s.type]||s.type,s.roc===null?"∞":fmt(s.roc,5),fmt(s.thickness,5),fmt(s.radius,5),s.material,fmt(s.nd,5),fmt(s.vd,3)],s.type==="Aperture"?"stoprow":"");
  row(["像面","z = "+fmt(d.sensor_z,5),"∞","—",fmt(d.sensor_radius,5),"air","1.00000","—"]);
  $("prescriptionMeta").textContent=(d.glass_catalog?d.glass_catalog+" · ":"")+`${d.surfaces.length} 面 · ${d.wavelengths.map(w=>fmt(w,4)).join(" / ")} µm`;
  const aspheres=d.surfaces.filter(s=>s.type==="Aspheric");
  $("asphericDetails").textContent=aspheres.length?aspheres.map(s=>`面 ${s.index}：k=${s.conic}；系数从 a${s.use_ai2?2:4} 起依次为 ${JSON.stringify(s.coefficients)}`).join("； "):"各面球面/光阑；nd / Vd 来自实际玻璃库。"+(d.export_materials==="catalog_names"?"SEQ / ZMX 保留真实玻璃牌号和高精度处方。":"此历史处方的商业导出仍使用 MODEL 玻璃近似。");
}
async function loadCachedAnalysis(id){
  if(window.analysisSuite?.ready&&!window.analysisSuite.legacy)return window.analysisSuite.loadSaved(id);
  try{const r=await fetch(runPath(id,"analysis/analysis.json"));if(!r.ok)return;const d=await r.json();if(d.analysis_version!==5){if(currentLens===id)runAnalysis(id,false);return;}analysisCache.set(id,d);if(currentLens===id)renderAnalysis(id,d);}catch(e){/* A new run normally has no cache yet. */}
}
function renderAnalysis(id,d){
  if(window.analysisSuite&&!window.analysisSuite.legacy)return;
  const ref=selectedPrescription();if(d.source_file!==ref.source_file||(ref.source_sha256&&d.source_sha256!==ref.source_sha256))return;
  if(currentLens!==id)return;analysisShown=id;
  for(const [key,file]of Object.entries(analysisFiles)){
    const im=(d.images||[]).find(im=>im.file===file);
    if(im){const url=runPath(id,(d.relative_dir||"analysis")+"/"+file)+"?v="+(d.generated_at||Date.now());plotImage($("plot-"+key),url,labels[key]);if(key==="mtf")plotImage($("overviewMtf"),url,labels[key],true);if(key==="spot")plotImage($("overviewSpot"),url,labels[key],true);}
    else{const reason=d.errors?.[({spot:"点列图",mtf:"几何 MTF",curvature:"场曲",distortion:"网格畸变",fan:"光线像差扇图"})[key]]||"未生成此项分析";makeEmpty($("plot-"+key),labels[key]+"未完成",reason);}
  }
  const meta=d.meta||{},errors=Object.keys(d.errors||{});
  const mtf=(d.images||[]).find(i=>i.file==="mtf_geometric.png"),select=$("mtfWavelength"),previous=select.value;
  select.replaceChildren(new Option("全部采样波长 · 综合MTF","all"));
  for(const variant of mtf?.variants||[])select.append(new Option(`${fmt(variant.wavelength_um*1000,2)} nm`,variant.file));
  select.value=[...select.options].some(o=>o.value===previous)?previous:"all";
  $("mtfSpectrumNote").textContent="采样波长："+(meta.mtf_wavelengths_um||meta.wavelengths_um||[]).map(w=>fmt(w*1000,2)).join(" / ")+" nm · 按保存光谱权重综合，保留各波长实际透过能量";
  renderSelectedMtf(id,d);
  $("anaStatus").textContent=`Optiland · MTF采样 ${(meta.mtf_wavelengths_um||meta.wavelengths_um||[]).map(w=>fmt(w*1000,1)).join(" / ")} nm · 半视场 ${fmt(meta.half_fov_deg,2)}°`+(errors.length?" · 部分未完成："+errors.join("、"):" · 5 项分析已生成");
  setExportLinks(id,lensFinal);
}
function renderSelectedMtf(id,data){
  if(currentLens!==id)return;
  const item=(data.images||[]).find(i=>i.file==="mtf_geometric.png");if(!item)return;
  const selected=(item.variants||[]).find(v=>v.file===$("mtfWavelength").value);
  const file=selected?selected.file:item.file;
  plotImage($("plot-mtf"),runPath(id,(data.relative_dir||"analysis")+"/"+file)+"?v="+(data.generated_at||Date.now()),selected?fmt(selected.wavelength_um*1000,2)+" nm · 几何MTF":labels.mtf);
}
$("mtfWavelength").onchange=()=>{const data=analysisCache.get(currentLens);if(data)renderSelectedMtf(currentLens,data);};
async function runAnalysis(id,force){
  if(window.analysisSuite&&window.analysisSuite.engine!=='optiland')return window.analysisSuite.runCurrent();
  if(!id||!hasSavedPrescription())return;
  if(!force&&analysisCache.has(id)){const cached=analysisCache.get(id),ref=selectedPrescription();if(cached.source_file===ref.source_file&&(!ref.source_sha256||cached.source_sha256===ref.source_sha256)){renderAnalysis(id,cached);return;}}
  if(analysisRequests.has(id))return analysisRequests.get(id);
  const task=(async()=>{
    if(currentLens===id){$("anaStatus").textContent="Optiland 实际追迹计算中…首次分析需要等待编译缓存";notify("正在分析 "+id);}
    try{const d=await postJson("/api/analysis",{run_id:id,engine:'optiland',force:!!force,...selectedPrescription()});d.generated_at=Date.now();analysisCache.set(id,d);if(currentLens===id){renderAnalysis(id,d);notify("分析完成 · "+id);}}
    catch(e){if(currentLens===id){$("anaStatus").textContent="分析失败："+e.message;for(const key of Object.keys(analysisFiles))makeEmpty($("plot-"+key),"分析未完成",e.message);notify("分析失败："+e.message,true);}}
    finally{analysisRequests.delete(id);if(currentLens===id)setExportLinks(id,lensFinal);}
  })();
  analysisRequests.set(id,task);if(currentLens===id)setExportLinks(id,lensFinal);return task;
}
$("btnAnalysis").onclick=()=>window.analysisSuite?window.analysisSuite.runCurrent():runAnalysis(currentLens,true);

function paintImageHeight(){
  const value=currentScene?.run_id===currentLens?currentScene.sensor_radius:null;
  const node=$('statImageHeight');if(!node)return;
  node.textContent=Number.isFinite(value)&&value>0?value.toFixed(3):'—';
}
function paintEvaluation(p){
  paintImageHeight();
  for(const id of ["m_efl","m_fov","m_fnum","m_cra","m_dist","m_vmin","m_bfl","m_ttl"])$(id).className="";
  showMetrics(p||{});drawChart(p?.history);
  const hasHistory=(p?.history?.length||0)>=2;
  $("chartEmpty").hidden=hasHistory;$("chart").hidden=!hasHistory;
  $("chartNote").textContent="本运行 "+(p?.history?.length||0)+" 条记录"+(!sourceFollowLatest?' · 非当前快照评价':Number.isFinite(p?.loss_rms)?" · 最近训练项 "+p.loss_rms.toExponential(2):"");
  const op=p?.engine==="optiland";
  $("chartRmsLegend").textContent=op?"评价 RMS（mm）":"训练 RMS 项";
  const metrics=displayedMetrics(p||{});
  $('overviewLayoutTitle').textContent=p?.engine==='autolens'&&metrics.display_kind==='native_evaluated_snapshot'?'原生保存光路 · 图内数值未重算':'优化流程保存光路';
  $("lossLabel").textContent=['native_evaluated_snapshot','independently_recorded'].includes(metrics.display_kind)?'快照实测 F 数':metrics.display_kind?'原生记录 F 数':'实测 F 数';
  $("statLoss").textContent=Number.isFinite(metrics.fnum)?metrics.fnum.toFixed(2):"—";
  $("statLossSub").textContent=targetDeviation(metricTargets(p||{}).fnum,metrics.fnum,2);$("statLossSub").title=metrics.source_file||'';
  $("metricProtocol").textContent="评价协议："+(metrics.evaluation_protocol||"历史记录未标注")+"；"+(metrics.rms_definition||'RMS尚未计算')+"；视场为近轴推算，追迹有效率不含传感器覆盖。颜色使用±5%参考范围提示偏差，非用户验收容差，不表示全项达标。"+(Number.isFinite(metrics.target_image_error_max_pct)?" 目标像点最大相对偏差："+fmt(metrics.target_image_error_max_pct,2)+"%（单独记录）。":"");
  const screening=p?.screening,badge=$("screeningBadge");
  badge.textContent=p?.engine==="reference"?"参考处方":p?.status==='stopped'?'已停止 · 尚未验收':p?.status==="finished"&&screening?(screening.eligible?"基础通过 · 像质未验收":"基础条件未通过"):(p?.status==="finished"?"计算完成 · 请核对指标":"计算中 · 尚未验收");
  badge.className="qualitybadge"+(p?.status==="finished"&&screening?(screening.eligible?" pass":" fail"):"");
  badge.title=screening?(screening.reasons||[]).join("；"):"展示当前处方指标；计算完成不代表MTF、通光、机械及公差等全部达标";
}
function updateLayout(id,p){
  const scene=currentScene;
  if(!scene||scene.run_id!==id||currentLens!==id)return;
  const layout=scene.snapshot_layout,identity=id+'|'+scene.source+'|'+scene.source_sha256;
  const matched=layout?.available&&layout.source_file===scene.source&&layout.source_sha256===scene.source_sha256&&layout.image_file&&layout.image_sha256;
  const key=identity+'|'+(matched?layout.image_sha256:'no-image');
  if(lastImg!==key){
    lastImg=key;
    if(matched){const src=runPath(id,layout.image_file)+'?sha256='+encodeURIComponent(layout.image_sha256);plotImage($('imgwrap'),src,'当前快照光路',true);plotImage($('overviewLayout'),src,'当前快照光路',true);$('layoutName').textContent=scene.source+' · '+layout.image_file;}
    else {const note=layout?.message||'当前快照没有已保存的同源光路图，可选择本快照计算光路分析。';makeEmpty($('imgwrap'),'当前快照暂无同源光路',note);makeEmpty($('overviewLayout'),'当前快照暂无同源光路',note);$('layoutName').textContent=scene.source+' · 尚未保存光路';}
  }
  const files=p.files||[];
  $('files').replaceChildren();for(const file of [...['final_lens.json','final_lens.seq','final_lens.zmx','completion.json','requirements_validation.json','source_execution.json','summary.json','curriculum_final.json','seed_matched.json'].filter(f=>files.includes(f)),...files.filter(f=>f.toLowerCase().endsWith('.agf'))]){const a=document.createElement('a');a.href=runPath(id,file);a.download=file;a.textContent=file+' ↓';$('files').append(a);}
}
function filesHasFinal(p){return(p.files||[]).includes("final_lens.json");}

async function poll(){
  if(pollBusy)return;pollBusy=true;
  try{
    const live=await requestJson("/api/state");activeJob=live;const globallyRunning=live.running===true;
    $("btnStart").disabled=globallyRunning||startPending;$("btnStop").disabled=!globallyRunning;$("btnStop").title=globallyRunning?"停止实际运行任务 "+live.run_id:"没有运行中的任务";
    $("focusStop").disabled=!globallyRunning;$("focusStop").title=$("btnStop").title;
    if(followActive&&live.has_job&&selectedRun!==live.run_id)selectRun(live.run_id);
    if(!selectedRun){$("runinfo").hidden=true;return;}
    const s=selectedRun===live.run_id?live:await requestJson("/api/record?run="+encodeURIComponent(selectedRun));
    if(!s.has_job)return;
    const p=s.progress||{},running=s.running===true,status=p.status||(running?"running":"unknown");
    selectedProgress=p;if(!currentLens||currentLens===s.run_id)lensMetrics=p;
    runParams=p.params||s.params||null;markRunDiffs();
    $("designTitle").textContent=runParams?.reference?runParams.label+" · 非本次优化结果":`${runParams?.foclen??"—"} mm / F${runParams?.fnum??"—"} · ${runParams?.elements??"—"} 片镜头`;
    const materialPool=p.glass_selection||runParams?.glass_selection;
    $("runinfo").hidden=false;$("runinfoTxt").textContent=`${s.run_id} · ${statusNames[status]||status}`+(materialPool?` · ${materialPool.catalog} / ${materialPool.policy_label} / ${materialPool.count} 个可用牌号`:"")+" · 橙色标注为表单差异";
    const activeStage=NativeProgress.stage(p);
    let stageName={curriculum:"课程学习",refine:"精调",optiland_initial:"一阶初始化",optiland_refine:"像质优化",screening:"候选结构筛查",polish:"优选精修",verification:"条件核验",analysis:"分析出图",export:"导出处方",init:"初始化"}[activeStage]||activeStage||"初始化";
    if(p.batch&&p.stage==='screening')stageName='候选生成 · '+stageName;
    $("stxt").textContent=running?stageName+"中":statusNames[status]||status;$("dot").className="dot "+(running?"running":status);
    const total=p.total_iters||0,it=p.iter||0;let overall=status==="finished"?100:["refine","optiland_refine"].includes(p.stage)?50+50*it/Math.max(total,1):50*it/Math.max(total,1);
    if(p.batch&&p.engine==='autolens'&&['curriculum','refine'].includes(activeStage)){
      const c=Number(runParams?.curriculum_iters||0),r=Number(runParams?.refine_iters||0);
      overall=100*((activeStage==='refine'?c:0)+it)/Math.max(c+r,1);
    }
    if(p.engine==='optiland'&&running)overall=activeStage==='optiland_refine'?50:0;
    if(p.batch)overall=100*(p.batch.completed+(running&&p.stage!=="polish"?Math.min(overall,100)/100:0))/Math.max(p.batch.total,1);
    $("bar").style.width=Math.max(0,Math.min(overall,100))+"%";
    $("siter").textContent=p.engine==="reference"?"官方舍入处方 · 本地评价 · 非优化运行":(p.engine==="optiland"?"Optiland CPU":p.engine==="autolens"?"AutoLens":"双内核")+" · "+(p.batch?`候选 ${p.batch.active_index??"—"} · ${p.batch.completed}/${p.batch.total} 完成 · ${stageName} ${it}/${total}`:p.engine==="optiland"?`残差评价 ${it} · nfev预算 ${p.nfev_budget??"—"}`:`${it} / ${total} 迭代`);
    if(p.engine==='optiland'){
      $("siter").textContent=`Optiland CPU${p.batch?` · 候选 ${p.batch.active_index??'—'} · ${p.batch.completed}/${p.batch.total} 完成`:''} · 评价记录 ${p.residual_evaluations??p.model_update_calls??it} 次 · ${runParams?.optiland_glass_mode==='expert'&&activeStage==='optiland_refine'?'每次局部迭代上限':'本阶段 nfev 预算'} ${p.nfev_budget??total}`+(p.solver_iterations!=null?` · 求解迭代 ${p.solver_iterations}`:'');
      $("siter").title='模型更新包含数值求导调用，不等于nfev。当前原生回调不提供实时nfev；阶段结束记录实际nfev。进度条仅示意已完成阶段。';
    }
    $("srate").textContent=p.it_per_s?fmt(p.it_per_s,1)+" iter/s":"";
    if(p.engine==='optiland'&&p.it_per_s)$("srate").textContent=fmt(p.it_per_s,1)+' 更新/s';
    paintEvaluation(lensMetrics||p);
    if(p.engine==='optiland'&&running){
      $("statRmsSub").textContent+=' · '+(p.snapshot_time?'保存的迭代快照':'仅阶段保存值');
      if(!(p.history?.length>=2))makeEmpty($("chartEmpty"),'当前阶段尚未保存曲线','求解仍在计算；指标与快照按进度回调或阶段结束更新。');
    }
    if(p.error){$("errBox").textContent=p.error;$("errBox").style.display="block";}
    if(!currentLens){currentLens=s.run_id;await viewLens(s.run_id,filesHasFinal(p),true);}
    if(currentLens===s.run_id&&sourceFollowLatest&&Date.now()-lastScenePoll>8000&&!window.analysisSuite?.busy){lastScenePoll=Date.now();await loadGeometry(s.run_id);}
    if(currentLens===s.run_id){const becameFinal=!lensFinal&&filesHasFinal(p);lensFinal=filesHasFinal(p);setExportLinks(s.run_id,lensFinal);updateLayout(s.run_id,p);if(becameFinal)await loadGeometry(s.run_id);if(becameFinal||(p.completion?.analysis_finished&&!analysisCache.has(s.run_id)))await loadCachedAnalysis(s.run_id);}
    if(!globallyRunning){stopRequestPending=false;if(p.status==='stopped'&&currentLens===s.run_id&&stoppedSnapshotShown!==s.run_id){stoppedSnapshotShown=s.run_id;if(sourceFollowLatest)await loadGeometry(s.run_id,'latest');}}
    const continuation=p.params?.resume_reference;
    if(continuation){$('siter').textContent+=' · 续算本段（来源 '+continuation.source_file+'）';$('siter').title='从来源快照保留结构继续；原生求解器重新建立，本段轮数从0开始，不是重新生成镜头。';}
    if(globallyRunning&&(s.stopping||stopRequestPending)){$('stxt').textContent='正在停止并保存…';$('siter').textContent='已收到停止请求，等待当前安全计算边界；不会继续下一轮优化';}
    updateStopControls();
    $("footerSource").textContent="运行 · "+s.run_id+(currentLens!==s.run_id?" · 处方查看中":"");
    $("followLive").classList.toggle("active",followActive);$("followLive").textContent=globallyRunning&&!followActive?"返回正在运行的任务":"跟随当前任务";
    if(logVisible&&Date.now()-lastLogAt>4000)loadLog();
    if(!globallyRunning&&pollTimer){clearInterval(pollTimer);pollTimer=null;refreshLibrary();}
  }catch(e){notify("状态读取失败："+e.message);}finally{pollBusy=false;}
}

function highlightCandidate(){document.querySelectorAll(".candidate").forEach(c=>c.classList.toggle("selected",c.dataset.lens===currentLens));}
const originalStart=start;
start=async()=>{try{await originalStart();}catch(e){notify("启动请求失败："+e.message,true);}};
const originalStop=stop;
let stopConfirmationPending=false;
function confirmCourseRestart(){
 return new Promise(resolve=>{const dialog=$('courseRestartDialog'),finish=()=>{dialog.removeEventListener('close',finish);resolve(dialog.returnValue==='restart');};
  dialog.returnValue='cancel';$('cancelCourseRestart').onclick=()=>dialog.close('cancel');$('confirmCourseRestart').onclick=()=>dialog.close('restart');dialog.addEventListener('close',finish);dialog.showModal();$('cancelCourseRestart').focus();
 });
}
function confirmStopOptimization(){
 return new Promise(resolve=>{const dialog=$('stopConfirmDialog');
  const finish=()=>{dialog.removeEventListener('close',finish);resolve(dialog.returnValue==='stop');};
  dialog.returnValue='cancel';$('cancelStop').onclick=()=>dialog.close('cancel');$('confirmStop').onclick=()=>dialog.close('stop');dialog.addEventListener('close',finish);dialog.showModal();$('cancelStop').focus();
 });
}
stop=async()=>{
 if(continuePending||stopRequestPending||stopConfirmationPending)return;
 if(!activeJob?.running&&canContinueStopped()){
  continuePending=true;updateStopControls();const oldRun=currentLens;
  try{const d=await prepareSavedContinuation(oldRun);notify('正在从停止结构继续。'+d.message);await start();if(lastRunId!==oldRun)refillResumeReference(null);}
  catch(e){notify('继续优化失败：'+e.message+'。没有重新生成结构。',true);}
  finally{continuePending=false;updateStopControls();}return;
 }
 if(!activeJob?.running){notify('没有运行中的任务或可继续的停止镜头',true);return;}
 const stopTarget=activeJob.run_id;stopConfirmationPending=true;let confirmed=false;
 try{confirmed=await confirmStopOptimization();}finally{stopConfirmationPending=false;}
 if(!confirmed)return;
 await poll();
 if(!activeJob?.running||activeJob.run_id!==stopTarget){notify('原任务已结束，未发送停止请求。');return;}
 stopRequestPending=true;updateStopControls();$('stxt').textContent='正在停止并保存…';
 try{await originalStop();notify('停止请求已接收，正在安全保存；完成后此按钮变为“继续优化”。');poll();}
 catch(e){stopRequestPending=false;updateStopControls();notify('停止请求失败：'+e.message,true);}
};
resetAnalysis();refreshCaps();linkImghFov("foclen");poll();
refreshLibrary();
setInterval(()=>{if(!pollTimer)poll();},3000);
