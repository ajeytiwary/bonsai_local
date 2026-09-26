"""Safe git lifecycle (SPEC M4): baseline/dirt, worktree/branch isolation,
task-owned staging, quarantine/reset of failed changes.

- Never blind `git add -A`: commit explicit task-owned paths only.
- Failed-task changes are quarantined/reset without touching unrelated work.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args],
                          text=True, capture_output=True, timeout=60)


@dataclass
class Baseline:
    commit: str = ""
    dirt: list[str] = field(default_factory=list)  # pre-existing uncommitted paths
    branch: str = ""


def capture_baseline(root: Path) -> Baseline:
    commit = _git(root, "rev-parse", "HEAD").stdout.strip()
    status = _git(root, "status", "--porcelain").stdout
    dirt = [line[3:].strip().strip('"') for line in status.splitlines() if line.strip()]
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    return Baseline(commit=commit, dirt=dirt, branch=branch)


def changed_vs_baseline(root: Path, baseline: Baseline) -> list[str]:
    """Paths changed since baseline commit (worktree + index + untracked)."""
    out = _git(root, "diff", "--name-only", baseline.commit).stdout
    out2 = _git(root, "diff", "--name-only").stdout
    out3 = _git(root, "diff", "--name-only", "--cached").stdout
    # untracked files never appear in diffs — take them from status.
    untracked = [l[3:].strip().strip('"') for l in
                 _git(root, "status", "--porcelain").stdout.splitlines()
                 if l.startswith("?? ")]
    seen = []
    for line in (out + "\n" + out2 + "\n" + out3).splitlines() + untracked:
        p = line.strip()
        if p and p not in seen:
            seen.append(p)
    return seen


def task_owned(changed: list[str], baseline_dirt: list[str]) -> list[str]:
    """Changed paths minus pre-existing dirt = task-owned."""
    return [p for p in changed if p not in set(baseline_dirt)]


def commit_paths(root: Path, paths: list[str], message: str) -> str:
    """Stage + commit explicit paths only. Never `git add -A`."""
    if not paths:
        return "no task-owned changes to commit"
    a = _git(root, "add", "--", *paths)
    if a.returncode != 0:
        return "commit skipped: " + (a.stderr or a.stdout)[-500:]
    c = _git(root, "-c", "user.name=Bonsai Agent", "-c",
             "user.email=bonsai@local", "commit", "-m", message)
    return (c.stdout + c.stderr)[-1000:]


def quarantine_reset(root: Path, paths: list[str]) -> str:
    """Reset + checkout failed task-owned paths; leave unrelated work alone."""
    if not paths:
        return "nothing to quarantine"
    # Split owned paths: untracked files are unlinked, tracked are reset.
    untracked_now = {l[3:].strip().strip('"') for l in
                     _git(root, "status", "--porcelain").stdout.splitlines()
                     if l.startswith("?? ")}
    owned_new = [p for p in paths if p in untracked_now]
    tracked = [p for p in paths if p not in untracked_now]
    for p in owned_new:
        try:
            (root / p).unlink()
        except OSError:
            pass
    if not tracked:
        return "quarantined: " + ", ".join(paths)
    r1 = _git(root, "reset", "-q", "--", *tracked)
    r2 = _git(root, "checkout", "--", *tracked)
    ok = r1.returncode == 0 and r2.returncode == 0
    return ("quarantined: " + ", ".join(paths)) if ok else (
        "quarantine failed: " + ((r1.stderr + r2.stderr) or "unknown")[-500:])


def create_worktree(repo: Path, path: Path, branch: str | None = None) -> str:
    """Isolate a task in a linked worktree (dedicated workspace per SPEC)."""
    args = ["worktree", "add"]
    if branch:
        args += ["-b", branch]
    args += [str(path)]
    r = _git(repo, *args)
    if r.returncode != 0:
        raise RuntimeError("worktree add failed: " + (r.stderr or r.stdout)[-500:])
    return str(path)


def remove_worktree(repo: Path, path: Path, force: bool = False) -> str:
    args = ["worktree", "remove"] + (["--force"] if force else []) + [str(path)]
    r = _git(repo, *args)
    return (r.stdout + r.stderr)[-500:]
