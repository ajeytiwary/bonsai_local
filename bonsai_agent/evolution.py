from __future__ import annotations
import argparse,copy,json,random
from dataclasses import asdict,dataclass
from pathlib import Path
from .prompts import PLANNER,WORKER,VERIFIER
@dataclass
class Genome:
    planner_prompt:str=PLANNER; worker_prompt:str=WORKER; verifier_prompt:str=VERIFIER
    max_steps:int=30; max_repairs:int=3; retrieve_top_k:int=8; compact_every:int=4; worker_temperature:float=0.1
def fitness(data):
    rows=[r for r in data.get("results",[]) if not r.get("skipped")]
    return {"pass_rate":sum(r.get("tests_pass",False) for r in rows)/max(1,len(rows)),
            "seconds":sum(r.get("seconds",0) for r in rows),
            "tokens":sum(r.get("total_tokens",0) for r in rows),
            "gpu_energy_wh":sum(r.get("gpu_energy_wh",0) for r in rows)}
def dominates(a,b):
    return a["pass_rate"]>=b["pass_rate"] and a["seconds"]<=b["seconds"] and a["tokens"]<=b["tokens"] and a["gpu_energy_wh"]<=b["gpu_energy_wh"] and any(a[k]!=b[k] for k in ("pass_rate","seconds","tokens","gpu_energy_wh"))
def pareto_front(rows): return [a for a in rows if not any(dominates(b["fitness"],a["fitness"]) for b in rows if b is not a)]
def promote(baseline,candidate):
    # Safety-first: never accept lower correctness. With equal correctness require a resource win.
    if candidate["pass_rate"]<baseline["pass_rate"]: return False
    if candidate["pass_rate"]>baseline["pass_rate"]: return True
    return candidate["seconds"]<baseline["seconds"] or candidate["tokens"]<baseline["tokens"] or candidate["gpu_energy_wh"]<baseline["gpu_energy_wh"]
def export_gepa_dataset(results_path,out_path):
    data=json.loads(Path(results_path).read_text()); rows=[{"input":{"task_id":r["id"],"category":r.get("category")},"score":1.0 if r.get("tests_pass") else 0.0,"feedback":r.get("stderr","")+r.get("stdout",""),"metrics":{k:r.get(k,0) for k in ("seconds","total_tokens","gpu_energy_wh","tool_calls")}} for r in data["results"]]
    Path(out_path).write_text(json.dumps(rows,indent=2))
def seed(out):
    Path(out).write_text(json.dumps(asdict(Genome()),indent=2))
def compare(base,candidate,out=None):
    b=fitness(json.loads(Path(base).read_text())); c=fitness(json.loads(Path(candidate).read_text())); result={"baseline":b,"candidate":c,"promote":promote(b,c)}
    if out: Path(out).write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
def main():
    p=argparse.ArgumentParser(); p.add_argument("--export-gepa",metavar="RESULTS"); p.add_argument("--seed",action="store_true"); p.add_argument("--compare",nargs=2,metavar=("BASELINE","CANDIDATE")); p.add_argument("--out",default="gepa-dataset.json"); a=p.parse_args()
    if a.export_gepa: export_gepa_dataset(a.export_gepa,a.out); print(a.out)
    elif a.seed: seed(a.out); print(a.out)
    elif a.compare: compare(*a.compare,a.out)
    else: p.error("choose --seed, --export-gepa, or --compare")
if __name__=="__main__": main()
