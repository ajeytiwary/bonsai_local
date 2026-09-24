from __future__ import annotations
import json,time
from pathlib import Path
from .db import StateDB
from .prompts import PLANNER,WORKER,VERIFIER,COMPACTOR
from .retrieval import RepoRetriever
from .telemetry import Telemetry
from .tools import WorkspaceTools

class Agent:
    def __init__(self,root,llm,tests="pytest -q",max_steps=100,compact_every=5,max_repairs=3,retrieve_top_k=8,unsafe_shell=False,auto_commit=True):
        self.root=Path(root).resolve(); self.llm=llm; self.tests=tests; self.max_steps=max_steps; self.compact_every=compact_every
        self.max_repairs=max_repairs; self.retrieve_top_k=retrieve_top_k; self.auto_commit=auto_commit
        self.db=StateDB(self.root/".agent/state.db"); self.tools=WorkspaceTools(self.root,unsafe_shell=unsafe_shell)
        self.retrieve=RepoRetriever(self.root)
        self._rid=None; self._tid=None
        if hasattr(self.llm,"bind"): self.llm.bind(self._observe_llm)

    def _observe_llm(self,meta):
        if self._rid is None: return
        self.db.log_llm(self._rid,self._tid,meta.get("role","unknown"),meta.get("usage"),meta.get("seconds",0))
        self.db.event(self._rid,self._tid,"llm",meta)

    def _role(self,role,tid=None):
        self._tid=tid
        if hasattr(self.llm,"role"): self.llm.role=role

    def start(self,objective):
        rid=self.db.create_run(objective,str(self.root)); self._rid=rid; self._role("planner")
        task_md=""
        p=self.root/"TASK.md"
        if p.exists(): task_md=p.read_text(errors="replace")[:12000]
        plan_prompt="OBJECTIVE:\n"+objective+"\n\nTASK.md:\n"+task_md+"\n\nREPO MAP:\n"+self.retrieve.repo_map()
        try:
            plan=self.llm.json(PLANNER,plan_prompt,700,expected="plan")
        except Exception as e:
            # Planning must not make the whole coding run unusable. A single direct
            # implementation task is a safe deterministic fallback.
            self.db.event(rid,None,"planner_fallback",{"error":repr(e)})
            plan={"tasks":[{"title":"Implement acceptance task","description":objective+"\nTASK.md:\n"+task_md,"acceptance":"Configured acceptance tests pass and benchmark tests remain unchanged.","depends_on":[]}]}
        ids=[]
        for i,t in enumerate(plan.get("tasks",[])):
            tid=self.db.add_task(rid,t["title"],t["description"],t.get("acceptance",""),t.get("depends_on",[])); ids.append(tid)
        self.db.event(rid,None,"plan",plan)
        return rid

    def run(self,rid):
        self._rid=rid
        run=self.db.get_run(rid)
        if not run: raise ValueError("unknown run "+str(rid))
        self.db.set_run_status(rid,"running")
        telemetry=Telemetry(self.root/".agent"/f"telemetry-{rid}.csv"); telemetry.start()
        try:
            completed=0
            while completed<self.max_steps:
                task=self.db.next_task(rid)
                if not task: break
                self.execute_task(rid,task,run["objective"]); completed+=1
                if completed%self.compact_every==0: self.compact(rid,run["objective"])
            remaining=[t for t in self.db.tasks(rid) if t["status"] not in ("done","blocked")]
            self.db.set_run_status(rid,"complete" if not remaining else "paused")
        except KeyboardInterrupt:
            self.db.set_run_status(rid,"paused"); raise
        except Exception as e:
            self.db.event(rid,None,"crash",{"error":repr(e)}); self.db.set_run_status(rid,"paused"); raise
        finally: telemetry.stop()

    def execute_task(self,rid,task,objective):
        self._role("worker",task["id"])
        self.db.update_task(task["id"],status="running",attempts=task["attempts"]+1)
        transcript=[]
        for _ in range(20):
            relevant=self.retrieve.search(task["title"]+" "+task["description"],self.retrieve_top_k)
            checkpoint=self.db.latest_checkpoint(rid)
            prompt=f"""OBJECTIVE: {objective}
TASK: {task['title']}
DESCRIPTION: {task['description']}
ACCEPTANCE: {task['acceptance']}
CHECKPOINT: {checkpoint[-5000:]}
RELEVANT REPOSITORY CONTEXT:
{json.dumps(relevant,ensure_ascii=False)[:18000]}
RECENT OBSERVATIONS:
{json.dumps(transcript[-5:],ensure_ascii=False)[:10000]}
Choose one next action."""
            self._role("worker",task["id"]); try:
                action=self.llm.json(WORKER,prompt,650,expected="action",retries=1)
            except Exception as e:
                # A malformed worker response is recoverable; record it as an
                # observation instead of crashing the entire benchmark case.
                self.db.event(rid,task["id"],"worker_parse_error",{"error":repr(e)})
                transcript.append({"tool":"worker_protocol","output":"Previous response was not a valid action object. Emit exactly one tool action with args, or done=true."})
                continue
            self.db.event(rid,task["id"],"worker",action)
            if action.get("done"):
                return self.verify(rid,task)
            name,args=action.get("tool"),action.get("args",{})
            try: out=self.tools.execute(name,args); ok=not out.startswith("BLOCKED:")
            except Exception as e: out="ERROR: "+repr(e); ok=False
            self.db.log_tool(rid,task["id"],name,args,out,ok); transcript.append({"tool":name,"output":out[-8000:]})
        self.db.update_task(task["id"],status="failed",result="worker step budget exhausted")

    def verify(self,rid,task):
        for repair in range(self.max_repairs+1):
            tests=self.tools.run_tests(self.tests); diff=self.tools.git_diff()
            evidence=f"TASK:{json.dumps(task)}\nTESTS:\n{tests[-16000:]}\nDIFF:\n{diff[-24000:]}"
            self._role("verifier",task["id"])
            try:
                verdict=self.llm.json(VERIFIER,evidence,350,expected="verdict")
            except Exception as e:
                self.db.event(rid,task["id"],"verifier_fallback",{"error":repr(e)})
                verdict={"verdict":"PASS" if tests.startswith("exit=0") else "FAIL","reason":"Deterministic fallback from external test exit status after structured verifier failure.","repair":"Fix the failing configured tests."}
            self.db.event(rid,task["id"],"verify",verdict)
            if verdict.get("verdict")=="PASS" and tests.startswith("exit=0"):
                commit=""
                if self.auto_commit:
                    commit=self.tools.verified_commit("bonsai: "+task["title"])
                self.db.update_task(task["id"],status="done",result=verdict.get("reason","")+" "+commit)
                return True
            if verdict.get("verdict")=="BLOCKED":
                self.db.update_task(task["id"],status="blocked",result=verdict.get("reason","")); return False
            if repair<self.max_repairs:
                repair_task={"title":task["title"],"description":verdict.get("repair","Repair failed verification"),"acceptance":task["acceptance"]}
                self._role("repair",task["id"]); action=self.llm.json(WORKER,"REPAIR:\n"+json.dumps(repair_task)+"\nEVIDENCE:\n"+evidence[-24000:],650,expected="action",retries=1)
                if action.get("tool"):
                    try: out=self.tools.execute(action["tool"],action.get("args",{})); ok=not out.startswith("BLOCKED:")
                    except Exception as e: out="ERROR: "+repr(e); ok=False
                    self.db.log_tool(rid,task["id"],action["tool"],action.get("args",{}),out,ok)
        self.db.update_task(task["id"],status="failed",result="verification/repair budget exhausted"); return False

    def compact(self,rid,objective):
        state={"objective":objective,"tasks":self.db.tasks(rid),"recent_events":self.db.events(rid,30)}
        self._role("compactor"); summary=self.llm.chat([{"role":"system","content":COMPACTOR},{"role":"user","content":json.dumps(state,ensure_ascii=False)[:26000]}],900,.1)
        self.db.checkpoint(rid,summary)

    def status(self,rid):
        return {"run":self.db.get_run(rid),"tasks":self.db.tasks(rid),"checkpoint":self.db.latest_checkpoint(rid),"llm":self.db.llm_summary(rid)}
