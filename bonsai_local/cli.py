from __future__ import annotations
import argparse
from pathlib import Path
from .agent import Agent
from .llm import Bonsai

def main():
    p=argparse.ArgumentParser(description="Persistent local Bonsai coding agent")
    p.add_argument("objective",nargs="+")
    p.add_argument("--repo",default=".")
    p.add_argument("--url",default="http://127.0.0.1:8091")
    p.add_argument("--model",default="Ternary-Bonsai-2-27B-PQ2_0")
    p.add_argument("--db",default=".bonsai/agent.db")
    p.add_argument("--test",default="pytest -q")
    p.add_argument("--max-steps",type=int,default=20)
    p.add_argument("--max-repairs",type=int,default=3)
    a=p.parse_args(); root=Path(a.repo).resolve()
    db=Path(a.db); db=db if db.is_absolute() else root/db
    agent=Agent(root,db,Bonsai(a.url,a.model),a.test,a.max_steps,a.max_repairs)
    rid=agent.run(" ".join(a.objective))
    print(f"Run {rid} finished. State: {db}")
if __name__=="__main__": main()
