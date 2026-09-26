from __future__ import annotations
import json,time
from pathlib import Path
from .db import StateDB
from .prompts import PLANNER,WORKER,VERIFIER,COMPACTOR
from .retrieval import RepoRetriever
from .telemetry import Telemetry
from .tools import WorkspaceTools
from .context import ContextBudget, fit_to_budget, usage_of
from .transcripts import validate_transcript
from .repo_index import RepoIndex
from . import gitwork
from . import checkpoints as ckpt_mod
from .progress import Progress, EventLog
from . import testscope

# tools that constitute a source edit (made_edit / repair loop tracking)
EDIT_TOOLS=("write_file","replace_in_file","apply_patch","create_file")

class Agent:
    def __init__(self,root,llm,tests="pytest -q",max_steps=100,compact_every=5,max_repairs=3,retrieve_top_k=8,unsafe_shell=False,auto_commit=True,verify_tests_only=False,worker_output_tokens=8192,context_total=65536,progress_sink=None):
        if worker_output_tokens<1024: raise ValueError("worker_output_tokens must be at least 1024")
        self.worker_output_tokens=worker_output_tokens
        self.root=Path(root).resolve(); self.llm=llm; self.tests=tests; self.max_steps=max_steps; self.compact_every=compact_every
        self.max_repairs=max_repairs; self.retrieve_top_k=retrieve_top_k; self.auto_commit=auto_commit; self.verify_tests_only=verify_tests_only
        self.db=StateDB(self.root/".agent/state.db"); self.tools=WorkspaceTools(self.root,unsafe_shell=unsafe_shell)
        self.retrieve=RepoRetriever(self.root)
        self.index=RepoIndex(self.root)
        self.budget=ContextBudget(total=context_total)
        self.progress=Progress(sink=progress_sink,model=getattr(llm,"model",""),harness="bonsai_local")
        self.events=EventLog(self.root/".agent"/"events.jsonl")
        self._rid=None; self._tid=None
        self._baseline=None; self._protected_before=None
        if hasattr(self.llm,"bind"): self.llm.bind(self._observe_llm)

    def _observe_llm(self,meta):
        if self._rid is None: return
        self.db.log_llm(self._rid,self._tid,meta.get("role","unknown"),meta.get("usage"),meta.get("seconds",0))
        self.db.event(self._rid,self._tid,"llm",meta)

    def _role(self,role,tid=None):
        self._tid=tid
        if hasattr(self.llm,"role"): self.llm.role=role

    def start(self,objective,single_task=False):
        rid=self.db.create_run(objective,str(self.root)); self._rid=rid; self._role("planner")
        task_md=""
        p=self.root/"TASK.md"
        if p.exists(): task_md=p.read_text(errors="replace")[:12000]
        if single_task:
            self.db.add_task(rid,"Complete TASK.md acceptance task",objective+"\nTASK.md:\n"+task_md,"Complete TASK.md requirements; configured tests pass and benchmark tests remain unchanged.")
            self.db.event(rid,None,"plan",{"mode":"single_task"})
            return rid
        plan_prompt="OBJECTIVE:\n"+objective+"\n\nTASK.md:\n"+task_md+"\n\nREPO MAP:\n"+self.retrieve.repo_map()
        try:
            plan=self.llm.json(PLANNER,plan_prompt,1200,expected="plan",retries=1,reasoning_budget=0)
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
        self.progress.run_id=rid
        run=self.db.get_run(rid)
        if not run: raise ValueError("unknown run "+str(rid))
        self.db.set_run_status(rid,"running")
        # M4: baseline + protected-test snapshot at run start (safe staging).
        try:
            self._baseline=gitwork.capture_baseline(self.root)
            self._protected_before=testscope.snapshot_protected(self.root)
        except Exception:
            self._baseline=None; self._protected_before=None
        self.progress.phase(None,"run_start",run["objective"][:160])
        t0=time.perf_counter()
        telemetry=Telemetry(self.root/".agent"/f"telemetry-{rid}.csv"); telemetry.start()
        try:
            completed=0
            while completed<self.max_steps:
                task=self.db.next_task(rid)
                if not task: break
                self.execute_task(rid,task,run["objective"]); completed+=1
                if completed%self.compact_every==0: self.compact(rid,run["objective"])
            remaining=[t for t in self.db.tasks(rid) if t["status"]!="done"]
            final="complete" if not remaining else "paused"
            self.db.set_run_status(rid,final)
            self.progress.final(None,final)
            self.events.event(rid,None,"run_end",time.perf_counter()-t0,final=="complete")
        except KeyboardInterrupt:
            # Ctrl-C must not corrupt task state: run stays resumable.
            self.db.set_run_status(rid,"paused")
            self.events.event(rid,None,"interrupted",time.perf_counter()-t0,False)
            raise
        except Exception as e:
            self.db.event(rid,None,"crash",{"error":repr(e)}); self.db.set_run_status(rid,"paused"); raise
        finally: telemetry.stop()

    def execute_task(self,rid,task,objective):
        self._role("worker",task["id"])
        self.db.update_task(task["id"],status="running",attempts=task["attempts"]+1)
        self.progress.phase(task["id"],"start",task["title"])
        t0=time.perf_counter()
        # Incremental index refresh (no full rescan per task) + search.
        try:
            self.index.refresh()
            relevant=self.index.search(task["title"]+" "+task["description"],self.retrieve_top_k)
        except Exception:
            relevant=self.retrieve.search(task["title"]+" "+task["description"],self.retrieve_top_k)
        checkpoint=self.db.latest_checkpoint(rid)
        prompt=f"""OBJECTIVE: {objective}
TASK: {task['title']}
DESCRIPTION: {task['description']}
ACCEPTANCE: {task['acceptance']}
WORKSPACE ROOT: {self.root}
Commands already run from this workspace root. Do not cd to guessed paths.
CONFIGURED TEST COMMAND: {self.tests}
CHECKPOINT: {checkpoint[-5000:]}
RELEVANT REPOSITORY CONTEXT:
{json.dumps(relevant,ensure_ascii=False)[:18000]}
Use the available tools to implement the task. Inspect only what is needed, edit source files, run focused tests, and when implementation is complete return a normal assistant message with no tool call. Never modify benchmark tests."""
        messages=[{"role":"system","content":WORKER},{"role":"user","content":prompt}]
        made_edit=False
        for step in range(20):
            self._role("worker",task["id"])
            if step==8 and not made_edit:
                messages[1]["content"]+="\nProgress check: you have inspected the repository. Make the required source edit now. Prefer replace_in_file (exact old/new) or apply_patch (unified diff) for localized changes; use write_file only for full rewrites or create_file for new files."
            if step>=12 and not made_edit and "diff --git" in self.tools.git_diff():
                made_edit=True
            choice={"type":"function","function":{"name":"write_file"}} if step>=12 and not made_edit else "auto"
            self.progress.request(task["id"],True)
            turn=self.llm.tool_turn(messages,max_tokens=self.worker_output_tokens,temperature=.2,reasoning_budget=2048,tool_choice=choice)
            self.progress.request(task["id"],False,getattr(self.llm,"last_meta",{}).get("last_request_id",""))
            use=usage_of(messages,self.budget)
            self.progress.context(task["id"],use.show())
            self.db.event(rid,task["id"],"worker_native",{"finish_reason":turn.get("finish_reason"),"content":turn.get("content","")[-2000:],"tool_calls":turn.get("tool_calls",[]),"context":use.show()})
            calls=turn.get("tool_calls") or []
            if not calls:
                return self.verify(rid,task)
            assistant={"role":"assistant","content":turn.get("content") or None,"tool_calls":[]}
            for call in calls:
                assistant["tool_calls"].append({"id":call["id"],"type":"function","function":{"name":call["name"],"arguments":call.get("raw_arguments") or json.dumps(call["args"],ensure_ascii=False)}})
            messages.append(assistant)
            for call in calls:
                name,args=call["name"],call["args"]
                if call.get("argument_error"):
                    out="ERROR: "+call["argument_error"]+"; retry with complete JSON arguments"; ok=False
                else:
                    try: out=self.tools.execute(name,args); ok=not out.startswith("BLOCKED:")
                    except Exception as e: out="ERROR: "+repr(e); ok=False
                if ok and name in EDIT_TOOLS: made_edit=True
                self.db.log_tool(rid,task["id"],name,args,out,ok)
                target=str((args or {}).get("path") or (args or {}).get("command") or (args or {}).get("query") or "")[:120]
                self.progress.tool(task["id"],name,target)
                messages.append({"role":"tool","tool_call_id":call["id"],"content":out[-12000:]})
            if made_edit and any(c["name"] in ("run_tests","run_command") for c in calls):
                tests=self.tools.run_tests(self.tests)
                ok=tests.startswith("exit=0")
                self.progress.test_result(task["id"],ok,tests.splitlines()[0][:160] if tests else "")
                if ok:
                    self.db.event(rid,task["id"],"worker_test_handoff",{"step":step+1})
                    return self.verify(rid,task)
            # Context budget (SPEC M4): fit by tokens, never split tool groups.
            messages,_=fit_to_budget(messages,self.budget,checkpoint)
            self.events.event(rid,task["id"],"step",time.perf_counter()-t0,True,step=step+1)
        self.db.update_task(task["id"],status="failed",result="native tool-call step budget exhausted")
        self.progress.final(task["id"],"failed")
        self.events.event(rid,task["id"],"task_end",time.perf_counter()-t0,False)

    def verify(self,rid,task):
        for repair in range(self.max_repairs+1):
            tests=self.tools.run_tests(self.tests); diff=self.tools.git_diff()
            evidence=f"TASK:{json.dumps(task)}\nTESTS:\n{tests[-5000:]}\nDIFF:\n{diff[-10000:]}"
            self._role("verifier",task["id"])
            try:
                if self.verify_tests_only:
                    verdict={"verdict":"PASS" if tests.startswith("exit=0") else "FAIL",
                             "reason":"Configured acceptance tests passed." if tests.startswith("exit=0") else "Configured acceptance tests failed.",
                             "repair":"Fix the configured acceptance tests."}
                else:
                    verdict=self.llm.json(VERIFIER,evidence,2048,expected="verdict",retries=1,reasoning_budget=0)
            except Exception as e:
                self.db.event(rid,task["id"],"verifier_fallback",{"error":repr(e)})
                verdict={"verdict":"BLOCKED","reason":"Structured verifier failed: "+repr(e),"repair":"Retry verification when the model is available."}
            self.db.event(rid,task["id"],"verify",verdict)
            if verdict.get("verdict")=="PASS" and tests.startswith("exit=0"):
                # Protected-test integrity: any protected modification is failure.
                prot=None
                if self._protected_before is not None:
                    prot=testscope.verify_protected(self.root,self._protected_before)
                    if not prot.get("ok"):
                        self.db.update_task(task["id"],status="failed",result="protected tests modified: "+json.dumps(prot))
                        self.progress.final(task["id"],"failed-protected")
                        return False
                commit=""
                if self.auto_commit:
                    # Task-owned staging: commit explicit paths only, never add -A.
                    owned=None
                    if self._baseline is not None:
                        try:
                            changed=gitwork.changed_vs_baseline(self.root,self._baseline)
                            owned=gitwork.task_owned(changed,self._baseline.dirt)
                        except Exception:
                            owned=None
                    if owned is not None:
                        commit=gitwork.commit_paths(self.root,owned,"bonsai: "+task["title"])
                    else:
                        commit=self.tools.verified_commit("bonsai: "+task["title"])
                self.db.update_task(task["id"],status="done",result=verdict.get("reason","")+" "+commit)
                self.progress.final(task["id"],"done")
                self.events.event(rid,task["id"],"task_end",0.0,True)
                return True
            if verdict.get("verdict")=="BLOCKED":
                self.db.update_task(task["id"],status="blocked",result=verdict.get("reason","")); return False
            if repair<self.max_repairs:
                repair_task={"title":task["title"],"description":verdict.get("repair","Repair failed verification"),"acceptance":task["acceptance"]}
                self._role("repair",task["id"])
                repair_messages=[{"role":"system","content":WORKER},{"role":"user","content":"REPAIR:\n"+json.dumps(repair_task)+"\nEVIDENCE:\n"+evidence[-24000:]}]
                for _ in range(4):
                    turn=self.llm.tool_turn(repair_messages,max_tokens=self.worker_output_tokens,temperature=.2,reasoning_budget=0,tool_choice="required")
                    calls=turn.get("tool_calls") or []
                    if not calls: break
                    assistant={"role":"assistant","content":turn.get("content") or None,"tool_calls":[]}
                    for call in calls:
                        assistant["tool_calls"].append({"id":call["id"],"type":"function","function":{"name":call["name"],"arguments":call.get("raw_arguments") or json.dumps(call["args"],ensure_ascii=False)}})
                    repair_messages.append(assistant)
                    changed=False
                    for call in calls:
                        if call.get("argument_error"):
                            out="ERROR: "+call["argument_error"]+"; retry with complete JSON arguments"; ok=False
                        else:
                            try: out=self.tools.execute(call["name"],call["args"]); ok=not out.startswith("BLOCKED:")
                            except Exception as e: out="ERROR: "+repr(e); ok=False
                        self.db.log_tool(rid,task["id"],call["name"],call["args"],out,ok)
                        repair_messages.append({"role":"tool","tool_call_id":call["id"],"content":out[-12000:]})
                        changed=changed or (ok and call["name"] in (*EDIT_TOOLS,"run_command"))
                    if changed: break
        self.db.update_task(task["id"],status="failed",result="verification/repair budget exhausted")
        # Quarantine failed task-owned changes without touching user work.
        if self._baseline is not None:
            try:
                changed=gitwork.changed_vs_baseline(self.root,self._baseline)
                owned=gitwork.task_owned(changed,self._baseline.dirt)
                if owned:
                    note=gitwork.quarantine_reset(self.root,owned)
                    self.db.event(rid,task["id"],"quarantine",{"paths":owned,"result":note})
            except Exception as e:
                self.db.event(rid,task["id"],"quarantine_error",{"error":repr(e)})
        self.progress.final(task["id"],"failed")
        return False

    def compact(self,rid,objective):
        state={"objective":objective,"tasks":self.db.tasks(rid),"recent_events":self.db.events(rid,30)}
        self._role("compactor"); summary=self.llm.chat([{"role":"system","content":COMPACTOR},{"role":"user","content":json.dumps(state,ensure_ascii=False)[:26000]}],900,.1)
        self.db.checkpoint(rid,summary)
        # Durable file checkpoint (SPEC M4 checkpoint/resume with revalidation).
        try:
            run=self.db.get_run(rid)
            tasks=self.db.tasks(rid)
            nxt=self.db.next_task(rid)
            cp=ckpt_mod.Checkpoint(
                objective=objective,
                acceptance=(nxt or {}).get("acceptance","") if nxt else "",
                baseline_commit=(self._baseline.commit if self._baseline else ""),
                task_owned_files=gitwork.task_owned(
                    gitwork.changed_vs_baseline(self.root,self._baseline),
                    self._baseline.dirt) if self._baseline else [],
                completed_steps=[t["title"] for t in tasks if t["status"]=="done"],
                unresolved_failures=[t["title"]+": "+t["result"] for t in tasks if t["status"] in ("failed","blocked")],
                tests=self.tests, summary=summary,
                next_action=("resume task "+str(nxt["id"]) if nxt else "run complete"))
            ckpt_mod.write_checkpoint(self.root,rid,cp)
        except Exception as e:
            self.db.event(rid,None,"checkpoint_error",{"error":repr(e)})

    def resume(self,rid):
        """Resume a paused run after revalidating filesystem/git state."""
        run=self.db.get_run(rid)
        if not run: raise ValueError("unknown run "+str(rid))
        cp=ckpt_mod.read_checkpoint(self.root,rid)
        report={"checkpoint_found":cp is not None,"revalidation":None}
        if cp is not None:
            report["revalidation"]=ckpt_mod.revalidate(self.root,cp)
            if not report["revalidation"]["ok"]:
                self.db.event(rid,None,"resume_revalidation_failed",report["revalidation"])
                return report
        self.db.event(rid,None,"resume",report)
        self.run(rid)
        report["resumed"]=True
        return report

    def status(self,rid):
        return {"run":self.db.get_run(rid),"tasks":self.db.tasks(rid),"checkpoint":self.db.latest_checkpoint(rid),"llm":self.db.llm_summary(rid)}
