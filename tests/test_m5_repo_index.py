"""M5 repository intelligence tests (SPEC: persistent symbol/chunk/BM25/
dependency/git index with incremental refresh).

Covers: qualified symbols, overlapping chunks, dependency reverse index,
reference search, git change metadata, query modes, embeddings interface,
incremental refresh, persistence round-trip, agent repo_map via index.
"""
import json
import subprocess

import pytest

from bonsai_agent.repo_index import (
    EmbeddingProvider, NullEmbeddings, RepoIndex, parse_symbols,
)


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


@pytest.fixture
def repo(tmp_path):
    _write(tmp_path, "pkg/alpha.py",
           "import os\nfrom pkg.beta import helper\n\n"
           "class Engine:\n    def start(self):\n        return helper()\n\n"
           "def run_all():\n    e = Engine()\n    return e.start()\n")
    _write(tmp_path, "pkg/beta.py",
           "def helper():\n    return 'ok'\n")
    _write(tmp_path, "tests/test_alpha.py",
           "from pkg.alpha import Engine\n\n"
           "def test_start():\n    assert Engine().start() == 'ok'\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    return tmp_path


def test_parse_symbols_qualified(repo):
    text = (repo / "pkg/alpha.py").read_text()
    syms = parse_symbols(text, ".py")
    names = [s["name"] for s in syms]
    assert "Engine" in names and "run_all" in names
    qual = [s["qualified"] for s in syms]
    assert "Engine.start" in qual  # method qualified by class
    kinds = {s["name"]: s["kind"] for s in syms}
    assert kinds["Engine"] == "class" and kinds["start"] == "method"


def test_refresh_builds_docs_and_stats(repo):
    idx = RepoIndex(repo)
    rep = idx.refresh()
    assert rep["added"] == 3 and rep["docs"] == 3
    st = idx.stats()
    assert st["docs"] == 3 and st["symbols"] >= 5 and st["chunks"] >= 3
    assert st["avg_len"] > 0


def test_chunks_overlap_and_carry_headers(repo):
    idx = RepoIndex(repo)
    big = "\n".join(f"# line {i}\ndef fn_{i}():\n    pass" for i in range(200))
    _write(repo, "big.py", big)
    idx.refresh()
    doc = idx.docs["big.py"]
    assert len(doc.chunks) > 1
    assert all(c.startswith("FILE big.py") for c in doc.chunks)
    # overlap: a boundary line appears in two adjacent chunks
    assert any(doc.chunks[i].splitlines()[-1] in doc.chunks[i + 1]
               for i in range(len(doc.chunks) - 1))


def test_dependency_reverse_index(repo):
    idx = RepoIndex(repo)
    idx.refresh()
    assert "pkg/beta" in " ".join(idx.docs["pkg/alpha.py"].imports)
    by = idx.imported_by("pkg/beta")
    assert "pkg/alpha.py" in by
    deps = idx.dependencies("pkg/alpha.py")
    assert deps["imports"] and "tests/test_alpha.py" in deps["imported_by"]


def test_references_find_callers(repo):
    idx = RepoIndex(repo)
    idx.refresh()
    refs = idx.references("helper")
    paths = {r["path"] for r in refs}
    assert "pkg/alpha.py" in paths and "pkg/beta.py" in paths


def test_git_metadata_recorded(repo):
    idx = RepoIndex(repo)
    idx.refresh()
    meta = idx.docs["pkg/alpha.py"].git
    assert meta.get("commits")  # at least the init commit hash
    assert meta.get("change_count", 0) >= 1


def test_query_modes(repo):
    idx = RepoIndex(repo)
    idx.refresh()
    sym = idx.search("Engine", top_k=3, mode="symbol")
    assert sym and sym[0]["path"] == "pkg/alpha.py"
    txt = idx.search("return 'ok'", top_k=3, mode="text")
    assert "pkg/beta.py" in {r["path"] for r in txt}
    path = idx.search("alpha", top_k=3, mode="path")
    assert any("alpha" in r["path"] for r in path)
    test = idx.search("start engine", top_k=3, mode="test")
    assert test and "test" in test[0]["path"]
    impl = idx.search("Engine start", top_k=3, mode="implementation")
    assert impl and impl[0]["path"] == "pkg/alpha.py"
    recent = idx.search("anything", top_k=3, mode="recent")
    assert recent  # all files share the init commit; returns recency order


def test_embeddings_interface_default_null(repo):
    idx = RepoIndex(repo)
    assert isinstance(idx.embeddings, EmbeddingProvider)
    assert isinstance(idx.embeddings, NullEmbeddings)
    assert idx.embeddings.available() is False
    assert idx.embeddings.embed(["a", "b"]) == [None, None]


def test_incremental_no_rescan(repo):
    idx = RepoIndex(repo)
    idx.refresh()
    mtimes = {p: d.mtime for p, d in idx.docs.items()}
    rep = idx.refresh()
    assert rep == {"added": 0, "updated": 0, "removed": 0, "docs": 3}
    assert {p: d.mtime for p, d in idx.docs.items()} == mtimes
    _write(repo, "pkg/beta.py", "def helper():\n    return 'changed'\n")
    rep2 = idx.refresh()
    assert rep2["updated"] == 1 and rep2["added"] == 0


def test_persistence_round_trip(repo):
    idx = RepoIndex(repo)
    idx.refresh()
    idx2 = RepoIndex(repo)  # loads from .agent/repo-index.json
    assert set(idx2.docs) == set(idx.docs)
    assert idx2.docs["pkg/alpha.py"].git.get("change_count", 0) >= 1
    assert any("Engine.start" in s for s in
               idx2.docs["pkg/alpha.py"].qualified_symbols)
    assert idx2.search("Engine", mode="symbol")


def test_agent_repo_map_uses_index(repo):
    from bonsai_agent.agent import Agent

    class FakeLLM:
        model = "fake"
        def bind(self, fn): pass

    agent = Agent(repo, FakeLLM())
    mp = agent.repo_map()
    assert "pkg/alpha.py" in mp and "Engine" in mp
    assert "pkg/beta.py" in mp


def test_cli_index_flags(repo):
    import subprocess as sp
    import sys
    r = sp.run([sys.executable, "-m", "bonsai_agent.cli", "--repo", str(repo),
                "--index-stats"], text=True, capture_output=True)
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    assert payload["docs"] == 3
    r2 = sp.run([sys.executable, "-m", "bonsai_agent.cli", "--repo", str(repo),
                 "--index-search", "Engine"], text=True, capture_output=True)
    assert r2.returncode == 0
    assert "pkg/alpha.py" in r2.stdout
