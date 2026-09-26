"""Persistent shell session.

Acceptance contract (SPEC "Persistent shell — mandatory"):
- Session preserves cwd, activated venv and exported environment variables
  across commands (cd project; source .venv/bin/activate; export FOO=bar; ...;
  every subsequent command sees cwd/venv/FOO).
- Each command exposes timeout, stdout, stderr, exit status and cancellation.

Implementation: one long-lived ``bash --noprofile --norc`` process with
``set -m`` (job control) so every command runs in its own process group.
Completion is detected with a per-command random sentinel printed by the
shell itself, which captures ``$?`` and ``$PWD``. Timeout/cancel sends
SIGTERM to the *job's* process group (never SIGINT: bash exits when its
foreground job dies of SIGINT — the WCE rule). Raw-fd select loop, no
threads, so output without trailing newlines cannot deadlock capture.
"""
from __future__ import annotations

import os
import re
import selectors
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

_SENTINEL_RE_TMPL = r"<<<BONSAI_DONE:{token}:rc=(-?\d+):cwd=(.*?)>>>"


@dataclass
class ShellResult:
    command: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    timed_out: bool = False
    cancelled: bool = False
    duration: float = 0.0
    cwd: str = ""
    error: str = ""

    def format(self) -> str:
        """Legacy-compatible report used by WorkspaceTools.run_command."""
        head = f"exit={self.exit_code if self.exit_code is not None else 'killed'}"
        if self.timed_out:
            head += " TIMED_OUT"
        if self.cancelled:
            head += " CANCELLED"
        return f"{head}\nSTDOUT:\n{self.stdout}\nSTDERR:\n{self.stderr}"


class ShellClosed(RuntimeError):
    pass


class PersistentShell:
    """A cwd/env-preserving bash session rooted at ``root``."""

    def __init__(self, root: str | Path, env: dict | None = None,
                 startup_commands: list[str] | None = None,
                 max_output_chars: int = 200_000):
        self.root = str(Path(root).resolve())
        self.max_output_chars = max_output_chars
        merged = {**os.environ, "PYTHONUNBUFFERED": "1"}
        if env:
            merged.update(env)
        self._proc = subprocess.Popen(
            ["bash", "--noprofile", "--norc"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=self.root, env=merged, start_new_session=True, bufsize=0,
        )
        # Job control: each job gets its own process group -> safe to killpg
        # without touching bash itself. Verified empirically on this machine.
        self._raw_write("set -m\n")
        # Shadow `exit`: a worker command containing `exit 3` must not end the
        # session (subshell exits like `bash -c 'exit 3'` still work normally).
        self._raw_write("exit() { return \"${1:-0}\"; }\n")
        # Discard the (empty) acknowledgment window; no prompt in non-interactive.
        self._pending_stdout = bytearray()
        self._pending_stderr = bytearray()
        self._lock = threading.RLock()  # one command at a time (run() nests cwd())
        self._cancel_requested = False
        for cmd in startup_commands or []:
            res = self.run(cmd, timeout=60)
            if res.exit_code not in (0, None):
                raise RuntimeError(f"startup command failed ({res.exit_code}): {cmd}\n{res.stderr}")
        self._cancel_requested = False

    # ------------------------------------------------------------------ helpers
    def _raw_write(self, data: str) -> None:
        if self._proc.poll() is not None:
            raise ShellClosed(f"shell exited with code {self._proc.returncode}")
        try:
            self._proc.stdin.write(data.encode())
            self._proc.stdin.flush()
        except BrokenPipeError as exc:
            raise ShellClosed(f"shell stdin closed (exit {self._proc.returncode})") from exc

    @staticmethod
    def _children_of(pid: int) -> list[int]:
        try:
            with open(f"/proc/{pid}/task/{pid}/children") as fh:
                return [int(x) for x in fh.read().split()]
        except OSError:
            return []

    def _kill_job(self, sig: int = signal.SIGTERM) -> list[int]:
        """Signal the process groups of all direct children (the jobs)."""
        killed = []
        for child in self._children_of(self._proc.pid):
            try:
                os.killpg(os.getpgid(child), sig)
                killed.append(child)
            except (ProcessLookupError, PermissionError, ProcessLookupError):
                try:
                    os.kill(child, sig)
                    killed.append(child)
                except (ProcessLookupError, PermissionError):
                    pass
        return killed

    def _drain(self, timeout: float) -> tuple[bytes, bytes]:
        """Read whatever has arrived on stdout/stderr.

        ``timeout=0`` does one non-blocking pass (data written before the
        sentinel is already in the pipe); otherwise blocks up to ``timeout``.
        """
        sel = selectors.DefaultSelector()
        sel.register(self._proc.stdout, selectors.EVENT_READ, "out")
        sel.register(self._proc.stderr, selectors.EVENT_READ, "err")
        out = bytearray(); err = bytearray()
        deadline = time.monotonic() + max(0.0, timeout)
        try:
            first = True
            while True:
                if first:
                    wait = max(0.0, timeout)
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    wait = min(remaining, 0.2)
                events = sel.select(timeout=wait)
                first = False
                for key, _ in events:
                    try:
                        chunk = os.read(key.fileobj.fileno(), 65536)
                    except OSError:
                        chunk = b""
                    if not chunk:
                        continue
                    (out if key.data == "out" else err).extend(chunk)
                if timeout == 0:
                    break
        finally:
            sel.close()
        return bytes(out), bytes(err)

    def _drain_until_sentinel(self, token: str, deadline: float,
                              cancel_check=None
                              ) -> tuple[bool, bytes, bytes, bool]:
        """select() loop until the sentinel appears on stdout or deadline.

        Returns (found, stdout, stderr, terminated) where ``terminated`` is
        True when the job was killed by SIGTERM (timeout or cancel).
        """
        sel = selectors.DefaultSelector()
        sel.register(self._proc.stdout, selectors.EVENT_READ, "out")
        sel.register(self._proc.stderr, selectors.EVENT_READ, "err")
        out = bytearray(); err = bytearray()
        pattern = re.compile(_SENTINEL_RE_TMPL.format(token=token).encode())
        found: re.Match | None = None
        terminated = False   # job has been SIGTERMed (timeout or cancel)
        killed_hard = False  # grace expired, SIGKILL sent
        try:
            while True:
                now = time.monotonic()
                if not terminated and cancel_check is not None and cancel_check():
                    self._kill_job(signal.SIGTERM)
                    terminated = True
                    deadline = now + 5.0  # grace for bash to print sentinel
                elif not terminated and now >= deadline:
                    self._kill_job(signal.SIGTERM)
                    terminated = True
                    deadline = now + 5.0
                elif terminated and not killed_hard and now >= deadline:
                    self._kill_job(signal.SIGKILL)
                    killed_hard = True
                    deadline = now + 2.0
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                for key, _ in sel.select(timeout=min(remaining, 0.15)):
                    try:
                        chunk = os.read(key.fileobj.fileno(), 65536)
                    except OSError:
                        chunk = b""
                    if not chunk:
                        if key.data == "out" and self._proc.poll() is not None:
                            # stdout closed and process gone
                            deadline = time.monotonic()
                        continue
                    if key.data == "out":
                        out.extend(chunk)
                        found = pattern.search(bytes(out))
                        if found:
                            # all stderr written by children precedes the sentinel
                            # (children exit before bash runs printf); drain it.
                            err.extend(self._drain(0.05)[1])
                            break
                    else:
                        err.extend(chunk)
                if found:
                    break
                if self._proc.poll() is not None and not found:
                    # bash died (e.g. command called exit); nothing more will come
                    break
        finally:
            sel.close()
        return found is not None, bytes(out), bytes(err), terminated

    # --------------------------------------------------------------------- API
    @property
    def alive(self) -> bool:
        return self._proc.poll() is None

    @property
    def pid(self) -> int:
        return self._proc.pid

    def cancel(self) -> None:
        """Request cancellation of the currently running command."""
        self._cancel_requested = True

    def run(self, command: str, timeout: float = 300.0,
            cancel_check=None) -> ShellResult:
        """Run ``command`` in the session; preserves cwd/env/venv state."""
        with self._lock:
            self._cancel_requested = False
            token = uuid.uuid4().hex
            result = ShellResult(command=command, cwd=self.cwd() if self.alive else self.root)
            if not self.alive:
                result.exit_code = None
                result.error = f"shell closed (exit {self._proc.returncode})"
                return result
            # Consume leftovers (e.g. job-control notices) before the command.
            pre_out, pre_err = self._drain(0.05)
            self._pending_stdout.extend(pre_out)
            self._pending_stderr.extend(pre_err)

            # Two-line form: the sentinel line reads $? of the command line.
            # No brace wrapping -> user commands containing } or heredocs work.
            sentinel_line = (
                f"printf '\\n<<<BONSAI_DONE:{token}:rc=%d:cwd=%s>>>\\n' \"$?\" \"$PWD\"\n"
            )
            started = time.monotonic()
            try:
                self._raw_write(command.rstrip("\n") + "\n" + sentinel_line)
            except ShellClosed as exc:
                result.exit_code = None
                result.error = str(exc)
                return result

            def _should_cancel():
                if self._cancel_requested:
                    return True
                return bool(cancel_check and cancel_check())

            ok, out, err, terminated = self._drain_until_sentinel(
                token, started + max(0.1, float(timeout)), _should_cancel)

            result.duration = time.monotonic() - started
            self._pending_stdout.extend(out)
            self._pending_stderr.extend(err)

            if ok:
                raw = bytes(self._pending_stdout)
                m = re.search(_SENTINEL_RE_TMPL.format(token=token).encode(), raw, re.S)
                if m:
                    before = raw[: m.start()]
                    after = raw[m.end():]
                    # The sentinel printf emits a leading "\n" separator; strip
                    # exactly one trailing newline that belongs to it.
                    if before.endswith(b"\n"):
                        before = before[:-1]
                    result.stdout = before.decode("utf-8", "replace")
                    result.exit_code = int(m.group(1))
                    result.cwd = m.group(2).decode("utf-8", "replace") or result.cwd
                    # stderr written by the job precedes the sentinel; the 50ms
                    # post-sentinel drain in _drain_until_sentinel collected it.
                    result.stderr = self._pending_stderr.decode("utf-8", "replace")
                    # trailing "\n" of the printf belongs to nothing yet
                    self._pending_stdout = bytearray(after.removeprefix(b"\n"))
                    self._pending_stderr.clear()
                    if terminated:
                        if self._cancel_requested:
                            result.cancelled = True
                        else:
                            result.timed_out = True
            else:
                # No sentinel: timed out hard, cancelled without reaping, or
                # the command consumed the sentinel line (interactive program).
                result.stdout = self._pending_stdout.decode("utf-8", "replace")
                result.stderr = self._pending_stderr.decode("utf-8", "replace")
                result.timed_out = not self._cancel_requested
                result.cancelled = self._cancel_requested
                # Resynchronize: kill any lingering job, then re-emit a sentinel
                # so the next command has a clean stream.
                self._kill_job(signal.SIGKILL)
                resync = uuid.uuid4().hex
                try:
                    self._raw_write(
                        f"printf '\\n<<<BONSAI_DONE:{resync}:rc=%d:cwd=%s>>>\\n' \"$?\" \"$PWD\"\n")
                    ok2, out2, err2, _ = self._drain_until_sentinel(resync, time.monotonic() + 3.0, None)
                    self._pending_stdout = bytearray()
                    self._pending_stderr = bytearray()
                    if ok2:
                        m2 = re.search(
                            _SENTINEL_RE_TMPL.format(token=resync).encode(), out2, re.S)
                        if m2:
                            result.exit_code = int(m2.group(1))
                            result.cwd = m2.group(2).decode("utf-8", "replace")
                except ShellClosed:
                    result.error = "shell closed during resync"
                result.stderr += ("\n[bonsai] command hit timeout/cancel; "
                                  "job process group terminated")
            for name in ("stdout", "stderr"):
                text = getattr(result, name)
                if len(text) > self.max_output_chars:
                    setattr(result, name,
                            "...[truncated]...\n" + text[-self.max_output_chars:])
            return result

    def cwd(self) -> str:
        with self._lock:
            return self._cwd_locked()

    def _cwd_locked(self) -> str:
        if not self.alive:
            return self.root
        token = uuid.uuid4().hex
        try:
            self._raw_write(
                f"printf '\\n<<<BONSAI_DONE:{token}:rc=0:cwd=%s>>>\\n' \"$PWD\"\n")
        except ShellClosed:
            return self.root
        ok, out, _, _ = self._drain_until_sentinel(token, time.monotonic() + 3.0, None)
        if ok:
            m = re.search(_SENTINEL_RE_TMPL.format(token=token).encode(), out, re.S)
            if m:
                # bytes before/after the probe sentinel are its own separators;
                # there is no command output to preserve.
                self._pending_stdout.extend(out[m.end():].removeprefix(b"\n"))
                return m.group(2).decode("utf-8", "replace") or self.root
        self._pending_stdout.extend(out)
        return self.root

    def close(self, timeout: float = 5.0) -> None:
        if self._proc.poll() is None:
            try:
                self._proc.stdin.write(b"unset -f exit; builtin exit\n")
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            try:
                self._proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._kill_job(signal.SIGKILL)
                self._proc.kill()
                self._proc.wait(timeout=3)

    def __enter__(self) -> "PersistentShell":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __del__(self):  # best effort; tests must not leak processes
        try:
            if self._proc.poll() is None:
                self._proc.kill()
        except Exception:
            pass
