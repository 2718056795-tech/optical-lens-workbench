"""Read canonical prescriptions for the workbench. No ray tracing or optimization.

Profiles are in millimetres and use the source engine's sag equation. Invalid
conic domains are reported rather than clipped into a different lens shape.
"""
import json
import math
from pathlib import Path


def finite(value, default=None):
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except (ValueError, TypeError):
        return default


def sag(surface, radius):
    roc = finite(surface.get("roc"))
    c = 1 / roc if roc else 0.0
    k = finite(surface.get("k"), 0) if surface["type"] == "Aspheric" else 0
    domain = 1 - (1 + k) * c * c * radius * radius
    if domain < -1e-10:
        return None
    value = c * radius * radius / (1 + math.sqrt(max(0, domain)))
    if surface["type"] == "Aspheric":
        start_order = 2 if surface.get("use_ai2", True) else 4
        for j, coeff in enumerate(surface.get("ai", [])):
            value += float(coeff) * radius ** (start_order + 2*j)
    return finite(value)


def build_scene(json_path):
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    if data.get('optiland_native_source'):
        from optiland_bridge import prescription_to_optiland
        optic,_=prescription_to_optiland(json_path,preserve_apertures=True)
        z=0.
        for row,native in zip(data['surfaces'],list(optic.surfaces)[1:-1]):
            row['(d)']=z;row['d_next']=float(native.thickness);z+=row['d_next'];row['roc']=float(native.geometry.radius)
            radius=getattr(getattr(native,'aperture',None),'r_max',None)
            if radius is None:radius=getattr(native,'semi_aperture',None)
            if radius is not None and math.isfinite(float(radius)) and float(radius)>0:row['r']=float(radius)
        data['(d_sensor)']=z
    from optiland_bridge import glass_catalog,native_cdgm_catalog
    catalog = glass_catalog(data.get("glass_catalog"),data.get("glass_catalog_revision"))
    rows, warnings = [], []
    z = 0.0
    for i, s in enumerate(data["surfaces"]):
        kind = s["type"]
        if kind not in ("Spheric", "Aspheric", "Aperture", "Plane"):
            raise ValueError(f"3D 暂不支持面型 {kind}")
        raw_z = s.get("(d)", s.get("d", z))
        z = finite(raw_z)
        thickness = finite(s.get("d_next"))
        if z is None or thickness is None:
            raise ValueError(f"第 {i+1} 面位置或间隔缺失/非有限数")
        radius = finite(s.get("r"))
        if radius is None or radius <= 0:
            raise ValueError(f"第 {i+1} 面口径无效")
        if kind in ("Spheric", "Aspheric"):
            raw_roc = s.get("roc")
            try:
                roc = float(raw_roc)
            except (ValueError, TypeError):
                raise ValueError(f"第 {i+1} 面曲率半径缺失/无效") from None
            if math.isnan(roc) or roc == 0:
                raise ValueError(f"第 {i+1} 面曲率半径无效")
        profile = []
        for j in range(33):
            r = radius*j/32
            dz = 0 if kind in ("Aperture", "Plane") else sag(s, r)
            profile.append([r, dz])
        if any(p[1] is None for p in profile):
            warnings.append(f"第 {i+1} 面存在无实数矢高区域，3D 省略无效部分")
        material = str(s.get("mat2", "air"))
        glass = catalog.get(material.lower(), {})
        rows.append({"index": i+1, "type": kind, "z": z,
                     "radius": radius, "roc": finite(s.get("roc")),
                     "thickness": thickness,
                     "material": material, "nd": finite(glass.get("nd"), 1 if material.lower()=="air" else None),
                     "vd": finite(glass.get("vd")), "conic": finite(s.get("k"), 0),
                     "coefficients": s.get("ai", []), "use_ai2": bool(s.get("use_ai2", True)),
                     "profile": profile})
        z += thickness
    sensor_z = finite(data.get("(d_sensor)", data.get("d_sensor", z)))
    if sensor_z is None:
        raise ValueError("像面位置无效")
    return {"source": Path(json_path).name, "units": "mm", "geometry_only": True,
            "surfaces": rows, "sensor_z": sensor_z,
            "sensor_radius": finite(data.get("r_sensor"), 1),
            "foclen": finite(data.get("foclen")), "fnum": finite(data.get("fnum")),
            "object_depth": finite(data.get("obj_depth")),
            "object_at_infinity": bool(data.get("object_at_infinity")),
            "wavelengths": data.get("wvln_ls", []),
            "primary_wavelength": finite(data.get("wvln_primary")),
            "export_materials":"catalog_names" if data.get('design_requirements') or native_cdgm_catalog(data) else "model",
            "glass_catalog": data.get("glass_catalog"),
            "glass_catalog_revision": data.get("glass_catalog_revision"),
            "has_explicit_fields":bool(data.get('design_fields')),
            "warnings": warnings}
