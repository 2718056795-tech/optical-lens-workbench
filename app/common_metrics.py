"""Common non-mutating optical measurement for both optimization engines."""
import math
import numpy as np
import torch

def evaluate(lens, fov, obj_depth, wvln_list, wvln_primary, spp):
    device = torch.device(lens.device)
    target_image_error=None
    def sample_explicit(f,w,count,scale=1.):
        if getattr(lens,'design_requirements',{}).get('object_at_infinity'):
            return lens.sample_from_fov(fov_x=f['x'],fov_y=f['y'],depth=float('inf'),num_rays=count,wvln=w,scale_pupil=scale)
        return lens.sample_from_points([[f['object_x_mm'],f['object_y_mm'],f['object_z_mm']]],num_rays=count,wvln=w,scale_pupil=scale)
    def paraxial_efl(wvln):
        """非破坏性近轴 EFL（ABCD 矩阵）。

        引擎的 calc_foclen_paraxial() 会把计算结果写回 self.foclen，
        覆盖 set_target_fov_fnum 设定的设计目标值，导致后续采样
        （sample_ring_arm_rays 等按 self.foclen 布置物方环）全部错位。
        此处复制其 ABCD 计算但只读不写。
        """
        def f(v, d=0.0):
            if v is None:
                return d
            if hasattr(v, "item"):
                return float(v.item())
            return float(v)

        surfaces = list(lens.surfaces)
        if len(surfaces) < 2:
            return float("nan")
        A, B, C, D = 1.0, 0.0, 0.0, 1.0
        n_prev = 1.0
        for i, surf in enumerate(surfaces):
            n_i = float(surf.mat2.refractive_index(wvln))
            P = (n_i - n_prev) * (f(getattr(surf, "c", None))
                                  + 2.0 * f(getattr(surf, "ai2", None)))
            C, D = -P * A + C, -P * B + D
            if i < len(surfaces) - 1:
                t = f(surfaces[i + 1].d) - f(surf.d)
                tr = t / n_i if n_i != 0.0 else 0.0
                A, B = A + tr * C, B + tr * D
            n_prev = n_i
        return -1.0 / C if C != 0 else float("nan")

    def _chief_ray(field_deg):
        """追主光线（光瞳趋零的中心光线），返回落点 (x, y) 或 None。"""
        ray = lens.sample_from_fov(
            fov_x=0.0, fov_y=field_deg, depth=float(obj_depth),
            num_rays=1, wvln=float(wvln_primary), scale_pupil=1e-6)
        out = lens.trace2sensor(ray)
        if not bool(out.is_valid.reshape(-1)[0]):
            return None
        o = out.o.reshape(-1, 3)[0]
        return float(o[0]), float(o[1])

    def measure_cra():
        """各视场主光线与像面法线夹角（度，max/mean）——主光线口径。"""
        with torch.no_grad():
            angles = []
            fields=getattr(lens,'design_fields',None)
            if fields:
                for f in fields:
                    ray=sample_explicit(f,float(wvln_primary),1,1e-6)
                    out=lens.trace2sensor(ray)
                    if not bool(out.is_valid.reshape(-1)[0]):return None,None
                    angles.append(math.degrees(math.acos(float(out.d.reshape(-1,3)[0,2].clamp(-1.,1.)))))
                return max(angles),sum(angles)/len(angles)
            fractions=[math.atan2(abs(f['object_y_mm']),abs(f['object_z_mm']))/math.radians(fov/2) for f in fields] if fields else (0.3,0.5,0.7,0.85,1.)
            for frac in fractions:
                th = math.degrees(math.radians(fov / 2.0) * frac)
                ray = lens.sample_from_fov(
                    fov_x=0.0, fov_y=th, depth=float(obj_depth),
                    num_rays=1, wvln=float(wvln_primary),
                    scale_pupil=1e-6)
                out = lens.trace2sensor(ray)
                if not bool(out.is_valid.reshape(-1)[0]):
                    return None, None
                d = out.d.reshape(-1, 3)[0]
                cos_a = float(d[2].clamp(-1.0, 1.0))
                angles.append(math.degrees(math.acos(cos_a)))
            if not angles:
                return None, None
            return max(angles), sum(angles) / len(angles)

    def measure_distortion():
        nonlocal target_image_error
        """主光线 f-tan 畸变（商业口径，与 Optiland 对齐，%）。

        参考理想像高 = 近轴主光线板比例 × tan(θ)；
        畸变 = |y_主光线 - y_理想| / y_理想，取 0.3~1.0 视场最大。
        """
        with torch.no_grad():
            fields=getattr(lens,'design_fields',None)
            if fields:
                req=getattr(lens,'design_requirements',{});angle=1e-3
                near=lens.sample_from_fov(fov_x=0.,fov_y=angle,depth=float('inf') if req.get('object_at_infinity') else float(obj_depth),num_rays=1,wvln=float(wvln_primary),scale_pupil=1e-6)
                traced=lens.trace2sensor(near)
                if not bool(traced.is_valid.reshape(-1)[0]):return None
                plate=float(traced.o.reshape(-1,3)[0,:2].norm())/math.tan(math.radians(angle))
                if not math.isfinite(plate) or plate<=0:return None
                worst=0.;target_image_error=0.
                for f in fields:
                    ideal=np.array([f['target_x_mm'],f['target_y_mm']]);height=float(np.linalg.norm(ideal))
                    ray=sample_explicit(f,float(wvln_primary),1,1e-6)
                    out=lens.trace2sensor(ray)
                    if not bool(out.is_valid.reshape(-1)[0]):return None
                    actual=out.o.reshape(-1,3)[0,:2].cpu().numpy()
                    if height>1e-9:target_image_error=max(target_image_error,float(np.linalg.norm(actual-ideal))/height*100)
                    tangent=math.hypot(math.tan(math.radians(f['x'])),math.tan(math.radians(f['y']))) if req.get('object_at_infinity') else math.hypot(f['object_x_mm'],f['object_y_mm'])/req['object_distance_mm']
                    first_order=plate*tangent
                    if first_order>1e-9:worst=max(worst,abs(float(np.linalg.norm(actual))/first_order-1))
                return worst*100
            th_max = math.radians(fov / 2.0)
            # 近轴板比例：超小视场主光线
            p_near = _chief_ray(math.degrees(th_max * 1e-3))
            if p_near is None:
                return None
            scale = math.hypot(*p_near) / math.tan(th_max * 1e-3)
            if scale <= 0:
                return None
            worst = 0.0
            fields=getattr(lens,'design_fields',None)
            fractions=[math.atan2(abs(f['object_y_mm']),abs(f['object_z_mm']))/th_max for f in fields] if fields else (0.3,0.5,0.7,0.85,1.)
            for frac in fractions:
                th = th_max * frac
                p = _chief_ray(math.degrees(th))
                if p is None:
                    return None
                y_real = math.hypot(*p)
                y_ideal = scale * math.tan(th)
                if y_ideal > 1e-9:
                    worst = max(worst, abs(y_real - y_ideal) / y_ideal)
            return float(worst * 100.0)

    def metrics():
        # Fixed common sampling; evaluation must not consume training RNG.
        with torch.random.fork_rng(devices=[device.index or 0] if device.type == "cuda" else []), torch.no_grad():
            torch.manual_seed(20261101)
            # 注意：不能用 lens.calc_foclen_paraxial()，它会写回
            # self.foclen，破坏设计目标（见 paraxial_efl 注释）。
            efl = paraxial_efl(float(wvln_primary))
            try:
                # Geometry can change between post_computation calls. Do not use
                # the cached pupil radius for an intermediate measurement.
                from spectrum import primary_ray_context
                with primary_ray_context(wvln_primary):
                    _, pupil_radius = lens.calc_entrance_pupil(paraxial=False)
                epd = 2*float(pupil_radius)
                fno = efl/epd if efl>0 and math.isfinite(epd) and epd>0 else None
            except (ValueError,TypeError):
                epd,fno = None,None
            r_sensor = float(lens.r_sensor)
            fov_meas = math.degrees(2.0 * math.atan2(r_sensor, efl)) \
                if efl > 0 else None
            rms_vals,valid_vals,rms_weights,field_results=[],[],[],[]
            explicit=getattr(lens,'design_fields',None)
            req=getattr(lens,'design_requirements',None)
            weights=req['spectrum']['weights'] if req else [1/len(wvln_list)]*len(wvln_list)
            for wi,w in enumerate(wvln_list):
                for frac in (range(len(explicit)) if explicit else (0.0, 0.7, 1.0)):
                    field = (fov / 2.0) * frac
                    rays = sample_explicit(explicit[frac],w,max(spp,32)) if explicit else lens.sample_from_fov(
                        fov_x=0.0, fov_y=field, depth=float(obj_depth),
                        num_rays=max(spp, 32), wvln=w, scale_pupil=1.0)
                    t = lens.trace2sensor(rays)
                    valid = t.is_valid.bool() & torch.isfinite(t.o).all(dim=-1)
                    valid_vals.append(float(valid.float().mean()))
                    xy = t.o[..., :2][valid]
                    if xy.shape[0] >= 2:
                        value=float(((xy-xy.mean(0)).square().sum(-1).mean()).sqrt())
                        rms_vals.append(value);rms_weights.append(weights[wi]*(explicit[frac]['weight'] if explicit else 1.))
                    else:value=None
                    if explicit:field_results.append(dict(field_index=frac+1,wavelength_um=w,weight=explicit[frac]['weight']*weights[wi],rms_mm=value,valid_fraction=valid_vals[-1]))
            rms = sum(v*w for v,w in zip(rms_vals,rms_weights))/sum(rms_weights) if rms_vals and sum(rms_weights)>0 else None
            cra_max, cra_mean = measure_cra()
            dist = None
            try:
                dist = measure_distortion()
            except Exception:
                pass
            return {
                "efl_mm": efl, "full_fov_deg": fov_meas,
                "fnum": fno,
                "fnum_recorded": float(lens.fnum),
                "entrance_pupil_diameter_mm": epd,
                "rms_spot_mm": rms,
                "valid_fraction": sum(valid_vals) / len(valid_vals),
                "valid_fraction_min": min(valid_vals),
                "bfl_mm": float(lens.d_sensor-lens.surfaces[-1].d),
                "evaluation_protocol": "v5-explicit-fields-v1: complete saved fields; finite/infinite object; configured field/spectral weights; fixed RNG; weighted mono centroid RMS" if explicit else "v4-screen-v3: degrees; design fields 0/.7/1; configured depth; fixed RNG; primary-wavelength pupil; mean centroid RMS over configured spectral samples",
                "full_fov_definition": "2*atan(sensor_radius/paraxial_efl); inferred, not a traced clear field",
                "rms_definition": f"Weighted mean of per-wavelength centroid RMS over {len(explicit) if explicit else 3} design fields x {len(wvln_list)} wavelengths, not a pooled polychromatic RMS",
                "design_field_count":len(explicit) if explicit else 3,
                "field_results":field_results,
                "target_image_error_max_pct":target_image_error,
                "distortion_definition":"paraxial f-tan chief-ray distortion; target image error recorded separately",
                "wavelengths_um":list(wvln_list),"primary_wavelength_um":float(wvln_primary),
                "rms_samples_available": len(rms_vals),
                "track_mm": float(lens.d_sensor-lens.surfaces[0].d),
                "cra_max_deg": cra_max, "cra_mean_deg": cra_mean,
                "distortion_max_pct": dist,
            }

    return metrics()
