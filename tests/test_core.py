import pytest
from bonsai_agent.db import StateDB
from bonsai_agent.tools import WorkspaceTools
def test_task_lifecycle(tmp_path):
    db=StateDB(tmp_path/'state.db'); rid=db.create_run('x'); tid=db.add_task(rid,'a','b','c'); assert db.next_task(rid)['id']==tid; db.update_task(tid,status='complete'); assert db.next_task(rid) is None
def test_workspace_boundary(tmp_path):
    t=WorkspaceTools(tmp_path)
    with pytest.raises(ValueError): t.read_file('../outside')
def test_write_read(tmp_path):
    t=WorkspaceTools(tmp_path); t.write_file('a/b.txt','hello'); assert t.read_file('a/b.txt')=='hello'
