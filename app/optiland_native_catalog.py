"""AGF coefficients registered through Optiland's public user-material API."""
import hashlib,json
from pathlib import Path
_registered={}

def register_selection(selection):
    from glass_selection import catalog_data
    from optiland.materials.registry import MaterialRegistry
    import yaml
    catalog=catalog_data(selection['catalog'],selection['revision'])
    source=catalog['source_sha256'];key=source+':'+','.join(n.lower() for n in selection['allowed_glasses'])
    if key in _registered:return _registered[key]
    folder=Path(__file__).resolve().parent/'runtime_cache/native_catalog'/source[:16]
    folder.mkdir(parents=True,exist_ok=True);aliases={};registry=MaterialRegistry.instance();known=set(registry.list_materials())
    for original in selection['allowed_glasses']:
        m=catalog['dispersion'][original.lower()]
        c=[m[k+'_coeff'] for k in 'abcdef']
        if m['calculate_mode']==2:formula='formula 2';coeff=[0.]+c
        elif m['calculate_mode']==1:formula='formula 3';coeff=[c[0],c[1],2,c[2],-2,c[3],-4,c[4],-6,c[5],-8]
        else:raise ValueError('未支持的AGF色散公式：'+original)
        alias='wb_'+source[:12]+'_'+hashlib.sha256(original.lower().encode('utf-8')).hexdigest()[:16]
        payload=dict(REFERENCE=selection['catalog']+' '+selection['revision'],
                     SPECS=dict(nd=m['nd'],Vd=m['vd']),DATA=[dict(type=formula,wavelength_range='0.3 1.2',coefficients=' '.join(str(v) for v in coeff)),dict(type='tabulated k',data='0.3 0\n1.2 0')])
        path=folder/(alias+'.yml');encoded=yaml.safe_dump(payload,sort_keys=False)
        if not path.exists() or path.read_text(encoding='utf-8')!=encoded:path.write_text(encoded,encoding='utf-8')
        if alias not in known:registry.register_file(path);known.add(alias)
        aliases[alias]=original.lower()
    _registered[key]=aliases
    return aliases

def material(name,selection):
    if str(name).lower()=='air':return 'air'
    from optiland.materials import Material,MatchPolicy
    aliases=register_selection(selection)
    alias=next((a for a,n in aliases.items() if n==str(name).lower()),None)
    if alias is None:raise ValueError('材料不在所选玻璃池：'+name)
    return Material(alias,match_policy=MatchPolicy.STRICT)
