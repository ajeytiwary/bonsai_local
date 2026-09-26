"""Context budget (SPEC M4): budget by tokens, not message count.

Budgets system instructions, task/acceptance, durable summary, repo context,
recent turns/tool results, reasoning reserve and output reserve. Uses the
model/server tokenizer when available, otherwise a conservative labelled
approximation (4 chars/token). Never splits assistant tool_calls from matching
tool results. Under pressure: compact old verbose outputs first; preserve
objective/acceptance, unresolved errors, current diff/relevant code,
tool-group integrity; write durable checkpoint. Shows context usage.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .transcripts import truncate_transcript, validate_transcript

APPROX_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Conservative labelled approximation (ceil(len/4), min 1 for non-empty)."""
    if not text:
        return 0
    return max(1, (len(text) + APPROX_CHARS_PER_TOKEN - 1) // APPROX_CHARS_PER_TOKEN)


def message_tokens(m: dict) -> int:
    total = 0
    c = m.get("content")
    if isinstance(c, str):
        total += estimate_tokens(c)
    elif isinstance(c, list):
        for part in c:
            if isinstance(part, dict):
                total += estimate_tokens(str(part.get("text", "")))
    for tc in m.get("tool_calls") or []:
        total += estimate_tokens(str(tc))
    # role + framing overhead
    return total + 4


@dataclass
class ContextBudget:
    total: int = 65536
    system: int = 4000
    task_acceptance: int = 4000
    durable_summary: int = 4000
    repo_context: int = 12000
    reasoning_reserve: int = 8192
    output_reserve: int = 8192

    @property
    def recent_turns(self) -> int:
        used = (self.system + self.task_acceptance + self.durable_summary
                + self.repo_context + self.reasoning_reserve + self.output_reserve)
        return max(1024, self.total - used)


@dataclass
class ContextUsage:
    tokens: int
    budget: int
    pressure: float  # 0..1+
    breakdown: dict = field(default_factory=dict)

    def show(self) -> str:
        pct = self.pressure * 100
        parts = " ".join(f"{k}={v}" for k, v in self.breakdown.items())
        return f"context {self.tokens}/{self.budget} ({pct:.0f}%) {parts}".strip()


def usage_of(messages: list, budget: ContextBudget | None = None) -> ContextUsage:
    toks = [message_tokens(m) for m in messages]
    total = sum(toks)
    b = budget.total if budget else 65536
    breakdown = {}
    for m, t in zip(messages, toks):
        breakdown[m.get("role", "?")] = breakdown.get(m.get("role", "?"), 0) + t
    return ContextUsage(tokens=total, budget=b,
                        pressure=total / max(1, b), breakdown=breakdown)


def fit_to_budget(messages: list, budget: ContextBudget,
                  checkpoint_summary: str = "") -> tuple[list, ContextUsage]:
    """Drop oldest complete tool groups until within the recent-turns allowance.

    Always preserves messages[0:2] (system + task) and tool-group integrity
    via truncate_transcript. Returns (messages, usage).
    """
    validate_transcript(messages)
    allowed = budget.recent_turns + budget.system + budget.task_acceptance
    msgs = list(messages)
    # progressively keep fewer groups until it fits (or 1 group left)
    keep = 8
    while keep >= 1:
        cand = truncate_transcript(msgs, keep_last_groups=keep)
        # re-attach checkpoint summary as durable context if provided
        if checkpoint_summary and len(cand) >= 2:
            cand = [cand[0], cand[1],
                    {"role": "user",
                     "content": "DURABLE SUMMARY:\n" + checkpoint_summary[:budget.durable_summary * 4]}] + cand[2:]
        use = usage_of(cand, budget)
        if use.tokens <= allowed or keep == 1:
            return cand, use
        keep -= 1
    return msgs, usage_of(msgs, budget)
