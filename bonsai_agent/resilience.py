"""Inference resilience (SPEC M4).

- connect/read timeouts (tuple passthrough to requests)
- bounded exponential backoff + jitter for connection failures,
  timeouts, HTTP 429 and 5xx
- never retry deterministic malformed 4xx (400/401/403/404/422)
- request ids (unique per attempt, returned for tracing)
- sanitized error metadata + body excerpt (secrets stripped, truncated)
- optional health/restart hook called before giving up
"""
from __future__ import annotations

import random
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

# 4xx that are deterministic client errors — never retry these.
NO_RETRY_STATUS = {400, 401, 403, 404, 422}
# 429 + 5xx are transient — retry with backoff.
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}

_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)(['\"]?)[^\s'\",}]+"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9\-._~+/=]+"),
    re.compile(r"(?i)(secret\s*[:=]\s*)(['\"]?)[^\s'\",}]+"),
    re.compile(r"(?i)(token\s*[:=]\s*)(['\"]?)[^\s'\",}]+"),
]


def new_request_id() -> str:
    """Short unique id per inference attempt (safe to log)."""
    return uuid.uuid4().hex[:12]


def sanitize(text: str, limit: int = 500) -> str:
    """Strip secret-looking values and truncate to a body excerpt."""
    out = str(text or "")
    for pat in _SECRET_PATTERNS:
        out = pat.sub(lambda m: m.group(1) + "***REDACTED***", out)
    # raw hex secrets (>=16 hex chars) — likely keys
    out = re.sub(r"\b[0-9a-fA-F]{16,}\b", "***REDACTED***", out)
    return out[:limit]


@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    jitter: float = 0.25

    def __post_init__(self):
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if self.base_delay <= 0 or self.max_delay <= 0:
            raise ValueError("delays must be positive")


def backoff_delay(attempt: int, cfg: RetryConfig,
                  rng: Callable[[], float] | None = None) -> float:
    """Bounded exponential backoff with +/- jitter. attempt is 0-based."""
    raw = min(cfg.base_delay * (2 ** attempt), cfg.max_delay)
    j = (rng() * 2 - 1) if rng else (random.random() * 2 - 1)
    return max(0.0, min(cfg.max_delay, raw * (1 + cfg.jitter * j)))


def classify(status_code: int | None, exc_name: str = "") -> str:
    """Return 'retry' or 'noretry' for an HTTP status / exception name."""
    name = (exc_name or "").lower()
    if status_code is not None:
        if status_code in NO_RETRY_STATUS:
            return "noretry"
        if status_code in RETRY_STATUS:
            return "retry"
        if 500 <= status_code <= 599:
            return "retry"
        if 400 <= status_code <= 499:
            return "noretry"
    if any(k in name for k in ("connect", "timeout", "temporar", "reset",
                               "unavailable", "overload", "toomany")):
        return "retry"
    if "malformed" in name or "validation" in name or "badrequest" in name:
        return "noretry"
    return "retry"  # unknown transport errors default to retry (bounded)


@dataclass
class AttemptError(Exception):
    """Sanitized inference failure with tracing metadata (no secrets)."""

    kind: str  # 'retry_exhausted' | 'noretry'
    status_code: int | None = None
    request_id: str = ""
    attempts: int = 0
    excerpt: str = ""
    retries: int = 0

    def as_dict(self) -> dict:
        return {"kind": self.kind, "status_code": self.status_code,
                "request_id": self.request_id, "attempts": self.attempts,
                "excerpt": self.excerpt, "retries": self.retries}


def call_with_retry(fn: Callable[[int, str], Any],
                    cfg: RetryConfig | None = None,
                    on_retry: Callable[[dict], None] | None = None,
                    sleep: Callable[[float], None] | None = None,
                    health_hook: Callable[[], bool] | None = None) -> tuple[Any, dict]:
    """Call fn(attempt, request_id) with bounded retry.

    fn must raise an exception carrying optional ``status_code`` attr
    (e.g. requests.HTTPError) or an exc whose name classifies retryable.
    Returns (result, meta) where meta has request ids, attempts, retries.
    Raises AttemptError (sanitized) when retries are exhausted or the
    error is deterministic.
    """
    cfg = cfg or RetryConfig()
    sleep = sleep or time.sleep
    last_exc: BaseException | None = None
    last_status: int | None = None
    ids: list[str] = []
    for attempt in range(cfg.max_retries + 1):
        rid = new_request_id()
        ids.append(rid)
        try:
            result = fn(attempt, rid)
            return result, {"request_ids": ids, "attempts": attempt + 1,
                            "retries": attempt, "last_request_id": rid}
        except Exception as e:  # noqa: BLE001 — classified below
            last_exc = e
            last_status = getattr(getattr(e, "response", None), "status_code",
                                  getattr(e, "status_code", None))
            kind = classify(last_status, type(e).__name__ + " " + str(e)[:120])
            if kind == "noretry" or attempt >= cfg.max_retries:
                if health_hook is not None and kind != "noretry":
                    try:
                        health_hook()
                    except Exception:
                        pass
                raise AttemptError(
                    kind="noretry" if kind == "noretry" else "retry_exhausted",
                    status_code=last_status, request_id=rid,
                    attempts=attempt + 1, excerpt=sanitize(repr(e)),
                    retries=attempt) from e
            delay = backoff_delay(attempt, cfg)
            if on_retry:
                on_retry({"attempt": attempt, "request_id": rid,
                          "delay": delay, "status_code": last_status,
                          "error": sanitize(repr(e), 200)})
            sleep(delay)
    raise AttemptError(kind="retry_exhausted", status_code=last_status,
                       request_id=ids[-1] if ids else "",
                       attempts=len(ids), excerpt=sanitize(repr(last_exc)),
                       retries=len(ids) - 1) from last_exc
