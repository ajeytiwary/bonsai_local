import argparse
from pathlib import Path
from .agent import Agent
from .llm import BonsaiLLM
def main():
    p=argparse.ArgumentParser(description='Persistent long-horizon Bonsai agent'); p.add_argument('objective',nargs='?'); p.add_argument('--repo',default='.'); p.add_argument('--url',default='http://127.0.0.1:8091'); p.add_argument('--model',default='Ternary-Bonsai-2-27B-PQ2_0'); p.add_argument('--tests',default='pytest -q'); p.add_argument('--max-steps',type=int,default=100); p.add_argument('--compact-every',type=int,default=5); p.add_argument('--resume',type=int); a=p.parse_args(); agent=Agent(Path(a.repo),BonsaiLLM(a.url,a.model),a.tests,a.max_steps,a.compact_every)
    if a.resume: rid=a.resume
    else:
        if not a.objective: p.error('objective required unless --resume is supplied')
        rid=agent.start(a.objective); print('Created run '+str(rid))
    agent.run(rid)
if __name__=='__main__': main()
