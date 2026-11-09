"""Small, testable image-plane residual with explicit extinguished-ray handling."""
import numpy as np


def spot_residuals(bundles, reference=None, scale=.05, invalid_penalty=10.,reference_index=1,spectral_weights=None):
    """Bundles are copied (x,y,intensity) arrays; the selected primary anchors them.

    A finite intersection belonging to a blocked or terminated ray must never
    be optimized as a valid image sample. The residual length stays fixed.
    """
    gx,gy,gi=bundles[reference_index]
    valid_green=np.isfinite(gx)&np.isfinite(gy)&np.isfinite(gi)&(gi>0)
    if reference is None:
        cx=float(np.mean(gx[valid_green])) if valid_green.any() else 0.
        cy=float(np.mean(gy[valid_green])) if valid_green.any() else 0.
    else:cx,cy=reference
    values=[]
    for index,(rx,ry,intensity) in enumerate(bundles):
        valid=np.isfinite(rx)&np.isfinite(ry)&np.isfinite(intensity)&(intensity>0)
        weight=spectral_weights[index]*len(bundles) if spectral_weights is not None else 1.
        denom=np.sqrt(len(rx))/np.sqrt(weight) if weight>0 else np.inf
        values.extend(np.where(valid,(rx-cx)/scale,invalid_penalty)/denom)
        values.extend(np.where(valid,(ry-cy)/scale,invalid_penalty)/denom)
    return values
