"""Full precision spherical prescriptions with actual catalog glass names.

SEQ/ZMX are generated as lens data, not executable optimization macros. Local
round-trip checks are required; no commercial-software numerical equivalence
is implied by this writer.
"""
import json,math
from pathlib import Path

def export(json_path,fmt,out_path):
    from optiland_bridge import autolens_json_to_optiland,glass_catalog
    data=json.loads(Path(json_path).read_text(encoding='utf-8'));surfaces=data['surfaces']
    if any(s['type'] not in ('Spheric','Aperture') for s in surfaces):raise ValueError('此导出接口仅支持球面和独立圆光阑')
    optic,_=autolens_json_to_optiland(json_path,preserve_apertures=True)
    from optiland_bridge import native_cdgm_catalog
    identified=native_cdgm_catalog(data)
    epd=float(optic.paraxial.EPD());manufacturer=data.get('glass_catalog') or identified[0];revision=data.get('glass_catalog_revision') or identified[1]
    catalog=glass_catalog(manufacturer,revision);req=data.get('design_requirements')
    infinity=bool(data.get('object_at_infinity'))
    angular_fields=infinity or not req
    if req:
        fields=[(f['x'],f['y'],f['weight']) if infinity else (f['object_x_mm'],f['object_y_mm'],f['weight']) for f in req['fields']]
    else:fields=[(float(f.x),float(f.y),float(f.weight)) for f in optic.fields.fields]
    waves=data['wvln_ls'];weights=data.get('spectral_weights',[1/len(waves)]*len(waves));primary=min(range(len(waves)),key=lambda i:abs(waves[i]-data['wvln_primary']))
    n=lambda v:format(float(v),'.17g')
    if fmt=='seq':
        lines=['! Optical Workbench spherical prescription; real catalog glass names',f'! Catalog {manufacturer} {revision}','RDM Y','DIM M','EPD '+n(epd),
               'WL '+' '.join(n(w*1000) for w in waves),'WTW '+' '.join(n(w) for w in weights),'REF '+str(primary+1),
               ('XAN ' if angular_fields else 'XOB ')+' '.join(n(f[0]) for f in fields),('YAN ' if angular_fields else 'YOB ')+' '.join(n(f[1]) for f in fields),'WTF '+' '.join(n(f[2]) for f in fields),
               'SO 0 '+('1e10' if infinity else n(abs(data['obj_depth'])))]
        for s in surfaces:
            curve=0. if s['type']=='Aperture' else 1/float(s['roc'])
            radius=0. if abs(curve)<1e-12 else 1/curve
            material=s.get('mat2','air').lower();glass='' if material=='air' else ' '+material.upper()+'_'+manufacturer
            lines.append('S '+n(radius)+' '+n(s['d_next'])+glass)
            if s['type']=='Aperture':lines.append(' STO')
            lines.append(' CIR CLR '+n(s['r']))
        lines.append('SI 0 0')
    elif fmt=='zmx':
        kind=0 if angular_fields else 1
        lines=['VERS 240000 3 0','MODE SEQ','NAME Optical Workbench','UNIT MM X W X CM MR CPMM','ENPD '+n(epd),f'FTYP {kind} 0 {len(fields)} {len(waves)} 0 0 0','GCAT '+manufacturer]
        lines.extend(f'WAVM {i+1} {n(w)} {n(weights[i])}' for i,w in enumerate(waves));lines.append('PWAV '+str(primary+1))
        for label,index in [('XFLN',0),('YFLN',1),('FWGN',2)]:lines.append(label+' '+' '.join(n(f[index]) for f in fields))
        lines.extend(['SURF 0',' TYPE STANDARD',' CURV 0',' DISZ '+('INFINITY' if infinity else n(abs(data['obj_depth'])))])
        for i,s in enumerate(surfaces,1):
            curve=0. if s['type']=='Aperture' else 1/float(s['roc'])
            lines.extend(['SURF '+str(i),' TYPE STANDARD',' CURV '+n(curve),' DISZ '+n(s['d_next']),' CLAP 0 '+n(s['r'])])
            if s['type']=='Aperture':lines.append(' STOP')
            material=s.get('mat2','air').lower()
            if material!='air':
                glass=catalog[material];lines.append(' GLAS '+material.upper()+' 0 0 '+n(glass['nd'])+' '+n(glass['vd'])+' 0 0')
        lines.extend(['SURF '+str(len(surfaces)+1),' TYPE STANDARD',' CURV 0',' DISZ 0'])
    else:raise ValueError('导出格式仅支持seq或zmx')
    Path(out_path).write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return str(out_path)
