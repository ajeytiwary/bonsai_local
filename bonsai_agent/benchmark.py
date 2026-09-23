from __future__ import annotations
import argparse,json,shutil,subprocess,tempfile,time
from pathlib import Path
def load_tasks(path): return json.loads(Path(path).read_text())["tasks"]
def run_task(task,agent_cmd="bonsai-agent",timeout=1800):
    fixture=Path(task["fixture"]).resolve()
    if not fixture.exists(): return {"id":task["id"],"split":task["split"],"tests_pass":False,"skipped":True,"error":"missing fixture "+str(fixture)}
    with tempfile.TemporaryDirectory(prefix="bonsai-bench-") as td:
        work=Path(td)/"repo"; shutil.copytree(fixture,work)
        subprocess.run(["git","init","-q"],cwd=work); subprocess.run(["git","add","."],cwd=work)
        subprocess.run(["git","-c","user.email=bench@local","-c","user.name=Bonsai Bench","commit","-qm","fixture"],cwd=work)
        start=time.time(); cp=subprocess.run([agent_cmd,"--repo",str(work),"--tests",task["test_command"],task["objective"]],text=True,capture_output=True,timeout=timeout)
        verify=subprocess.run(task["test_command"],cwd=work,shell=True,text=True,capture_output=True)
        return {"id":task["id"],"split":task["split"],"agent_exit":cp.returncode,"tests_pass":verify.returncode==0,"seconds":time.time()-start,"stdout":cp.stdout[-4000:],"stderr":cp.stderr[-4000:]}
def main():
    p=argparse.ArgumentParser(); p.add_argument("--tasks",default="benchmarks/tasks.json"); p.add_argument("--split",choices=["train","val","test"]); p.add_argument("--out",default="benchmark-results.json"); a=p.parse_args()
    tasks=[x for x in load_tasks(a.tasks) if not a.split or x["split"]==a.split]; results=[]
    for t in tasks:
        print("RUN",t["id"],flush=True)
        try: results.append(run_task(t))
        except Exception as e: results.append({"id":t["id"],"split":t["split"],"tests_pass":False,"error":str(e)})
    usable=[x for x in results if not x.get("skipped")]
    payload={"results":results,"pass_rate":sum(x.get("tests_pass",False) for x in usable)/max(1,len(usable))}
    Path(a.out).write_text(json.dumps(payload,indent=2)); print(json.dumps(payload,indent=2))
if __name__=="__main__": main()
