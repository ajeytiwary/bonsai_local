import argparse,json
from pathlib import Path
from .agent import Agent
from .llm import BonsaiLLM
def main():
    p=argparse.ArgumentParser(description="Persistent/evolution-ready local Bonsai agent")
    p.add_argument("objective",nargs="?"); p.add_argument("--repo",default="."); p.add_argument("--url",default="http://127.0.0.1:8091"); p.add_argument("--model",default="Ternary-Bonsai-2-27B-PQ2_0")
    p.add_argument("--tests",default="pytest -q"); p.add_argument("--max-steps",type=int,default=100); p.add_argument("--compact-every",type=int,default=5); p.add_argument("--max-repairs",type=int,default=3); p.add_argument("--retrieve-top-k",type=int,default=8)
    p.add_argument("--worker-output-tokens",type=int,default=8192,help="Maximum model output tokens per worker or repair turn (default: 8192)")
    p.add_argument("--single-task",action="store_true"); p.add_argument("--verify-tests-only",action="store_true"); p.add_argument("--resume",type=int); p.add_argument("--status",type=int); p.add_argument("--unsafe-shell",action="store_true"); p.add_argument("--no-auto-commit",action="store_true")
    p.add_argument("--index-stats",action="store_true",help="M5: print persistent repo-index stats JSON and exit")
    p.add_argument("--index-search",default=None,help="M5: search the persistent repo index for QUERY and exit")
    p.add_argument("--openjev",action="store_true",help="M7: enable local OpenJEV decision layer (generic profile)")
    p.add_argument("--openjev-profile",default="generic",choices=["generic","compliance"],help="M7: OpenJEV profile (default: generic)")
    a=p.parse_args()
    provider=None
    if a.openjev:
        from .openjev import LocalDecisionProvider
        provider=LocalDecisionProvider(profile=a.openjev_profile)
    if a.index_stats or a.index_search:
        from .repo_index import RepoIndex
        idx=RepoIndex(Path(a.repo)); idx.refresh()
        if a.index_stats: print(json.dumps(idx.stats(),indent=2)); return
        for h in idx.search(a.index_search,8): print(json.dumps(h)[:2000])
        return
    agent=Agent(Path(a.repo),BonsaiLLM(a.url,a.model),a.tests,a.max_steps,a.compact_every,a.max_repairs,a.retrieve_top_k,a.unsafe_shell,not a.no_auto_commit,a.verify_tests_only,a.worker_output_tokens,decision_provider=provider)
    if a.status: print(json.dumps(agent.status(a.status),indent=2)); return
    if a.resume:
        print(json.dumps(agent.resume(a.resume),indent=2)); print(json.dumps(agent.status(a.resume),indent=2)); return
    else:
        if not a.objective: p.error("objective required unless --resume/--status supplied")
        rid=agent.start(a.objective,single_task=a.single_task); print("Created run",rid)
    agent.run(rid); print(json.dumps(agent.status(rid),indent=2))
if __name__=="__main__": main()
