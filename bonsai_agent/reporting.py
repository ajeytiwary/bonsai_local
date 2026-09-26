"""M6 structured reports (SPEC observability): JSONL events + summary JSON.

report_path(results_dir) -> benchmarks/results/m6-<stamp>.json
write_report(tasks, reports, out) writes the SPEC-compatible summary:
{results, clean_count, total_tasks, pass_rate, total_seconds,
 total_tokens, tiers:{tier: {clean/total}}, promotion:{...}}.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

RESULTS_DIR = Path("benchmarks/results")


def report_path(stamp: str | None = None) -> Path:
    stamp = stamp or datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return RESULTS_DIR / f"m6-{stamp}.json"


def write_report(tasks: list[dict], reports: list[dict],
                 out: Path | str) -> dict:
    from bonsai_agent.harness import compare_reports
    out = Path(out)
    by_id = {r.get("id"): r for r in reports}
    tiers: dict[str, dict] = {}
    for t in tasks:
        tier = str(t["tier"])
        tiers.setdefault(tier, {"clean": 0, "total": 0})
        tiers[tier]["total"] += 1
        if by_id.get(t["id"], {}).get("clean"):
            tiers[tier]["clean"] += 1
    clean_count = sum(1 for r in reports if r.get("clean"))
    payload = {
        "results": reports,
        "clean_count": clean_count,
        "total_tasks": len(tasks),
        "pass_rate": clean_count / max(1, len(tasks)),
        "total_seconds": round(sum(r.get("seconds", 0) for r in reports), 1),
        "total_tokens": sum(r.get("total_tokens", 0) for r in reports),
        "tiers": tiers,
        "promotion": compare_reports(reports),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))
    return payload
