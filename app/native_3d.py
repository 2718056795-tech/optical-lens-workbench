"""Embed the unchanged upstream mesh/ray components in their actual VTK renderers."""
import inspect,math
from pathlib import Path
import numpy as np

def make_renderer(model,engine,data,waves,interactive=False,ignore_object=True):
    if engine=='optiland':
        from optiland.visualization.system.optic_viewer_3d import OpticViewer3D
        viewer=OpticViewer3D(model)
        from view_framing import frame_3d
        object_z=None if model.object_surface.is_infinite else float(np.asarray(model.surfaces.global_z_positions).ravel()[0])
        if interactive:
            if ignore_object:
                state={'done':False}
                def frame_native_window(window,event):
                    if state['done']:return
                    renderer=window.GetRenderers().GetFirstRenderer()
                    if renderer is not None and renderer.GetActors().GetNumberOfItems():
                        frame_3d(renderer,True,object_z);state['done']=True
                viewer.ren_win.AddObserver('StartEvent',frame_native_window)
            viewer.view(fields='all',wavelengths=waves,num_rays=7,distribution='ring',dark_mode=False,hide_vignetted=False);return None
        # The native view() adds these exact components then enters iren.Start().
        # Embedding omits only the standalone event loop, never the optical/render code.
        renderer=viewer._make_renderer(False);window=viewer.ren_win
        window.SetOffScreenRendering(1);window.SetSize(1200,760);window.AddRenderer(renderer)
        viewer.rays.plot(renderer,fields='all',wavelengths=waves,num_rays=7,distribution='ring',hide_vignetted=False)
        viewer.system.plot(renderer)
        framing=frame_3d(renderer,ignore_object,object_z)
        camera=renderer.GetActiveCamera();camera.SetPosition(1,0,0);camera.SetFocalPoint(0,0,0);camera.SetViewUp(0,1,0);renderer.ResetCamera();camera.Azimuth(150)
        return renderer,window,dict(native_viewer=inspect.getfile(OpticViewer3D),native_components=['OpticViewer3D._make_renderer','Rays3D.plot','OpticalSystem.plot'],displayed_field_count=len(model.fields.fields),field_sampling='all original fields',view_framing=framing),viewer
    from native_sources import configure_analysis_runtime
    configure_analysis_runtime()
    import pyvista as pv
    plotter=pv.Plotter(off_screen=not interactive,window_size=(1200,760))
    fields=data.get('design_fields',[]);pairs=[]
    for f in fields:
        if data.get('object_at_infinity'):
            tx,ty=math.tan(math.radians(f['x'])),math.tan(math.radians(f['y']))
        else:
            distance=abs(float(data['obj_depth']));tx,ty=float(f['object_x_mm'])/distance,float(f['object_y_mm'])/distance
        pairs.append((math.degrees(math.atan(math.hypot(tx,ty))),math.degrees(math.atan2(ty,tx))))
    if not pairs:pairs=[(0.,90.),(math.degrees(float(model.rfov))*.7,90.),(math.degrees(float(model.rfov)),90.)]
    model.draw_lens_3d(plotter=plotter,draw_rays=False,ray_rings=2,ray_arms=8,mesh_rings=24,mesh_arms=64,is_wrap=False)
    from deeplens.geolens_pkg.vis3d import geolens_ray_poly,curve_list_to_polydata,merge,_wrap_base_poly_to_pyvista
    empty_fields=0
    for polar,azimuth in pairs:
        for curves in geolens_ray_poly(model,[polar],[azimuth],n_rings=2,n_arms=8):
            polygons=curve_list_to_polydata(curves)
            if not polygons:empty_fields+=1;continue
            mesh=_wrap_base_poly_to_pyvista(merge(polygons),pv)
            if mesh.n_points:plotter.add_mesh(mesh)
            else:empty_fields+=1
    from view_framing import frame_3d
    framing=frame_3d(plotter.renderer,ignore_object)
    plotter.view_isometric();plotter.reset_camera()
    if interactive:plotter.show();return None
    return plotter.renderer,plotter.render_window,dict(native_viewer=inspect.getfile(type(model).draw_lens_3d),native_components=['GeoLens.draw_lens_3d','geolens_ray_poly','PyVista.Plotter / VTK'],displayed_field_count=len(pairs),fields_without_visible_paths=empty_fields,field_directions_deg=pairs,field_sampling='each saved field; native parallel ray convention',view_framing=framing),plotter

def render(model,engine,data,r):
    import vtk
    ignore=r.req['options'].get('ignore_object',True)
    renderer,window,audit,owner=make_renderer(model,engine,data,r.waves,ignore_object=ignore)
    actors=renderer.GetActors();actors.InitTraversal();points=[];line_count=0
    for i in range(actors.GetNumberOfItems()):
        actor=actors.GetNextActor();mapper=actor.GetMapper()
        if not actor.GetVisibility():continue
        if mapper is None:continue
        mapper.Update();poly=mapper.GetInput()
        if poly is not None and poly.GetNumberOfPoints():
            from vtk.util.numpy_support import vtk_to_numpy
            p=np.array(vtk_to_numpy(poly.GetPoints().GetData()),copy=True);points.append(p);r.arrays[f'native_3d.actor.{i}.points']=p
            if hasattr(poly,'GetNumberOfLines'):line_count+=poly.GetNumberOfLines()
    if not points:raise ValueError('原生3D未产生几何数据')
    images=[];camera=renderer.GetActiveCamera();saved=vtk.vtkCamera();saved.DeepCopy(camera)
    try:
        for label,az,el in [('原生斜视',0,0),('原生旋转视图',60,20),('原生反向视图',150,-10)]:
            camera.DeepCopy(saved);camera.Azimuth(az);camera.Elevation(el);renderer.ResetCameraClippingRange();window.Render()
            name=f'plot_{len(images)+1:02d}.png';grab=vtk.vtkWindowToImageFilter();grab.SetInput(window);grab.ReadFrontBufferOff();grab.Update()
            writer=vtk.vtkPNGWriter();writer.SetFileName(str(r.out/name));writer.SetInputConnection(grab.GetOutputPort());writer.Write()
            images.append(dict(file=name,label=engine+' · '+label+' · 原生VTK渲染'))
        r.images+=images;r.summary.update(native_3d=dict(**audit,actors=actors.GetNumberOfItems(),line_cells=line_count,point_count=sum(len(p) for p in points),renderer='native VTK',interactive_available=True))
        r.notes+=['3D几何、光线与渲染来自所选内核原生组件，不是工作台几何查看器。页面提供原生渲染的三个视角；“打开原生交互窗口”可在该内核原生窗口拖动/缩放。']
        r.notes+=['忽略物面已开启：只裁切原生显示中远离镜组的物方部分并重新适配视图，实际物距、追迹和优化不变。' if ignore else '忽略物面已关闭：显示原生完整物方光路；长物距可能使镜组显得很小。']
        if engine=='autolens':r.notes+=['本固定版AutoLens原生3D采用主波长、平行光采样；其有限物距3D光线不等同有限物点追迹，未替换原生算法。有限物距实际通光请看该内核2D/点列，或选择Optiland原生3D。']
    finally:
        if engine=='autolens':owner.close()
        else:window.Finalize()
