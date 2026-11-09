"""Shared engine routing and explicit capability checks."""
ENGINES = {"autolens": "optimizer_runner.py", "optiland": "optiland_runner.py"}
ROUTES = {"autolens": ("autolens", "autolens"), "optiland": ("optiland", "optiland")}
OP_ONLY_AUTOLENS = ("sag2diam_max", "diam2thick_max", "tmax2tmin_max", "surf_angle_max", "bend_angle_max")
AUTO_CONTROLS = ("scale_pupil", "w_ray_bend", "w_clearance", "w_envelope", "w_profile")

def worker_for(params):
    return ENGINES[params.get("engine", "autolens")]

def apply_route(params):
    chosen=params.get('route') or params.get('engine','autolens')
    if chosen not in ROUTES:return 'V7仅支持全程AutoLens或全程Optiland，已取消混合路线'
    params.update(route=chosen,engine=chosen,refine_engine=chosen)
    return None


def engine_error(params, engine=None):
    engine = engine or params.get("engine", "autolens")
    if engine not in ENGINES:
        return "优化内核需选择 AutoLens 或 Optiland"
    if params.get("refine_engine", "autolens") not in ENGINES:
        return "精修内核非法"
    if engine == "optiland":
        if params.get("device") == "cuda":
            return "Optiland 优化此版本使用 CPU，请选择 CPU 或自动"
        if params.get("glass_table","CDGM") not in ("CDGM","SCHOTT"):
            return "Optiland 固定材料初始化当前支持 CDGM/SCHOTT"
        for key in ("aspheric", "optim_mat", "prune", "cover_glass"):
            if key=='cover_glass' and params.get('requirements'):continue
            if params.get(key) in (True, "1", "true"):
                return "Optiland 当前支持球面、固定真实玻璃；请关闭 " + key
        for key in OP_ONLY_AUTOLENS:
            if params.get(key) not in (None, ""):
                return "Optiland 当前不支持此约束：" + key
    return None
