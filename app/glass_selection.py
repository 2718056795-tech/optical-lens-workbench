"""Auditable manufacturer/catalog/allowed-glass constraints for both engines.

Only the preserved local AGF data are used. No live inventory is inferred from
historical melt-frequency codes. The source library is never modified.
"""
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parent
MATERIAL_DIR=ROOT/"data/catalogs/legacy"
CATALOGS={"CDGM":"成都光明 CDGM","SCHOTT":"肖特 SCHOTT"}
SOURCES={"CDGM":{"202609":ROOT/"data/catalogs/CDGM202609.AGF","202409":MATERIAL_DIR/"CDGM.AGF"},"SCHOTT":{"202412":MATERIAL_DIR/"SCHOTT.AGF"}}
LEGACY_REVISION={"CDGM":"202409","SCHOTT":"202412"}
POLICIES={"frequent":"仅 MA", "frequent_12":"MA + A（常用）", "frequent_123":"MA + A + B", "all":"全部可用牌号", "custom":"自定义可用牌号", "legacy_common":"兼容旧版常用清单"}


def _text(path):
    raw=Path(path).read_bytes()
    return raw.decode("utf-16" if raw.startswith((b"\xff\xfe",b"\xfe\xff")) else "utf-8-sig")


@lru_cache(maxsize=8)
def catalog_data(catalog,revision=None):
    if catalog not in CATALOGS:
        raise ValueError("玻璃库未安装：请选择成都光明 CDGM 或肖特 SCHOTT")
    revision=revision or next(iter(SOURCES[catalog]))
    if revision not in SOURCES[catalog]:raise ValueError("未安装该玻璃库版本："+str(revision))
    path=SOURCES[catalog][revision]
    from optiland_bridge import read_agf
    dispersion=read_agf(path)
    text=_text(path);rows=[];current=None;header=[]
    metadata_path=ROOT/"data/catalogs"/(catalog+revision+"_metadata.json")
    metadata=json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
    source_hash=hashlib.sha256(path.read_bytes()).hexdigest()
    if catalog=="CDGM" and revision=="202609":
        excel=ROOT/"data/supplier_reference/CDGM202609.xlsx"
        if not metadata or metadata.get("agf_sha256")!=source_hash or not excel.is_file() or hashlib.sha256(excel.read_bytes()).hexdigest()!=metadata.get("excel_sha256"):
            raise ValueError("CDGM202609 色散目录与厂家频次Excel未配套或文件校验失败")
    grades=metadata.get("rows",{});conflicts={r[0].lower() for r in metadata.get("nd_vd_mismatches",[])}
    def code(value):
        try:return int(value)
        except (ValueError,TypeError):return 0
    for line in text.splitlines():
        parts=line.split()
        if not parts:continue
        if parts[0]=="CC":header.append(line[3:].strip())
        if parts[0]=="NM":
            name=parts[1];status=code(parts[7]) if len(parts)>7 else 0
            current={"name":name,"nd":float(parts[4]),"vd":float(parts[5]),
                     "status":status,"melt_frequency":code(parts[8]) if len(parts)>8 else 0,
                     "exclude_substitution":bool(code(parts[6])) if len(parts)>6 else False,
                     "relative_cost":grades.get(name.lower(),{}).get("relative_price"),"formula":int(parts[2])}
            current["melt_grade"]=grades.get(name.lower(),{}).get("melt_grade")
            if catalog=="CDGM" and revision=="202409":
                current["melt_grade"]={1:"MA",2:"A"}.get(current["melt_frequency"])
            current["source_conflict"]=name.lower() in conflicts
            current["selectable"]=status!=2 and not current["exclude_substitution"] and current["formula"] in (1,2) and not current["source_conflict"]
            rows.append(current)
        elif parts[0]=="OD" and current and not metadata:
            try:
                value=float(parts[1]);current["relative_cost"]=value if value>0 else None
            except (ValueError,IndexError):pass
    legacy=json.loads((MATERIAL_DIR/"materials_data.json").read_text(encoding="utf-8"))["CDGM_GLASS"]
    legacy_names={n.lower() for n in legacy}
    profiles={}
    for key in POLICIES:
        if key=="custom":continue
        profiles[key]=[r["name"] for r in rows if r["selectable"] and (
            key=="all" or key=="frequent" and r["melt_grade"]=="MA" or
            key=="frequent_12" and r["melt_grade"] in ("MA","A") or
            key=="frequent_123" and r["melt_grade"] in ("MA","A","B") or
            key=="legacy_common" and (catalog!="CDGM" or r["name"].lower() in legacy_names))]
    return {"catalog":catalog,"revision":revision,"revisions":list(SOURCES[catalog]),"label":CATALOGS[catalog],"source_file":str(path),
            "source_sha256":source_hash,"source_header":"; ".join(header),
            "rows":rows,"profiles":profiles,"dispersion":dispersion,
            "frequency_source_sha256":metadata.get("excel_sha256"),
            "cost_note":"价格系数来自配套Excel，H-K9L=10；未列出的价格留空，不是当前报价。" if metadata else "成本为AGF相对值，不是当前报价。",
            "frequency_note":"MA/A/B 等按配套厂家 Excel 分级筛选（2024兼容库依据旧AGF编码）；不是使用次数或即时库存。Excel与AGF明显冲突的牌号禁止选用。"}


def public_catalog(catalog,revision=None):
    d=catalog_data(catalog,revision)
    return {k:v for k,v in d.items() if k!="dispersion"}


def resolve_selection(params):
    catalog=params.get("glass_table","CDGM");policy=params.get("glass_policy","legacy_common")
    if policy not in POLICIES:raise ValueError("玻璃范围非法")
    revision=params.get("glass_catalog_revision") or LEGACY_REVISION.get(catalog)
    data=catalog_data(catalog,revision);lookup={r["name"].lower():r for r in data["rows"]}
    if policy=="custom":
        raw=params.get("allowed_glasses")
        if isinstance(raw,str):raw=[n for n in re.split(r"[,;，；\s]+",raw.strip()) if n]
        if not isinstance(raw,list) or not raw or len(raw)>512:
            raise ValueError("自定义玻璃池需勾选1~512个牌号")
        selected=[]
        for name in raw:
            if not isinstance(name,str) or name.lower() not in lookup:
                raise ValueError(f"牌号 {name!r} 不在 {catalog} 库内")
            row=lookup[name.lower()]
            if not row["selectable"]:raise ValueError(f"牌号 {row['name']} 已停用、排除替换、数据冲突或色散公式不受支持")
            if row["name"] not in selected:selected.append(row["name"])
    else:selected=data["profiles"][policy]
    if not selected:raise ValueError("当前玻璃范围没有可用牌号，请更改频次范围或自定义清单")
    return {"catalog":catalog,"revision":data["revision"],"policy":policy,"policy_label":POLICIES[policy],
            "allowed_glasses":selected,"count":len(selected),"source_header":data["source_header"],
            "source_sha256":data["source_sha256"],"frequency_source_sha256":data["frequency_source_sha256"],"frequency_note":data["frequency_note"]}


def register_catalog(params):
    """Choose the manufacturer before GeoLens deserializes colliding names."""
    selection=resolve_selection(params)
    frozen=params.get("glass_selection")
    if frozen and (frozen.get("source_sha256")!=selection["source_sha256"] or frozen.get("allowed_glasses")!=selection["allowed_glasses"] or frozen.get("frequency_source_sha256")!=selection["frequency_source_sha256"]):
        raise ValueError("玻璃库或可用清单在任务启动后变化，请重新提交任务")
    import deeplens.material.materials as materials
    materials.MATERIAL_data.update(catalog_data(selection["catalog"],selection["revision"])["dispersion"])
    return selection


def match_lens(lens,params,preserve=False):
    selection=resolve_selection(params);data=catalog_data(selection["catalog"],selection["revision"])
    allowed={n.lower():n for n in selection["allowed_glasses"]}
    if preserve:
        names=[s.mat2.get_name() for s in lens.surfaces if s.mat2.get_name().lower()!="air"]
        outside=[n for n in names if n.lower() not in allowed]
        if outside:raise ValueError("来源处方超出当前玻璃池，无法原样精修："+", ".join(outside))
        return selection
    from deeplens.material import Material
    def number(value):
        return float(value.detach().cpu()) if hasattr(value,"detach") else float(value)
    # Legacy CDGM uses its original rounded n/V matching positions so old runs
    # retain their baseline; all newly selected pools match the AGF nd/Vd.
    legacy=None
    if selection["catalog"]=="CDGM" and selection["policy"]=="legacy_common":
        legacy={k.lower():v for k,v in json.loads((MATERIAL_DIR/"materials_data.json").read_text(encoding="utf-8"))["CDGM_GLASS"].items()}
    for surf in lens.surfaces:
        mat=surf.mat2
        if mat.get_name().lower()=="air":continue
        n,v=number(mat.n),number(mat.V)
        if not math.isfinite(n) or not math.isfinite(v):raise ValueError("连续材料参数非有限数，不能匹配玻璃")
        def score(name):
            d=data["dispersion"][name.lower()];nd,vd=legacy[name.lower()] if legacy else (d["nd"],d["vd"])
            return abs(nd-n)/.4+abs(vd-v)/40.
        chosen=min(selection["allowed_glasses"],key=score)
        surf.mat2=Material(chosen,device=lens.device)
        surf.mat2.set_material_param_agf(data["dispersion"],chosen.lower())
    return selection


def stamp_json(path,selection):
    path=Path(path);data=json.loads(path.read_text(encoding="utf-8"))
    data["glass_catalog"]=selection["catalog"]
    data["glass_catalog_revision"]=selection["revision"]
    data["glass_catalog_sha256"]=selection["source_sha256"]
    data["glass_policy"]=selection["policy"]
    data["allowed_glasses"]=selection["allowed_glasses"]
    allowed={n.lower() for n in selection["allowed_glasses"]}
    data["materials_are_catalog_glasses"]=all(str(s.get("mat2","air")).lower() in allowed|{"air"} for s in data["surfaces"])
    tmp=path.with_suffix(path.suffix+".catalog.tmp")
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8");tmp.replace(path)


def verify_prescription(data,params):
    selection=resolve_selection(params);allowed={n.lower() for n in selection["allowed_glasses"]}
    if data.get("glass_catalog",selection["catalog"])!=selection["catalog"]:
        raise ValueError("来源处方的制造商目录与精修设置不一致")
    if data.get("glass_catalog_revision",selection["revision"])!=selection["revision"]:
        raise ValueError("来源处方玻璃目录版本与精修设置不一致")
    names=[str(s.get("mat2","air")) for s in data["surfaces"] if str(s.get("mat2","air")).lower()!="air"]
    outside=[n for n in names if n.lower() not in allowed]
    if outside:raise ValueError("处方含可用池以外的玻璃："+", ".join(outside))
    return dict(selection,actual_glasses=names,all_actual_glasses_allowed=True)
