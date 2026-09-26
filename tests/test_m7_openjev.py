"""M7 OpenJEV tests: DecisionProvider API, six decisions, escalation,
compliance profile, agent wiring (fail-closed, no orchestration API change).
"""
import pytest

from bonsai_agent import openjev
from bonsai_agent.openjev import Decision, LocalDecisionProvider


@pytest.fixture(params=["generic", "compliance"])
def provider(request):
    return LocalDecisionProvider(profile=request.param)


def test_api_shape_all_questions(provider):
    cases = {
        "task_route": (["implementation", "test", "research"],
                       {"title": "fix bug", "description": "patch app.py"}),
        "tool_route": (["read", "edit", "test"], {"step": 0}),
        "risk_gate": (["allow", "escalate", "block"],
                      {"command": "pytest -q"}),
        "test_scope": (["focused", "full", "both"],
                       {"changed_files": 1, "risk": "low"}),
        "completion_gate": (["complete", "continue", "escalate"],
                            {"tests_pass": True, "protected_ok": True,
                             "remaining": 0}),
        "verify_result": (["PASS", "FAIL", "BLOCKED"],
                          {"tests_pass": True, "test_output": "exit=0"}),
    }
    for q, (choices, ev) in cases.items():
        d = provider.choose(q, choices, ev)
        assert isinstance(d, Decision)
        assert d.choice in choices
        assert abs(sum(d.probabilities.values()) - 1.0) < 1e-6
        assert set(d.probabilities) == set(choices)
        assert 0.0 <= d.confidence <= 1.0
        assert isinstance(d.escalate, bool) and d.reason


def test_task_route_keywords():
    p = LocalDecisionProvider()
    assert p.choose("task_route", ["implementation", "test", "research"],
                    {"title": "add regression test",
                     "description": "pytest coverage"}).choice == "test"
    assert p.choose("task_route", ["implementation", "test", "research"],
                    {"title": "survey papers",
                     "description": "research comparison"}).choice == "research"
    assert p.choose("task_route", ["implementation", "test", "research"],
                    {"title": "fix off-by-one",
                     "description": "patch ledger"}).choice == "implementation"


def test_tool_route_progression():
    p = LocalDecisionProvider()
    early = p.choose("tool_route", ["read", "edit", "test"], {"step": 0})
    assert early.choice == "read"
    late = p.choose("tool_route", ["read", "edit", "test"],
                    {"step": 9, "made_edit": True})
    assert late.choice == "test"


def test_risk_gate_blocks_dangerous():
    p = LocalDecisionProvider()
    d = p.choose("risk_gate", ["allow", "escalate", "block"],
                 {"command": "sudo rm -rf /tmp/x"})
    assert d.choice == "block" and d.escalate is True
    ok = p.choose("risk_gate", ["allow", "escalate", "block"],
                  {"command": "pytest -q"})
    assert ok.choice == "allow" and ok.escalate is False


def test_risk_gate_compliance_escalates_mutating():
    p = LocalDecisionProvider(profile="compliance")
    d = p.choose("risk_gate", ["allow", "escalate", "block"],
                 {"command": "git push origin main"})
    assert d.choice == "escalate" and d.escalate is True


def test_test_scope_compliance_forces_both():
    p = LocalDecisionProvider(profile="compliance")
    d = p.choose("test_scope", ["focused", "full", "both"],
                 {"changed_files": 1, "risk": "low"})
    assert d.choice == "both"
    g = LocalDecisionProvider(profile="generic")
    assert g.choose("test_scope", ["focused", "full", "both"],
                    {"changed_files": 1, "risk": "low"}).choice == "focused"
    assert g.choose("test_scope", ["focused", "full", "both"],
                    {"changed_files": 9, "risk": "high"}).choice == "both"


def test_completion_gate_honest_fail():
    p = LocalDecisionProvider()
    d = p.choose("completion_gate", ["complete", "continue", "escalate"],
                 {"tests_pass": False, "protected_ok": True, "remaining": 1})
    assert d.choice == "continue"
    bad = p.choose("completion_gate", ["complete", "continue", "escalate"],
                   {"tests_pass": True, "protected_ok": False,
                    "remaining": 0})
    assert bad.choice == "escalate"


def test_verify_result_mapping():
    p = LocalDecisionProvider()
    assert p.choose("verify_result", ["PASS", "FAIL", "BLOCKED"],
                    {"tests_pass": True,
                     "test_output": "exit=0"}).choice == "PASS"
    assert p.choose("verify_result", ["PASS", "FAIL", "BLOCKED"],
                    {"tests_pass": False,
                     "test_output": "exit=1 FAILED"}).choice == "FAIL"
    assert p.choose("verify_result", ["PASS", "FAIL", "BLOCKED"],
                    {"tests_pass": False,
                     "test_output": "exit=none",
                     "error": "timeout"}).choice == "BLOCKED"


def test_unknown_question_fails_closed():
    p = LocalDecisionProvider()
    d = p.choose("mystery_decision", ["a", "b"], {})
    assert d.escalate is True and d.confidence == 0.0


def test_low_confidence_escalates():
    p = LocalDecisionProvider(profile="generic")
    d = p.choose("task_route", ["implementation", "test", "research"],
                 {"title": "zzz", "description": "qqq"})
    assert d.escalate is True  # uniform-ish scores below threshold


def test_bad_profile_rejected():
    with pytest.raises(ValueError):
        LocalDecisionProvider(profile="strict")


def test_decision_to_dict_round_trip():
    p = LocalDecisionProvider()
    d = p.choose("risk_gate", ["allow", "escalate", "block"],
                 {"command": "pytest -q"})
    payload = d.to_dict()
    assert payload["choice"] == "allow"
    assert payload["question"] == "risk_gate"


def test_agent_wiring_optional_and_fail_closed(tmp_path):
    """Agent accepts decision_provider=None (default) or a provider;
    provider exceptions never break the run (fail closed to heuristics)."""
    import subprocess
    from bonsai_agent.agent import Agent

    class FakeLLM:
        model = "fake"
        def bind(self, fn): pass
        def tool_turn(self, *a, **k):
            return {"content": "done", "finish_reason": "stop",
                    "tool_calls": []}
        def json(self, *a, **k):
            raise RuntimeError("no model")

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "app.py").write_text("x = 1\n")
    (tmp_path / "TASK.md").write_text("# t\n")
    agent = Agent(tmp_path, FakeLLM(), tests="true", auto_commit=False)
    assert agent.decide is None  # default: heuristics unchanged

    agent2 = Agent(tmp_path, FakeLLM(), tests="true", auto_commit=False,
                   decision_provider=LocalDecisionProvider())
    assert agent2.decide is not None
    # provider consulted through the safe wrapper, never raises
    assert agent2._ask("task_route", ["implementation", "test"],
                       {"title": "fix", "description": ""}) in (
                           "implementation", "test")
    assert agent2._ask("bogus", ["a"], {}) == "a"  # fail closed to [0]

    class Boom:
        def choose(self, *a, **k):
            raise RuntimeError("provider down")
    agent3 = Agent(tmp_path, FakeLLM(), tests="true", auto_commit=False,
                   decision_provider=Boom())
    assert agent3._ask("task_route", ["implementation", "test"], {}) == \
        "implementation"  # heuristic fallback, run continues


def test_cli_openjev_flags():
    import subprocess as sp
    import sys
    r = sp.run([sys.executable, "-m", "bonsai_agent.cli", "--help"],
               text=True, capture_output=True)
    assert r.returncode == 0
    assert "--openjev" in r.stdout and "--openjev-profile" in r.stdout
