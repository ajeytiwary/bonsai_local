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
