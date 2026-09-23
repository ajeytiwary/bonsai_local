from __future__ import annotations
import json, sqlite3
from pathlib import Path

SCHEMA='''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, objective TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'running', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL, acceptance TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, result TEXT NOT NULL DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS memories(id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, kind TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS tool_calls(id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, task_id INTEGER, tool TEXT NOT NULL, args TEXT NOT NULL, output TEXT NOT NULL, ok INTEGER NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS checkpoints(id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, summary TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
'''
class StateDB:
    def __init__(self,path:Path):
        path.parent.mkdir(parents=True,exist_ok=True); self.conn=sqlite3.connect(path); self.conn.row_factory=sqlite3.Row; self.conn.executescript(SCHEMA)
    def create_run(self,objective):
        c=self.conn.execute('INSERT INTO runs(objective) VALUES(?)',(objective,)); self.conn.commit(); return c.lastrowid
    def add_task(self,run_id,title,description,acceptance='',status='pending'):
        c=self.conn.execute('INSERT INTO tasks(run_id,title,description,acceptance,status) VALUES(?,?,?,?,?)',(run_id,title,description,acceptance,status)); self.conn.commit(); return c.lastrowid
    def tasks(self,run_id): return [dict(x) for x in self.conn.execute('SELECT * FROM tasks WHERE run_id=? ORDER BY id',(run_id,))]
    def next_task(self,run_id):
        r=self.conn.execute("SELECT * FROM tasks WHERE run_id=? AND status IN ('pending','repair') ORDER BY CASE status WHEN 'repair' THEN 0 ELSE 1 END,id LIMIT 1",(run_id,)).fetchone(); return dict(r) if r else None
    def update_task(self,task_id,**fields):
        allowed={'status','result','attempts','acceptance','description'}; fields={k:v for k,v in fields.items() if k in allowed}
        if fields: self.conn.execute('UPDATE tasks SET '+', '.join(k+'=?' for k in fields)+' WHERE id=?',(*fields.values(),task_id)); self.conn.commit()
    def remember(self,run_id,kind,content): self.conn.execute('INSERT INTO memories(run_id,kind,content) VALUES(?,?,?)',(run_id,kind,content)); self.conn.commit()
    def memories(self,run_id,limit=30): return [dict(x) for x in self.conn.execute('SELECT * FROM memories WHERE run_id=? ORDER BY id DESC LIMIT ?',(run_id,limit))][::-1]
    def log_tool(self,run_id,task_id,tool,args,output,ok): self.conn.execute('INSERT INTO tool_calls(run_id,task_id,tool,args,output,ok) VALUES(?,?,?,?,?,?)',(run_id,task_id,tool,json.dumps(args),output[-20000:],int(ok))); self.conn.commit()
    def checkpoint(self,run_id,summary): self.conn.execute('INSERT INTO checkpoints(run_id,summary) VALUES(?,?)',(run_id,summary)); self.conn.commit()
    def latest_checkpoint(self,run_id):
        r=self.conn.execute('SELECT summary FROM checkpoints WHERE run_id=? ORDER BY id DESC LIMIT 1',(run_id,)).fetchone(); return r['summary'] if r else ''
