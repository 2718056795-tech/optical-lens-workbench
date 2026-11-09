"""Output provenance only; no optical calculations or live-model mutation."""
import hashlib,json
from pathlib import Path
from engine_io import write_json

def source_marker(path,root=None):
    path=Path(path)
    return dict(source_file=path.relative_to(root).as_posix() if root else path.name,source_sha256=hashlib.sha256(path.read_bytes()).hexdigest())

def bind_layout(root,source,image):
    root=Path(root);source=Path(source);image=Path(image)
    if not source.is_file() or not image.is_file():return
    try:table=json.loads((root/'layout_bindings.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):table={}
    if not isinstance(table,dict):table={}
    key=image.relative_to(root).as_posix()
    table[key]=dict(source_marker(source,root),image_sha256=hashlib.sha256(image.read_bytes()).hexdigest())
    write_json(root/'layout_bindings.json',table)

def record_snapshot(state,source,root,image=None):
    """Optional bookkeeping must never fail an otherwise valid optical step."""
    state.pop('metrics_source',None)
    try:
        state['metrics_source']=source_marker(source,root)
        if image is not None:bind_layout(root,source,image)
    except (OSError,ValueError,TypeError) as exc:
        state['output_provenance_warning']=str(exc)

def record_comparison(state,params,root):
    """Report existing results only; failures leave finalization available."""
    if params.get('resume_phase')=='finalize':return
    metrics=state.get('metrics_final') or state.get('metrics_current')
    if not metrics:return
    record_snapshot(state,Path(root)/'final_lens.json',root)
    marker=state.get('metrics_source')
    if not marker:return
    try:
        from result_comparison import compare
        write_json(Path(root)/'comparison_report.json',compare(params,metrics,**marker))
    except (OSError,ValueError,TypeError) as exc:
        state['comparison_report_warning']=str(exc)
