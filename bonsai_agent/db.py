from __future__ import annotations
import json,sqlite3
from pathlib import Path
SCHEMA="""
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY,objective TEXT NOT NULL,repo TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'running',created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY,run_id INTEGER NOT NULL,title TEXT NOT NULL,description TEXT NOT NULL,acceptance TEXT NOT NULL DEFAULT '',depends_on TEXT NOT NULL DEFAULT '[]',status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,result TEXT NOT NULL DEFAULT '',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS memories(id INTEGER PRIMARY KEY,run_id INTEGER NOT NULL,kind TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS tool_calls(id INTEGER PRIMARY KEY,run_id INTEGER NOT NULL,task_id INTEGER,tool TEXT NOT NULL,args TEXT NOT NULL,output TEXT NOT NULL,ok INTEGER NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS checkpoints(id INTEGER PRIMARY KEY,run_id INTEGER NOT NULL,summary TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,run_id INTEGER NOT NULL,task_id INTEGER,kind TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS llm_calls(id INTEGER PRIMARY KEY,run_id INTEGER,task_id INTEGER,role TEXT,prompt_tokens INTEGER DEFAULT 0,completion_tokens INTEGER DEFAULT 0,total_tokens INTEGER DEFAULT 0,seconds REAL DEFAULT 0,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
"""
class StateDB:
    def __init__(self,path:Path):
        path.parent.mkdir(parents=True,exist_ok=True); self.conn=sqlite3.connect(path); self.conn.row_factory=sqlite3.Row; self.conn.executescript(SCHEMA); self._migrate()
    def _migrate(self):
        cols={r[1] for r in self.conn.execute("PRAGMA table_info(runs)")};
        if "repo" not in cols: self.conn.execute("ALTER TABLE runs ADD COLUMN repo TEXT NOT NULL DEFAULT ''")
        if "updated_at" not in cols: self.conn.execute("ALTER TABLE runs ADD COLUMN updated_at TEXT DEFAULT CURRENT_TIMESTAMP")
        cols={r[1] for r in self.conn.execute("PRAGMA table_info(tasks)")};
        if "depends_on" not in cols: self.conn.execute("ALTER TABLE tasks ADD COLUMN depends_on TEXT NOT NULL DEFAULT '[]'")
        self.conn.commit()
    def create_run(self,objective,repo=""):
        c=self.conn.execute("INSERT INTO runs(objective,repo) VALUES(?,?)",(objective,repo)); self.conn.commit(); return c.lastrowid
    def get_run(self,rid):
        r=self.conn.execute("SELECT * FROM runs WHERE id=?",(rid,)).fetchone(); return dict(r) if r else None
    def set_run_status(self,rid,status): self.conn.execute("UPDATE runs SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(status,rid)); self.conn.commit()
    def add_task(self,run_id,title,description,acceptance="",depends_on=None,status="pending"):
        c=self.conn.execute("INSERT INTO tasks(run_id,title,description,acceptance,depends_on,status) VALUES(?,?,?,?,?,?)",(run_id,title,description,acceptance,json.dumps(depends_on or []),status)); self.conn.commit(); return c.lastrowid
    def tasks(self,rid): return [dict(x) for x in self.conn.execute("SELECT * FROM tasks WHERE run_id=? ORDER BY id",(rid,))]
    def next_task(self,rid):
        done={t["id"] for t in self.tasks(rid) if t["status"]=="done"}
        for t in self.tasks(rid):
            if t["status"] not in ("pending","repair","running"): continue
            deps=json.loads(t.get("depends_on") or "[]")
            if all((not isinstance(d,int)) or d in done for d in deps): return t
        return None
    def update_task(self,tid,**fields):
        allowed={"status","result","attempts","acceptance","description","depends_on"}; fields={k:v for k,v in fields.items() if k in allowed}
        if fields: self.conn.execute("UPDATE tasks SET "+", ".join(k+"=?" for k in fields)+" WHERE id=?",(*fields.values(),tid)); self.conn.commit()
    def event(self,rid,tid,kind,payload): self.conn.execute("INSERT INTO events(run_id,task_id,kind,payload) VALUES(?,?,?,?)",(rid,tid,kind,json.dumps(payload,ensure_ascii=False,default=str))); self.conn.commit()
    def events(self,rid,limit=30): return [dict(x) for x in self.conn.execute("SELECT * FROM events WHERE run_id=? ORDER BY id DESC LIMIT ?",(rid,limit))][::-1]
    def log_tool(self,rid,tid,tool,args,output,ok): self.conn.execute("INSERT INTO tool_calls(run_id,task_id,tool,args,output,ok) VALUES(?,?,?,?,?,?)",(rid,tid,tool,json.dumps(args),output[-20000:],int(ok))); self.conn.commit()
    def checkpoint(self,rid,summary): self.conn.execute("INSERT INTO checkpoints(run_id,summary) VALUES(?,?)",(rid,summary)); self.conn.commit()
    def latest_checkpoint(self,rid):
        r=self.conn.execute("SELECT summary FROM checkpoints WHERE run_id=? ORDER BY id DESC LIMIT 1",(rid,)).fetchone(); return r["summary"] if r else ""
