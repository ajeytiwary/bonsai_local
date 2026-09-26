"""M6 harness adapters (SPEC): identical tasks through multiple harnesses.

Adapters (all record the SPEC promotion metrics):
- bonsai_local: direct Agent run in-process (offline-capable with a stub LLM).
- hermes: `.venv-hermes/bin/hermes chat` against the live Bonsai server
  (requires 8091 + Hermes config; skipped in CI without them).
- paperclip: Paperclip issue -> Hermes gateway -> Bonsai chain metadata
  recorder (live chain exercised in M3 E2E; here we record the contract
  fields without re-running the chain).

Metrics per SPEC promotion ordering: clean task success; pass rate;
clean exit/recovery; protected-test integrity; only then efficiency
(tokens/time/energy).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

PROMOTION_ORDER = ["clean", "pass_rate", "clean_exit",
                   "tests_unchanged", "total_tokens", "seconds"]


def _git_init(work: Path) -> None:
    # Fixtures ship with their own .git (T301 needs its regressing history);
    # keep it. Otherwise init a fresh repo for baseline/verify.
    if (work / ".git").is_dir():
        return
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    subprocess.run(["git", "add", "."], cwd=work, check=True)
    subprocess.run(["git", "-c", "user.email=bench@local",
                    "-c", "user.name=Bonsai Bench",
                    "commit", "-qm", "fixture"], cwd=work, check=True)


def _protected_intact(fixture: Path, work: Path) -> bool:
    for p in list(fixture.glob("test*.py")) + list((fixture / "tests").glob("test*.py") if (fixture / "tests").is_dir() else []):
        rel = p.relative_to(fixture)
        if not (work / rel).is_file():
            return False
        if (work / rel).read_bytes() != p.read_bytes():
            return False
    return True


def _verify(work: Path, test_command: str, hidden_check: str = "") -> dict:
    v = subprocess.run(test_command, cwd=work, shell=True, text=True,
                       capture_output=True, timeout=600)
    hidden_ok: bool | None = None
    hidden_out = ""
    if hidden_check:
        h = subprocess.run(hidden_check, cwd=work, shell=True, text=True,
                           capture_output=True, timeout=600)
        hidden_ok = h.returncode == 0
        hidden_out = (h.stdout + h.stderr)[-1000:]
    return {"tests_pass": v.returncode == 0,
            "test_stdout": (v.stdout + v.stderr)[-2000:],
            "hidden_pass": hidden_ok, "hidden_stdout": hidden_out}


def run_bonsai_local(task: dict, llm_factory=None,
                     timeout_s: float = 600) -> dict:
    """Run a tier task through the in-process bonsai_local Agent.

    llm_factory(root) -> LLM; defaults to a stub that raises (marks
    adapter wiring without needing a model). Returns SPEC metrics dict.
    """
    from bonsai_agent.agent import Agent
    from bonsai_agent import testscope

    t0 = time.time()
    fixture = Path(task["fixture"])
    td = tempfile.mkdtemp(prefix="bonsai-m6-")
    work = Path(td) / "repo"
    shutil.copytree(fixture, work)
    _git_init(work)
    baseline = subprocess.run(task["test_command"], cwd=work, shell=True,
                              text=True, capture_output=True)
    baseline_failed = baseline.returncode != 0
    before = testscope.snapshot_protected(work)
    if llm_factory is None:
        def llm_factory(_root):
            raise RuntimeError("no LLM configured for bonsai_local adapter")
    llm = llm_factory(work)
    agent = Agent(work, llm, tests=task["test_command"],
                  max_steps=30, verify_tests_only=True)
    status = "error"
    err = ""
    try:
        rid = agent.start(task["objective"], single_task=True)
        agent.run(rid)
        status = agent.db.get_run(rid)["status"]
        llm_sum = agent.db.llm_summary(rid)
    except Exception as e:  # noqa: BLE001 — recorded, not raised
        err = repr(e)[:500]
        llm_sum = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                   "total_tokens": 0, "seconds": 0.0}
    ver = _verify(work, task["test_command"], task.get("hidden_check", ""))
    prot = testscope.verify_protected(work, before)
    intact = _protected_intact(fixture, work)
    tests_pass = ver["tests_pass"] and (ver["hidden_pass"] is not False)
    clean = (baseline_failed and status == "complete" and tests_pass
             and prot["ok"] and intact)
    return {"harness": "bonsai_local", "id": task["id"], "tier": task["tier"],
            "baseline_failed": baseline_failed, "run_status": status,
            "tests_pass": tests_pass, "hidden_pass": ver["hidden_pass"],
            "tests_unchanged": intact and prot["ok"],
            "protected_detail": prot,
            "clean": clean, "clean_exit": status in ("complete", "paused"),
            "pass_rate": 1.0 if clean else 0.0,
            "seconds": round(time.time() - t0, 1),
            "total_tokens": llm_sum.get("total_tokens", 0),
            "tool_calls": llm_sum.get("calls", 0),
            "error": err, "test_stdout": ver["test_stdout"],
            "workdir": str(work)}


def hermes_cmd(prompt: str, model: str = "bonsai-abliterated-mtp",
               hermes_bin: str = ".venv-hermes/bin/hermes") -> list[str]:
    """CLI argv for a Hermes direct-mode coding turn (M2-proven flags)."""
    return [hermes_bin, "chat", "-q", prompt, "-Q", "--yolo",
            "--model", model]


def paperclip_contract(task: dict, company: str = "bonsai-local",
                       employee: str = "Bonsai Coder") -> dict:
    """Record the Paperclip->Hermes->Bonsai dispatch contract for a task."""
    from bonsai_agent.paperclip import TaskContract
    contract = TaskContract(
        task_id=task["id"], objective=task["objective"],
        acceptance="Configured tests pass and benchmark tests remain unchanged.",
        workspace=str(task["fixture"]), verification=task["test_command"])
    issue = contract.to_issue(task["id"])
    return {"harness": "paperclip", "id": task["id"], "tier": task["tier"],
            "company": company, "employee": employee,
            "issue_title": issue["title"],
            "issue_body_chars": len(issue["description"]),
            "contract_keys": sorted(issue.keys())}


def compare_reports(reports: list[dict]) -> dict:
    """Rank harness reports per SPEC promotion ordering."""
    def key(r):
        return (not r.get("clean", False),
                -(r.get("pass_rate", 0.0)),
                not r.get("clean_exit", False),
                not r.get("tests_unchanged", False),
                r.get("total_tokens", 10 ** 12),
                r.get("seconds", 10 ** 12))
    ranked = sorted(reports, key=key)
    return {"promotion_order": PROMOTION_ORDER,
            "ranking": [r.get("harness", r.get("id")) for r in ranked],
            "reports": reports}


def main() -> None:  # CLI: bonsai-harness
    import argparse
    from bonsai_agent.tiers import tier_tasks
    p = argparse.ArgumentParser(description="M6 harness adapter runner")
    p.add_argument("--tier", type=int, default=None)
    p.add_argument("--harness", choices=["bonsai_local", "paperclip"],
                   default="bonsai_local")
    p.add_argument("--out", default="benchmarks/results/harness.json")
    a = p.parse_args()
    tasks = tier_tasks(a.tier)
    reports = []
    for t in tasks:
        print("RUN", a.harness, t["id"], flush=True)
        if a.harness == "paperclip":
            reports.append(paperclip_contract(t))
        else:
            reports.append(run_bonsai_local(t))
    payload = compare_reports(reports)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(payload, indent=2))
    print(json.dumps({k: v for k, v in payload.items()
                      if k != "reports"}, indent=2))


if __name__ == "__main__":
    main()
