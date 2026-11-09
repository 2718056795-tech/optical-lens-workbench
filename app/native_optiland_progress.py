"""Read-only snapshots from native solver vectors; never updates live variables."""
import copy,math

def snapshot_from_vector(base,variables,vector,contract=None):
    if len(variables)!=len(vector):raise ValueError('求解向量与变量数不一致')
    result=copy.deepcopy(base)
    for variable,value in zip(variables,vector):
        physical=float(variable.variable.inverse_scale(value))
        row=result['surfaces'][int(variable.surface_number)-1]
        if variable.type=='reciprocal_radius':
            row['(c)']=physical;row['roc']=1/physical if abs(physical)>1e-14 else 1e14
        elif variable.type=='thickness':row['d_next']=physical
        else:raise ValueError('未实现此变量的只读快照：'+variable.type)
    gaps=[s['d_next'] for s in result['surfaces']]
    if contract:gaps=contract.project_gaps(gaps)
    z=0.
    for row,gap in zip(result['surfaces'],gaps):row['(d)']=z;row['d_next']=float(gap);z+=float(gap)
    result['(d_sensor)']=z
    return result

def render_snapshot(path,image_path,title='Optiland saved checkpoint; primary wavelength'):
    """Draw an independent Optiland copy with native iterative stop aiming."""
    from optiland_bridge import prescription_to_optiland
    import matplotlib.pyplot as plt
    import json
    from pathlib import Path
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    track=float(data['(d_sensor)'])-float(data['surfaces'][0].get('(d)',0.))
    pad=max(.5,track*.05)
    height=max(float(s['r']) for s in data['surfaces'])*1.15
    height=max(height,float(data.get('r_sensor') or 0)*1.1)
    copied,_=prescription_to_optiland(path,preserve_apertures=True)
    fig,ax=copied.draw(fields='all',wavelengths='primary',num_rays=5,hide_vignetted=False,show=False,title=title,
                       xlim=(-pad,track+pad),ylim=(-height,height),figsize=(10,4.5))
    # Fit ray segments only within the displayed optical train. The distant
    # object stays outside the view, while edge-field rays remain visible.
    lo,hi=-pad,track+pad
    for line in ax.lines:
        xy=line.get_xydata()
        for a,b in zip(xy[:-1],xy[1:]):
            if not all(math.isfinite(float(v)) for v in (*a,*b)):continue
            for x,y in (a,b):
                if lo<=x<=hi:height=max(height,abs(float(y))*1.05)
            if b[0]!=a[0]:
                for x in (lo,hi):
                    if min(a[0],b[0])<=x<=max(a[0],b[0]):
                        y=a[1]+(x-a[0])*(b[1]-a[1])/(b[0]-a[0]);height=max(height,abs(float(y))*1.05)
    ax.set_ylim(-height,height)
    fig.savefig(image_path,dpi=130,bbox_inches='tight');plt.close(fig)
