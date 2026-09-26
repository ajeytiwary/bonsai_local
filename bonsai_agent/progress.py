"""Live progress + structured observability (SPEC M4 streaming/observability).

- Progress events: run/task id, model/harness, phase, request start/end,
  tool, command/edit target, test result, retry, context usage, elapsed,
  final status. Hidden reasoning never exposed.
- JSONL event log (timestamp/run/task/phase/duration/success/safe metadata)
  plus human-readable lines. Never logs secrets.
- summary JSON compatible with existing benchmark outputs.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .resilience import sanitize


class Progress:
    """Human-readable live progress sink (stdout by default)."""

    def __init__(self, sink=None, run_id=None, model="", harness="bonsai_local"):
        import sys
        self.sink = sink or sys.stdout
        self.run_id = run_id
        self.model = model
        self.harness = harness
        self._t0 = time.perf_counter()

    def _emit(self, text: str):
        elapsed = time.perf_counter() - self._t0
        self.sink.write(f"[{elapsed:7.1f}s run={self.run_id} {self.harness}/{self.model}] {text}\n")
        self.sink.flush()

    def phase(self, task_id, phase: str, detail: str = ""):
        self._emit(f"task={task_id} phase={phase} {sanitize(detail, 200)}".rstrip())

    def request(self, task_id, start: bool, request_id: str = ""):
        self._emit(f"task={task_id} request={'start' if start else 'end'} rid={request_id}")

    def tool(self, task_id, name: str, target: str = ""):
        self._emit(f"task={task_id} tool={name} {sanitize(target, 160)}".rstrip())

    def test_result(self, task_id, ok: bool, detail: str = ""):
        self._emit(f"task={task_id} test={'PASS' if ok else 'FAIL'} {sanitize(detail, 200)}".rstrip())

    def retry(self, task_id, attempt: int, delay: float, status=None):
        self._emit(f"task={task_id} retry attempt={attempt} delay={delay:.1f}s status={status}")

    def context(self, task_id, usage: str):
        self._emit(f"task={task_id} {usage}")

    def final(self, task_id, status: str):
        self._emit(f"task={task_id} final={status}")


class EventLog:
    """Structured JSONL events + summary JSON (benchmark-compatible)."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._t0 = time.time()

    def event(self, run_id, task_id, phase: str, duration: float = 0.0,
              success: bool | None = None, **meta):
        rec = {"ts": time.time(), "run": run_id, "task": task_id,
               "phase": phase, "duration_s": round(duration, 3),
               "success": success,
               "meta": {k: sanitize(str(v), 500) for k, v in meta.items()}}
        with self.path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        return rec

    def summary(self, results: list[dict]) -> dict:
        """Benchmark-compatible summary: clean/pass counts + totals."""
        clean = sum(1 for r in results if r.get("clean"))
        total = len(results)
        payload = {"results": results, "clean_count": clean, "total_tasks": total,
                   "pass_rate": clean / max(1, total),
                   "total_seconds": sum(r.get("seconds", 0) for r in results),
                   "total_tokens": sum(r.get("total_tokens", 0) for r in results)}
        return payload
