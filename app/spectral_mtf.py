"""Polychromatic geometric OTF with an approximate circular-pupil envelope.

Complex OTFs are summed before taking their modulus. Thus wavelength-dependent
image displacement is retained; this is not an average of monochromatic MTFs.
This ray-based approximation is not a wavefront diffraction MTF calculation.
"""
import numpy as np


def ray_otf(bundle,frequencies):
    x,y,intensity=(np.asarray(v,dtype=float).ravel() for v in bundle)
    valid=np.isfinite(x)&np.isfinite(y)&np.isfinite(intensity)&(intensity>0)
    if not valid.any():raise ValueError('MTF所需视场/波长没有有效光线')
    energy=float(intensity[valid].sum())/len(intensity)
    def transform(position):
        phase=np.exp(-2j*np.pi*np.outer(frequencies,position[valid]))
        return phase@intensity[valid]/intensity[valid].sum()
    return np.stack([transform(y),transform(x)]),energy


def combine_otfs(otfs,energies,weights):
    w=np.asarray(energies)*np.asarray(weights)
    if not np.isfinite(w).all() or (w<0).any() or w.sum()<=0:raise ValueError('MTF光谱能量权重非法')
    return np.sum(np.asarray(otfs)*w[:,None,None],axis=0)/w.sum()


def circular_envelope(frequency,wavelength_um,fnum):
    ratio=np.clip(np.asarray(frequency)*wavelength_um*1e-3*fnum,0,1)
    return 2/np.pi*(np.arccos(ratio)-ratio*np.sqrt(1-ratio**2))


def generate_spectral_mtf(optic,wavelengths,weights,out_dir):
    import json
    from pathlib import Path
    import matplotlib.pyplot as plt
    waves=list(dict.fromkeys(float(w) for w in wavelengths))
    if len(weights)!=len(wavelengths) or not np.isfinite(weights).all() or min(weights)<0 or sum(weights)<=0:
        raise ValueError('光谱权重数量/数值非法')
    # Merge duplicate monochromatic inputs from historical files.
    merged=[sum(v for old,v in zip(wavelengths,weights) if float(old)==w) for w in waves]
    merged=np.asarray(merged,dtype=float);merged/=merged.sum()
    fnum=abs(float(optic.paraxial.FNO()))
    if not np.isfinite(fnum) or fnum<=0:raise ValueError('MTF需要有限正F数')
    frequency=np.linspace(0,min(2000,1/(min(waves)*1e-3*fnum)),256)
    monochromatic=[];combined=[];throughputs=[]
    for field in (0.,.7,1.):
        otfs=[];energies=[]
        for wave in waves:
            ray=optic.trace(0.,field,wave,num_rays=24,distribution='hexapolar')
            bundle=[np.asarray(v).copy() for v in (ray.x,ray.y,ray.i)]
            otf,energy=ray_otf(bundle,frequency)
            otfs.append(otf*circular_envelope(frequency,wave,fnum));energies.append(energy)
        monochromatic.append(np.abs(otfs));combined.append(np.abs(combine_otfs(otfs,energies,merged)));throughputs.append(energies)
    out=Path(out_dir)
    def plot(values,filename,title):
        fig,ax=plt.subplots(figsize=(10,4))
        for index,(field,curves) in enumerate(zip((0.,.7,1.),values)):
            for k,direction in enumerate(('T','S')):ax.plot(frequency,curves[k],color=f'C{index}',linestyle='-' if k==0 else '--',label=f'{field:.1f} field {direction}')
        ax.set(xlim=(0,float(frequency[-1])),ylim=(0,1.02),xlabel='Spatial frequency (cycles/mm)',ylabel='MTF',title=title)
        ax.grid(alpha=.2);ax.legend(loc='upper right',fontsize=8);fig.tight_layout()
        fig.savefig(out/filename,dpi=130,bbox_inches='tight');plt.close(fig)
    plot(combined,'mtf_geometric.png',f'Polychromatic geometric MTF | {min(waves)*1000:g}-{max(waves)*1000:g} nm | {len(waves)} sample(s)')
    variants=[]
    for j,wave in enumerate(waves):
        filename=f'mtf_wavelength_{j+1}.png'
        plot([m[j] for m in monochromatic],filename,f'Monochromatic geometric MTF | {wave*1000:g} nm')
        variants.append(dict(wavelength_um=wave,file=filename))
    numeric=dict(frequency_cycles_mm=frequency.tolist(),wavelengths_um=waves,weights=merged.tolist(),
                 polychromatic_mtf=np.asarray(combined).tolist(),monochromatic_mtf=np.asarray(monochromatic).tolist(),throughput=np.asarray(throughputs).tolist(),
                 method='complex geometric OTF sum, common image coordinates, circular-pupil diffraction envelope approximation; not wavefront diffraction MTF',ray_sampling='hexapolar 24')
    (out/'mtf_spectral_data.json').write_text(json.dumps(numeric,indent=2,allow_nan=False),encoding='utf-8')
    return dict(variants=variants,wavelengths_um=waves,weights=merged.tolist(),method=numeric['method'])
