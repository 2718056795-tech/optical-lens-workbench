"""One basic screening definition shared by single runs and multi-seed ranking."""
import math

def number(p, key, default):
    return float(p[key]) if p.get(key) not in (None, "") else default


def rank_metrics(metrics, params):
    """Screening policy v1; eligibility is not full optical acceptance."""
    m = metrics or {}
    required = ("efl_mm", "fnum", "rms_spot_mm", "valid_fraction_min", "distortion_max_pct")
    if any(not isinstance(m.get(k), (int, float)) or not math.isfinite(m[k]) for k in required):
        return {"score": None, "eligible": False, "reasons": ["缺少有限的完整评价指标"]}
    target = number(params, "foclen", 20)
    if params.get("by_imgh") in (True, "1", "true"):
        target = float(params["imgh"]) / math.tan(math.radians(float(params["fov"])/2))
    efl_err = abs(m["efl_mm"]/target-1)*100
    fno_err = abs(m["fnum"]/float(params["fnum"])-1)*100
    valid = m["valid_fraction_min"]
    reasons = []
    if m["efl_mm"] <= 0 or efl_err > 5:
        reasons.append("焦距偏差>5%或非正焦距")
    if fno_err > 5:
        reasons.append("F数偏差>5%")
    if not 0.95 <= valid <= 1:
        reasons.append("最差视场/波长有效率<95%")
    if m["rms_spot_mm"] < 0 or m["distortion_max_pct"] < 0:
        return {"score": None, "eligible": False, "reasons": ["评价指标非法"]}
    dist_scale = number(params, "distortion_max", 0.05)*100
    if params.get("distortion_max") not in (None, "") and m["distortion_max_pct"] > dist_scale:
        reasons.append("超出畸变上限")
    for key, lo, hi in (("track_mm", "ttl_min", "ttl_max"), ("bfl_mm", "bfl_min", "bfl_max")):
        for bound, lower in ((lo, True), (hi, False)):
            if params.get(bound) not in (None, ""):
                value = m.get(key)
                if value is None or not math.isfinite(value) or (value < float(params[bound]) if lower else value > float(params[bound])):
                    reasons.append("未通过 " + bound)
    score = efl_err/5 + fno_err/5 + m["rms_spot_mm"]/0.05 + m["distortion_max_pct"]/dist_scale + max(0, 1-valid)/0.02
    if params.get("cra_cap") not in (None, ""):
        cra = m.get("cra_max_deg")
        if cra is None or not math.isfinite(cra):
            return {"score": None, "eligible": False, "reasons": ["CRA 缺失"]}
        score += cra/float(params["cra_cap"])
        if cra > float(params["cra_cap"]):
            reasons.append("超出CRA上限")
    return {"score": score, "eligible": not reasons, "reasons": reasons,
            "efl_error_pct": efl_err, "fnum_error_pct": fno_err}

