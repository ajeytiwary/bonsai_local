"""Localized editing primitives (SPEC "Editing — mandatory").

Replaces write_file-only editing with:
- ``apply_patch``  — unified diff application (exact context matching)
- ``replace_in_file`` — exact string replacement with a strict
  unique-match precondition unless an occurrence index is given
- ``read_range``   — ranged reads of large files
- ``create_file``  — new-file creation (fails if the file exists)
- ``write_file``   — explicit full replacement (kept in WorkspaceTools)

Every operation returns/raises with a structured report: files changed,
diff/stat, precondition matched, ambiguity/error. Localized changes only —
never rewrite a large source file for a localized change.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path


class EditError(ValueError):
    """Base class — message is safe to surface to the model."""


class AmbiguityError(EditError):
    """old text matched more than once and no occurrence was selected."""


class PreconditionError(EditError):
    """old text did not match at all (or context lines mismatched)."""


@dataclass
class EditReport:
    op: str
    files_changed: list[str] = field(default_factory=list)
    diff: str = ""
    insertions: int = 0
    deletions: int = 0
    precondition: str = ""
    error: str = ""

    def to_text(self) -> str:
        lines = [f"OK: {self.op}"]
        if self.files_changed:
            lines.append("files changed: " + ", ".join(self.files_changed))
        lines.append(f"stat: +{self.insertions} -{self.deletions}")
        lines.append(f"precondition: {self.precondition}")
        if self.diff:
            lines.append("diff:")
            lines.append(self.diff)
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {
            "op": self.op, "files_changed": self.files_changed,
            "insertions": self.insertions, "deletions": self.deletions,
            "precondition": self.precondition, "diff": self.diff,
            "error": self.error,
        }


def _stat(before: str, after: str) -> tuple[int, int]:
    a = before.splitlines(keepends=True)
    b = after.splitlines(keepends=True)
    ins = dels = 0
    sm = difflib.SequenceMatcher(a=a, b=b)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "delete"):
            dels += i2 - i1
        if tag in ("replace", "insert"):
            ins += j2 - j1
    return ins, dels


def _make_diff(path: str, before: str, after: str) -> str:
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"a/{path}", tofile=f"b/{path}", n=3))


class Editor:
    """Workspace-scoped editing engine. All paths resolved under ``root``."""

    def __init__(self, root: Path, resolve=None):
        self.root = Path(root).resolve()
        self._resolve = resolve  # optional WorkspaceTools._path for shared guard

    def _path(self, p) -> Path:
        if self._resolve is not None:
            return self._resolve(p)
        x = (self.root / p).resolve()
        if x != self.root and self.root not in x.parents:
            raise EditError("path escapes workspace")
        return x

    def _rel(self, p: Path) -> str:
        try:
            return str(p.relative_to(self.root))
        except ValueError:
            return str(p)

    # ------------------------------------------------------------------ read
    def read_range(self, path: str, start_line: int = 1, end_line: int | None = None,
                   context: int = 0, max_chars: int = 30000) -> str:
        """1-based inclusive ranged read; ``context`` extends the window."""
        p = self._path(path)
        if not p.exists():
            raise EditError(f"no such file: {path}")
        lines = p.read_text(errors="replace").splitlines()
        if start_line < 1:
            raise EditError("start_line must be >= 1")
        lo = max(1, start_line - context)
        hi = min(len(lines), (end_line if end_line is not None else start_line) + context)
        if start_line > len(lines):
            raise EditError(f"start_line {start_line} beyond EOF ({len(lines)} lines)")
        window = lines[lo - 1:hi]
        width = len(str(hi))
        out = "\n".join(f"{i:>{width}}\t{l}" for i, l in zip(range(lo, hi + 1), window))
        if len(out) > max_chars:
            raise EditError(f"range too large ({len(out)} chars > {max_chars}); narrow it")
        return out

    # ------------------------------------------------------------- replace
    def replace_in_file(self, path: str, old: str, new: str,
                        occurrence: int | None = None) -> EditReport:
        """Exact replacement with strict unique-match precondition.

        ``occurrence`` is a 1-based index into the match list; when omitted,
        the old text must match exactly once (ambiguity is an error).
        """
        if old == new:
            raise EditError("old and new are identical; nothing to do")
        if old == "":
            raise EditError("old text must not be empty")
        p = self._path(path)
        if not p.exists():
            raise EditError(f"no such file: {path}")
        before = p.read_text(errors="replace")
        matches = [m.start() for m in re.finditer(re.escape(old), before)]
        if not matches:
            raise PreconditionError(
                f"precondition failed: old text not found in {self._rel(p)} "
                f"(0 matches). Inspect the file and retry with exact text.")
        if len(matches) > 1 and occurrence is None:
            lines = [before[:m].count("\n") + 1 for m in matches]
            raise AmbiguityError(
                f"ambiguity: old text matches {len(matches)} times in "
                f"{self._rel(p)} at lines {lines}. Provide occurrence "
                f"(1..{len(matches)}) or include more context to make it unique.")
        if occurrence is None:
            occurrence = 1
        if not (1 <= occurrence <= len(matches)):
            raise PreconditionError(
                f"occurrence {occurrence} out of range (1..{len(matches)})")
        idx = matches[occurrence - 1]
        after = before[:idx] + new + before[idx + len(old):]
        ins, dels = _stat(before, after)
        rel = self._rel(p)
        p.write_text(after)
        return EditReport(
            op=f"replace_in_file({rel}, occurrence={occurrence})",
            files_changed=[rel], diff=_make_diff(rel, before, after),
            insertions=ins, deletions=dels,
            precondition=f"unique match {occurrence}/{len(matches)}")

    # ---------------------------------------------------------------- patch
    def apply_patch(self, patch: str, path: str | None = None) -> EditReport:
        """Apply a unified diff. ``path`` narrows a multi-file patch.

        Every hunk is verified against current content: context/removed lines
        must match exactly at the stated position, otherwise the whole patch
        fails with a report of which hunk mismatched (atomic per file).
        """
        if not patch.strip():
            raise EditError("empty patch")
        files = self._parse_patch(patch)
        if path is not None:
            files = {k: v for k, v in files.items() if k == path or k.endswith("/" + path)}
            if not files:
                raise EditError(f"patch contains no file matching {path}")
        report = EditReport(op="apply_patch")
        # _parse_patch already verified every hunk against current content for
        # all files, so no write happens unless the whole patch is exact.
        pending: list[tuple[Path, str]] = []
        for rel, (before, after, is_new) in files.items():
            if after == before and not is_new:
                continue  # no-op hunks are fine, skip identical files
            p = self._path(rel)
            ins, dels = _stat(before, after)
            report.files_changed.append(rel)
            report.insertions += ins
            report.deletions += dels
            report.diff += _make_diff(rel, before, after)
            pending.append((p, after))
        if not pending:
            raise EditError("patch applies no changes (content already matches)")
        for p, new_text in pending:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(new_text)
        report.precondition = f"all hunks matched exactly ({len(pending)} file(s))"
        return report

    # header forms: --- a/x  +++ b/x   |  --- x  +++ x  |  --- /dev/null (new)
    _HDR_OLD = re.compile(r"^---\s+(?:a/)?([^\t\n]+)")
    _HDR_NEW = re.compile(r"^\+\+\+\s+(?:b/)?([^\t\n]+)")
    _HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

    def _parse_patch(self, patch: str) -> dict[str, tuple[str, str, bool]]:
        """Return {rel_path: (before_text, after_text, is_new)} by replaying
        hunks against current file content (exactness verified per hunk)."""
        return self._replay(patch)

    def _replay(self, patch: str) -> dict[str, tuple[str, str, bool]]:
        """Replay hunks against actual file content to get exact old/new."""
        result: dict[str, tuple[str, str, bool]] = {}
        cur: str | None = None
        is_new = False
        hunks: list[tuple[int, int, list[str]]] = []  # (old_start, old_count, lines)

        def flush_file():
            nonlocal cur, is_new, hunks
            if cur is not None and hunks:
                result[cur] = _replay_file(cur, hunks, is_new, self.root)
            cur, is_new, hunks = None, False, []

        def _replay_file(rel, hunks_list, is_new_file, root):
            p = self._path(rel)
            if is_new_file:
                if p.exists():
                    raise PreconditionError(
                        f"precondition failed: patch creates {rel} but the "
                        f"file already exists")
                current: list[str] = []
            else:
                if not p.exists():
                    raise PreconditionError(
                        f"no such file for patch: {rel} (inspect before editing)")
                current = p.read_text(errors="replace").splitlines(keepends=True)
            out_lines = list(current)
            offset = 0
            for old_start, old_count, hlines in hunks_list:
                pos = old_start - 1 + offset
                expected: list[str] = []
                produced: list[str] = []
                for hl in hlines:
                    tag, text = hl[0], hl[1:]
                    if tag == " ":
                        expected.append(text if text.endswith("\n") else text + "\n")
                        produced.append(text if text.endswith("\n") else text + "\n")
                    elif tag == "-":
                        expected.append(text if text.endswith("\n") else text + "\n")
                    elif tag == "+":
                        produced.append(text if text.endswith("\n") else text + "\n")
                    elif hl.startswith("\\"):
                        continue
                actual = out_lines[pos:pos + len(expected)]
                if actual != expected:
                    # locate first mismatch for a precise error
                    for k, (av, ev) in enumerate(zip(actual, expected)):
                        if av != ev:
                            lineno = old_start + k
                            raise PreconditionError(
                                f"precondition failed in {rel} at line {lineno}: "
                                f"expected {ev.rstrip()!r}, found {av.rstrip()!r}. "
                                f"Re-read the file and regenerate the patch.")
                    raise PreconditionError(
                        f"precondition failed in {rel}: hunk at line {old_start} "
                        f"extends past EOF (file has {len(out_lines)} lines). "
                        f"Re-read the file and regenerate the patch.")
                out_lines[pos:pos + len(expected)] = produced
                offset += len(produced) - len(expected)
            return ("".join(current), "".join(out_lines), is_new_file)

        for line in patch.splitlines(keepends=True):
            if line.startswith("--- "):
                flush_file()
                m = self._HDR_OLD.match(line)
                cur = m.group(1).strip() if m else None
                is_new = line.startswith("--- /dev/null") or (
                    cur == "/dev/null")
                if line.startswith("--- /dev/null"):
                    cur = None  # waiting for +++
                continue
            if line.startswith("+++ "):
                m = self._HDR_NEW.match(line)
                name = m.group(1).strip() if m else None
                if name == "/dev/null":
                    raise EditError("deletion patches are not supported; "
                                    "remove the file via run_command instead")
                if cur is None:
                    cur = name
                    is_new = True
                continue
            m = self._HUNK.match(line)
            if m and cur is not None:
                old_start = int(m.group(1))
                old_count = int(m.group(2) or "1")
                if old_count == 0:
                    is_new = True
                hunks.append((old_start, old_count, []))
                continue
            if hunks and cur is not None and line and line[0] in " -+":
                hunks[-1][2].append(line)
                continue
            if hunks and cur is not None and line.startswith("\\"):
                continue
        flush_file()
        if not result:
            raise EditError("could not parse patch: no file hunks found")
        return result

    # ---------------------------------------------------------- create/new
    def create_file(self, path: str, content: str) -> EditReport:
        if not isinstance(content, str) or not content.strip():
            raise EditError("refusing empty or whitespace-only file content")
        p = self._path(path)
        if p.exists():
            raise PreconditionError(
                f"{self._rel(p)} already exists — use replace_in_file or "
                f"write_file (explicit full replacement) instead of create_file")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        rel = self._rel(p)
        return EditReport(
            op=f"create_file({rel})", files_changed=[rel],
            diff=_make_diff(rel, "", content),
            insertions=len(content.splitlines()), deletions=0,
            precondition="new file (no precondition)")
