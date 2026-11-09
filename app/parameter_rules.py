"""Joint parameter checks and explicit engineering limits for new UI jobs.

Legacy jobs without spec_contract retain their numerical default behaviour;
all jobs still receive basic type, ordering and feasibility checks.
"""
import math

CONTRACT="v4-explicit-v1"
PAIRS=(("bfl_min","bfl_max"),("ttl_min","ttl_max"),
       ("air_edge_min","air_edge_max"),("air_center_min","air_center_max"),
       ("thick_edge_min","thick_edge_max"),("thick_center_min","thick_center_max"))


def check_and_resolve(p):
    def value(key,default=None):
        raw=p.get(key)
        if raw in (None,""):return default
        if isinstance(raw,bool):raise ValueError(key+" 需为数值，不能是布尔值")
        val=float(raw)
        if not math.isfinite(val):raise ValueError(key+" 必须是有限数值")
        return val
    try:
        if p.get('analysis_engine','optiland') not in ('autolens','optiland'):raise ValueError('未知分析内核')
        from design_requirements import enabled,prepare_fields,compile_requirements
        prepare_fields(p)
        for key in ("aspheric","cover_glass","optim_mat","prune","by_imgh","object_at_infinity"):
            if key not in p:continue
            raw=p[key]
            if raw in (None,""):p[key]=False
            elif isinstance(raw,bool):pass
            elif str(raw).lower() in ("true","1"):p[key]=True
            elif str(raw).lower() in ("false","0"):p[key]=False
            else:raise ValueError(key+" 需为开/关布尔值")
        for key in ("elements","curriculum_iters","refine_iters","num_ring","spp"):
            if p.get(key) in (None,""):continue
            v=value(key)
            if not v.is_integer():raise ValueError(key+" 需为整数，不能自动截断小数")
            p[key]=int(v)
        if enabled(p) and p.get('cover_glass'):
            p['bfl']=float(p.get('cover_gap_mm') or .3)
        if enabled(p) and p.get('thickness') in (None,'') and value('fixed_ttl_mm') is not None:
            p['thickness']=value('fixed_ttl_mm')
        n=int(p.get("elements",4))
        stop=p.get("stop_pos","middle")
        if stop not in ("front","middle","back"):
            k=value("stop_pos")
            if k is None or not k.is_integer() or not 0<=k<=n:
                raise ValueError("光阑位置必须是第0~"+str(n)+"片后")
            p["stop_pos"]=int(k)
        for lo,hi in PAIRS:
            a,b=value(lo),value(hi)
            if a is not None and b is not None and not a<b:
                raise ValueError(lo+" 必须小于 "+hi+"（当前不支持用相等边界固定变量）")
        focal,fov,bfl=value("foclen"),value("fov"),value("bfl")
        length=value("thickness")
        if length is not None and bfl is not None and length<=bfl:
            raise ValueError("总长必须大于初始后截距，需为镜片和间隔留空间")
        if value("bfl_min") is not None and value("ttl_max") is not None and value("bfl_min")>=value("ttl_max"):
            raise ValueError("BFL下限必须小于TTL上限")
        for key in ("bfl_min","bfl_max"):
            bound=value(key)
            if bound is not None and bfl is not None and (bfl<bound if key.endswith("min") else bfl>bound):
                raise ValueError("初始BFL与 "+key+" 冲突，请调整初始值或边界")
        interior=stop=="middle" or isinstance(p.get("stop_pos"),int) and 0<p["stop_pos"]<n
        uses_auto=p.get("engine","autolens")=="autolens" or p.get("refine_engine")=="autolens"
        if interior and uses_auto and value("air_center_max") is not None and value("air_center_max")<.1:
            raise ValueError("AutoLens中间独立光阑需在两侧各留至少0.1mm中心空气间隔")
        from spectrum import resolve_spectrum
        p["spectrum"]=resolve_spectrum(p)
        contract=p.get("spec_contract")
        if contract not in (None,"",CONTRACT):raise ValueError("参数约定版本不受支持")
        if contract==CONTRACT:
            if focal is None or fov is None or bfl is None:raise ValueError("请填写焦距、全视场和初始BFL")
            h=value("imgh")
            if h is not None and 0<fov<180 and not (enabled(p) and p.get('field_mode')=='manual'):
                derived=focal*math.tan(math.radians(fov/2))
                if p.get("by_imgh"):
                    focal=h/math.tan(math.radians(fov/2));p["foclen"]=focal
                elif abs(h-derived)>max(.02,.001*abs(derived)):
                    raise ValueError("焦距、像高和全视场不一致：像高≈焦距×tan(全视场/2)，三者不可独立指定")
            cap=length if length is not None else focal+bfl
            cap=min(cap,value("ttl_max",cap))
            p["effective_total_length_cap_mm"]=cap
            p["seed_total_length_mm"]=cap
            defaults={"ttl_min":.1,"ttl_max":cap,"bfl_min":.05,"bfl_max":min(500.,cap),
                      "air_center_min":.1,"air_center_max":min(200.,cap),
                      "air_edge_min":.05,"air_edge_max":min(200.,cap),
                      "thick_center_min":.4,"thick_center_max":min(200.,cap),
                      "thick_edge_min":.4,"thick_edge_max":min(200.,cap),
                      "cra_cap":20.,"distortion_max":.03}
            for key,default in defaults.items():
                if p.get(key) in (None,""):p[key]=default
            p["ttl_max"]=cap
            for lo,hi in PAIRS:
                if not value(lo)<value(hi):raise ValueError(lo+" 与实际 "+hi+" 冲突")
            if not value("bfl_min")<=bfl<=value("bfl_max") or bfl>=cap:
                raise ValueError("初始BFL不在有效边界内，或没有给镜片留下总长空间")
            minimum=n*value("thick_center_min")+n*value("air_center_min")+value("bfl_min")
            if minimum>=cap:raise ValueError("镜片数、最小中心厚度/间隔和BFL下限之和已达到或超过总长上限")
        if p.get('engine')=='optiland':
            from optiland_native_inputs import normalize
            normalize(p)
        if enabled(p):
            requirement=compile_requirements(p)
            if p.get('requirements') and p['requirements']!=requirement:
                raise ValueError('统一设计条件与保存的参数不一致，拒绝静默更改')
            p['requirements']=requirement
        return None
    except (ValueError,TypeError,OverflowError) as exc:
        return str(exc) if str(exc) else "参数格式非法"
