"""Read-only target comparisons; never alter optimization or invent tolerances."""
import math

def compare(params,metrics,source_file=None,source_sha256=None):
    p=params or {};m=metrics or {};rows=[]
    def number(value):
        try:value=float(value)
        except (TypeError,ValueError):return None
        return value if math.isfinite(value) else None
    cfg=p.get('autolens_config') or p
    for key,label,target_key,unit in [('efl_mm','焦距','foclen','mm'),('fnum','F数','fnum',''),('full_fov_deg','近轴推算全视场','fov','°')]:
        target=number(cfg.get(target_key));actual=number(m.get(key))
        rows.append(dict(key=key,label=label,target=target,measured=actual,unit=unit,
            relative_error_pct=(actual-target)/abs(target)*100 if actual is not None and target not in (None,0) else None,
            status='deviation_only' if actual is not None and target is not None else 'unavailable',
            note='未设置验收容差，仅显示偏差；不改变优化目标'))
    for key,label,param,factor,unit in [('cra_max_deg','CRA上限','cra_cap',1,'°'),('distortion_max_pct','畸变上限','distortion_max',100,'%')]:
        limit=number(p.get(param));actual=number(m.get(key))
        if limit is not None:
            limit*=factor
            rows.append(dict(key=key,label=label,target=limit,measured=actual,unit=unit,status='unavailable' if actual is None else 'within_limit' if actual<=limit else 'outside_limit'))
    for key,label,prefix in [('bfl_mm','后截距','bfl'),('track_mm','总长','ttl')]:
        actual=number(m.get(key));low=number(p.get(prefix+'_min'));high=number(p.get(prefix+'_max'))
        if low is not None or high is not None:
            ok=actual is not None and (low is None or actual>=low) and (high is None or actual<=high)
            rows.append(dict(key=key,label=label,min=low,max=high,measured=actual,unit='mm',status='unavailable' if actual is None else 'within_limit' if ok else 'outside_limit'))
    return dict(source_file=source_file,source_sha256=source_sha256,all_passed=None,rows=rows,
        bound_failures=sum(r['status']=='outside_limit' for r in rows),scope='独立结果对照；未设容差的目标不判定通过；不代表完整光学验收')
