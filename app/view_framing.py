"""Read-only framing of native plotted paths and meshes; never optical inputs."""
import hashlib
import numpy as np


def frame_2d(ax,z_bounds,radius,ignore_object=True):
    """Limit display only; intersect crossing ray segments to avoid clipped bundles."""
    radius=max(float(radius),1e-6);left,right=map(float,z_bounds)
    pad=max((right-left)*.05,radius,.5)
    lo,hi=left-pad,right+pad
    if not ignore_object:
        points=[line.get_xydata() for line in ax.lines]
        points=np.concatenate(points) if points else np.empty((0,2))
        points=points[np.isfinite(points).all(axis=1)]
        if len(points):
            lo=min(lo,float(points[:,0].min()));hi=max(hi,float(points[:,0].max()))
            pad=max((hi-lo)*.02,.5);lo-=pad;hi+=pad
    heights=[radius]
    for line in ax.lines:
        xy=line.get_xydata()
        for a,b in zip(xy[:-1],xy[1:]):
            if not np.isfinite([a,b]).all():continue
            for x,y in (a,b):
                if lo<=x<=hi:heights.append(abs(float(y)))
            for x in (lo,hi):
                if min(a[0],b[0])<=x<=max(a[0],b[0]) and abs(b[0]-a[0])>1e-12:
                    heights.append(abs(float(a[1]+(b[1]-a[1])*(x-a[0])/(b[0]-a[0]))))
    h=max(heights)*1.08;ax.set_xlim(lo,hi);ax.set_ylim(-h,h)
    return dict(ignore_object=bool(ignore_object),xlim_mm=[lo,hi],ylim_mm=[-h,h],optical_inputs_changed=False)


def frame_3d(renderer,ignore_object=True,object_z=None):
    """Clip native display actors before the physical train, retaining source meshes.

    Native actor matrices are respected: the world-space plane is transformed
    into each mapper's local frame. No ray or model is retraced or changed.
    """
    import vtk
    actors=renderer.GetActors();actors.InitTraversal();entries=[];geometry=[];hidden=[]
    for _ in range(actors.GetNumberOfItems()):
        actor=actors.GetNextActor();mapper=actor.GetMapper()
        if mapper is None:continue
        mapper.Update();poly=mapper.GetInput()
        if poly is None or not poly.GetNumberOfPoints():continue
        bounds=np.asarray(actor.GetBounds(),float)
        if not np.isfinite(bounds).all():continue
        obj=object_z is not None and abs(bounds[4]-object_z)<1e-5 and abs(bounds[5]-object_z)<1e-5
        entries.append((actor,mapper,poly,bounds,obj))
        if obj:hidden.append(actor)
        elif poly.GetNumberOfPolys()+poly.GetNumberOfStrips()>0:geometry.append(bounds)
    audit=dict(ignore_object=bool(ignore_object),optical_inputs_changed=False,object_actors_hidden=0,actors_clipped=0)
    from vtk.util.numpy_support import vtk_to_numpy
    digest=hashlib.sha256()
    for actor,mapper,poly,bounds,obj in entries:
        digest.update(np.ascontiguousarray(vtk_to_numpy(poly.GetPoints().GetData())).tobytes())
        matrix=actor.GetMatrix();digest.update(np.array([[matrix.GetElement(i,j) for j in range(4)] for i in range(4)]).tobytes())
    audit['native_geometry_sha256']=digest.hexdigest()
    if not ignore_object:return audit
    if not geometry:raise ValueError('没有可用于视图适配的原生镜组几何，未擅自截断显示')
    bounds=np.asarray(geometry);left=float(bounds[:,4].min());right=float(bounds[:,5].max());pad=max((right-left)*.05,.5);cut=left-pad
    audit.update(near_train_z_mm=[left,right],display_cut_z_mm=cut)
    for actor in hidden:actor.SetVisibility(False)
    audit['object_actors_hidden']=len(hidden)
    for actor,mapper,poly,bounds,obj in entries:
        if obj:continue
        if bounds[4]>=cut:continue
        if bounds[5]<cut:actor.SetVisibility(False);continue
        matrix=actor.GetMatrix();mat=np.array([[matrix.GetElement(i,j) for j in range(4)] for i in range(4)])
        origin=np.linalg.solve(mat,np.array([0.,0.,cut,1.]))[:3];normal=mat[:3,:3].T@np.array([0.,0.,1.])
        plane=vtk.vtkPlane();plane.SetOrigin(*origin);plane.SetNormal(*normal)
        clip=vtk.vtkClipPolyData();clip.SetClipFunction(plane);clip.SetInputData(poly);clip.InsideOutOff();clip.Update()
        mapper.SetInputConnection(clip.GetOutputPort());mapper.Update();audit['actors_clipped']+=1
    return audit
