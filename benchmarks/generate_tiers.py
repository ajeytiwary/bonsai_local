"""Materialize M6 Tier 1-5 fixtures under benchmarks/tiers_fixtures/.

Idempotent: wipes and regenerates. Tier 0 (B01-B40) is untouched.
Each fixture ships TASK.md + app/tests + (Tier 3) REPRO.md + git history.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent / "tiers_fixtures"


def _w(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


# Rootdir import fix: pytest's rootdir-based sys.path insertion (rootdir
# itself, not the test file's dir) means `tests/` imports of top-level
# packages fail when rootdir != fixture dir. A fixture-local conftest.py
# that pins sys.path to the fixture dir keeps `pytest -q` working from
# the fixture root with no extra flags.
_CONFTEST = ("import sys\nfrom pathlib import Path\n"
             "sys.path.insert(0, str(Path(__file__).parent))\n")


def _git_init(d: Path, msg: str = "fixture") -> None:
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "add", "."], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.email=bench@local",
                    "-c", "user.name=Bonsai Bench",
                    "commit", "-qm", msg], cwd=d, check=True)


def build_t101(d: Path) -> None:
    """Tier 1 editing: ~600-line module, two localized bugs, hidden tests."""
    body = ['"""Ledger module — do not restructure; fix the two bugs."""',
            "", "RATE = 1.05", ""]
    for i in range(120):
        body.append(f"def helper_{i}(x):\n    return x + {i}\n")
    body.append("def apply_rate(amount):\n    return amount * RATE + 1  # BUG: off-by-one surcharge\n")
    body.append("def clamp_total(xs, lo, hi):\n    return max(lo, max(hi, sum(xs)))  # BUG: max instead of min\n")
    _w(d / "ledger.py", "\n".join(body))
    _w(d / "test_ledger.py",
       "from ledger import apply_rate, clamp_total\n"
       "def test_rate():\n    assert apply_rate(100) == 105.0\n"
       "def test_clamp():\n    assert clamp_total([1, 2], 0, 10) == 3\n"
       "    assert clamp_total([20], 0, 10) == 10\n")
    _w(d / "test_hidden.py",
       "from ledger import apply_rate, clamp_total, helper_0, helper_119\n"
       "def test_hidden_rate():\n    assert apply_rate(0) == 0.0\n"
       "    assert apply_rate(200) == 210.0\n"
       "def test_hidden_clamp():\n"
       "    assert clamp_total([], 0, 10) == 0\n"
       "    assert clamp_total([-5], 0, 10) == 0\n"
       "def test_helpers_intact():\n"
       "    assert helper_0(1) == 1 and helper_119(1) == 120\n")
    _w(d / "TASK.md",
       "# Task T101 (Tier 1 editing)\n\n"
       "In `ledger.py`, fix `apply_rate` (must be exactly `amount * RATE`) "
       "and `clamp_total` (must bound the sum within [lo, hi]). "
       "Do not restructure the module or modify tests.\n")


def build_t201(d: Path) -> None:
    """Tier 2 repo reasoning: bug lives across imports; decoy files."""
    _w(d / "pkg" / "__init__.py", "")
    _w(d / "pkg" / "config.py", 'CURRENCY = "USD"\nRATE = 1.05\n')
    _w(d / "pkg" / "pricing.py",
       "from pkg.config import RATE\n\n"
       "def price(amount):\n    return amount * RATE\n")
    _w(d / "pkg" / "cart.py",
       "from pkg.pricing import price\n\n"
       "def total(items):\n    return sum(price(x) for x in items) + 1  # BUG: stray surcharge\n")
    for i in range(15):  # decoys: irrelevant modules
        _w(d / "pkg" / f"decoy_{i}.py",
           f'"""Decoy module {i} — unrelated."""\nVALUE_{i} = {i}\n')
    _w(d / "tests" / "test_cart.py",
       "from pkg.cart import total\n"
       "def test_total():\n    assert total([100]) == 105.0\n"
       "    assert total([]) == 0.0\n")
    _w(d / "tests" / "test_hidden.py",
       "from pkg.cart import total\n"
       "from pkg.pricing import price\n"
       "def test_hidden():\n    assert price(200) == 210.0\n"
       "    assert total([100, 100]) == 210.0\n")
    _w(d / "TASK.md",
       "# Task T201 (Tier 2 repo reasoning)\n\n"
       "Cart totals are 1.0 too high. Trace the cross-file imports "
       "(`pkg/cart.py` <- `pkg/pricing.py` <- `pkg/config.py`) and fix the "
       "real defect. Many `decoy_*` modules are irrelevant. "
       "Do not modify tests.\n")
    _w(d / "conftest.py", _CONFTEST)


def build_t301(d: Path) -> None:
    """Tier 3 debugging: git history holds the regression; REPRO.md trace."""
    _w(d / "app.py", "def clamp(x, lo, hi):\n    return min(hi, max(lo, x))\n")
    _w(d / "test_app.py",
       "from app import clamp\n"
       "def test_clamp():\n    assert clamp(5, 0, 10) == 5\n"
       "    assert clamp(-1, 0, 10) == 0\n"
       "    assert clamp(20, 0, 10) == 10\n")
    _git_init(d, "baseline correct")
    # regressing commit (visible in git log)
    (d / "app.py").write_text(
        "def clamp(x, lo, hi):\n    return max(lo, max(hi, x))  # REGRESSION\n")
    subprocess.run(["git", "-C", str(d), "commit", "-qam", "regress clamp"],
                   check=True)
    _w(d / "REPRO.md",
       "# Repro\n\n```\n$ pytest -q\nFAILED test_app.py::test_clamp - assert 20 == 10\n"
       "```\n\n`git log --oneline` shows a recent 'regress clamp' commit. "
       "Revert the regression in `app.py`, run the focused test, then the full suite.\n")
    _w(d / "TASK.md",
       "# Task T301 (Tier 3 debugging/history)\n\n"
       "Follow REPRO.md: reproduce the failure, inspect `git log`/`git show` "
       "to find the regressing commit, fix `app.py`, run the focused test "
       "then the full suite. Do not modify tests.\n")


def build_t401(d: Path) -> None:
    """Tier 4 multi-file feature: model/store/api/config + tests."""
    _w(d / "store" / "__init__.py", "")
    _w(d / "store" / "model.py",
       '"""Item model."""\n\n'
       "class Item:\n    def __init__(self, name, price):\n"
       "        self.name = name\n        self.price = price\n")
    _w(d / "store" / "db.py",
       '"""In-memory item store — implement."""\n\n'
       "class Store:\n    def __init__(self):\n        raise NotImplementedError\n"
       "    def add(self, item):\n        raise NotImplementedError\n"
       "    def get(self, name):\n        raise NotImplementedError\n"
       "    def total(self):\n        raise NotImplementedError\n")
    _w(d / "store" / "api.py",
       '"""JSON API over the store — implement."""\n\n'
       "def to_json(store):\n    raise NotImplementedError\n\n"
       "def from_json(payload):\n    raise NotImplementedError\n")
    _w(d / "config.toml", 'currency = "USD"\nrate = 1.05\n')
    _w(d / "tests" / "test_store.py",
       "from store.model import Item\n"
       "from store.db import Store\n"
       "from store.api import to_json, from_json\n"
       "import json\n"
       "def test_flow():\n"
       "    s = Store()\n"
       "    s.add(Item('a', 100))\n"
       "    assert s.get('a').price == 100\n"
       "    assert s.total() == 100\n"
       "    payload = json.loads(to_json(s))\n"
       "    assert payload[0]['name'] == 'a'\n"
       "    s2 = from_json(to_json(s))\n"
       "    assert s2.total() == 100\n")
    _w(d / "tests" / "test_hidden.py",
       "from store.model import Item\n"
       "from store.db import Store\n"
       "def test_hidden():\n"
       "    s = Store()\n"
       "    assert s.total() == 0\n"
       "    assert s.get('missing') is None\n"
       "    s.add(Item('a', 1)); s.add(Item('b', 2))\n"
       "    assert s.total() == 3\n")
    _w(d / "TASK.md",
       "# Task T401 (Tier 4 multi-file feature)\n\n"
       "Implement `Store` (dict-backed: add/get/total, get returns None when "
       "missing), `to_json`/`from_json` (JSON list of {name, price}), "
       "keeping `Item` and `config.toml` as-is. Do not modify tests.\n")
    _w(d / "conftest.py", _CONFTEST)


def build_t501(d: Path) -> None:
    """Tier 5 long horizon: three sequential steps, independently tested."""
    _w(d / "pipe.py",
       '"""Three-step pipeline — implement each step."""\n\n'
       "def parse(text):\n    raise NotImplementedError\n\n"
       "def validate(rows):\n    raise NotImplementedError\n\n"
       "def summarize(rows):\n    raise NotImplementedError\n")
    _w(d / "test_step1.py",
       "from pipe import parse\n"
       "def test_parse():\n"
       "    assert parse('a:1,b:2') == [{'a': '1'}, {'b': '2'}]\n")
    _w(d / "test_step2.py",
       "from pipe import parse, validate\n"
       "def test_validate():\n"
       "    assert validate([{'a': '1'}, {'b': ''}]) == [{'a': '1'}]\n")
    _w(d / "test_step3.py",
       "from pipe import parse, validate, summarize\n"
       "def test_summarize():\n"
       "    rows = validate(parse('a:1,b:2'))\n"
       "    assert summarize(rows) == {'count': 2}\n")
    _w(d / "TASK.md",
       "# Task T501 (Tier 5 long horizon)\n\n"
       "Implement `pipe.py` in order: (1) `parse` splits `k:v` pairs on "
       "commas into a list of single-key dicts; (2) `validate` drops rows "
       "with empty values; (3) `summarize` returns `{'count': len(rows)}`. "
       "Run each step's test as you go. Do not modify tests.\n")


BUILDERS = {"T101": build_t101, "T201": build_t201, "T301": build_t301,
            "T401": build_t401, "T501": build_t501}


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    ROOT.mkdir(parents=True)
    for tid, build in BUILDERS.items():
        d = ROOT / tid
        d.mkdir(parents=True)
        build(d)
        if tid != "T301":  # T301 manages its own history
            _git_init(d, f"fixture {tid}")
    print("generated", len(BUILDERS), "tier fixtures in", ROOT)


if __name__ == "__main__":
    main()
