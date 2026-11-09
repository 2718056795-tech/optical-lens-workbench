"""AutoLens 处方 -> Optiland 分析桥（V4）。

把 V1 AutoLens 写出的 final_lens.json 转成 Optiland Optic：
  - 球面/光阑/厚度/材料逐一映射（非球面暂不支持，报错提示）；
  - 玻璃折射率按 AutoLens 同款 AGF 玻璃库与同款色散公式计算
    （系数与公式照搬 deeplens/material/materials.py，不修改 V1 快照）；
  - 输出 MTF / 点列 / 场曲 / 网格畸变 PNG 与 Zemax .zmx / CODE V .seq 导出。

只依赖 optiland + matplotlib + numpy，不 import torch/deeplens。
"""
import json
import math
import os
import re
import threading
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")

V3_ROOT = Path(__file__).resolve().parent
# Keep compiled kernels and plotting caches inside this workspace, including
# when the bridge is imported by the HTTP handler rather than a worker.
os.environ.setdefault("NUMBA_CACHE_DIR", str(V3_ROOT / "runtime_cache" / "numba"))
os.environ.setdefault("MPLCONFIGDIR", str(V3_ROOT / "runtime_cache" / "matplotlib"))
V1_MATERIAL_DIR = V3_ROOT / "data" / "catalogs" / "legacy"

# ---------------------------------------------------------------- 玻璃库
# 以下 AGF 解析与色散公式照搬 V1/AutoLens/deeplens/material/materials.py
# （read_agf / set_material_param_agf / ior），保证与优化引擎折射率一致。

def read_agf(file_path):
    encodings = ["utf-8", "utf-16"]
    for enc in encodings:
        try:
            with open(file_path, "r", encoding=enc) as f:
                lines = f.readlines()
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"Error! {file_path} not found.")

    nm_lines = [line for line in lines if re.match(r"^NM\b", line)]
    cd_lines = [line for line in lines if re.match(r"^CD\b", line)]

    materials = {}
    for i in range(len(nm_lines)):
        nm_parts = nm_lines[i].strip().split()
        cd_parts = cd_lines[i].strip().split()
        materials[nm_parts[1].lower()] = {
            "calculate_mode": float(nm_parts[2]),
            "nd": float(nm_parts[4]),
            "vd": float(nm_parts[5]),
            "a_coeff": float(cd_parts[1]),
            "b_coeff": float(cd_parts[2]),
            "c_coeff": float(cd_parts[3]),
            "d_coeff": float(cd_parts[4]),
            "e_coeff": float(cd_parts[5]),
            "f_coeff": float(cd_parts[6]),
        }
    return materials


_CATALOG = None


def glass_catalog(catalog=None, revision=None):
    if catalog is not None:
        if catalog not in ("CDGM", "SCHOTT"):
            raise ValueError("未安装该制造商玻璃库："+str(catalog))
        from glass_selection import catalog_data, LEGACY_REVISION
        return catalog_data(catalog,revision or LEGACY_REVISION[catalog])["dispersion"]
    global _CATALOG
    if _CATALOG is None:
        cat = {}
        for agf in ("MISC.AGF", "PLASTIC2022.AGF", "CDGM.AGF", "SCHOTT.AGF"):
            p = V1_MATERIAL_DIR / agf
            if p.is_file():
                cat.update(read_agf(str(p)))
        _CATALOG = cat
    return _CATALOG

def native_cdgm_catalog(data):
    """Recognize native CDGM names only when the bundled catalog bytes match upstream."""
    if data.get('glass_catalog') not in (None,'CDGM'):return None
    if data.get('glass_catalog_revision') not in (None,'202409'):return None
    names={str(s.get('mat2','air')).lower() for s in data['surfaces']}-{'air',''}
    if not names or not names.issubset(glass_catalog('CDGM','202409')):return None
    from native_sources import AUTO_DIR
    from glass_selection import catalog_data
    source=AUTO_DIR/'deeplens/material/CDGM.AGF'
    stored=Path(catalog_data('CDGM','202409')['source_file'])
    if source.read_bytes()!=stored.read_bytes():raise ValueError('原生CDGM与导出目录字节不一致，禁止猜测目录玻璃色散')
    return 'CDGM','202409'


def glass_ior(name, wvln_um, catalog=None, revision=None):
    """与 deeplens Material.ior 相同的折射率（波长 um）。"""
    m = glass_catalog(catalog,revision)[name.lower()]
    w = float(wvln_um)
    if m["calculate_mode"] == 2:  # sellmeier
        k1, l1 = m["a_coeff"], m["b_coeff"]
        k2, l2 = m["c_coeff"], m["d_coeff"]
        k3, l3 = m["e_coeff"], m["f_coeff"]
        n2 = (1 + k1 * w**2 / (w**2 - l1)
              + k2 * w**2 / (w**2 - l2)
              + k3 * w**2 / (w**2 - l3))
    else:  # schott（calculate_mode == 1）
        a0, a1, a2 = m["a_coeff"], m["b_coeff"], m["c_coeff"]
        a3, a4, a5 = m["d_coeff"], m["e_coeff"], m["f_coeff"]
        ws = w**2
        n2 = a0 + a1 * ws + (a2 + (a3 + (a4 + a5 / ws) / ws) / ws) / ws
    return math.sqrt(n2)


def _optiland_material(name, sample_wvlns, mode="table", catalog=None, revision=None):
    """构造 Optiland 材料（air -> None）。

    mode="table"：按设计波长表格化折射率（分析用，色散最准）；
    mode="abbe"：用 AGF 中 nd/vd 建阿贝材料（导出用——Zemax/CODE V
    写出器只接受目录玻璃或 MODEL 玻璃，表格材料会被拒绝）。
    """
    if name.lower() in ("air", ""):
        return None
    if '/' in name:raise ValueError('此快照含连续MODEL材料，当前目录玻璃桥不能完整表达其色散；请选择AutoLens原生分析，或选择已匹配目录玻璃的快照。')
    if mode == "abbe":
        from optiland.materials import AbbeMaterial
        m = glass_catalog(catalog,revision)[name.lower()]
        mat = AbbeMaterial(m["nd"], m["vd"])
        mat.name = name  # 导出文件里保留牌号便于识别
        return mat
    from optiland.materials import DataMaterial
    lo, hi = min(sample_wvlns) - 0.02, max(sample_wvlns) + 0.02
    grid = sorted(set(list(sample_wvlns) +
                      [lo + (hi - lo) * i / 8 for i in range(9)]))
    ns = [glass_ior(name, w, catalog, revision) for w in grid]
    return DataMaterial.from_samples(wavelengths=grid, indices=ns, name=name)


# ---------------------------------------------------------------- 结构转换

def prescription_to_optiland(json_path, material_mode="table", preserve_apertures=False):
    """AutoLens 处方 JSON -> (Optic, meta)。仅支持球面 + 圆光阑。"""
    import numpy as np
    from optiland.optic import Optic

    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    if data.get('optiland_native_source'):
        import hashlib
        from optiland.fileio import load_optiland_file
        if data['optiland_native_source']!='native_optic.json':raise ValueError('原生模型路径非法')
        native=Path(json_path).parent/'native_optic.json'
        if hashlib.sha256(native.read_bytes()).hexdigest()!=data.get('native_model_sha256'):raise ValueError('原生导入模型指纹不符')
        optic=load_optiland_file(str(native))
        return optic,dict(source_json=str(json_path),native_import=True,optical_model='original Optiland model after strict field/wavelength validation',
                          half_fov_deg=math.degrees(math.atan(float(data['r_sensor'])/float(data['foclen']))),wavelengths_um=optic.wavelengths.get_wavelengths(),
                          foclen=data['foclen'],fnum=data['fnum'],surfaces_mapped=len(data['surfaces']))
    surfs = data["surfaces"]
    wvlns = data.get("wvln_ls", [0.486, 0.587, 0.656])
    primary = data.get("wvln_primary", 0.587)
    manufacturer = data.get("glass_catalog")
    revision = data.get("glass_catalog_revision")

    lens = Optic()
    obj_depth = abs(float(data.get("obj_depth", -20000.0)))
    if data.get("object_at_infinity") or not math.isfinite(obj_depth) or obj_depth < 1e-6:
        obj_depth = np.inf
    if preserve_apertures and math.isfinite(obj_depth):
        obj_depth += float(surfs[0].get("(d)", surfs[0].get("d", 0)))
    lens.add_surface(index=0, radius=np.inf, thickness=obj_depth)

    mats = {}
    idx = 1
    for s in surfs:
        t = s["type"]
        roc = float(s["roc"]) if "roc" in s else np.inf
        if t == "Aperture":
            lens.add_surface(index=idx, radius=np.inf,
                             thickness=float(s["d_next"]),
                             material="air", is_stop=True)
        elif t == "Spheric":
            g = s["mat2"]
            if g not in mats:
                if data.get('optiland_material_model')=='agf-formula-v1' and g.lower()!='air':
                    from optiland_native_catalog import material
                    from glass_selection import resolve_selection
                    selection=resolve_selection(dict(glass_table=manufacturer,glass_catalog_revision=revision,glass_policy='custom',allowed_glasses=data['allowed_glasses']))
                    mats[g]=material(g,selection)
                else:mats[g] = _optiland_material(g, wvlns, mode=material_mode, catalog=manufacturer, revision=revision)
            lens.add_surface(index=idx, radius=roc,
                             thickness=float(s["d_next"]),
                             material=mats[g] if mats[g] else "air")
        else:
            raise NotImplementedError(
                f"面型 {t} 暂不支持 Optiland 分析（目前仅支持球面）")
        idx += 1
    lens.add_surface(index=idx, radius=np.inf, material="air")  # 像面

    lens.set_aperture("imageFNO", float(data["fnum"]))
    lens.set_field_type("angle")
    rfov_half = math.degrees(math.atan(
        float(data["r_sensor"]) / float(data["foclen"])))
    for fy in (0.0, 0.7 * rfov_half, rfov_half):
        lens.add_field(y=fy)
    if data.get('design_requirements'):
        infinity=data['design_requirements'].get('object_at_infinity',False)
        lens.fields.fields.clear();lens.fields.set_type('angle' if infinity else 'object_height')
        for f in data['design_fields']:lens.fields.add(x=f['x'] if infinity else f['object_x_mm'],y=f['y'] if infinity else f['object_y_mm'],weight=f['weight'])
        lens.ray_tracer.set_aiming('iterative',max_iter=12,tol=1e-7)
        from optiland.physical_apertures import RadialAperture
        stop_index=next(i for i,s in enumerate(surfs) if s['type']=='Aperture')
        lens.surfaces[stop_index+1].aperture=RadialAperture(r_max=float(surfs[stop_index]['r']))
    primary_index=1 if data.get('spectral_model')=='native-three-v1' else min(range(len(wvlns)),key=lambda i:abs(wvlns[i]-primary))
    for wi,w in enumerate(wvlns):
        lens.wavelengths.add(value=w,is_primary=wi==primary_index,weight=data.get('spectral_weights',[1/len(wvlns)]*len(wvlns))[wi])
    if preserve_apertures:
        from optiland.physical_apertures import RadialAperture
        stops = [i for i, s in enumerate(surfs) if s["type"] == "Aperture"]
        if len(stops) != 1:
            raise ValueError("分析需要恰好一个独立光阑")
        lens.set_aperture("float_by_stop_size", 2*float(surfs[stops[0]]["r"]))
        for i, s in enumerate(surfs):
            if i != stops[0]:
                lens.surfaces[i+1].aperture = RadialAperture(r_max=float(s["r"]))

    if data.get('optiland_inputs'):
        from optiland_native_inputs import configure_model
        configure_model(lens,data['optiland_inputs'])

    meta = {
        "source_json": str(json_path),
        "glass_catalog": manufacturer,
        "glass_catalog_revision": revision,
        "foclen": data["foclen"], "fnum": data["fnum"],
        "half_fov_deg": rfov_half, "wavelengths_um": wvlns,
        "glasses": sorted(k for k in mats if mats[k] is not None),
        "surfaces_mapped": len(surfs),
        "aperture_mode": "saved physical stop and surface radii" if preserve_apertures else "image FNO",
        "object_model": "infinity" if math.isinf(obj_depth) else "finite",
    }
    return lens, meta


# ---------------------------------------------------------------- 分析输出

_ANALYSIS_LOCK = threading.Lock()


def compute_analysis(json_path, out_dir):
    """生成 Optiland 分析图与摘要；返回可 JSON 化的结果 dict。"""
    import matplotlib
    matplotlib.use("Agg")
    matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei",
                                              "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    import matplotlib.pyplot as plt

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    lens, meta = prescription_to_optiland(json_path, preserve_apertures=True)
    # optiland 导入时会经 seaborn 改全局字体，需在其后再设中文字体
    matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei",
                                              "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False

    meta["mtf_method"] = "polychromatic geometric OTF; circular-pupil envelope approximation"
    meta["primary_wavelength_um"] = float(json.loads(Path(json_path).read_text(encoding="utf-8")).get("wvln_primary", 0.587))
    result = {"ok": True, "analysis_version": 5, "meta": meta, "images": [], "errors": {}}
    jobs = [
        ("mtf_geometric.png", "几何 MTF", "optiland.mtf", "GeometricMTF"),
        ("spot_diagram.png", "点列图", "optiland.analysis", "SpotDiagram"),
        ("field_curvature.png", "场曲", "optiland.analysis", "FieldCurvature"),
        ("grid_distortion.png", "网格畸变", "optiland.analysis", "GridDistortion"),
        ("ray_fan.png", "光线像差扇图", "optiland.analysis", "RayFan"),
    ]
    with _ANALYSIS_LOCK:  # matplotlib 全局状态，串行执行
        for fname, label, modname, clsname in jobs:
            try:
                import importlib
                if clsname=='GeometricMTF':
                    from spectral_mtf import generate_spectral_mtf
                    data=json.loads(Path(json_path).read_text(encoding='utf-8'))
                    waves=data.get('wvln_ls',[.486,.587,.656])
                    spectral=generate_spectral_mtf(lens,waves,data.get('spectral_weights',[1/len(waves)]*len(waves)),out)
                    meta.update(mtf_method=spectral['method'],mtf_wavelengths_um=spectral['wavelengths_um'],mtf_weights=spectral['weights'])
                    result['images'].append(dict(file=fname,label=label,variants=spectral['variants']));continue
                cls = getattr(importlib.import_module(modname), clsname)
                plt.close("all")
                ana = cls(lens, num_points=65) if clsname == "RayFan" else cls(lens)
                ana.view()
                fig = plt.gcf()
                fig.suptitle(f"{label} - {Path(json_path).parent.name}",
                             fontsize=10)
                fig.savefig(str(out / fname), dpi=110, bbox_inches="tight")
                plt.close("all")
                result["images"].append({"file": fname, "label": label})
            except Exception as e:  # 单项失败不拖垮整体
                result["errors"][label] = f"{type(e).__name__}: {e}"
    return result


def export_lens(json_path, fmt, out_path):
    """导出 Zemax .zmx 或 CODE V .seq（玻璃按 nd/vd MODEL 玻璃写出）。"""
    data=json.loads(Path(json_path).read_text(encoding='utf-8'))
    if data.get('optiland_native_source'):
        import shutil
        original=Path(json_path).parent/data['source_original_file']
        if original.suffix.lower()=='.'+fmt:
            shutil.copyfile(original,out_path);return str(out_path)
        optic,_=prescription_to_optiland(json_path,preserve_apertures=True)
        from optiland.fileio import save_codev_file,save_zemax_file
        (save_codev_file if fmt=='seq' else save_zemax_file)(optic,str(out_path));return str(out_path)
    if data.get('design_requirements') or native_cdgm_catalog(data):
        from interchange_export import export
        return export(json_path,fmt,out_path)
    lens, _ = autolens_json_to_optiland(json_path, material_mode="abbe", preserve_apertures=True)
    from optiland.fileio import save_codev_file, save_zemax_file
    if fmt == "zmx":
        save_zemax_file(lens, str(out_path))
    elif fmt == "seq":
        save_codev_file(lens, str(out_path))
    else:
        raise ValueError("fmt 仅支持 zmx / seq")
    return str(out_path)


if __name__ == "__main__":
    import sys
    jp = sys.argv[1]
    od = sys.argv[2] if len(sys.argv) > 2 else str(Path(jp).parent / "analysis")
    r = compute_analysis(jp, od)
    print(json.dumps({k: (v if k != "meta" else None) for k, v in r.items()},
                     ensure_ascii=False, indent=1))


def autolens_json_to_optiland(*args,**kwargs):
    """Legacy JSON-format alias; model construction uses Optiland only."""
    return prescription_to_optiland(*args,**kwargs)
