"""M6 benchmark expansion (SPEC): Tiers 1-6 definitions + fixture builders.

Tier 0 (B25-B32 in benchmarks/tasks.json) is the frozen gate and is NOT
redefined here. Tiers 1-5 are real-repository tasks materialized under
benchmarks/tiers_fixtures/ by benchmarks/generate_tiers.py. Tier 6 is
adversarial robustness scenarios exercised with mocks (no LLM needed).

Each tier task: {id, tier, category, fixture, objective, test_command,
hidden_check} where hidden_check is an optional shell command run AFTER
the agent finishes (hidden acceptance not visible in TASK.md).
"""
from __future__ import annotations

import json
from pathlib import Path

TIERS_VERSION = 1

# id, tier, category, objective, test_command, hidden_check
TIER_TASKS = [
    {"id": "T101", "tier": 1, "category": "editing",
     "fixture": "benchmarks/tiers_fixtures/T101",
     "objective": "Fix the two localized bugs in the large module described in TASK.md without changing benchmark tests.",
     "test_command": "pytest -q",
     "hidden_check": "pytest -q test_hidden.py"},
    {"id": "T201", "tier": 2, "category": "repo-reasoning",
     "fixture": "benchmarks/tiers_fixtures/T201",
     "objective": "Find the cross-file bug described in TASK.md across the multi-file package without changing benchmark tests.",
     "test_command": "pytest -q",
     "hidden_check": "pytest -q tests/test_hidden.py"},
    {"id": "T301", "tier": 3, "category": "debugging",
     "fixture": "benchmarks/tiers_fixtures/T301",
     "objective": "Reproduce the stack trace in REPRO.md using git history, fix the regression, run focused then full tests.",
     "test_command": "pytest -q",
     "hidden_check": ""},
    {"id": "T401", "tier": 4, "category": "multi-file-feature",
     "fixture": "benchmarks/tiers_fixtures/T401",
     "objective": "Implement the multi-file feature described in TASK.md (model/store/api/config/tests).",
     "test_command": "pytest -q",
     "hidden_check": "pytest -q tests/test_hidden.py"},
    {"id": "T501", "tier": 5, "category": "long-horizon",
     "fixture": "benchmarks/tiers_fixtures/T501",
     "objective": "Implement the three sequential steps in TASK.md (parse/validate/summarize); each step is independently tested.",
     "test_command": "pytest -q",
     "hidden_check": ""},
]

# Tier 6 adversarial scenarios (mock-level, no LLM). Each maps to the
# existing module that must handle it; tests/test_m6_benchmark.py drives them.
TIER6_SCENARIOS = [
    {"id": "T601", "name": "http-503-retry",
     "expect": "resilience retries 503 with backoff then succeeds"},
    {"id": "T602", "name": "malformed-tool-args",
     "expect": "transcript validation rejects orphan/malformed tool calls"},
    {"id": "T603", "name": "oversized-output",
     "expect": "tool output truncated, run continues"},
    {"id": "T604", "name": "flaky-command",
     "expect": "retry wrapper recovers a flaky command"},
    {"id": "T605", "name": "unrelated-dirt",
     "expect": "task_owned excludes pre-existing dirt; quarantine preserves it"},
    {"id": "T606", "name": "test-tampering",
     "expect": "protected-test modification detected and fails task"},
    {"id": "T607", "name": "interrupted-session",
     "expect": "checkpoint write + revalidate after simulated interrupt"},
    {"id": "T608", "name": "conflicting-edit",
     "expect": "ambiguous replace rejected, no file change"},
]


def tier_tasks(tier: int | None = None) -> list[dict]:
    if tier is None:
        return list(TIER_TASKS)
    return [t for t in TIER_TASKS if t["tier"] == tier]


def write_tiers_json(path: Path = Path("benchmarks/tiers.json")) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {"version": TIERS_VERSION, "tasks": TIER_TASKS,
         "tier6": TIER6_SCENARIOS}, indent=2))
    return path


def load_tiers_json(path: Path = Path("benchmarks/tiers.json")) -> dict:
    return json.loads(Path(path).read_text())
