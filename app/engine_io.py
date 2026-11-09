"""Engine-neutral JSON IO and numeric input helpers; no optical engine imports."""
import json,math,os,time
from pathlib import Path

def write_json(path, data):
    def clean(value):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(v) for v in value]
        return value
    tmp = str(path) + ".tmp"
    Path(tmp).write_text(json.dumps(clean(data), ensure_ascii=True, indent=1, allow_nan=False),
                         encoding="utf-8")
    # Windows readers may briefly open the destination without delete sharing.
    # Keep the atomic replacement; retry transient sharing violations only.
    for attempt in range(8):
        try:
            os.replace(tmp,path)
            break
        except PermissionError:
            if attempt==7:raise
            time.sleep(.01*2**attempt)

def opt(params, key, default=None):
    """Read an optional numeric param; empty string / None -> default."""
    v = params.get(key, None)
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default

class StopRequested(Exception):
    pass
