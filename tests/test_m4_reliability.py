"""M4 reliability tests (SPEC required tests).

Covers: retry/backoff + no-retry malformed 4xx, sanitized errors,
tool transcript integrity + truncation groups, token compaction budget,
checkpoint/resume revalidation, incremental repo index, focused-test
selection + protected-test hashes, task-owned staging + dirty
isolation/rollback, Hermes config generation, Paperclip adapter/health.
"""
import io
import json

import pytest

from bonsai_agent.resilience import (
    AttemptError, RetryConfig, backoff_delay, call_with_retry, classify,
    new_request_id, sanitize,
)
from bonsai_agent.transcripts import (
    TranscriptError, truncate_transcript, validate_transcript,
)
from bonsai_agent.context import (
    ContextBudget, estimate_tokens, fit_to_budget, usage_of,
)
from bonsai_agent import checkpoints as ckpt_mod
from bonsai_agent.checkpoints import Checkpoint
from bonsai_agent import gitwork
from bonsai_agent import testscope
from bonsai_agent.repo_index import RepoIndex
from bonsai_agent.progress import EventLog, Progress


# ------------------------------------------------------------- retry/backoff

def test_backoff_bounded_and_growing():
    cfg = RetryConfig(base_delay=0.5, max_delay=8.0, jitter=0.0)
    d0 = backoff_delay(0, cfg, rng=lambda: 0.5)
    d1 = backoff_delay(1, cfg, rng=lambda: 0.5)
    d9 = backoff_delay(9, cfg, rng=lambda: 0.5)
    assert d0 == pytest.approx(0.5)
    assert d1 == pytest.approx(1.0)
    assert d9 == pytest.approx(8.0)  # capped at max_delay


def test_classify_no_retry_malformed_4xx():
    for s in (400, 401, 403, 404, 422, 418):
        assert classify(s) == "noretry", s


def test_classify_retry_transient():
    for s in (408, 429, 500, 502, 503, 504):
        assert classify(s) == "retry", s
    assert classify(None, "ConnectError") == "retry"
    assert classify(None, "ReadTimeout") == "retry"


def test_call_with_retry_retries_503_then_succeeds():
    calls = []

    class Fake503(Exception):
        status_code = 503

    def fn(attempt, rid):
        calls.append((attempt, rid))
        if attempt < 2:
            raise Fake503("service unavailable")
        return "ok"

    cfg = RetryConfig(max_retries=3, base_delay=0.01, max_delay=0.05, jitter=0.0)
    result, meta = call_with_retry(fn, cfg, sleep=lambda s: None)
    assert result == "ok"
    assert meta["attempts"] == 3 and meta["retries"] == 2
    assert len({r for _, r in calls}) == 3  # unique request id per attempt


def test_call_with_retry_no_retry_on_400():
    slept = []

    class Fake400(Exception):
        status_code = 400

    def fn(attempt, rid):
        raise Fake400("malformed request: bad json")

    with pytest.raises(AttemptError) as ei:
        call_with_retry(fn, RetryConfig(max_retries=3), sleep=slept.append)
    assert ei.value.kind == "noretry"
    assert ei.value.status_code == 400
    assert slept == []  # never slept = never retried


def test_sanitize_strips_secrets():
    dirty = "apiKey: abcdef1234567890abcdef header Bearer sk-xyz-token value secret= hunter2 token= abc"
    clean = sanitize(dirty)
    assert "abcdef1234567890abcdef" not in clean
    assert "REDACTED" in clean
    assert len(sanitize("x" * 1000)) <= 500


def test_request_ids_unique():
    assert len({new_request_id() for _ in range(50)}) == 50


# ------------------------------------------------------- transcript integrity

def _group(cid="c1"):
    return [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "do"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": cid, "type": "function",
                         "function": {"name": "read_file", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": cid, "content": "out"},
    ]


def test_transcript_valid_group():
    out = validate_transcript(_group())
    assert out["valid"] and out["tool_calls"] == 1


def test_transcript_orphan_call_fails():
    msgs = _group()[:3]
    with pytest.raises(TranscriptError, match="orphan"):
        validate_transcript(msgs)


def test_transcript_orphan_result_fails():
    msgs = [{"role": "user", "content": "x"},
            {"role": "tool", "tool_call_id": "nope", "content": "y"}]
    with pytest.raises(TranscriptError, match="preceding call"):
        validate_transcript(msgs)


def test_transcript_bad_role_fails():
    with pytest.raises(TranscriptError, match="invalid role"):
        validate_transcript([{"role": "hidden", "content": "reasoning trace"}])


def test_truncate_never_splits_group():
    msgs = ([{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
            + _group("c1")[2:] + _group("c2")[2:] + _group("c3")[2:])
    kept = truncate_transcript(msgs, keep_last_groups=1)
    assert kept[:2] == msgs[:2]
    validate_transcript(kept)  # still valid: no orphan
    assert any(m.get("tool_call_id") == "c3" for m in kept)
    assert not any(m.get("tool_call_id") == "c1" for m in kept)


# ------------------------------------------------------------ context budget

def test_estimate_tokens_conservative():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcdefgh") == 2


def test_fit_to_budget_preserves_system_and_groups():
    budget = ContextBudget(total=200, system=10, task_acceptance=10,
                           durable_summary=10, repo_context=10,
                           reasoning_reserve=10, output_reserve=10)
    msgs = ([{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
            + _group("c1")[2:] + _group("c2")[2:] + _group("c3")[2:])
    fitted, use = fit_to_budget(msgs, budget)
    validate_transcript(fitted)
    assert fitted[0]["content"] == "s" and fitted[1]["content"] == "u"
    assert use.tokens <= use.budget


def test_usage_show_reports_pressure():
    budget = ContextBudget(total=1000)
    use = usage_of([{"role": "user", "content": "hello world"}], budget)
    assert "context" in use.show() and "/" in use.show()


# -------------------------------------------------------- checkpoint / resume

def test_checkpoint_write_read_revalidate(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path,
                          text=True, capture_output=True).stdout.strip()
    cp = Checkpoint(objective="o", acceptance="a", baseline_commit=head,
                    task_owned_files=["a.txt"], summary="s", next_action="n")
    ckpt_mod.write_checkpoint(tmp_path, 1, cp)
    back = ckpt_mod.read_checkpoint(tmp_path, 1)
    assert back.objective == "o" and back.file_hashes.get("a.txt")
    assert ckpt_mod.revalidate(tmp_path, back)["ok"]
    (tmp_path / "a.txt").write_text("changed!")
    rep = ckpt_mod.revalidate(tmp_path, back)
    assert not rep["ok"] and any("a.txt" in i for i in rep["issues"])


# ---------------------------------------------------------- incremental index

def test_repo_index_incremental(tmp_path):
    (tmp_path / "alpha.py").write_text("def sentinel_ingest():\n    return 'ok'\n")
    (tmp_path / "beta.py").write_text("def unrelated():\n    pass\n")
    idx = RepoIndex(tmp_path)
    r1 = idx.refresh()
    assert r1["added"] == 2
    top = idx.search("sentinel ingest", top_k=1)
    assert top and top[0]["path"] == "alpha.py"
    assert "sentinel_ingest" in top[0]["symbols"]
    r2 = idx.refresh()  # no changes -> nothing re-read
    assert r2["added"] == 0 and r2["updated"] == 0
    (tmp_path / "beta.py").write_text("def sentinel_ingest_v2():\n    pass\n")
    r3 = idx.refresh()
    assert r3["updated"] == 1 and r3["added"] == 0
    assert (idx.state_path).exists()


# ------------------------------------------------- testscope + protected hash

def test_protected_hash_detects_modification(tmp_path):
    (tmp_path / "test_app.py").write_text("def test_x(): assert True\n")
    before = testscope.snapshot_protected(tmp_path)
    assert testscope.verify_protected(tmp_path, before)["ok"]
    (tmp_path / "test_app.py").write_text("def test_x(): assert False\n")
    rep = testscope.verify_protected(tmp_path, before)
    assert not rep["ok"] and rep["modified"]


def test_focused_tests_for(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("x=1\n")
    (tmp_path / "app.py").write_text("x=1\n")
    found = testscope.focused_tests_for(["app.py"], tmp_path)
    assert any("test_app" in f for f in found)


# ---------------------------------------------- git task-owned + quarantine

def _git_repo(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "app.py").write_text("v1\n")
    (tmp_path / "user.txt").write_text("mine\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    return tmp_path


def test_task_owned_excludes_preexisting_dirt(tmp_path):
    _git_repo(tmp_path)
    (tmp_path / "user.txt").write_text("user edit\n")  # pre-existing dirt
    base = gitwork.capture_baseline(tmp_path)
    assert "user.txt" in base.dirt
    (tmp_path / "app.py").write_text("v2\n")  # task change
    changed = gitwork.changed_vs_baseline(tmp_path, base)
    owned = gitwork.task_owned(changed, base.dirt)
    assert "app.py" in owned and "user.txt" not in owned


def test_quarantine_resets_task_only(tmp_path):
    _git_repo(tmp_path)
    (tmp_path / "user.txt").write_text("user edit\n")
    base = gitwork.capture_baseline(tmp_path)
    (tmp_path / "app.py").write_text("v2 broken\n")
    (tmp_path / "scratch_new.py").write_text("tmp\n")
    changed = gitwork.changed_vs_baseline(tmp_path, base)
    owned = gitwork.task_owned(changed, base.dirt)
    gitwork.quarantine_reset(tmp_path, owned)
    assert (tmp_path / "app.py").read_text() == "v1\n"
    assert (tmp_path / "user.txt").read_text() == "user edit\n"  # untouched
    assert not (tmp_path / "scratch_new.py").exists()


def test_commit_paths_never_adds_all(tmp_path):
    _git_repo(tmp_path)
    (tmp_path / "user.txt").write_text("user edit\n")
    base = gitwork.capture_baseline(tmp_path)
    (tmp_path / "app.py").write_text("v2\n")
    owned = gitwork.task_owned(gitwork.changed_vs_baseline(tmp_path, base), base.dirt)
    out = gitwork.commit_paths(tmp_path, owned, "bonsai: fix")
    assert "user.txt" not in out or "1 file changed" in out
    import subprocess
    show = subprocess.run(["git", "show", "--name-only", "--pretty=format:"],
                          cwd=tmp_path, text=True, capture_output=True).stdout
    assert "app.py" in show and "user.txt" not in show


# ------------------------------------------------- progress + observability

def test_progress_and_eventlog_no_secrets(tmp_path):
    sink = io.StringIO()
    p = Progress(sink=sink, run_id=1, model="m", harness="h")
    p.phase(2, "start", "apiKey= abcdef1234567890abcdef begin")
    p.retry(2, 1, 0.5, status=503)
    p.final(2, "done")
    text = sink.getvalue()
    assert "abcdef1234567890abcdef" not in text and "REDACTED" in text
    log = EventLog(tmp_path / "events.jsonl")
    rec = log.event(1, 2, "step", 1.5, True, apiKey="abcdef1234567890abcdef")
    assert "abcdef1234567890abcdef" not in json.dumps(rec)
    summary = log.summary([{"clean": True, "seconds": 1, "total_tokens": 5},
                           {"clean": False, "seconds": 2, "total_tokens": 7}])
    assert summary["clean_count"] == 1 and summary["pass_rate"] == 0.5


# --------------------------------------- llm wiring: retry + tuple timeouts

def test_llm_retries_503_and_sends_request_id(monkeypatch):
    from bonsai_agent.llm import BonsaiLLM
    from bonsai_agent.resilience import RetryConfig
    seen = []
    calls = {"n": 0}

    class R:
        def raise_for_status(self):
            if calls["n"] < 3:
                e = Exception("503 Service Unavailable")
                e.status_code = 503
                raise e

        def json(self):
            return {"usage": {}, "choices": [{"message": {"content": "hi"}}]}

    def post(url, json, timeout, headers=None, **kw):
        calls["n"] += 1
        seen.append((timeout, (headers or {}).get("X-Request-Id")))
        return R()

    monkeypatch.setattr("bonsai_agent.llm.requests.post", post)
    llm = BonsaiLLM(timeout=900,
                    retry_config=RetryConfig(max_retries=3, base_delay=0.01,
                                             max_delay=0.05, jitter=0.0))
    assert llm.chat([{"role": "user", "content": "hi"}]) == "hi"
    assert calls["n"] == 3
    assert seen[0][0] == (10, 900)  # tuple (connect, read) timeout
    assert len({r for _, r in seen}) == 3  # unique rid per attempt


def test_llm_no_retry_400_raises_runtime(monkeypatch):
    from bonsai_agent.llm import BonsaiLLM

    class R:
        def raise_for_status(self):
            e = Exception("400 malformed")
            e.status_code = 400
            raise e

        def json(self):
            raise AssertionError("unreachable")

    monkeypatch.setattr("bonsai_agent.llm.requests.post",
                        lambda *a, **k: R())
    with pytest.raises(RuntimeError, match="noretry"):
        BonsaiLLM().chat([{"role": "user", "content": "hi"}])


def test_llm_rejects_orphan_transcript():
    from bonsai_agent.llm import BonsaiLLM
    llm = BonsaiLLM()
    bad = [{"role": "user", "content": "x"},
           {"role": "assistant", "content": None,
            "tool_calls": [{"id": "c9", "type": "function",
                            "function": {"name": "read_file",
                                         "arguments": "{}"}}]}]
    with pytest.raises(Exception, match="orphan"):
        llm._post({"model": "m", "messages": bad}, 10, 0.2)
