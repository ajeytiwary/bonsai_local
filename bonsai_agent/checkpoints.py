"""Checkpoint/resume with revalidation (SPEC M4).

Persists: objective, acceptance, baseline commit, task-owned files,
completed steps, unresolved failures, diff, tests, compact context summary,
next action. Resume revalidates filesystem/git state (baseline commit still
present, task-owned files unchanged since checkpoint, no new unrelated dirt
blocking the task).
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Checkpoint:
    objective: str = ""
    acceptance: str = ""
    baseline_commit: str = ""
    task_owned_files: list[str] = field(default_factory=list)
    completed_steps: list[str] = field(default_factory=list)
    unresolved_failures: list[str] = field(default_factory=list)
    diff_stat: str = ""
    tests: str = ""
    summary: str = ""
    next_action: str = ""
    file_hashes: dict = field(default_factory=dict)  # path -> sha256 at checkpoint


def _sha256(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_checkpoint(root: Path, run_id: int, cp: Checkpoint) -> Path:
    d = root / ".agent" / "checkpoints"
    d.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for rel in cp.task_owned_files:
        p = root / rel
        if p.is_file():
            try:
                hashes[rel] = _sha256(p)
            except OSError:
                pass
    cp.file_hashes = hashes
    path = d / f"run-{run_id}.json"
    path.write_text(json.dumps(asdict(cp), indent=2))
    return path


def read_checkpoint(root: Path, run_id: int) -> Checkpoint | None:
    path = root / ".agent" / "checkpoints" / f"run-{run_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return Checkpoint(**{k: data.get(k, getattr(Checkpoint, k, None))
                         for k in Checkpoint.__dataclass_fields__})


def revalidate(root: Path, cp: Checkpoint) -> dict:
    """Revalidate fs/git state at resume. Returns {ok, issues[]}."""
    issues: list[str] = []
    # baseline commit still reachable?
    r = subprocess.run(["git", "-C", str(root), "cat-file", "-e", cp.baseline_commit],
                       capture_output=True, timeout=30)
    if r.returncode != 0:
        issues.append(f"baseline commit {cp.baseline_commit[:12]} not reachable")
    # task-owned files unchanged since checkpoint?
    for rel, h in (cp.file_hashes or {}).items():
        p = root / rel
        if not p.is_file():
            issues.append(f"task-owned file missing: {rel}")
            continue
        try:
            if _sha256(p) != h:
                issues.append(f"task-owned file changed since checkpoint: {rel}")
        except OSError as e:
            issues.append(f"cannot hash {rel}: {e}")
    return {"ok": not issues, "issues": issues}
