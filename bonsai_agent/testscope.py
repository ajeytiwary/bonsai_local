"""Test-scope selection + protected-test hashing (SPEC M4 tests section).

- focused during iteration (files touched -> nearest test files)
- task acceptance before success (configured command)
- broad regression at final checkpoint/PR/risk trigger
- hash protected benchmark/acceptance tests before and after; any
  protected-test modification is failure.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

TEST_NAME_HINTS = ("test_", "_test", "tests", "spec")


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def hash_files(paths: list[Path]) -> dict[str, str]:
    out = {}
    for p in paths:
        try:
            out[str(p)] = _sha256_bytes(Path(p).read_bytes())
        except OSError:
            out[str(p)] = "<missing>"
    return out


def protected_test_files(repo: Path, patterns=("test*.py", "*_test.py")) -> list[Path]:
    found: list[Path] = []
    for pat in patterns:
        found.extend(sorted(repo.rglob(pat)))
    # exclude agent state + venvs
    return [p for p in found
            if not any(x in p.parts for x in
                       (".agent", ".venv", "venv", "node_modules", "__pycache__"))]


def snapshot_protected(repo: Path) -> dict[str, str]:
    return hash_files(protected_test_files(repo))


def verify_protected(repo: Path, before: dict[str, str]) -> dict:
    """Compare current protected-test hashes to `before`.

    Returns {ok, modified[], added[], removed[]}. Any modification is failure.
    """
    after = snapshot_protected(repo)
    modified = [k for k in before if k in after and before[k] != after[k]]
    added = [k for k in after if k not in before]
    removed = [k for k in before if k not in after]
    return {"ok": not (modified or added or removed),
            "modified": modified, "added": added, "removed": removed}


def focused_tests_for(changed: list[str], repo: Path) -> list[str]:
    """Map touched source files to nearest test files (same dir, then root tests/)."""
    tests: list[str] = []
    for rel in changed:
        stem = Path(rel).stem
        cands = [Path(rel).parent / f"test_{stem}.py",
                 Path(rel).parent / f"{stem}_test.py",
                 repo / "tests" / f"test_{stem}.py"]
        for c in cands:
            if (repo / c).is_file() if not c.is_absolute() else c.is_file():
                s = str(c)
                if s not in tests:
                    tests.append(s)
    # fallback: any test file with a matching name hint
    if not tests:
        for t in protected_test_files(repo):
            if any(h in t.name for h in TEST_NAME_HINTS):
                tests.append(str(t.relative_to(repo)))
                if len(tests) >= 4:
                    break
    return tests
