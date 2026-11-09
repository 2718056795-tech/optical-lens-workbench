"""Fit the 2D layout to actual ray paths inside the lens's axial window.

An infinite object's distant launch point must not dominate the view. Keep the
existing Z window, but include every finite line segment within that window.
"""
import numpy as np


def visible_line_heights(ax):
    left,right=sorted(ax.get_xlim());heights=[]
    for line in ax.lines:
        x=np.asarray(line.get_xdata(),dtype=float).ravel()
        y=np.asarray(line.get_ydata(),dtype=float).ravel()
        finite=np.isfinite(x)&np.isfinite(y)
        heights.extend(y[finite&(x>=left)&(x<=right)].tolist())
        for index in range(len(x)-1):
            if not (finite[index] and finite[index+1]):continue
            a,b=x[index:index+2]
            if a==b:continue
            for boundary in (left,right):
                fraction=(boundary-a)/(b-a)
                if 0<=fraction<=1:
                    heights.append(float(y[index]+fraction*(y[index+1]-y[index])))
    return heights


def fit_layout_axes(ax,margin=.08):
    old_ylim=ax.get_ylim();heights=list(old_ylim)+visible_line_heights(ax)
    low,high=min(heights),max(heights)
    pad=max((high-low)*margin,1e-3)
    ax.set_ylim(low-pad,high+pad)
    # Preserve the millimetre scale of the lens; do not stretch its geometry.
    ax.set_aspect('equal',adjustable='box')
    return {'xlim':list(ax.get_xlim()),'ylim':list(ax.get_ylim()),
            'visible_line_ymin':min(heights),'visible_line_ymax':max(heights),
            'margin_fraction':margin}


def save_optiland_layout(optic,filename,title=None,sensor_radius=None):
    import matplotlib.pyplot as plt
    fig,ax=optic.draw(show=False)
    try:
        if sensor_radius is not None:
            # The viewer's inferred image marker can be shorter than the saved
            # sensor. Draw the actual meridional half-span from the prescription.
            image_z=float(np.asarray(optic.surfaces.vertices_gcs)[-1,2])
            ax.plot([image_z,image_z],[-sensor_radius,sensor_radius],
                    color='#8b8b8b',linewidth=1.3,zorder=4)
        if title:ax.set_title(title,fontsize=11)
        evidence=fit_layout_axes(ax)
        fig.savefig(filename,dpi=150,bbox_inches='tight',pad_inches=.12)
        return evidence
    finally:plt.close(fig)
