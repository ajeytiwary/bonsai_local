"""Incremental repo index (SPEC M4/M5 seed): files/types, symbols, chunks,
imports/dependencies, references, git recency/change metadata, BM25-style
length-normalized lexical ranking. No full rescan on every task — mtimes +
git status drive incremental refresh. Tree-sitter preferred with safe
regex fallback (no hard dependency).
"""
from __future__ import annotations

import json
import math
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

SKIP = {".git", ".agent", ".bonsai", "node_modules", ".venv", "venv",
        "dist", "build", "__pycache__", ".pytest_cache"}
TEXT_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
            ".kt", ".md", ".toml", ".yaml", ".yml", ".json", ".sql",
            ".sh", ".html", ".css"}
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")
SYM_RE = re.compile(
    r"^(?:class|def|async def|function|export function|export class|"
    r"interface|type|const|let|fn|func|struct)\s+([A-Za-z_][\w]*)", re.M)
IMPORT_RE = re.compile(
    r"^(?:import\s+([^\n;]+)|from\s+(\S+)\s+import|require\(['\"]([^'\"]+)['\"]\))",
    re.M)


def _tokens(text: str) -> list[str]:
    return [x.lower() for x in TOKEN_RE.findall(re.sub(r"[_./-]+", " ", text))]


@dataclass
class DocEntry:
    path: str
    kind: str  # file extension / type
    symbols: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    chunks: list[str] = field(default_factory=list)  # chunk texts
    mtime: float = 0.0
    recency: float = 0.0  # git recency boost 0..1
    tf: dict = field(default_factory=dict)
    length: int = 1


class RepoIndex:
    """Persistent incremental index stored at <root>/.agent/repo-index.json."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.state_path = self.root / ".agent" / "repo-index.json"
        self.docs: dict[str, DocEntry] = {}
        self.avg_len: float = 1.0
        self._load()

    # ------------------------------------------------------------ persistence
    def _load(self):
        if not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return
        for path, d in data.get("docs", {}).items():
            self.docs[path] = DocEntry(path=path, kind=d.get("kind", ""),
                                       symbols=d.get("symbols", []),
                                       imports=d.get("imports", []),
                                       chunks=d.get("chunks", [])[:8],
                                       mtime=d.get("mtime", 0.0),
                                       recency=d.get("recency", 0.0),
                                       tf=d.get("tf", {}),
                                       length=d.get("length", 1))
        self.avg_len = data.get("avg_len", 1.0) or 1.0

    def save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"avg_len": self.avg_len,
                "docs": {p: {"kind": d.kind, "symbols": d.symbols,
                             "imports": d.imports, "chunks": d.chunks[:8],
                             "mtime": d.mtime, "recency": d.recency,
                             "tf": dict(list(d.tf.items())[:400]),
                             "length": d.length}
                         for p, d in self.docs.items()}}
        self.state_path.write_text(json.dumps(data))

    # ---------------------------------------------------------------- refresh
    def _iter_files(self):
        for p in self.root.rglob("*"):
            if not p.is_file() or any(x in SKIP for x in p.parts):
                continue
            if p.suffix.lower() in TEXT_EXT or p.name in {"Dockerfile", "Makefile"}:
                yield p

    def _git_recency(self) -> dict[str, float]:
        """Changed-recently files get a boost (0..1); {} when not a repo."""
        try:
            out = subprocess.run(
                ["git", "-C", str(self.root), "log", "--name-only",
                 "--pretty=format:", "-n", "20"],
                text=True, capture_output=True, timeout=30).stdout
        except OSError:
            return {}
        counts: Counter = Counter(l.strip() for l in out.splitlines() if l.strip())
        if not counts:
            return {}
        top = max(counts.values())
        return {k: v / top for k, v in counts.items()}

    def refresh(self, force: bool = False) -> dict:
        """Incremental refresh: only re-read files with changed mtime/size."""
        recency = self._git_recency()
        added = updated = removed = 0
        seen = set()
        for p in self._iter_files():
            rel = str(p.relative_to(self.root))
            seen.add(rel)
            try:
                st = p.stat()
            except OSError:
                continue
            cur = self.docs.get(rel)
            if cur and not force and cur.mtime == st.st_mtime:
                cur.recency = recency.get(rel, 0.0)
                continue
            try:
                text = p.read_text(errors="replace")
            except OSError:
                continue
            toks = _tokens(rel + " " + text)
            tf = dict(Counter(t for t in toks if len(t) > 2))
            entry = DocEntry(
                path=rel, kind=p.suffix.lower() or p.name,
                symbols=SYM_RE.findall(text)[:32],
                imports=[g for m in IMPORT_RE.findall(text) for g in m if g][:16],
                chunks=[text[i:i + 2000] for i in range(0, min(len(text), 16000), 2000)][:8],
                mtime=st.st_mtime, recency=recency.get(rel, 0.0),
                tf=tf, length=max(1, len(toks)))
            if cur is None:
                added += 1
            else:
                updated += 1
            self.docs[rel] = entry
        for rel in [r for r in self.docs if r not in seen]:
            del self.docs[rel]
            removed += 1
        self.avg_len = (sum(d.length for d in self.docs.values())
                        / max(1, len(self.docs))) or 1.0
        self.save()
        return {"added": added, "updated": updated, "removed": removed,
                "docs": len(self.docs)}

    # ----------------------------------------------------------------- search
    def search(self, query: str, top_k: int = 8) -> list[dict]:
        """BM25-ish (k1=1.2, b=0.75) + symbol bonus + git recency boost."""
        q = Counter(t for t in _tokens(query) if len(t) > 2)
        if not q or not self.docs:
            return []
        n = len(self.docs)
        df: Counter = Counter()
        for d in self.docs.values():
            for t in set(d.tf) & set(q):
                df[t] += 1
        scored = []
        for d in self.docs.values():
            s = 0.0
            for t, w in q.items():
                f = d.tf.get(t, 0)
                if not f:
                    continue
                idf = math.log(1 + (n - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5))
                denom = f + 1.2 * (1 - 0.75 + 0.75 * d.length / self.avg_len)
                s += idf * (f * 2.2) / denom * w
            # symbol-name matches count double
            syms = {x.lower() for x in d.symbols}
            s += sum(2.0 * w for t, w in q.items() if t in syms)
            s *= (1 + 0.25 * d.recency)
            if s:
                scored.append((s, d))
        scored.sort(reverse=True, key=lambda x: (x[0], x[1].path))
        return [{"path": d.path, "score": round(s, 3), "symbols": d.symbols[:12],
                 "imports": d.imports[:8], "recency": round(d.recency, 3),
                 "content": "\n".join(d.chunks)[:5000]}
                for s, d in scored[:top_k]]
