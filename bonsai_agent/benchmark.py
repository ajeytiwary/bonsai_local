from __future__ import annotations
import argparse,csv,json,shutil,subprocess,tempfile,time
from pathlib import Path

def load_tasks(path): return json.loads(Path(path).read_text())["tasks"]
def _telemetry(path):
    rows=[]
    if path.exists():
        with path.open() as f: rows=list(csv.DictReader(f))
    watts=[float(r["power_w"]) for r in rows if r.get("power_w")]
    wh=0.0
    for a,b in zip(rows,rows[1:]):
        try: wh+=(float(a["power_w"])+float(b["power_w"]))/2*(float(b["ts"])-float(a["ts"]))/3600
        except (ValueError,KeyError): pass
    return {"gpu_energy_wh":wh,"peak_power_w":max(watts,default=0.0),"telemetry_samples":len(rows)}
def run_task(task,agent_cmd="bonsai-agent",timeout=1800,url="http://127.0.0.1:8091",model="Ternary-Bonsai-2-27B-PQ2_0"):
    fixture=Path(task["fixture"]).resolve()
    if not fixture.exists(): return {"id":task["id"],"split":task["split"],"tests_pass":False,"skipped":True,"error":"missing fixture "+str(fixture)}
    with tempfile.TemporaryDirectory(prefix="bonsai-bench-") as td:
        work=Path(td)/"repo"; shutil.copytree(fixture,work)
        subprocess.run(["git","init","-q"],cwd=work); subprocess.run(["git","add","."],cwd=work)
        subprocess.run(["git","-c","user.email=bench@local","-c","user.name=Bonsai Bench","commit","-qm","fixture"],cwd=work)
        start=time.time()
        cmd=[agent_cmd,"--repo",str(work),"--url",url,"--model",model,"--tests",task["test_command"],task["objective"]]
        cp=subprocess.run(cmd,text=True,capture_output=True,timeout=timeout)
        verify=subprocess.run(task["test_command"],cwd=work,shell=True,text=True,capture_output=True)
        state={}
        try:
            import sqlite3
            db=sqlite3.connect(work/".agent/state.db"); db.row_factory=sqlite3.Row
            r=db.execute("select id from runs order by id desc limit 1").fetchone()
            if r:
                u=db.execute("select count(*) calls,coalesce(sum(prompt_tokens),0) prompt_tokens,coalesce(sum(completion_tokens),0) completion_tokens,coalesce(sum(total_tokens),0) total_tokens,coalesce(sum(seconds),0) llm_seconds from llm_calls where run_id=?",(r["id"],)).fetchone()
                tc=db.execute("select count(*) n from tool_calls where run_id=?",(r["id"],)).fetchone()["n"]
                state={**dict(u),"tool_calls":tc,"run_id":r["id"]}
                state.update(_telemetry(work/".agent"/f"telemetry-{r['id']}.csv"))
        except Exception as e: state={"instrumentation_error":repr(e)}
        clean=cp.returncode==0; passed=verify.returncode==0
        return {"id":task["id"],"split":task["split"],"category":task.get("category"),"agent_exit":cp.returncode,"agent_exit_clean":clean,"tests_pass":passed,"task_success":clean and passed,"seconds":time.time()-start,**state,"stdout":cp.stdout[-4000:],"stderr":cp.stderr[-4000:]}
def main():
    p=argparse.ArgumentParser(); p.add_argument("--tasks",default="benchmarks/tasks.json"); p.add_argument("--split",choices=["train","val","test"]); p.add_argument("--out",default="benchmark-results.json")
    p.add_argument("--url",default="http://127.0.0.1:8091"); p.add_argument("--model",default="Ternary-Bonsai-2-27B-PQ2_0"); p.add_argument("--timeout",type=int,default=1800); a=p.parse_args()
    tasks=[x for x in load_tasks(a.tasks) if not a.split or x["split"]==a.split]; results=[]
    for t in tasks:
        print("RUN",t["id"],flush=True)
        try: results.append(run_task(t,timeout=a.timeout,url=a.url,model=a.model))
        except Exception as e: results.append({"id":t["id"],"split":t["split"],"tests_pass":False,"error":str(e)})
    usable=[x for x in results if not x.get("skipped")]
    payload={"results":results,
             "pass_rate":sum(x.get("tests_pass",False) for x in usable)/max(1,len(usable)),
             "clean_success_rate":sum(x.get("task_success",False) for x in usable)/max(1,len(usable)),
             "clean_exit_rate":sum(x.get("agent_exit_clean",False) for x in usable)/max(1,len(usable)),
             "total_seconds":sum(x.get("seconds",0) for x in usable),
             "total_tokens":sum(x.get("total_tokens",0) for x in usable),
             "gpu_energy_wh":sum(x.get("gpu_energy_wh",0) for x in usable)}
    Path(a.out).write_text(json.dumps(payload,indent=2)); print(json.dumps(payload,indent=2))
if __name__=="__main__": main()
