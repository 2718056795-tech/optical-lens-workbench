"""External cancellation at native Python boundaries; no solver/math changes."""
import time
from pathlib import Path


class CancellationProbe:
    def __init__(self,folder,source_roots,exception,protect_mutations=False):
        self.flag=Path(folder)/'stop.flag';self.roots=tuple(str(Path(p).resolve()) for p in source_roots)
        self.exception=exception;self.protect=protect_mutations;self.active=False;self.next_check=0.;self.requested=False
    def check(self,frame,event):
        if not self.active or event not in ('call','return') or not frame.f_code.co_filename.startswith(self.roots):return
        now=time.monotonic()
        if now>=self.next_check:self.requested=self.flag.exists();self.next_check=now+.05
        if not self.requested:return
        if self.protect:
            # Finish in-place shape/material/optimizer updates before saving.
            names={'shape','correct_shape','prune','prune_surf','post','post_computation','initialize','project','restore_materials','set_target_fov_fnum','set_fnum','update_r','get_optimizer','step','write','write_lens_json','match_materials'}
            parent=frame.f_back
            while parent:
                if parent.f_code.co_name in names:return
                parent=parent.f_back
        self.active=False
        raise self.exception('用户请求停止：已到达可保存的计算边界')
