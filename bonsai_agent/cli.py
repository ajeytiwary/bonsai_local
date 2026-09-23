import argparse,json
from pathlib import Path
from .agent import Agent
from .llm import BonsaiLLM
def main():
    p=argparse.ArgumentParser(description="Persistent/evolution-ready local Bonsai agent")
    p.add_argument("objective",nargs="?"); p.add_argument("--repo",default="."); p.add_argument("--url",default="http://127.0.0.1:8091"); p.add_argument("--model",default="Ternary-Bonsai-2-27B-PQ2_0")
    p.add_argument("--tests",default="pytest -q"); p.add_argument("--max-steps",type=int,default=100); p.add_argument("--compact-every",type=int,default=5); p.add_argument("--max-repairs",type=int,default=3); p.add_argument("--retrieve-top-k",type=int,default=8)
    p.add_argument("--resume",type=int); p.add_argument("--status",type=int); p.add_argument("--unsafe-shell",action="store_true"); p.add_argument("--no-auto-commit",action="store_true")
    a=p.parse_args(); agent=Agent(Path(a.repo),BonsaiLLM(a.url,a.model),a.tests,a.max_steps,a.compact_every,a.max_repairs,a.retrieve_top_k,a.unsafe_shell,not a.no_auto_commit)
    if a.status: print(json.dumps(agent.status(a.status),indent=2)); return
    if a.resume: rid=a.resume
    else:
        if not a.objective: p.error("objective required unless --resume/--status supplied")
        rid=agent.start(a.objective); print("Created run",rid)
    agent.run(rid); print(json.dumps(agent.status(rid),indent=2))
if __name__=="__main__": main()
