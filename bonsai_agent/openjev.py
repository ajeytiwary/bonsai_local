"""M7 OpenJEV — Phase-2 typed decision layer (SPEC).

Bonsai keeps open-ended reasoning/code/research/explanations. OpenJEV only
handles closed-set decisions. Low-confidence/high-risk results escalate to
Bonsai/human.

API (stable across profiles — switching generic <-> compliance never
changes the orchestration call shape):
    provider = LocalDecisionProvider(profile="generic")  # or "compliance"
    d = provider.choose(question, choices, evidence)
    # d -> Decision(choice, probabilities, confidence, escalate, reason)

Initial decisions: task_route, tool_route, risk_gate, test_scope,
completion_gate, verify_result. Unknown questions get a safe uniform
fallback (escalate=True) so new callers fail closed, not open.
"""
from __future__ import annotations

from dataclasses import dataclass, field

QUESTIONS = ("task_route", "tool_route", "risk_gate", "test_scope",
             "completion_gate", "verify_result")

PROFILES = ("generic", "compliance")

# Escalation thresholds per profile: below this confidence -> escalate.
THRESHOLDS = {"generic": 0.55, "compliance": 0.70}

# Commands that are always high-risk (block or escalate even in generic).
_ALWAYS_RISKY = ("sudo ", "rm -rf /", "mkfs", "shutdown", "reboot",
                 "--force", "reset --hard", "clean -f")


@dataclass
class Decision:
    question: str
    choice: str
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0
    escalate: bool = True
    reason: str = ""

    def to_dict(self) -> dict:
        return {"question": self.question, "choice": self.choice,
                "probabilities": dict(self.probabilities),
                "confidence": round(self.confidence, 3),
                "escalate": self.escalate, "reason": self.reason}


class DecisionProvider:
    """Base orchestration API. Subclasses implement `choose`."""

    def __init__(self, profile: str = "generic"):
        if profile not in PROFILES:
            raise ValueError(f"unknown OpenJEV profile: {profile}")
        self.profile = profile

    @property
    def threshold(self) -> float:
        return THRESHOLDS[self.profile]

    def choose(self, question: str, choices: list[str],
               evidence: dict | None = None) -> Decision:
        raise NotImplementedError


def _normalize(scores: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, v) for v in scores.values()) or 1.0
    probs = {k: round(max(0.0, v) / total, 4) for k, v in scores.items()}
    # Renormalize after rounding so probabilities sum to exactly 1.0.
    drift = round(1.0 - sum(probs.values()), 4)
    if drift and probs:
        top = max(probs, key=lambda k: probs[k])
        probs[top] = round(probs[top] + drift, 4)
    return probs


def _decide(question: str, choices: list[str], scores: dict[str, float],
            reason: str, threshold: float) -> Decision:
    probs = _normalize({c: scores.get(c, 0.0) for c in choices})
    best = max(choices, key=lambda c: probs[c])
    conf = probs[best]
    esc = conf < threshold or best in ("escalate", "BLOCKED")
    return Decision(question=question, choice=best, probabilities=probs,
                    confidence=conf, escalate=esc, reason=reason)


class LocalDecisionProvider(DecisionProvider):
    """Local heuristic adapter — no server, stdlib only, deterministic.

    Compliance profile uses the same `choose()` API with stricter
    thresholds + conservative overrides (risk_gate escalates on any
    privileged/mutating command, test_scope forces both, completion
    requires clean protected tests).
    """

    def choose(self, question: str, choices: list[str],
               evidence: dict | None = None) -> Decision:
        ev = dict(evidence or {})
        if question not in QUESTIONS:
            probs = _normalize({c: 1.0 for c in choices}) if choices else {}
            return Decision(question=question,
                            choice=choices[0] if choices else "",
                            probabilities=probs, confidence=0.0,
                            escalate=True,
                            reason="unknown question: fail closed")
        fn = {"task_route": self._task_route, "tool_route": self._tool_route,
              "risk_gate": self._risk_gate, "test_scope": self._test_scope,
              "completion_gate": self._completion_gate,
              "verify_result": self._verify_result}[question]
        return fn(list(choices), ev)

    # ------------------------------------------------------------- decisions
    def _task_route(self, choices: list[str], ev: dict) -> Decision:
        text = f"{ev.get('title', '')} {ev.get('description', '')}".lower()
        test_hit = any(k in text for k in ("test", "pytest", "regression",
                                           "acceptance", "spec"))
        research_hit = any(k in text for k in ("research", "survey",
                                               "compare", "investigate",
                                               "literature"))
        scores = {c: 0.0 for c in choices}
        no_signal = not (test_hit or research_hit)
        for c in choices:
            cl = c.lower()
            if no_signal and cl in ("implementation", "test", "research"):
                scores[c] = 1.0  # ambiguous: uniform → low confidence → escalate
            elif cl == "test" and test_hit:
                scores[c] = 0.9
            elif cl == "research" and research_hit:
                scores[c] = 0.9
            elif cl == "implementation" and not (test_hit or research_hit):
                scores[c] = 0.9
            elif cl in ("implementation", "test", "research"):
                scores[c] = 0.1
            else:
                scores[c] = 0.05
        if self.profile == "compliance" and research_hit and "research" in scores:
            scores["research"] = 0.95  # route research away from code tools
        return _decide("task_route", choices, scores,
                       "keyword route over title+description", self.threshold)

    def _tool_route(self, choices: list[str], ev: dict) -> Decision:
        step = int(ev.get("step", 0))
        made_edit = bool(ev.get("made_edit", False))
        scores = {c: 0.0 for c in choices}
        for c in choices:
            cl = c.lower()
            if not made_edit and cl in ("read", "read_file", "read_range",
                                        "search", "search_files", "list_files"):
                scores[c] = 0.8 if step < 8 else 0.3
            elif not made_edit and cl in ("edit", "replace_in_file",
                                          "apply_patch", "write_file",
                                          "create_file"):
                scores[c] = 0.7 if step >= 4 else 0.2
            elif made_edit and cl in ("test", "run_tests", "run_command"):
                scores[c] = 0.9
            elif cl in ("read", "search", "edit", "test"):
                scores[c] = 0.2
            else:
                scores[c] = 0.1
        return _decide("tool_route", choices, scores,
                       f"step={step} made_edit={made_edit}", self.threshold)

    def _risk_gate(self, choices: list[str], ev: dict) -> Decision:
        cmd = str(ev.get("command", "") or "")
        cl = cmd.lower()
        risky = any(k in cl for k in _ALWAYS_RISKY)
        scores = {c: 0.0 for c in choices}
        for c in choices:
            lc = c.lower()
            if risky and lc == "block":
                scores[c] = 0.95
            elif risky and lc == "escalate":
                scores[c] = 0.7
            elif not risky and lc == "allow":
                scores[c] = 0.9
            elif lc in ("allow", "block", "escalate"):
                scores[c] = 0.1
            else:
                scores[c] = 0.05
        d = _decide("risk_gate", choices, scores,
                    "deny-pattern match" if risky else "no deny-pattern match",
                    self.threshold)
        if self.profile == "compliance" and not risky:
            # Compliance escalates mutating commands even when allowed.
            mutating = any(k in cl for k in ("rm ", "git push", "git commit",
                                             "chmod", "chown", "curl", "wget"))
            if mutating and d.choice == "allow" and "escalate" in choices:
                probs = _normalize({**d.probabilities, "escalate": 0.65,
                                    "allow": 0.35})
                conf = probs["escalate"]
                return Decision(question="risk_gate", choice="escalate",
                                probabilities=probs, confidence=conf,
                                escalate=True,
                                reason="compliance: mutating command escalated")
        return d

    def _test_scope(self, choices: list[str], ev: dict) -> Decision:
        if self.profile == "compliance" and "both" in choices:
            probs = _normalize({c: (0.9 if c == "both" else 0.05)
                                for c in choices})
            return Decision(question="test_scope", choice="both",
                            probabilities=probs, confidence=0.9,
                            escalate=False,
                            reason="compliance: always focused+full")
        n = int(ev.get("changed_files", ev.get("changed", 1) or 1))
        risk = str(ev.get("risk", "low")).lower()
        scores = {c: 0.0 for c in choices}
        for c in choices:
            lc = c.lower()
            if lc == "focused" and n <= 2 and risk == "low":
                scores[c] = 0.85
            elif lc == "full" and (n > 2 or risk != "low"):
                scores[c] = 0.85
            elif lc == "both" and (n > 4 or risk == "high"):
                scores[c] = 0.9
            elif lc in ("focused", "full", "both"):
                scores[c] = 0.15
            else:
                scores[c] = 0.05
        return _decide("test_scope", choices, scores,
                       f"changed={n} risk={risk}", self.threshold)

    def _completion_gate(self, choices: list[str], ev: dict) -> Decision:
        passed = bool(ev.get("tests_pass", False))
        protected = bool(ev.get("protected_ok", True))
        remaining = int(ev.get("remaining", 0))
        scores = {c: 0.0 for c in choices}
        for c in choices:
            lc = c.lower()
            if lc == "complete" and passed and protected and remaining == 0:
                scores[c] = 0.92
            elif lc == "continue" and (not passed or remaining > 0):
                scores[c] = 0.88
            elif lc == "escalate" and (not protected or ev.get("blocked")):
                scores[c] = 0.9
            elif lc in ("complete", "continue", "escalate"):
                scores[c] = 0.1
            else:
                scores[c] = 0.05
        d = _decide("completion_gate", choices, scores,
                    f"tests_pass={passed} protected_ok={protected} "
                    f"remaining={remaining}", self.threshold)
        if self.profile == "compliance" and d.choice == "complete":
            if not protected and "escalate" in choices:
                return Decision(question="completion_gate",
                                choice="escalate",
                                probabilities=_normalize(
                                    {c: (0.9 if c == "escalate" else 0.05)
                                     for c in choices}),
                                confidence=0.9, escalate=True,
                                reason="compliance: protected tests not clean")
        return d

    def _verify_result(self, choices: list[str], ev: dict) -> Decision:
        out = str(ev.get("test_output", "") or "")
        err = str(ev.get("error", "") or "")
        passed = bool(ev.get("tests_pass", out.startswith("exit=0")))
        blocked = bool(err) or "BLOCKED" in out or "Traceback" in out and not passed
        scores = {c: 0.0 for c in choices}
        for c in choices:
            if c == "PASS" and passed and not blocked:
                scores[c] = 0.93
            elif c == "FAIL" and not passed and not blocked:
                scores[c] = 0.9
            elif c == "BLOCKED" and blocked:
                scores[c] = 0.85
            elif c in ("PASS", "FAIL", "BLOCKED"):
                scores[c] = 0.08
            else:
                scores[c] = 0.05
        return _decide("verify_result", choices, scores,
                       f"tests_pass={passed} blocked={blocked}",
                       self.threshold)
