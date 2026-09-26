"""Paperclip control-plane helpers (M3).

Paperclip stays a control plane — never the coding shell/file harness.
This module builds hermes_gateway employee payloads matching the installed
Paperclip OpenAPI schema (POST /api/companies/{companyId}/agents) and the
hermes_gateway adapter config schema (GET /api/adapters/hermes_gateway/config-schema),
plus the SPEC task contract and service-health checks.

Secrets (HERMES_KEY / apiKey) are passed in by the caller and never logged.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field

ADAPTER_TYPE = "hermes_gateway"
DEFAULT_TIMEOUT_SEC = 600
DEFAULT_SESSION_STRATEGY = "issue"

VALID_ROLES = {
    "ceo", "cto", "cmo", "cfo", "security", "engineer", "designer",
    "pm", "qa", "devops", "researcher", "general",
}
VALID_SESSION_STRATEGIES = {"issue", "agent", "run", "none"}


class PaperclipConfigError(ValueError):
    """Raised when an employee/adapter payload fails local validation."""


def build_gateway_adapter(
    api_base_url: str,
    api_key: str,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    session_key_strategy: str = DEFAULT_SESSION_STRATEGY,
    event_reconnect_ms: int = 2000,
    instructions: str = "",
) -> dict:
    """Build a hermes_gateway adapterConfig dict.

    Required by the adapter schema: apiBaseUrl + apiKey (the Hermes
    API_SERVER_KEY, sent as Authorization: Bearer). apiKey must be a real
    secret (>=16 chars); the gateway refuses placeholders.
    """
    if not api_base_url or not api_base_url.startswith(("http://", "https://")):
        raise PaperclipConfigError("apiBaseUrl must be an http(s) URL")
    if not api_key or len(api_key) < 16:
        raise PaperclipConfigError("apiKey must be a strong secret (>=16 chars)")
    if session_key_strategy not in VALID_SESSION_STRATEGIES:
        raise PaperclipConfigError(
            f"sessionKeyStrategy must be one of {sorted(VALID_SESSION_STRATEGIES)}"
        )
    if timeout_sec <= 0:
        raise PaperclipConfigError("timeoutSec must be positive")
    cfg: dict = {
        "apiBaseUrl": api_base_url.rstrip("/"),
        "apiKey": api_key,
        "timeoutSec": timeout_sec,
        "sessionKeyStrategy": session_key_strategy,
        "eventReconnectMs": event_reconnect_ms,
    }
    if instructions:
        cfg["instructions"] = instructions
    return cfg


def redact_adapter(cfg: dict) -> dict:
    """Return a copy of an adapterConfig safe for logs (apiKey redacted)."""
    out = dict(cfg)
    if "apiKey" in out:
        out["apiKey"] = "***REDACTED***"
    return out


def build_employee_payload(
    name: str,
    role: str,
    adapter_config: dict,
    title: str = "",
    capabilities: str = "",
    instructions_md: str = "",
    entry_file: str = "AGENTS.md",
) -> dict:
    """Build a CreateAgent payload for POST /api/companies/{companyId}/agents."""
    if not name:
        raise PaperclipConfigError("employee name is required")
    if role not in VALID_ROLES:
        raise PaperclipConfigError(f"role must be one of {sorted(VALID_ROLES)}")
    for k in ("apiBaseUrl", "apiKey"):
        if k not in adapter_config:
            raise PaperclipConfigError(f"adapterConfig missing required key: {k}")
    payload: dict = {
        "name": name,
        "role": role,
        "adapterType": ADAPTER_TYPE,
        "adapterConfig": adapter_config,
    }
    if title:
        payload["title"] = title
    if capabilities:
        payload["capabilities"] = capabilities
    if instructions_md:
        payload["instructionsBundle"] = {
            "entryFile": entry_file,
            "files": {entry_file: instructions_md},
        }
    return payload


CODER_INSTRUCTIONS = """# Bonsai Coder
You are a local coding employee. Work only inside the provided workspace.
Make small localized patches (replace_in_file / apply_patch semantics).
Run the relevant focused tests, then report: files changed, tests run with
results, and any blockers. Never rewrite a large file for a localized change.
"""

RESEARCHER_INSTRUCTIONS = """# Bonsai Researcher
You research code and questions. Cite file paths and evidence for every claim.
Return structured findings: summary, evidence (file:line), open questions.
"""

QA_INSTRUCTIONS = """# Bonsai QA
You verify work. Run the acceptance/test commands from the task contract.
Report PASS or FAIL with exact evidence (command, exit code, output excerpt).
"""


def employee_templates(api_base_url: str, api_key: str) -> list[dict]:
    """Reusable coding/research/QA-verifier employee payloads (SPEC M3)."""
    return [
        build_employee_payload(
            name="Bonsai Coder",
            role="engineer",
            title="Local coding employee",
            capabilities=(
                "Implements small localized code changes in a dedicated "
                "worktree. Runs tests. Returns summary with files changed "
                "and test results."
            ),
            adapter_config=build_gateway_adapter(api_base_url, api_key),
            instructions_md=CODER_INSTRUCTIONS,
        ),
        build_employee_payload(
            name="Bonsai Researcher",
            role="researcher",
            title="Local research employee",
            capabilities=(
                "Researches codebases and questions. Returns evidence-backed "
                "findings with file paths and citations."
            ),
            adapter_config=build_gateway_adapter(api_base_url, api_key),
            instructions_md=RESEARCHER_INSTRUCTIONS,
        ),
        build_employee_payload(
            name="Bonsai QA",
            role="qa",
            title="Local QA verifier employee",
            capabilities=(
                "Verifies patches by running tests and checking acceptance "
                "criteria. Returns PASS/FAIL with evidence."
            ),
            adapter_config=build_gateway_adapter(api_base_url, api_key),
            instructions_md=QA_INSTRUCTIONS,
        ),
    ]


@dataclass
class TaskContract:
    """SPEC M3 task contract: id, objective, acceptance, workspace/repo,
    permissions, verification/test command, result summary, final status."""

    objective: str
    acceptance: str
    workspace: str
    permissions: str = "read-write inside workspace only"
    verification: str = ""
    result_summary: str = ""
    status: str = "todo"
    task_id: str = ""

    def validate(self) -> None:
        missing = [
            f for f in ("objective", "acceptance", "workspace")
            if not getattr(self, f)
        ]
        if missing:
            raise PaperclipConfigError(
                f"task contract missing required fields: {missing}"
            )

    def to_issue(self, title: str) -> dict:
        """Render as Paperclip issue create/update args (CLI-friendly)."""
        self.validate()
        description = (
            f"TASK CONTRACT\nobjective: {self.objective}\n"
            f"acceptance: {self.acceptance}\nworkspace: {self.workspace}\n"
            f"permissions: {self.permissions}\nverification: {self.verification}\n"
            f"result: {self.result_summary}\nstatus: {self.status}"
        )
        return {"title": title, "description": description}


@dataclass
class HealthResult:
    name: str
    ok: bool
    detail: str = ""
    latency_ms: int = 0


def check_http_json(url: str, timeout: int = 5,
                    headers: dict | None = None) -> HealthResult:
    """GET a URL, expect JSON. Never sends or logs secrets."""
    import time
    start = time.monotonic()
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(4096).decode("utf-8", "replace")
            json.loads(body)  # must be JSON
            ms = int((time.monotonic() - start) * 1000)
            return HealthResult(name=url, ok=True,
                                detail=f"http={resp.status}", latency_ms=ms)
    except Exception as e:  # noqa: BLE001 — health detail string
        ms = int((time.monotonic() - start) * 1000)
        return HealthResult(name=url, ok=False, detail=str(e)[:200],
                            latency_ms=ms)


def paperclip_health(base_url: str = "http://127.0.0.1:3100") -> HealthResult:
    """Paperclip service health via GET /api/health."""
    return check_http_json(base_url.rstrip("/") + "/api/health")


def hermes_gateway_health(base_url: str = "http://127.0.0.1:8642") -> HealthResult:
    """Hermes gateway health via GET /health (no key required)."""
    return check_http_json(base_url.rstrip("/") + "/health")
