from __future__ import annotations
import json, sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS runs(
 id INTEGER PRIMARY KEY, objective TEXT NOT NULL, repo TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'running', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS tasks(
 id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, title TEXT NOT NULL,
 description TEXT NOT NULL, acceptance TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
 result TEXT NOT NULL DEFAULT '', FOREIGN KEY(run_id) REFERENCES runs(id));
CREATE TABLE IF NOT EXISTS events(
 id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, task_id INTEGER,
 kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS checkpoints(
 id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, summary TEXT NOT NULL,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP);
"""

class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db=sqlite3.connect(path)
        self.db.row_factory=sqlite3.Row
        self.db.executescript(SCHEMA)
    def create_run(self, objective:str, repo:str)->int:
        c=self.db.execute("INSERT INTO runs(objective,repo) VALUES(?,?)",(objective,repo)); self.db.commit(); return c.lastrowid
    def add_task(self, run_id:int, title:str, description:str, acceptance:str="")->int:
        c=self.db.execute("INSERT INTO tasks(run_id,title,description,acceptance) VALUES(?,?,?,?)",(run_id,title,description,acceptance)); self.db.commit(); return c.lastrowid
    def tasks(self, run_id:int):
        return [dict(x) for x in self.db.execute("SELECT * FROM tasks WHERE run_id=? ORDER BY id",(run_id,))]
    def next_task(self, run_id:int):
        r=self.db.execute("SELECT * FROM tasks WHERE run_id=? AND status IN ('pending','repair') ORDER BY id LIMIT 1",(run_id,)).fetchone()
        return dict(r) if r else None
    def update_task(self, tid:int, status:str, result:str=""):
        self.db.execute("UPDATE tasks SET status=?, result=?, attempts=attempts+1 WHERE id=?",(status,result,tid)); self.db.commit()
    def event(self, run_id:int, kind:str, payload:Any, task_id:int|None=None):
        self.db.execute("INSERT INTO events(run_id,task_id,kind,payload) VALUES(?,?,?,?)",(run_id,task_id,kind,json.dumps(payload,ensure_ascii=False,default=str))); self.db.commit()
    def checkpoint(self, run_id:int, summary:str):
        self.db.execute("INSERT INTO checkpoints(run_id,summary) VALUES(?,?)",(run_id,summary)); self.db.commit()
    def latest_checkpoint(self, run_id:int)->str:
        r=self.db.execute("SELECT summary FROM checkpoints WHERE run_id=? ORDER BY id DESC LIMIT 1",(run_id,)).fetchone()
        return r["summary"] if r else ""
