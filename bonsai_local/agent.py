from __future__ import annotations
import json
from pathlib import Path
from .db import Store
from .llm import Bonsai
from .tools import Workspace

SYSTEM="""You are Bonsai, a careful autonomous software engineer. Work on exactly one bounded task.
Never claim a change you did not make. Inspect before editing. Prefer small changes. Run tests.
Return ONLY JSON:
{"summary":"...", "done":false, "tool_calls":[{"tool":"read_file|write_file|list_files|run_command|git_diff|git_status|run_tests","args":{...}}]}
Set done=true only when the task is implemented and verified. Maximum 5 tool calls per turn."""

VERIFY="""You are an independent verifier. Judge only evidence shown. Return ONLY JSON:
{"verdict":"PASS|FAIL","reason":"...", "repair":"specific repair instructions if FAIL"}"""

PLAN="""Decompose the objective into 3-12 ordered, independently verifiable tasks.
Return ONLY a JSON array: [{"title":"...","description":"...","acceptance":"..."}].
Include tests/documentation where appropriate. Avoid vague tasks."""

class Agent:
    def __init__(self, repo:Path, db_path:Path, llm:Bonsai, test_cmd:str="pytest -q", max_steps=20, max_repairs=3):
        self.ws=Workspace(repo); self.store=Store(db_path); self.llm=llm
        self.test_cmd=test_cmd; self.max_steps=max_steps; self.max_repairs=max_repairs
    def plan(self,objective:str):
        tree=self.ws.list(".")
        return self.llm.json(PLAN,f"OBJECTIVE:\n{objective}\n\nREPOSITORY TREE:\n{tree}",2500)
    def compact(self,run_id:int)->str:
        tasks=self.store.tasks(run_id)
        compact=[{"id":t["id"],"title":t["title"],"status":t["status"],"result":t["result"][-1000:]} for t in tasks]
        return json.dumps(compact,indent=2)
    def run(self,objective:str)->int:
        rid=self.store.create_run(objective,str(self.ws.root))
        for t in self.plan(objective):
            self.store.add_task(rid,t["title"],t["description"],t.get("acceptance",""))
        completed=0
        while (task:=self.store.next_task(rid)):
            ok=self.execute_task(rid,task,objective)
            if not ok: break
            completed+=1
            if completed%3==0:
                summary=self.llm.chat("Compress project state. Preserve decisions, interfaces, failures and next work.",self.compact(rid),1200)
                self.store.checkpoint(rid,summary)
        return rid
    def execute_task(self,rid:int,task:dict,objective:str)->bool:
        transcript=[]
        for step in range(self.max_steps):
            state=self.store.latest_checkpoint(rid) or self.compact(rid)
            prompt=f"""OBJECTIVE: {objective}
CURRENT TASK: {task['title']}
DESCRIPTION: {task['description']}
ACCEPTANCE: {task['acceptance']}
CHECKPOINT/STATE:
{state}
RECENT TOOL RESULTS:
{json.dumps(transcript[-6:],ensure_ascii=False)[:18000]}
Choose the next concrete action."""
            try: action=self.llm.json(SYSTEM,prompt,2200)
            except Exception as e:
                self.store.event(rid,"model_error",str(e),task["id"]); continue
            self.store.event(rid,"agent",action,task["id"])
            for call in action.get("tool_calls",[])[:5]:
                try: out=self.ws.execute(call)
                except Exception as e: out=f"TOOL ERROR: {e}"
                transcript.append({"call":call,"result":out[-12000:]})
                self.store.event(rid,"tool",{"call":call,"result":out[-12000:]},task["id"])
            if action.get("done"):
                return self.verify_and_repair(rid,task,objective,transcript)
        self.store.update_task(task["id"],"failed","step budget exhausted"); return False
    def verify_and_repair(self,rid:int,task:dict,objective:str,transcript:list)->bool:
        for attempt in range(self.max_repairs+1):
            tests=self.ws.test(self.test_cmd)
            diff=self.ws.git_diff()
            evidence=f"TASK:{task}\nTESTS:\n{tests}\nDIFF:\n{diff[-30000:]}"
            verdict=self.llm.json(VERIFY,evidence,1200)
            self.store.event(rid,"verify",verdict,task["id"])
            if verdict.get("verdict")=="PASS" and "exit=0" in tests:
                self.store.update_task(task["id"],"done",verdict.get("reason","")); return True
            if attempt>=self.max_repairs: break
            repair={"title":task["title"],"description":verdict.get("repair","Fix verification failures"),"acceptance":task["acceptance"]}
            for _ in range(6):
                action=self.llm.json(SYSTEM,f"REPAIR TASK:\n{repair}\nTEST OUTPUT:\n{tests[-12000:]}\nDIFF:\n{diff[-12000:]}",1800)
                for call in action.get("tool_calls",[])[:5]:
                    try: out=self.ws.execute(call)
                    except Exception as e: out=f"TOOL ERROR: {e}"
                    self.store.event(rid,"repair_tool",{"call":call,"result":out[-8000:]},task["id"])
                if action.get("done"): break
        self.store.update_task(task["id"],"failed","verification failed"); return False
