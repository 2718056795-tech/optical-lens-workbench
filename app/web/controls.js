
const $ = id => document.getElementById(id);
let pollTimer = null, lastRunId = null, lastImg = "", startPending = false;

function fmt(x, d=3){
  if (x === null || x === undefined || !isFinite(x)) return "-";
  return Number(x).toFixed(d);
}
function setText(id, txt, cls){ const el = $(id); el.textContent = txt;
  el.className = cls || ""; }

async function refreshCaps(){
  try{
    const c = await (await fetch("/api/capabilities")).json();
    $("devBadge").textContent = c.cuda_available
      ? "GPU · " + c.gpu_name : "仅 CPU";
    $("devBadge").className = "badge" + (c.cuda_available ? " gpu" : "");
  }catch(e){ $("devBadge").textContent = "设备未知"; }
}

const OPTILAND_FIELDS=['optiland_solver','optiland_tol','optiland_x_scale','optiland_spot_reference','optiland_aiming','optiland_aiming_iters','optiland_aiming_tol','optiland_geometry_mode','optiland_glass_mode','optiland_glass_neighbours','optiland_edge_weight','optiland_target_weight'];
const NUM_FIELDS = ["foclen","fnum","fov","bfl","thickness","imgh","obj_depth",
  "wavelength_min_nm","wavelength_max_nm","cra_cap","distortion_max","curriculum_iters",
  "refine_iters","w_dist","scale_pupil","num_ring","spp","bfl_min",
  "bfl_max","ttl_min","ttl_max","air_edge_min","air_edge_max","air_center_min",
  "air_center_max","thick_edge_min","thick_edge_max","thick_center_min",
  "thick_center_max","sag2diam_max","diam2thick_max","tmax2tmin_max",
  "surf_angle_max","bend_angle_max","w_cra","w_ray_bend","w_clearance",
  "w_envelope","w_profile"];

// ---- 运行参数标注：表单不覆盖，只标差异 + 一键回填 ----
// [输入框 id, 参数键, 变换] 变换: "pct" 表示运行参数是小数、界面显示百分数
const RUN_FIELDS = [
  ...OPTILAND_FIELDS.map(k=>[k,k]),
  ["route","route"],
  ["image_geometry_pair","image_geometry_pair"],
  ["foclen","foclen"],["fnum","fnum"],["fov","fov"],["bfl","bfl"],
  ["thickness","thickness"],["imgh","imgh"],["obj_depth","obj_depth"],
  ["wavelength_min_nm","wavelength_min_nm"],["wavelength_max_nm","wavelength_max_nm"],
  ["cra_cap","cra_cap"],["distortion_max","distortion_max","pct"],
  ["cover_glass","cover_glass","bool"],["elements","elements"],
  ["stop_pos","stop_pos"],["glass_table","glass_table"],["glass_policy","glass_policy"],["glass_catalog_revision","glass_catalog_revision"],
  ["aspheric","aspheric","bool"],
  ["curriculum_iters","curriculum_iters"],["refine_iters","refine_iters"],
  ["w_dist","w_dist"],["scale_pupil","scale_pupil"],
  ["num_ring","num_ring"],["spp","spp"],["centroid","centroid"],
  ["device","device"],
  ["optim_mat","optim_mat","bool"],["prune","native_shape_control","bool"],
  ...["bfl_min","bfl_max","ttl_min","ttl_max","air_edge_min","air_edge_max",
      "air_center_min","air_center_max","thick_edge_min","thick_edge_max",
      "thick_center_min","thick_center_max","sag2diam_max","diam2thick_max",
      "tmax2tmin_max","surf_angle_max","bend_angle_max","w_cra",
      "w_ray_bend","w_clearance","w_envelope","w_profile"].map(k => [k, k]),
];
let runParams = null;
function runFieldValue(key){
  if(runParams?.[key]!=null)return runParams[key];
  if(key==="wavelength_min_nm"||key==="wavelength_max_nm"){
    const waves=runParams?.spectrum?.wavelengths_um||[runParams?.wvln_b??.486,runParams?.wvln_g??.587,runParams?.wvln_r??.656];
    return Number((1000*(key==="wavelength_min_nm"?Math.min(...waves):Math.max(...waves))).toPrecision(12));
  }
}
function updateSpectrumHint(){
  const low=Number($("wavelength_min_nm").value),high=Number($("wavelength_max_nm").value);
  if(!Number.isFinite(low)||!Number.isFinite(high)||low<300||high>1200||low>high){$("spectrumHint").textContent="请填写300～1200nm内的升序范围";return;}
  const waves=[low,(low+high)/2,high];
  $("spectrumHint").textContent=`原生三波长：${waves.map(w=>Number(w.toFixed(3))).join(" / ")} nm；中点为主波长，等权${low===high?'（单色三槽重合）':''}`;
}
for(const id of ["wavelength_min_nm","wavelength_max_nm"])$(id).addEventListener("input",updateSpectrumHint);
updateSpectrumHint();
function runDispVal(rv, mode){
  if (mode === "pct") return rv * 100;
  if (mode === "bool") return !!rv;
  return rv;
}
function normStopPos(raw){
  // 历史运行参数可能是 front/middle/back，统一换算为"第 K 片后"
  if (typeof raw !== "string" || !isNaN(parseInt(raw, 10))) return raw;
  const n = parseInt((runParams && runParams.elements), 10) || 4;
  return raw === "front" ? 0 : raw === "back" ? n : (n >> 1);
}
function markRunDiffs(){
  document.querySelectorAll(".rv").forEach(e => e.remove());
  document.querySelectorAll("label.diff").forEach(e => e.classList.remove("diff"));
  if (!runParams) return;
  for (const [id, key, mode] of RUN_FIELDS){
    const el = $(id);
    if (!el) continue;
    const raw = runFieldValue(key);
    if (raw === undefined || raw === null || raw === "") continue;
    let disp = runDispVal(raw, mode);
    if (key === "stop_pos") disp = normStopPos(disp);
    if(key === "route" && !["autolens","optiland"].includes(disp))disp=runParams.engine==="optiland"?"optiland":"autolens";
    const cur = el.type === "checkbox" ? el.checked
      : String(el.value).trim();
    const same = el.type === "checkbox"
      ? cur === !!disp
      : el.type === "number" && cur!=="" && Number.isFinite(Number(disp))
      ? Math.abs(Number(cur)-Number(disp))<=1e-9*Math.max(1,Math.abs(Number(disp)))
      : cur === String(disp);
    if (!same){
      const lab = el.closest("label") || el.closest(".chk");
      if (!lab) continue;
      lab.classList.add("diff");
      const tag = document.createElement("span");
      tag.className = "rv";
      tag.textContent = "运行值: " + (mode === "bool" ? (disp ? "开" : "关")
        : key === "stop_pos" ? "第" + disp + "片后" : typeof disp==="number"?Number(disp.toPrecision(8)):disp);
      lab.appendChild(tag);
    }
  }
}
function refillRunParams(){
  if (!runParams) return;
  refillResumeReference(runParams.resume_reference||null);
  if(['autolens','optiland'].includes(runParams.analysis_engine)&&$('analysisEngine').value!==runParams.analysis_engine){$('analysisEngine').value=runParams.analysis_engine;$('analysisEngine').dispatchEvent(new Event('change'));}
  $("route").value=runParams.engine==="optiland"?"optiland":"autolens";
  if(runParams.elements!=null){$('elements').value=String(runParams.elements);rebuildStopOptions();}
  for (const [id, key, mode] of RUN_FIELDS){
    const el = $(id);
    const raw = runFieldValue(key);
    if (!el || raw === undefined || raw === null || raw === "") continue;
    let disp = runDispVal(raw, mode);
    if (key === "stop_pos") disp = normStopPos(disp);
    if(key === "route" && !["autolens","optiland"].includes(disp))disp=runParams.engine==="optiland"?"optiland":"autolens";
    if (el.type === "checkbox") el.checked = !!disp;
    else el.value = String(disp);
  }
  if(window.designImport)window.designImport.refill(runParams);
  configureRoute(false);
  if(runParams.engine==='autolens'||runParams.cra_cap!=null)$('cra_cap').value=runParams.cra_cap??'';
  if(runParams.engine==='optiland'&&!runParams.optiland_input_version){$('optiland_spot_reference').value='monochromatic';$('optiland_geometry_mode').value='v7_compat';}
  // Route changes may restore a previously disabled checkbox; saved parameters win.
  if(runParams.engine==='autolens'&&typeof runParams.optim_mat==='boolean'&&!$('optim_mat').disabled)$('optim_mat').checked=runParams.optim_mat;
  if(window.requirementsUI)window.requirementsUI.refill(runParams);
  updateSpectrumHint();
  if (window.glassUI&&runParams.autolens_protocol!=='autolens-official-main-v1') window.glassUI.refill(runParams);
  markRunDiffs();
  formRoute=$('route').value;rememberEngineForm(formRoute);
}
$("btnRefill").addEventListener("click", refillRunParams);

// The selected pair is authoritative; editing either input changes only the third.
const IMAGE_PAIRS={focal_field:{inputs:["foclen","fov"],output:"imgh",name:"像高"},
  focal_height:{inputs:["foclen","imgh"],output:"fov",name:"全视场"},
  height_field:{inputs:["imgh","fov"],output:"foclen",name:"焦距"}};
function linkImghFov(_src,strict=false){
  const manual=$("field_mode").value==="manual",mode=IMAGE_PAIRS[$("image_geometry_pair").value];
  $("image_geometry_pair").disabled=manual;
  for(const id of ["foclen","fov","imgh"]){
    const computed=manual?id!=="foclen":id===mode.output;
    $(id).readOnly=computed;$(id+"Derived").hidden=!computed;
    $(id+"Derived").textContent=manual?"按视场表":"自动计算";
  }
  if(manual){$("imageGeometryHint").textContent="手动视场：全视场与像高由坐标表及目标像点确定；焦距可输入。切回自动取点后恢复所选两项联动。";return;}
  const values=Object.fromEntries(mode.inputs.map(id=>[id,parseFloat($(id).value)]));
  const valid=mode.inputs.every(id=>Number.isFinite(values[id])&&values[id]>0&&(id!=="fov"||values[id]<180));
  if(!valid){
    $(mode.output).value="";$("imageGeometryHint").textContent="请填写两项正数；全视场需小于180°。";
    if(strict)throw Error("请先填写所选的两项已知参数；全视场需大于0°且小于180°");return;
  }
  const result=mode.output==="imgh"?values.foclen*Math.tan(values.fov*Math.PI/360):
    mode.output==="fov"?2*Math.atan(values.imgh/values.foclen)*180/Math.PI:values.imgh/Math.tan(values.fov*Math.PI/360);
  if(!Number.isFinite(result)||result<=0){$(mode.output).value="";if(strict)throw Error("所选参数无法计算出有效结果");return;}
  $(mode.output).value=Number(result.toPrecision(12));
  $("imageGeometryHint").textContent=`${mode.name}自动计算，只读。像高为传感器半径，全视场为对角全角；按一阶 h = f·tan(全角/2) 换算，非实际畸变模型。`;
}
function refillImageGeometry(p){
  $("image_geometry_pair").value=Object.hasOwn(IMAGE_PAIRS,p.image_geometry_pair)?p.image_geometry_pair:
    p.imgh!=null?(p.foclen!=null||p.fov==null?"focal_height":"height_field"):"focal_field";
  linkImghFov();
}
$("image_geometry_pair").addEventListener("change",()=>{linkImghFov();window.requirementsUI?.summary();markRunDiffs();});
$("fov").addEventListener("input", () => {linkImghFov();window.requirementsUI?.summary();});
$("imgh").addEventListener("input", () => {linkImghFov();window.requirementsUI?.summary();});
$("foclen").addEventListener("input", () => linkImghFov("foclen"));

// 光阑位置选项随镜片组数联动：第 0..N 片后，默认 N/2 片后
function rebuildStopOptions(){
  const n = parseInt($("elements").value, 10) || 4;
  const prev = $("stop_pos").value;
  const prevNorm = prev === "front" ? "0"
    : prev === "back" ? String(n)
    : prev === "middle" ? String(n >> 1) : prev;
  let html = "";
  for (let k = 0; k <= n; k++){
    const tag = k === 0 ? "（最前）" : k === n ? "（最后）" : "";
    html += `<option value="${k}">第 ${k} 片后${tag}</option>`;
  }
  $("stop_pos").innerHTML = html;
  const k = parseInt(prevNorm, 10);
  $("stop_pos").value = (isNaN(k) || k < 0 || k > n) ? String(n >> 1) : String(k);
}
$("elements").addEventListener("change", rebuildStopOptions);
rebuildStopOptions();

function collectParams(){  linkImghFov(null,true);const v = id => $(id).value;
  if($('route').value==='autolens'){
    if(window.designImport?.source?.mode==='resume'&&!window.resumeReference)throw new Error('AutoLens官方入口不接导入文件的原结构续算；请选择按技术参数重新生成，或切换Optiland。');
    const p={engine:'autolens',route:'autolens',refine_engine:'autolens',workflow_mode:'direct-v1',
      foclen:v('foclen'),fov:v('fov'),fnum:v('fnum'),bfl:v('bfl'),thickness:v('thickness'),
      elements:v('elements'),stop_pos:v('stop_pos'),aspheric:false,seed:42,device:v('device'),
      image_geometry_pair:v('image_geometry_pair'),imgh:v('imgh'),
      curriculum_iters:v('curriculum_iters'),refine_iters:v('refine_iters'),analysis_engine:$('analysisEngine').value};
    if(v('cra_cap')!==''){if(window.nativeCraReady!==true)throw Error('当前后台未支持原生CRA输入，请关闭旧版窗口再打开V10.0.0');p.cra_cap=v('cra_cap');}
    if(window.resumeReference){p.resume_reference={...window.resumeReference};p.curriculum_iters=Number(window.resumeReference.initial_budget||0);p.aspheric=!!runParams?.aspheric;p.seed=runParams?.seed??runParams?.autolens_config?.seed??42;if(runParams?.lens_group_sizes)p.lens_group_sizes=runParams.lens_group_sizes;}
    return p;
  }
  const p = {
    foclen: v("foclen"), fov: v("fov"), fnum: v("fnum"), bfl: v("bfl"),
    image_geometry_pair:v("image_geometry_pair"),
    thickness: v("thickness"), elements: v("elements"),
    stop_pos: v("stop_pos"), glass_table: v("glass_table"),
    aspheric: $("aspheric").checked,
    imgh: v("imgh"), obj_depth: v("obj_depth"),
    wavelength_min_nm:v("wavelength_min_nm"),wavelength_max_nm:v("wavelength_max_nm"),
    cra_cap: v("cra_cap"),
    distortion_max: v("distortion_max") === "" ? "" : Number(v("distortion_max")) / 100,
    cover_glass: $("cover_glass").checked,
    curriculum_iters: v("curriculum_iters"), refine_iters: v("refine_iters"),
    w_dist: v("w_dist"), scale_pupil: v("scale_pupil"),
    num_ring: v("num_ring"), spp: v("spp"),
    centroid: v("centroid"), device: v("device"), seed: 42, workflow_mode:"direct-v1",analysis_engine:$('analysisEngine').value,
    optim_mat: $("optim_mat").checked, prune:false,native_shape_control:true,
    spec_contract:"v4-explicit-v1",
  };
  for (const k of NUM_FIELDS) {
    if (!(k in p)) p[k] = v(k);
  }
  const route=routeInfo();p.route=$("route").value;p.engine=route.engine;p.refine_engine=route.refine_engine;
  if(route.engine==="optiland") {
    p.device="cpu";
    for(const k of ["scale_pupil","w_ray_bend","w_clearance","w_envelope","w_profile"])delete p[k];
  }
  if(route.engine==="optiland"||route.refine_engine==="optiland"){
    p.aspheric=false;
    for(const k of ["sag2diam_max","diam2thick_max","tmax2tmin_max","surf_angle_max","bend_angle_max"])delete p[k];
  }
  if(route.engine==="optiland"){p.optim_mat=false;p.prune=false;}
  if(route.engine==='optiland'){
    if(window.nativeOptilandReady!==true)throw Error('当前后台未支持Optiland原生参数，请关闭旧版窗口再打开V10.0.0');
    p.optiland_input_version='optiland-native-inputs-v2';for(const key of OPTILAND_FIELDS)p[key]=v(key);
    delete p.spp;delete p.centroid;delete p.scale_pupil;delete p.native_shape_control;
  }
  if(!window.glassUI)throw new Error("玻璃选择模块未加载，请重启工作台后再开始");
  window.glassUI.collect(p);
  if(window.requirementsUI)window.requirementsUI.collect(p);
  if(route.engine==='optiland'&&p.optiland_geometry_mode==='native'){delete p.fixed_stop_z_mm;delete p.fixed_ttl_mm;}
  if(window.designImport)window.designImport.collect(p);
  if(window.resumeReference){p.resume_reference={...window.resumeReference};delete p.design_import_id;delete p.design_import_mode;p.curriculum_iters=Number(window.resumeReference.initial_budget||0);}
  return p;
}

function routeInfo(){
  return {autolens:{engine:"autolens",refine_engine:"autolens"},
    optiland:{engine:"optiland",refine_engine:"optiland"}}[$("route").value];
}
const disabledValues={};
let savedDeviceChoice="auto";
const formCache={};let formRoute=$('route').value;
const commonFormFields=new Set(['image_geometry_pair','foclen','fnum','fov','imgh','elements','stop_pos']);
function rememberEngineForm(route){formCache[route]=Object.fromEntries([...document.querySelectorAll('.parameters input,.parameters select')].filter(e=>e.id&&!commonFormFields.has(e.id)).map(e=>[e.id,e.type==='checkbox'?e.checked:e.value]));}
function switchEngineForm(){
  rememberEngineForm(formRoute);const next=$('route').value,stored=formCache[next];
  if(stored)for(const [id,value] of Object.entries(stored)){const e=$(id);if(e)e.type==='checkbox'?e.checked=value:e.value=value;}
  else if(next==='optiland'){$('cra_cap').value='20';$('w_dist').value='10';preset('std');}
  formRoute=next;configureRoute(false);window.requirementsUI?.summary();
}
function engineDisable(id,disable){
  const el=$(id);if(!el)return;
  if(disable&&!el.disabled&&el.type==="checkbox"){disabledValues[id]=el.checked;el.checked=false;}
  if(!disable&&el.disabled&&el.type==="checkbox"&&id in disabledValues)el.checked=disabledValues[id];
  el.disabled=disable;
  const label=el.closest("label")||el.closest(".chk");
  if(label){label.style.opacity=disable?".45":"";label.title=disable?"当前 Optiland 路线暂不支持此项":"";}
}
function updateStartMode(){
  const resume=!!window.resumeReference||window.designImport?.source?.mode==='resume';
  $("curriculum_iters").disabled=resume;
  if(resume)$("curriculum_iters").value=String(window.resumeReference?.initial_budget||0);
  $("curriculum_iters").title=resume?(Number(window.resumeReference?.initial_budget||0)>0?'保留结构继续当前初始优化阶段，不重新生成镜头':'保留结构，跳过初始优化阶段'):'从技术要求建立结构后的初始优化预算';
  applyResumeLocks();
}
const resumeLockedControls=new Map();
function applyResumeLocks(){
  const locked=!!window.resumeReference&&runParams?.engine==='autolens';
  for(const id of ['elements','stop_pos','aspheric','lens_group_sizes','seed','route','image_geometry_pair','foclen','fov','fnum','bfl','thickness','imgh']){
    const node=$(id);if(!node)continue;
    if(locked){if(!resumeLockedControls.has(id))resumeLockedControls.set(id,{disabled:node.disabled,title:node.title});node.disabled=true;node.title='续算保留原镜头结构和目标；更改请先取消快照来源并新建任务';}
    else if(resumeLockedControls.has(id)){const original=resumeLockedControls.get(id);node.disabled=original.disabled;node.title=original.title;resumeLockedControls.delete(id);}
  }
}
function configureRoute(reset){
  const r=routeInfo(),op=r.engine==="optiland",hasOp=op||r.refine_engine==="optiland";
  $("initialBudgetLabel").textContent=op?"一阶 nfev 预算":"课程学习迭代";
  $("refineBudgetLabel").textContent=op?"像质 nfev 预算":"精调迭代";
  $("ringUsageLabel").textContent="Optiland光瞳采样环数";
  $("sppUsageLabel").textContent=op?"共同评价每视场光线数":"每视场光线数";
  $("engineNote").textContent=op?
    "Optiland：CPU、球面、固定真实玻璃；先一阶/Seidel，再曲率与正厚度的多色点列优化。预算为求解器 nfev，含数值求导时实际追迹次数更多。":
    "AutoLens：直接运行官方课程优化、材料匹配和精调，再分析与导出。";
  for(const id of ["aspheric","sag2diam_max","diam2thick_max","tmax2tmin_max","surf_angle_max","bend_angle_max"])engineDisable(id,hasOp);
  for(const id of ["optim_mat","prune","scale_pupil","w_ray_bend","w_clearance","w_envelope","w_profile"])engineDisable(id,op);
  $("scale_pupil").value="1.05";$("scale_pupil").disabled=true;
  $("scale_pupil").closest("label").title="AutoLens官方课程流程固定1.05；精调沿用原生采样参数";
  if(op&&!$("device").disabled)savedDeviceChoice=$("device").value;
  if(!op&&$("device").disabled)$("device").value=savedDeviceChoice;
  $("device").disabled=op;if(op)$("device").value="cpu";
  if(reset)preset("std");
  updateStartMode();
  applyOfficialMode();
}
function applyOfficialMode(){
  const auto=$('route').value==='autolens';document.body.classList.toggle('official-autolens',auto);
  if(auto){$('field_mode').value='auto';$('fov').disabled=false;$('imgh').disabled=false;}
  const allowed=new Set(['image_geometry_pair','foclen','fnum','fov','bfl','thickness','imgh','elements','stop_pos','curriculum_iters','refine_iters','device','cra_cap']);
  $('cra_cap').disabled=auto&&window.nativeCraReady!==true;
  $('cra_cap').placeholder=auto?(window.nativeCraReady===true?'留空=原生默认（软约束）':'重开V10.0.0后启用'):'默认20°';$('cra_cap').min='0';$('cra_cap').max=auto?'89.9':'89';
  for(const label of document.querySelectorAll('.parameters label,.parameters .chk')){
    const controls=[...label.querySelectorAll('input,select')];
    label.classList.toggle('official-hidden',auto&&controls.length>0&&!controls.some(e=>allowed.has(e.id)));
  }
  for(const detail of document.querySelectorAll('.parameters details'))detail.classList.toggle('official-hidden',auto&&![...detail.querySelectorAll('input,select')].some(e=>allowed.has(e.id)));
  const lengthLabel=$('thickness').closest('label');if(lengthLabel?.firstChild?.nodeType===3)lengthLabel.firstChild.textContent=auto?'初始总长 (mm)':'总长上限 TTL (mm)';
  for(const o of $('device').options)o.disabled=auto&&o.value==='cpu';if(auto&&$('device').value==='cpu')$('device').value='auto';
  $('spectrumHint').hidden=auto;$('fieldSummary').hidden=auto;$('imageGeometryHint').hidden=true;$('workflowModeHint').hidden=true;
  $('engineNote').textContent=auto?'原生流程 · 课程512 / 精调1024光线 · CRA为原生软约束':'';
  const hiddenOpti=['spp','centroid','optim_mat','prune','aspheric','scale_pupil','w_ray_bend','w_clearance','w_envelope','w_profile','sag2diam_max','diam2thick_max','tmax2tmin_max','surf_angle_max','bend_angle_max'];
  for(const id of hiddenOpti){const e=$(id),label=e.closest('label')||e.closest('.chk');label?.classList.toggle('official-hidden',!auto||!allowed.has(id));}
  for(const e of document.querySelectorAll('.optiland-only'))e.hidden=auto;
  document.querySelector('.wavelength-range').hidden=auto;
  const compat=$('optiland_geometry_mode').value==='v7_compat';
  for(const id of ['fixed_stop_z_mm','fixed_ttl_mm'])$(id).closest('label').hidden=!auto&&!compat;
  $('optilandGlassHint').hidden=auto||$('optiland_glass_mode').value!=='expert';
  $('optiland_glass_neighbours').disabled=$('optiland_glass_mode').value!=='expert';
  $('optiland_solver').disabled=!auto&&$('optiland_glass_mode').value==='expert';
  $('optiland_x_scale').disabled=!auto&&$('optiland_glass_mode').value==='expert';
  if(!auto)$('refineBudgetLabel').textContent=$('optiland_glass_mode').value==='expert'?'每次换玻璃局部迭代上限':'像质 nfev 预算';
  const weightLabel=$('w_dist').closest('label');if(weightLabel.firstChild.nodeType===3)weightLabel.firstChild.textContent=auto?'畸变损失权重':'畸变约束权重';
  $('w_dist').disabled=auto;
  applyResumeLocks();
}
window.applyOfficialMode=applyOfficialMode;
$("route").addEventListener("change",switchEngineForm);
for(const id of ['optiland_geometry_mode','optiland_glass_mode'])$(id).addEventListener('change',applyOfficialMode);
if(formRoute==='autolens')$('cra_cap').value='';
configureRoute(false);

function preset(mode){
  const m = (routeInfo().engine==="optiland"?{
    fast:{curriculum_iters:10,refine_iters:10},
    std:{curriculum_iters:60,refine_iters:120},
    deep:{curriculum_iters:200,refine_iters:400}
  }:{
    fast: {curriculum_iters: 150, refine_iters: 80},
    std:  {curriculum_iters: 2000, refine_iters: 3000},
    deep: {curriculum_iters: 4000, refine_iters: 6000},
  })[mode];
  $("curriculum_iters").value = m.curriculum_iters;
  $("refine_iters").value = m.refine_iters;
  updateStartMode();
  document.querySelectorAll(".presets button").forEach(b =>
    b.classList.toggle("active", b.textContent.includes(
      {fast: "快速", std: "标准", deep: "充分"}[mode])));
}

async function start(){
  if(startPending)return;
  startPending=true;$("btnStart").disabled=true;
  const label=$("btnStart").innerHTML;let launched=false;$("btnStart").textContent="正在校核并启动…";
  try{
  $("errBox").style.display = "none";
  $("errBox").textContent = "";
  const params=collectParams();
  if(params.resume_reference?.phase==='curriculum'||params.resume_reference?.course_restart){
    if(!await confirmCourseRestart()){$('footerStatus').textContent='已取消课程重启，未启动优化。';return false;}
    params.resume_acknowledge_course_restart=true;
  }
  const r = await fetch("/api/start", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(params)});
  const j = await r.json();
  if (!r.ok)throw new Error(j.error || `请求失败 ${r.status}`);
  launched=true;
  onNewRun(j.run_id);
  $("footerStatus").textContent="已启动新任务 · "+j.run_id;
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(poll, 1500); poll();
  }catch(e){
    $("errBox").textContent="启动失败："+e.message;$("errBox").style.display="block";
    $("errBox").scrollIntoView({block:"nearest"});$("footerStatus").textContent="未启动新任务，请按提示修改参数后重试。";
  }finally{
    startPending=false;$("btnStart").innerHTML=label;
    $("btnStart").disabled=launched||!!(typeof activeJob!=="undefined"&&activeJob?.running);
    poll();
  }
}

async function stop(){const r=await fetch('/api/stop',{method:'POST'}),d=await r.json();if(!r.ok)throw Error(d.error||'停止请求失败');return d;}

function drawChart(hist){
  const cv = $("chart"), ctx = cv.getContext("2d");
  const W = cv.width, H = cv.height, pad = 10;
  ctx.clearRect(0, 0, W, H);
  if (!hist || hist.length < 2) return;
  const rms = hist.map(h => h.loss_rms);
  const reg = hist.map(h => h.loss_reg == null ? null : h.loss_reg * 10);
  if (!rms.length) return;
  const all = rms.concat(reg).filter(v => v != null && Number.isFinite(v));
  if (!all.length) return;
  let lo = Math.min(...all), hi = Math.max(...all);
  if (hi - lo < 1e-9){ hi = lo + 1; }
  const X = i => pad + (W - 2 * pad) * i / (hist.length - 1);
  const Y = v => H - pad - (H - 2 * pad) * (v - lo) / (hi - lo);
  ctx.strokeStyle = "#e0e5ee"; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(0, Y(0)); ctx.lineTo(W, Y(0)); ctx.stroke();
  const line = (vals, color) => {
    ctx.strokeStyle = color; ctx.lineWidth = 1.8; ctx.beginPath();
    let penDown=false;
    vals.forEach((v, i) => { const x = X(i), y = Y(v);
      if(!Number.isFinite(v)){penDown=false;return;}
      penDown ? ctx.lineTo(x, y) : ctx.moveTo(x, y);penDown=true; });
    ctx.stroke();
  };
  line(rms, "#007aff"); line(reg, "#bf8a2d");
  ctx.fillStyle = "#7c899c"; ctx.font = "10px -apple-system,sans-serif";
  ctx.fillText("max " + hi.toExponential(2), 6, 14);
  ctx.fillText("min " + lo.toExponential(2), 6, H - 5);
}

function metricTargets(p){
  const raw=p.params||{},target=p.target||{},number=v=>v!==null&&v!==''&&v!==undefined&&Number.isFinite(Number(v))?Number(v):null;
  return {...target,efl_mm:number(target.efl_mm??raw.foclen),full_fov_deg:number(target.full_fov_deg??raw.fov),fnum:number(target.fnum??raw.fnum),
    cra_cap_deg:number(target.cra_cap_deg??raw.cra_cap),distortion_max_pct:number(target.distortion_max_pct??raw.distortion_max)};
}
function targetDeviation(target,value,decimals=2,unit=''){
  if(!Number.isFinite(target))return '目标 —';
  const delta=Number.isFinite(value)&&Math.abs(target)>1e-12?100*(value-target)/Math.abs(target):null;
  return '目标 '+fmt(target,decimals)+unit+(delta===null?'':` · 偏差 ${delta>=0?'+':''}${delta.toFixed(2)}%`);
}
function showMetrics(p){
  const t = metricTargets(p), m0 = p.metrics_initial || {};
  setText("t_efl", fmt(t.efl_mm, 2)); setText("t_fov", fmt(t.full_fov_deg, 1));
  setText("t_fnum", fmt(t.fnum, 1));
  setText("t_cra", t.cra_cap_deg != null ? "≤ " + fmt(t.cra_cap_deg, 1) : "—");
  setText("t_dist", t.distortion_max_pct != null
    ? "≤ " + fmt(t.distortion_max_pct * 100, 1) : "—");
  setText("m0_efl", fmt(m0.efl_mm, 2));
  setText("m0_fov", fmt(m0.full_fov_deg, 1));
  setText("m0_fnum", fmt(m0.fnum, 1));
  setText("m0_rms", fmt(m0.rms_spot_mm, 4));
  setText("m0_cra", fmt(m0.cra_max_deg, 2));
  setText("m0_dist", fmt(m0.distortion_max_pct, 2));
  setText("m0_val", fmt(m0.valid_fraction, 3));
  const cur = displayedMetrics(p);
  setText("m_efl", fmt(cur.efl_mm, 2));
  setText("m_fov", fmt(cur.full_fov_deg, 1));
  setText("m_fnum", fmt(cur.fnum, 1));
  setText("m_rms", fmt(cur.rms_spot_mm, 4));
  setText("m_cra", fmt(cur.cra_max_deg, 2));
  setText("m_dist", fmt(cur.distortion_max_pct, 2));
  setText("m_val", fmt(cur.valid_fraction, 3));
  setText("m0_vmin", fmt(m0.valid_fraction_min,3));
  setText("m_vmin", fmt(cur.valid_fraction_min,3));
  const input=p.params||{},constraints=p.constraints||{};
  for(const [key,unit] of [["bfl","bfl_mm"],["ttl","track_mm"]]){
    const lo=input[key+"_min"]??constraints[key+"_min"],hi=input[key+"_max"]??constraints[key+"_max"];
    setText("t_"+key,lo!=null||hi!=null?`${lo==null?"—":fmt(Number(lo),3)} ~ ${hi==null?"—":fmt(Number(hi),3)}`:"未显式限定");
    setText("m0_"+key,fmt(m0[unit],3));setText("m_"+key,fmt(cur[unit],3));
    if(Number.isFinite(cur[unit])&&(lo!=null||hi!=null))$("m_"+key).className=(lo==null||cur[unit]>=Number(lo))&&(hi==null||cur[unit]<=Number(hi))?"good":"bad";
  }
  if(Number.isFinite(cur.valid_fraction_min))$("m_vmin").className=cur.valid_fraction_min>=.95?"good":"bad";
  const ok = (a, b, tol) => Number.isFinite(a) && Number.isFinite(b)
    && Math.abs(a - b) <= tol * Math.max(Math.abs(b), 1e-9);
  if (cur.efl_mm !== undefined && cur.efl_mm !== null && isFinite(cur.efl_mm)){
    $("m_efl").className = ok(cur.efl_mm, t.efl_mm, 0.05) ? "good" : "bad";
    $("m_fov").className = ok(cur.full_fov_deg, t.full_fov_deg, 0.05) ? "good" : "bad";
  }
  if(Number.isFinite(cur.fnum))$("m_fnum").className=ok(cur.fnum,t.fnum,.05)?"good":"bad";
  if (Number.isFinite(cur.cra_max_deg) && t.cra_cap_deg != null){
    $("m_cra").className = cur.cra_max_deg <= t.cra_cap_deg ? "good" : "bad";
  }
  if (Number.isFinite(cur.distortion_max_pct) && t.distortion_max_pct != null){
    $("m_dist").className =
      cur.distortion_max_pct <= t.distortion_max_pct * 100 ? "good" : "bad";
  }
  // stat cards
  $("statEfl").textContent = fmt(cur.efl_mm, 2);
  $("statEflSub").textContent = targetDeviation(t.efl_mm,cur.efl_mm,2,' mm');
  $("statFov").textContent = Number.isFinite(cur.full_fov_deg)
    ? fmt(cur.full_fov_deg, 1) + "°" : "—";
  $("statFovSub").textContent = targetDeviation(t.full_fov_deg,cur.full_fov_deg,1,'°');
  $("statRms").textContent = Number.isFinite(cur.rms_spot_mm)
    ? fmt(cur.rms_spot_mm, 4) : "—";
  const waveCount=cur.wavelengths_um?.length||p.wvln_ls?.length||p.params?.spectrum?.wavelengths_um?.length||(p.params?.wvln_g!=null?3:null);
  const measuredFields=cur.design_field_count||p.params?.requirements?.fields?.length||p.params?.field_count;
  const mode=cur.rms_definition?.includes('polychromatic')?'多色共同质心':'各波长独立质心';
  $("statRmsSub").textContent=waveCount?`${mode} · ${measuredFields??"保存的"}视场 × ${waveCount}波长`:"保存记录的采样";
}

function displayedMetrics(p){
  const scene=typeof currentScene!=='undefined'?currentScene:null;
  if(scene&&scene.run_id===currentLens){
    const metrics=scene.saved_metrics;
    if(metrics?.source_file===scene.source&&metrics.source_sha256===scene.source_sha256)return metrics;
  }
  return {};
}

