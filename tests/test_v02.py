from pathlib import Path
from bonsai_agent.db import StateDB
from bonsai_agent.tools import WorkspaceTools
from bonsai_agent.safety import CommandPolicy
from bonsai_agent.retrieval import RepoRetriever

def test_store_resume_and_dependencies(tmp_path):
 s=StateDB(tmp_path/"a.db"); r=s.create_run("x",str(tmp_path)); a=s.add_task(r,"a","a"); b=s.add_task(r,"b","b",depends_on=[a])
 assert s.next_task(r)["id"]==a
 s.update_task(a,status="done")
 assert s.next_task(r)["id"]==b
 s.set_run_status(r,"paused"); assert s.get_run(r)["status"]=="paused"

def test_workspace_blocks_escape(tmp_path):
 w=WorkspaceTools(tmp_path)
 try: w.read_file("../secret")
 except ValueError: pass
 else: raise AssertionError("escape allowed")

def test_safety_blocks_destructive_commands():
 p=CommandPolicy()
 assert not p.check("sudo rm -rf /tmp/x").allowed
 assert not p.check("git reset --hard HEAD").allowed
 assert p.check("pytest -q").allowed

def test_retrieval(tmp_path):
 (tmp_path/"alpha.py").write_text("def sentinel_ingest():\n    return 'ok'\n")
 (tmp_path/"beta.py").write_text("def unrelated():\n    pass\n")
 r=RepoRetriever(tmp_path)
 assert "sentinel_ingest" in r.repo_map()
 assert r.search("sentinel ingest",top_k=1)[0]["path"]=="alpha.py"

def test_verified_commit_requires_git(tmp_path):
 w=WorkspaceTools(tmp_path)
 out=w.git_status()
 assert out.startswith("exit=")


def test_llm_summary(tmp_path):
 s=StateDB(tmp_path/"a.db"); r=s.create_run("x")
 s.log_llm(r,None,"planner",{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15},1.25)
 x=s.llm_summary(r); assert x["calls"]==1 and x["total_tokens"]==15 and x["seconds"]==1.25

def test_evolution_promotion():
 from bonsai_agent.evolution import promote
 base={"pass_rate":.75,"seconds":100,"tokens":1000,"gpu_energy_wh":10}
 assert promote(base,{"pass_rate":.875,"seconds":120,"tokens":1200,"gpu_energy_wh":12})
 assert promote(base,{"pass_rate":.75,"seconds":90,"tokens":1000,"gpu_energy_wh":10})
 assert not promote(base,{"pass_rate":.625,"seconds":10,"tokens":10,"gpu_energy_wh":1})


def test_json_parser_selects_schema_not_outer_list():
 from bonsai_agent.llm import BonsaiLLM
 x=BonsaiLLM.parse_json('noise [1,2] then {"done":true,"summary":"ok"} trailing',"action")
 assert x["done"] is True

def test_json_parser_balanced_truncated_tail():
 from bonsai_agent.llm import BonsaiLLM
 text='{"verdict":"FAIL","reason":"x","repair":"y"} trailing {"broken":'
 assert BonsaiLLM.parse_json(text,"verdict")["verdict"]=="FAIL"

def test_json_parser_rejects_wrong_schema():
 import pytest
 from bonsai_agent.llm import BonsaiLLM
 with pytest.raises(ValueError): BonsaiLLM.parse_json('[{"tool":"read_file"}]',"action")


def test_structured_schema_is_sent(monkeypatch):
 from bonsai_agent.llm import BonsaiLLM
 seen={}
 class R:
  def raise_for_status(self): pass
  def json(self): return {"usage":{},"choices":[{"message":{"content":'{"verdict":"PASS","reason":"ok","repair":""}'}}]}
 def post(url,json,timeout): seen.update(json); return R()
 monkeypatch.setattr("bonsai_agent.llm.requests.post",post)
 x=BonsaiLLM().json("s","u",expected="verdict")
 assert x["verdict"]=="PASS"
 assert seen["response_format"]["type"]=="json_object"
 assert seen["response_format"]["schema"]["required"]==["verdict","reason","repair"]
 assert "json_schema" not in seen

def test_plan_schema_bounds_tasks():
 from bonsai_agent.llm import SCHEMAS
 s=SCHEMAS["plan"]["properties"]["tasks"]
 assert s["minItems"]==1 and s["maxItems"]==6


def test_json_retries_malformed_structured_output(monkeypatch):
 from bonsai_agent.llm import BonsaiLLM
 replies=iter([
  {"usage":{},"choices":[{"message":{"content":"I should use a tool"}}]},
  {"usage":{},"choices":[{"message":{"content":'{"tool":"read_file","args":{"path":"app.py"}}'}}]},
 ])
 class R:
  def __init__(self,x): self.x=x
  def raise_for_status(self): pass
  def json(self): return self.x
 def post(url,json,timeout): return R(next(replies))
 monkeypatch.setattr("bonsai_agent.llm.requests.post",post)
 x=BonsaiLLM().json("s","u",expected="action",retries=1)
 assert x["tool"]=="read_file"


def test_native_tool_call_parsing(monkeypatch):
 from bonsai_agent.llm import BonsaiLLM
 seen={}
 class R:
  def raise_for_status(self): pass
  def json(self):
   return {"usage":{},"choices":[{"finish_reason":"tool_calls","message":{"content":"","tool_calls":[{"id":"c1","type":"function","function":{"name":"write_file","arguments":'{"path":"app.py","content":"x=1"}'}}]}}]}
 def post(url,json,timeout): seen.update(json); return R()
 monkeypatch.setattr("bonsai_agent.llm.requests.post",post)
 x=BonsaiLLM().tool_turn([{"role":"user","content":"fix it"}])
 assert x["finish_reason"]=="tool_calls"
 assert x["tool_calls"][0]["name"]=="write_file"
 assert x["tool_calls"][0]["args"]["path"]=="app.py"
 assert seen["tool_choice"]=="auto"
 assert any(tool["function"]["name"]=="run_tests" for tool in seen["tools"])
 assert seen["thinking_budget_tokens"]==2048


def test_native_tool_history_keeps_system_first(tmp_path):
 from bonsai_agent.agent import Agent

 class FakeLLM:
  def __init__(self): self.messages=[]
  def bind(self, observer): pass
  def tool_turn(self, messages, **kwargs):
   self.messages.append([m.copy() for m in messages])
   if len(self.messages)==1:
    return {"content":"", "tool_calls":[{"id":"c1","name":"read_file","args":{"path":"TASK.md"}}],"finish_reason":"tool_calls"}
   return {"content":"done", "tool_calls":[],"finish_reason":"stop"}

 (tmp_path/"TASK.md").write_text("task")
 llm=FakeLLM(); agent=Agent(tmp_path,llm,auto_commit=False)
 rid=agent.db.create_run("task",str(tmp_path))
 agent.db.add_task(rid,"task","task")
 agent.verify=lambda *args: True
 agent.execute_task(rid,agent.db.tasks(rid)[0],"task")
 assert [m["role"] for m in llm.messages[1]]==["system","user","assistant","tool"]


def test_truncated_native_tool_arguments_are_reported(monkeypatch):
 from bonsai_agent.llm import BonsaiLLM
 class Response:
  def raise_for_status(self): pass
  def json(self):
   return {"choices":[{"finish_reason":"length","message":{"tool_calls":[{"id":"c1","function":{"name":"write_file","arguments":"{\"path\":\"app.py\",\"content\":\"unfinished"}}]}}]}
 monkeypatch.setattr("bonsai_agent.llm.requests.post",lambda *args,**kwargs: Response())
 call=BonsaiLLM().tool_turn([{"role":"user","content":"write"}])["tool_calls"][0]
 assert "argument_error" in call
 assert call["raw_arguments"].startswith('{"path":"app.py"')
 assert call["args"]=={}


def test_named_tool_choice_limits_available_tools(monkeypatch):
 from bonsai_agent.llm import BonsaiLLM
 seen={}
 class Response:
  def raise_for_status(self): pass
  def json(self): return {"choices":[{"message":{"content":"done"}}]}
 def post(url,json,timeout): seen.update(json); return Response()
 monkeypatch.setattr("bonsai_agent.llm.requests.post",post)
 BonsaiLLM().tool_turn([{"role":"user","content":"write"}],tool_choice={"type":"function","function":{"name":"write_file"}})
 assert seen["tool_choice"]=="required"
 assert [item["function"]["name"] for item in seen["tools"]]==["write_file"]
