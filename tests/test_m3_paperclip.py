"""M3: Paperclip adapter generation, task contract, service health."""
import pytest

from bonsai_agent.paperclip import (
    ADAPTER_TYPE,
    PaperclipConfigError,
    TaskContract,
    build_employee_payload,
    build_gateway_adapter,
    employee_templates,
    hermes_gateway_health,
    paperclip_health,
    redact_adapter,
)


def test_gateway_adapter_required_fields():
    cfg = build_gateway_adapter("http://127.0.0.1:8642", "x" * 32)
    assert cfg["apiBaseUrl"] == "http://127.0.0.1:8642"
    assert cfg["apiKey"] == "x" * 32
    assert cfg["timeoutSec"] == 600
    assert cfg["sessionKeyStrategy"] == "issue"


def test_gateway_adapter_rejects_short_key():
    with pytest.raises(PaperclipConfigError):
        build_gateway_adapter("http://127.0.0.1:8642", "bonsai-local")


def test_gateway_adapter_rejects_bad_url():
    with pytest.raises(PaperclipConfigError):
        build_gateway_adapter("not-a-url", "x" * 32)


def test_gateway_adapter_rejects_bad_strategy():
    with pytest.raises(PaperclipConfigError):
        build_gateway_adapter("http://127.0.0.1:8642", "x" * 32,
                              session_key_strategy="global")


def test_redact_adapter_never_leaks_key():
    cfg = build_gateway_adapter("http://127.0.0.1:8642", "s" * 32)
    red = redact_adapter(cfg)
    assert red["apiKey"] == "***REDACTED***"
    assert "s" * 8 not in str(red)
    assert cfg["apiKey"] == "s" * 32  # original untouched


def test_employee_payload_schema():
    cfg = build_gateway_adapter("http://127.0.0.1:8642", "k" * 32)
    p = build_employee_payload("Bonsai Coder", "engineer", cfg,
                               title="t", capabilities="c",
                               instructions_md="# hi\n")
    assert p["adapterType"] == ADAPTER_TYPE == "hermes_gateway"
    assert p["adapterConfig"]["apiBaseUrl"] == "http://127.0.0.1:8642"
    assert p["instructionsBundle"]["entryFile"] == "AGENTS.md"
    assert p["instructionsBundle"]["files"]["AGENTS.md"] == "# hi\n"


def test_employee_payload_rejects_bad_role():
    cfg = build_gateway_adapter("http://127.0.0.1:8642", "k" * 32)
    with pytest.raises(PaperclipConfigError):
        build_employee_payload("X", "intern", cfg)


def test_employee_templates_coding_research_qa():
    ts = employee_templates("http://127.0.0.1:8642", "k" * 32)
    assert len(ts) == 3
    by_name = {t["name"]: t for t in ts}
    assert by_name["Bonsai Coder"]["role"] == "engineer"
    assert by_name["Bonsai Researcher"]["role"] == "researcher"
    assert by_name["Bonsai QA"]["role"] == "qa"
    for t in ts:
        assert t["adapterType"] == "hermes_gateway"
        assert "AGENTS.md" in t["instructionsBundle"]["files"]


def test_task_contract_requires_objective_acceptance_workspace():
    with pytest.raises(PaperclipConfigError):
        TaskContract(objective="", acceptance="a", workspace="w").validate()
    with pytest.raises(PaperclipConfigError):
        TaskContract(objective="o", acceptance="", workspace="w").validate()


def test_task_contract_to_issue_has_all_fields():
    tc = TaskContract(objective="fix B01", acceptance="tests pass",
                      workspace="/tmp/wt", verification="pytest -q",
                      result_summary="done", status="done")
    issue = tc.to_issue("Smoke task")
    assert issue["title"] == "Smoke task"
    for token in ("objective:", "acceptance:", "workspace:", "permissions:",
                  "verification:", "result:", "status:"):
        assert token in issue["description"]


def test_health_result_shape():
    r = paperclip_health("http://127.0.0.1:1")
    assert r.ok is False and r.detail
    r2 = hermes_gateway_health("http://127.0.0.1:1")
    assert r2.ok is False and r2.detail
