"""Native tool transcript validation (SPEC M4 inference resilience).

Before sending a message list to the model, verify:
- assistant tool_calls preserved (ids unique, well-formed)
- every tool result matches a preceding call id
- all calls get results (no orphan calls)
- truncation never cuts a group (assistant+results stay together)
- content is chat-template compatible (roles, types)
"""
from __future__ import annotations


class TranscriptError(ValueError):
    pass


VALID_ROLES = {"system", "user", "assistant", "tool"}


def validate_transcript(messages) -> dict:
    """Validate a chat message list. Returns summary dict or raises TranscriptError."""
    if not isinstance(messages, list) or not messages:
        raise TranscriptError("messages must be a non-empty list")
    pending: dict[str, int] = {}  # call id -> assistant index
    seen_ids: set[str] = set()
    groups = 0
    for i, m in enumerate(messages):
        if not isinstance(m, dict):
            raise TranscriptError(f"message {i} is not a dict")
        role = m.get("role")
        if role not in VALID_ROLES:
            raise TranscriptError(f"message {i} has invalid role {role!r}")
        if role == "assistant":
            tcs = m.get("tool_calls") or []
            for tc in tcs:
                cid = tc.get("id") if isinstance(tc, dict) else None
                if not cid or not isinstance(cid, str):
                    raise TranscriptError(f"assistant message {i} has tool_call without id")
                if cid in seen_ids:
                    raise TranscriptError(f"duplicate tool_call id {cid!r}")
                seen_ids.add(cid)
                pending[cid] = i
        elif role == "tool":
            cid = m.get("tool_call_id")
            if not cid:
                raise TranscriptError(f"tool message {i} missing tool_call_id")
            if cid not in pending:
                raise TranscriptError(
                    f"tool result {i} references unknown/preceding call id {cid!r} "
                    "(every result must match a preceding call)")
            del pending[cid]
            groups += 1
        content = m.get("content")
        if content is not None and not isinstance(content, (str, list)):
            raise TranscriptError(f"message {i} content must be str/list/None")
    if pending:
        raise TranscriptError(
            "orphan tool calls without results: " + ", ".join(sorted(pending)))
    return {"messages": len(messages), "tool_calls": len(seen_ids),
            "tool_results": groups, "valid": True}


def truncate_transcript(messages, keep_last_groups: int = 4) -> list:
    """Drop oldest complete assistant/tool exchanges, preserving group integrity.

    Keeps messages[0:2] (system/user pair) exactly once, then the last
    `keep_last_groups` tool groups plus trailing non-tool messages.
    Never splits an assistant tool_calls block from its results.
    """
    if len(messages) <= 2:
        return list(messages)
    head = messages[:2]
    rest = messages[2:]
    # find assistant indices that start a tool group
    group_starts = [i for i, m in enumerate(rest)
                    if m.get("role") == "assistant" and (m.get("tool_calls") or [])]
    if not group_starts:
        return head + rest[-(keep_last_groups * 2):] if keep_last_groups else head
    # keep last N groups: from start of Nth-from-last group to end
    start = group_starts[max(0, len(group_starts) - keep_last_groups)]
    return head + rest[start:]
