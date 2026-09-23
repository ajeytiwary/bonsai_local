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
