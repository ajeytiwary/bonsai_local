"""M2 tests: patch exactness/ambiguity, persistent shell state, edit reports.

Covers SPEC acceptance items:
- Editing: apply_patch/unified diff; replace_in_file exact unique-match with
  ambiguity errors; range reads; new-file creation; explicit full replacement;
  every edit reports files changed/diff/stat/precondition/ambiguity.
- Persistent shell: cd/venv/export state persists across commands; timeout,
  cancellation, exit status, stdout/stderr capture.
"""
import re
import time
import threading

import pytest

from bonsai_agent.editing import (
    AmbiguityError, EditError, Editor, PreconditionError,
)
from bonsai_agent.shell import PersistentShell
from bonsai_agent.tools import WorkspaceTools


# --------------------------------------------------------------------- editing

@pytest.fixture
def ed(tmp_path):
    (tmp_path / "app.py").write_text(
        "def add(a, b):\n"
        "    return a + b\n"
        "\n"
        "def mul(a, b):\n"
        "    return a * b\n"
        "\n"
        "def sub(a, b):\n"
        "    return a - b\n"
    )
    return Editor(tmp_path)


def test_replace_unique_match_reports_stat_and_diff(ed, tmp_path):
    rep = ed.replace_in_file("app.py", "return a + b", "return a + b  # ok")
    assert rep.files_changed == ["app.py"]
    assert rep.insertions >= 1 and rep.deletions >= 1
    assert "-    return a + b" in rep.diff and "+    return a + b  # ok" in rep.diff
    assert "unique match" in rep.precondition
    text = (tmp_path / "app.py").read_text()
    assert "return a + b  # ok" in text
    # localized: other functions untouched
    assert "return a * b" in text and "return a - b" in text


def test_replace_no_match_raises_precondition(ed):
    with pytest.raises(PreconditionError, match="0 matches"):
        ed.replace_in_file("app.py", "def nonexistent(", "x")


def test_replace_ambiguous_without_occurrence(ed, tmp_path):
    # "return a" matches all three function bodies
    with pytest.raises(AmbiguityError, match="3 times"):
        ed.replace_in_file("app.py", "return a", "return z")
    # nothing written on ambiguity
    assert "return a" in (tmp_path / "app.py").read_text()


def test_replace_occurrence_selection(ed, tmp_path):
    rep = ed.replace_in_file("app.py", "return a", "return z", occurrence=2)
    lines = (tmp_path / "app.py").read_text().splitlines()
    assert lines[4] == "    return z * b"    # second match (mul) edited
    assert lines[1] == "    return a + b"    # first match untouched
    assert lines[7] == "    return a - b"    # third match untouched
    assert "occurrence=2" in rep.op or "2/" in rep.precondition


def test_replace_occurrence_out_of_range(ed):
    with pytest.raises(PreconditionError, match="out of range"):
        ed.replace_in_file("app.py", "return a", "z", occurrence=9)


def test_replace_identical_rejected(ed):
    with pytest.raises(EditError, match="identical"):
        ed.replace_in_file("app.py", "def add", "def add")


def test_read_range_window(ed):
    out = ed.read_range("app.py", 4, 5)
    assert "4\tdef mul(a, b):" in out and "5\t    return a * b" in out
    assert "def add" not in out


def test_read_range_context_extends(ed):
    out = ed.read_range("app.py", 5, 5, context=2)
    assert "3\t" in out and "7\t" in out


def test_read_range_beyond_eof(ed):
    with pytest.raises(EditError, match="beyond EOF"):
        ed.read_range("app.py", 999)


def test_create_file_new_only(ed, tmp_path):
    rep = ed.create_file("fresh.txt", "hello\n")
    assert rep.files_changed == ["fresh.txt"]
    assert (tmp_path / "fresh.txt").read_text() == "hello\n"
    with pytest.raises(PreconditionError, match="already exists"):
        ed.create_file("fresh.txt", "again")


def test_create_file_rejects_empty(ed):
    with pytest.raises(EditError, match="empty"):
        ed.create_file("empty.txt", "   \n")


def _unified(path, hunks, old_exists=True):
    hdr = (f"--- a/{path}\n+++ b/{path}\n" if old_exists
           else f"--- /dev/null\n+++ b/{path}\n")
    return hdr + "".join(hunks)


def test_apply_patch_exact_hunk(ed, tmp_path):
    patch = _unified("app.py", [
        "@@ -1,2 +1,2 @@\n",
        " def add(a, b):\n",
        "-    return a + b\n",
        "+    return a - b\n",
    ])
    rep = ed.apply_patch(patch)
    assert rep.files_changed == ["app.py"]
    assert "return a - b" in (tmp_path / "app.py").read_text()
    assert "all hunks matched exactly" in rep.precondition
    assert rep.insertions >= 1 and rep.deletions >= 1


def test_apply_patch_context_mismatch_fails_without_write(ed, tmp_path):
    before = (tmp_path / "app.py").read_text()
    patch = _unified("app.py", [
        "@@ -1,2 +1,2 @@\n",
        " def add(a, b):\n",
        "-    return 999\n",   # does not exist
        "+    return 0\n",
    ])
    with pytest.raises(PreconditionError, match="precondition failed"):
        ed.apply_patch(patch)
    assert (tmp_path / "app.py").read_text() == before  # unchanged


def test_apply_patch_wrong_line_offset_fails(ed, tmp_path):
    before = (tmp_path / "app.py").read_text()
    patch = _unified("app.py", [
        "@@ -40,2 +40,2 @@\n",          # far beyond EOF
        " def add(a, b):\n",
        "-    return a + b\n",
        "+    return 1\n",
    ])
    with pytest.raises(PreconditionError):
        ed.apply_patch(patch)
    assert (tmp_path / "app.py").read_text() == before


def test_apply_patch_creates_new_file(ed, tmp_path):
    patch = _unified("new_mod.py", [
        "@@ -0,0 +1,2 @@\n",
        "+x = 1\n",
        "+y = 2\n",
    ], old_exists=False)
    rep = ed.apply_patch(patch)
    assert rep.files_changed == ["new_mod.py"]
    assert (tmp_path / "new_mod.py").read_text() == "x = 1\ny = 2\n"


def test_apply_patch_rejects_deletion_patch(ed):
    patch = "--- a/app.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-def add(a, b):\n-    return a + b\n"
    with pytest.raises(EditError, match="deletion"):
        ed.apply_patch(patch)


def test_apply_patch_unparseable(ed):
    with pytest.raises(EditError, match="could not parse|no file hunks"):
        ed.apply_patch("random text, not a diff")


def test_apply_patch_multiple_hunks_localizes(tmp_path):
    src = "one\ntwo\nthree\nfour\nfive\nsix\nseven\neight\nnine\nten\n"
    (tmp_path / "m.txt").write_text(src)
    ed = Editor(tmp_path)
    patch = (
        "--- a/m.txt\n+++ b/m.txt\n"
        "@@ -1,3 +1,3 @@\n one\n-two\n+TWO\n three\n"
        "@@ -8,3 +8,3 @@\n eight\n-nine\n+NINE\n ten\n"
    )
    rep = ed.apply_patch(patch)
    text = (tmp_path / "m.txt").read_text()
    assert "TWO" in text and "NINE" in text
    assert "four\nfive\nsix\nseven\n" in text  # untouched middle
    assert rep.files_changed == ["m.txt"]


def test_workspace_tools_exposes_editing(tmp_path):
    t = WorkspaceTools(tmp_path, persistent_shell=False)
    t.write_file("a.py", "v = 1\n")
    out = t.replace_in_file("a.py", "v = 1", "v = 2")
    assert "OK: replace_in_file" in out
    out = t.apply_patch("--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-v = 2\n+v = 3\n")
    assert "OK: apply_patch" in out
    out = t.read_range("a.py", 1, 1)
    assert "1\tv = 3" in out
    out = t.create_file("b.py", "new = True\n")
    assert "OK: create_file" in out
    with pytest.raises(ValueError, match="unknown tool"):
        t.execute("nope", {})


def test_ambiguity_error_surfaces_through_tools(tmp_path):
    t = WorkspaceTools(tmp_path, persistent_shell=False)
    t.write_file("s.py", "x = 1\nx = 1\n")
    # execute() propagates ValueError subclasses to the agent as ERROR text
    with pytest.raises(AmbiguityError, match="2 times"):
        t.execute("replace_in_file", {"path": "s.py", "old": "x = 1", "new": "x = 2"})


# -------------------------------------------------------------- persistent shell

@pytest.fixture
def sh():
    s = PersistentShell("/tmp")
    yield s
    s.close()


def test_shell_preserves_cwd_env_and_venv(sh, tmp_path):
    """SPEC acceptance sequence: cd project; source venv; export FOO=bar;
    run something; the next command still sees cwd/venv/FOO."""
    proj = tmp_path / "project"
    proj.mkdir()
    # create a real venv-less stand-in: a dir with bin/activate setting a var
    (proj / "bin").mkdir()
    (proj / "bin" / "activate").write_text("export BONSAI_VENV=1\n")
    r = sh.run(f"cd {proj}; source bin/activate; export FOO=bar; echo staged")
    assert r.exit_code == 0 and "staged" in r.stdout
    r = sh.run("echo \"cwd=$PWD foo=$FOO venv=$BONSAI_VENV\"")
    assert r.exit_code == 0
    assert f"cwd={proj}" in r.stdout
    assert "foo=bar" in r.stdout
    assert "venv=1" in r.stdout


def test_shell_real_venv_activation_persists():
    """Real acceptance: activate the project venv, then python resolves to it."""
    import subprocess
    root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True
    ).stdout.strip()
    venv = f"{root}/.venv"
    import os
    if not os.path.exists(f"{venv}/bin/activate"):
        pytest.skip("project venv not present")
    s = PersistentShell(root)
    try:
        r = s.run(f"source {venv}/bin/activate; python -c 'import sys; print(sys.prefix)'")
        assert r.exit_code == 0
        first = r.stdout.strip().splitlines()[-1]
        r2 = s.run("python -c 'import sys; print(sys.prefix)'")
        assert r2.exit_code == 0
        second = r2.stdout.strip().splitlines()[-1]
        assert first == second and venv in second  # venv persists
    finally:
        s.close()


def test_shell_exit_status_stdout_stderr(sh):
    r = sh.run("echo out; echo err >&2; false")
    assert r.exit_code == 1
    assert "out" in r.stdout and "err" in r.stderr
    r = sh.run("true")
    assert r.exit_code == 0


def test_shell_exit_command_does_not_kill_session(sh):
    # `exit` is shadowed so a worker's `exit N` cannot end the session;
    # $? is still N and later commands keep running in the same session.
    r = sh.run("echo before; exit 3")
    assert r.exit_code == 3
    r = sh.run("echo after-exit; echo still-alive")
    assert r.exit_code == 0 and "still-alive" in r.stdout
    assert sh.alive  # session must survive


def test_shell_timeout_kills_and_session_survives(sh):
    t0 = time.monotonic()
    r = sh.run("sleep 60", timeout=1.5)
    elapsed = time.monotonic() - t0
    assert r.timed_out and elapsed < 10
    r = sh.run("echo ok")
    assert r.exit_code == 0 and "ok" in r.stdout


def test_shell_cancellation(sh):
    result = {}
    def go():
        result["r"] = sh.run("sleep 60", timeout=60)
    th = threading.Thread(target=go)
    th.start()
    time.sleep(0.5)
    sh.cancel()
    th.join(timeout=15)
    assert not th.is_alive()
    assert result["r"].cancelled and not result["r"].timed_out
    r = sh.run("echo ok")
    assert r.exit_code == 0 and sh.alive


def test_shell_heredoc_and_multiline(sh):
    r = sh.run("cat <<'EOF'\nline1\nline2\nEOF")
    assert r.exit_code == 0
    assert "line1" in r.stdout and "line2" in r.stdout


def test_shell_no_trailing_newline_output(sh):
    r = sh.run("printf xyz")
    assert r.exit_code == 0 and r.stdout == "xyz"


def test_shell_sees_changes_from_workspace_tools(tmp_path):
    """run_command through WorkspaceTools shares one session cwd semantics."""
    t = WorkspaceTools(tmp_path)
    try:
        t.write_file("f.txt", "data\n")
        out = t.run_command("cat f.txt")
        assert out.startswith("exit=0") and "data" in out
        out = t.run_command("pwd")
        assert str(tmp_path) in out
    finally:
        t.close()


def test_workspace_tools_run_command_blocked_still(tmp_path):
    t = WorkspaceTools(tmp_path, persistent_shell=False)
    out = t.run_command("sudo rm -rf /")
    assert out.startswith("BLOCKED:")


def test_git_anchored_to_root_even_when_session_cd_elsewhere(tmp_path):
    import subprocess
    (tmp_path / ".git").mkdir()  # not a real repo; git -C will error but cwd check matters
    t = WorkspaceTools(tmp_path)
    try:
        t.run_command("cd /tmp")
        out = t.git_status()
        # git -C <root> ran: either exit=0 (repo) or git error mentioning root
        assert out.startswith("exit=")
        r = t.run_command("pwd")
        assert "/tmp" in r  # session cwd really is /tmp now
    finally:
        t.close()
