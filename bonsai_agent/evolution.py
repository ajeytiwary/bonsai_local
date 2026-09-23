from __future__ import annotations
import argparse,copy,json,random
from dataclasses import dataclass
from pathlib import Path
@dataclass
class Genome:
    planner_prompt:str; worker_prompt:str; verifier_prompt:str
    max_steps:int=30; max_repairs:int=3; retrieve_top_k:int=8; compact_every:int=4; worker_temperature:float=0.1
def mutate(g,reflector,feedback):
    ng=copy.deepcopy(g); target=random.choice(["planner_prompt","worker_prompt","verifier_prompt"]); old=getattr(ng,target)
    setattr(ng,target,reflector("Improve this agent component from benchmark feedback. Preserve JSON contracts.\nCOMPONENT:"+target+"\nCURRENT:\n"+old+"\nFEEDBACK:\n"+feedback))
    if random.random()<.4: ng.retrieve_top_k=max(3,min(16,ng.retrieve_top_k+random.choice([-2,2])))
    return ng
def pareto_front(rows):
    def dominates(a,b): return a["pass_rate"]>=b["pass_rate"] and a["seconds"]<=b["seconds"] and (a["pass_rate"]>b["pass_rate"] or a["seconds"]<b["seconds"])
    return [a for a in rows if not any(dominates(b,a) for b in rows if b is not a)]
def export_gepa_dataset(results_path,out_path):
    data=json.loads(Path(results_path).read_text()); rows=[{"input":{"task_id":r["id"]},"score":1.0 if r.get("tests_pass") else 0.0,"feedback":r.get("stderr","")+r.get("stdout","")} for r in data["results"]]
    Path(out_path).write_text(json.dumps(rows,indent=2))
def main():
    p=argparse.ArgumentParser(); p.add_argument("--export-gepa",metavar="RESULTS"); p.add_argument("--out",default="gepa-dataset.json"); a=p.parse_args()
    if a.export_gepa: export_gepa_dataset(a.export_gepa,a.out); print(a.out)
if __name__=="__main__": main()
