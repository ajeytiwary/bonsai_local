from __future__ import annotations
import csv,subprocess,threading,time
from pathlib import Path
class Telemetry:
    def __init__(self,path:Path,interval=1.0): self.path=path; self.interval=interval; self.stop_event=threading.Event(); self.thread=None
    def start(self): self.path.parent.mkdir(parents=True,exist_ok=True); self.thread=threading.Thread(target=self._loop,daemon=True); self.thread.start()
    def stop(self):
        self.stop_event.set()
        if self.thread: self.thread.join(timeout=3)
    def _loop(self):
        while not self.stop_event.is_set():
            row={"ts":time.time()}
            try:
                out=subprocess.check_output(["nvidia-smi","--query-gpu=utilization.gpu,memory.used,power.draw,temperature.gpu","--format=csv,noheader,nounits"],text=True,timeout=2).strip().splitlines()[0]
                u,m,p,t=[float(x.strip()) for x in out.split(",")]; row.update(gpu_util=u,vram_mb=m,power_w=p,temp_c=t)
            except Exception: row.update(gpu_util="",vram_mb="",power_w="",temp_c="")
            exists=self.path.exists() and self.path.stat().st_size>0
            with self.path.open("a",newline="") as f:
                w=csv.DictWriter(f,fieldnames=row.keys())
                if not exists: w.writeheader()
                w.writerow(row)
            self.stop_event.wait(self.interval)
