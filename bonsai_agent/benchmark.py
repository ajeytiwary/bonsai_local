from __future__ import annotations
import argparse,csv,json,os,shutil,subprocess,sys,tempfile,time
from pathlib import Path


def load_tasks(path):
    return json.loads(Path(path).read_text())["tasks"]


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
    if not fixture.exists():
        return {"id":task["id"],"split":task["split"],"tests_pass":False,"clean":False,"skipped":True,"error":"missing fixture "+str(fixture)}
    with tempfile.TemporaryDirectory(prefix="bonsai-bench-") as td:
        work=Path(td)/"repo"; shutil.copytree(fixture,work)
        subprocess.run(["git","init","-q"],cwd=work,check=True)
        subprocess.run(["git","add","."],cwd=work,check=True)
        subprocess.run(["git","-c","user.email=bench@local","-c","user.name=Bonsai Bench","commit","-qm","fixture"],cwd=work,check=True)
        start=time.time()
        env={**os.environ,"PATH":str(Path(sys.executable).parent)+os.pathsep+os.environ.get("PATH",""),
             "PYTHONDONTWRITEBYTECODE":"1","PYTEST_ADDOPTS":"-p no:cacheprovider"}
        cmd=[agent_cmd,"--single-task","--verify-tests-only","--repo",str(work),"--url",url,"--model",model,"--tests",task["test_command"],task["objective"]]
        try:
            cp=subprocess.run(cmd,text=True,capture_output=True,timeout=timeout,env=env)
            agent_exit=cp.returncode; stdout=cp.stdout[-4000:]; stderr=cp.stderr[-4000:]
        except subprocess.TimeoutExpired as e:
            agent_exit=-1; stdout=(e.stdout or b"").decode(errors="replace")[-4000:] if isinstance(e.stdout,bytes) else (e.stdout or "")[-4000:]
            stderr=(e.stderr or b"").decode(errors="replace")[-4000:] if isinstance(e.stderr,bytes) else (e.stderr or "")[-4000:]
            stderr+="\nAgent timed out"
        verify=subprocess.run(task["test_command"],cwd=work,shell=True,text=True,capture_output=True,env=env)
        status=subprocess.run(["git","status","--porcelain"],cwd=work,text=True,capture_output=True)
        test_files=sorted(p.name for p in fixture.glob("test*.py"))
        tests_unchanged=all((work/name).is_file() and (work/name).read_bytes()==(fixture/name).read_bytes() for name in test_files)
        state={}; run_status=None; task_statuses=[]
        try:
            import sqlite3
            db=sqlite3.connect(work/".agent/state.db"); db.row_factory=sqlite3.Row
            r=db.execute("select id,status from runs order by id desc limit 1").fetchone()
            if r:
                run_status=r["status"]
                task_statuses=[x["status"] for x in db.execute("select status from tasks where run_id=?",(r["id"],))]
                u=db.execute("select count(*) calls,coalesce(sum(prompt_tokens),0) prompt_tokens,coalesce(sum(completion_tokens),0) completion_tokens,coalesce(sum(total_tokens),0) total_tokens,coalesce(sum(seconds),0) llm_seconds from llm_calls where run_id=?",(r["id"],)).fetchone()
                tc=db.execute("select count(*) n from tool_calls where run_id=?",(r["id"],)).fetchone()["n"]
                state={**dict(u),"tool_calls":tc,"run_id":r["id"]}
                state.update(_telemetry(work/".agent"/f"telemetry-{r['id']}.csv"))
        except Exception as e:
            state={"instrumentation_error":repr(e)}
        tests_pass=verify.returncode==0
        clean=(agent_exit==0 and tests_pass and tests_unchanged and run_status=="complete" and bool(task_statuses) and all(s=="done" for s in task_statuses))
        return {"id":task["id"],"split":task["split"],"category":task.get("category"),"agent_exit":agent_exit,
                "tests_pass":tests_pass,"tests_unchanged":tests_unchanged,"run_status":run_status,"task_statuses":task_statuses,
                "clean":clean,"seconds":time.time()-start,**state,"git_status":status.stdout[-1000:],"test_stdout":verify.stdout[-2000:],
                "test_stderr":verify.stderr[-2000:],"stdout":stdout,"stderr":stderr}


def main():
    p=argparse.ArgumentParser(); p.add_argument("--tasks",default="benchmarks/tasks.json"); p.add_argument("--split",choices=["train","val","test"]); p.add_argument("--out",default="benchmark-results.json")
    p.add_argument("--url",default="http://127.0.0.1:8091"); p.add_argument("--model",default="Ternary-Bonsai-2-27B-PQ2_0"); p.add_argument("--timeout",type=int,default=1800); a=p.parse_args()
    tasks=[x for x in load_tasks(a.tasks) if not a.split or x["split"]==a.split]; results=[]
    for t in tasks:
        print("RUN",t["id"],flush=True)
        try: results.append(run_task(t,timeout=a.timeout,url=a.url,model=a.model))
        except Exception as e: results.append({"id":t["id"],"split":t["split"],"tests_pass":False,"clean":False,"error":str(e)})
        Path(a.out).write_text(json.dumps({"results":results},indent=2))
        print("RESULT",t["id"],"CLEAN" if results[-1].get("clean") else "FAIL",flush=True)
    payload={"results":results,"clean_count":sum(x.get("clean",False) for x in results),"total_tasks":len(tasks),
             "pass_rate":sum(x.get("clean",False) for x in results)/max(1,len(tasks)),
             "total_seconds":sum(x.get("seconds",0) for x in results),"total_tokens":sum(x.get("total_tokens",0) for x in results),
             "gpu_energy_wh":sum(x.get("gpu_energy_wh",0) for x in results)}
    Path(a.out).write_text(json.dumps(payload,indent=2)); print(json.dumps(payload,indent=2))
if __name__=="__main__": main()
