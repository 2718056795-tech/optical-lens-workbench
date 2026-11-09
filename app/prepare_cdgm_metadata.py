"""Re-extract the preserved official Excel; does not edit or recalculate it.

Requires data/supplier_reference/CDGM202609.xlsx and the matching AGF. Uses OOXML
cached literal values with the standard library, with explicit column checks.
"""
import collections
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

ROOT=Path(__file__).resolve().parent
NS={"s":"http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def main():
    excel=ROOT/"data/supplier_reference/CDGM202609.xlsx";agf=ROOT/"data/catalogs/CDGM202609.AGF"
    with zipfile.ZipFile(excel) as z:
        strings=["".join(n.itertext()) for n in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("s:si",NS)]
        def sheet_rows(file):
            result=[]
            for row in ET.fromstring(z.read(file)).findall("s:sheetData/s:row",NS):
                values={}
                for c in row.findall("s:c",NS):
                    v=c.find("s:v",NS);value=v.text if v is not None else ""
                    if c.get("t")=="s":value=strings[int(value)]
                    values[re.sub(r"\d+$","",c.get("r"))]=value
                result.append(values)
            return result
        rows=sheet_rows("xl/worksheets/sheet1.xml");header=rows[0]
        assert header["A"]=="Glass" and header["N"]=="nd"
        freq=next(c for c,v in header.items() if v=="Melt Frequency");price=next(c for c,v in header.items() if v=="Relative Price")
        table={}
        for row in rows[2:]:
            name=row.get("A","").strip();grade=row.get(freq,"").strip()
            if not name or grade not in ("MA","A","B","C","D","NEW"):continue
            assert name.lower() not in table,name
            table[name.lower()]={"name":name,"melt_grade":grade,"relative_price":float(row[price]) if row.get(price) else None,"nd":float(row["N"]),"vd":float(row["X"])}
        remarks="\n".join(r.get("A","") for r in sheet_rows("xl/worksheets/sheet4.xml") if "the glass" in r.get("A",""))
    mapping=collections.Counter();conflicts=[];matched=0
    for line in agf.read_text(encoding="utf-16").splitlines():
        if not line.startswith("NM "):continue
        p=line.split();name=p[1].lower()
        if name not in table:continue
        r=table[name];matched+=1;mapping[(p[8],r["melt_grade"])]+=1
        if abs(float(p[4])-r["nd"])>2e-5 or abs(float(p[5])-r["vd"])>.04:conflicts.append([p[1],p[4:6],r["nd"],r["vd"]])
    assert matched==len(table),"some Excel glasses have no matching AGF record"
    data={"catalog":"CDGM","revision":"202609","excel_source_url":"https://www.cdgmgd.com/downloadFile.htm?uid=d5ilBXjFgXCK9VxoDmb","agf_source_url":"https://www.cdgmgd.com/downloadFile.htm?uid=pvntrGdxCC64MZei1SX","excel_sha256":hashlib.sha256(excel.read_bytes()).hexdigest(),"agf_sha256":hashlib.sha256(agf.read_bytes()).hexdigest(),"sheet":"optical glass","frequency_column":freq,"price_column":price,"excel_grade_counts":dict(collections.Counter(r["melt_grade"] for r in table.values())),"matched_agf_records":matched,"code_grade_counts":{str(k):v for k,v in mapping.items()},"nd_vd_mismatches":conflicts,"supplier_remarks":remarks,"rows":table}
    (ROOT/"data/catalogs/CDGM202609_metadata.json").write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:data[k] for k in ("excel_grade_counts","matched_agf_records","nd_vd_mismatches")},ensure_ascii=False,indent=2))


if __name__=="__main__":main()
