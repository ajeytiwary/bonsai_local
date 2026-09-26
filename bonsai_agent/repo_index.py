"""M5 repository intelligence (SPEC): persistent symbol/chunk/BM25/
dependency/git index with incremental refresh.

Stdlib only (no tree-sitter / embedding hard dependency). Symbol parsing
is a safe regex fallback: Python (class/def/method/imports), JS/TS
(function/class/arrow-const/import/require), plus generic C-like
(fn/func/struct/interface/type/const/let) symbol lines. Embeddings are an
interface (NullEmbeddings default); a real provider can be injected via
RepoIndex(root, embeddings=...) without changing callers.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

INDEX_VERSION = "m5"

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

_PY_CLASS = re.compile(r"^(\s*)class\s+([A-Za-z_]\w*)")
_PY_DEF = re.compile(r"^(\s*)async\s+def\s+([A-Za-z_]\w*)|^(\s*)def\s+([A-Za-z_]\w*)")
_JS_FUNC = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)"
    r"|^\s*(?:export\s+)?class\s+([A-Za-z_]\w*)"
    r"|^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_]\w*)\s*=\s*(?:async\s*)\("
    r"|^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_]\w*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>")
_C_SYM = re.compile(
    r"^\s*(?:fn|func|struct|interface|type)\s+([A-Za-z_]\w*)"
    r"|^\s*(?:const|let)\s+([A-Za-z_]\w*)\s*=")

CHUNK_CHARS = 2000
CHUNK_OVERLAP = 200
MAX_FILE_CHARS = 16000
MAX_CHUNKS = 8


def _tokens(text: str) -> list[str]:
    return [x.lower() for x in TOKEN_RE.findall(re.sub(r"[_./-]+", " ", text))]


def parse_symbols(text: str, suffix: str) -> list[dict]:
    """Best-effort symbol table: [{name, kind, line, qualified}]."""
    out: list[dict] = []
    lines = text.splitlines()
    if suffix == ".py":
        stack: list[tuple[int, str]] = []
        for i, line in enumerate(lines, 1):
            m = _PY_CLASS.match(line)
            if m:
                indent = len(m.group(1).replace("\t", "    "))
                name = m.group(2)
                while stack and stack[-1][0] >= indent:
                    stack.pop()
                out.append({"name": name, "kind": "class", "line": i,
                            "qualified": name})
                stack.append((indent, name))
                continue
            m = _PY_DEF.match(line)
            if m:
                raw_indent = m.group(1) if m.group(1) is not None else (m.group(3) or "")
                indent = len(raw_indent.replace("\t", "    "))
                name = m.group(2) or m.group(4)
                while stack and stack[-1][0] >= indent:
                    stack.pop()
                kind = "method" if stack else "function"
                qual = f"{stack[-1][1]}.{name}" if stack else name
                out.append({"name": name, "kind": kind, "line": i,
                            "qualified": qual})
    elif suffix in {".js", ".ts", ".tsx", ".jsx"}:
        for i, line in enumerate(lines, 1):
            m = _JS_FUNC.match(line)
            if m:
                name = next(g for g in m.groups() if g)
                kind = "class" if "class " in line else "function"
                out.append({"name": name, "kind": kind, "line": i,
                            "qualified": name})
    else:
        for i, line in enumerate(lines, 1):
            m = _C_SYM.match(line)
            if m:
                name = next(g for g in m.groups() if g)
                out.append({"name": name, "kind": "symbol", "line": i,
                            "qualified": name})
    return out[:64]


def chunk_text(text: str, path: str) -> list[str]:
    """Overlapping chunks with FILE headers (standalone-interpretable)."""
    body = text[:MAX_FILE_CHARS]
    chunks = []
    start = 0
    while start < len(body) and len(chunks) < MAX_CHUNKS:
        end = min(len(body), start + CHUNK_CHARS)
        chunks.append(f"FILE {path} [chars {start}-{end}]\n" + body[start:end])
        if end >= len(body):
            break
        start = end - CHUNK_OVERLAP
    return chunks or [f"FILE {path} [chars 0-0]\n"]


def normalize_imports(text: str) -> list[str]:
    """Raw import strings + path-ish module tokens for the dep graph."""
    raw = [g for m in IMPORT_RE.findall(text) for g in m if g]
    mods: list[str] = []
    for r in raw:
        for part in re.split(r"[,\s;]+", r):
            part = part.strip().strip("'\"()")
            if not part or part in {"as", "from", "import"}:
                continue
            mods.append(part)
            mods.append(part.replace(".", "/"))
    seen = []
    for m in raw + mods:
        if m and m not in seen:
            seen.append(m)
    return seen[:24]


class EmbeddingProvider:
    """Interface: real providers (local model / API) plug in here."""

    def available(self) -> bool:
        return False

    def embed(self, texts: list[str]) -> list:
        return [None] * len(texts)


class NullEmbeddings(EmbeddingProvider):
    """Default: no embeddings; lexical BM25 carries retrieval."""


@dataclass
class DocEntry:
    path: str
    kind: str  # file extension / type
    symbols: list[str] = field(default_factory=list)  # symbol names
    qualified_symbols: list[str] = field(default_factory=list)
    symbol_table: list[dict] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    chunks: list[str] = field(default_factory=list)  # chunk texts
    mtime: float = 0.0
    size: int = 0
    recency: float = 0.0  # git recency boost 0..1
    git: dict = field(default_factory=dict)  # commits/change_count/author/date
    tf: dict = field(default_factory=dict)
    length: int = 1


class RepoIndex:
    """Persistent incremental index stored at <root>/.agent/repo-index.json."""

    def __init__(self, root: Path, embeddings: EmbeddingProvider | None = None):
        self.root = Path(root).resolve()
        self.state_path = self.root / ".agent" / "repo-index.json"
        self.embeddings = embeddings or NullEmbeddings()
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
        if data.get("version") not in (None, INDEX_VERSION):
            return  # stale schema: start fresh, refresh() rebuilds
        for path, d in data.get("docs", {}).items():
            table = d.get("symbol_table") or []
            self.docs[path] = DocEntry(
                path=path, kind=d.get("kind", ""),
                symbols=d.get("symbols", []),
                qualified_symbols=d.get(
                    "qualified_symbols",
                    [s.get("qualified", s.get("name", "")) for s in table
                     if isinstance(s, dict)]),
                symbol_table=table,
                imports=d.get("imports", []),
                chunks=d.get("chunks", [])[:MAX_CHUNKS],
                mtime=d.get("mtime", 0.0), size=d.get("size", 0),
                recency=d.get("recency", 0.0), git=d.get("git", {}),
                tf=d.get("tf", {}), length=d.get("length", 1))
        self.avg_len = data.get("avg_len", 1.0) or 1.0

    def save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": INDEX_VERSION, "avg_len": self.avg_len,
                "docs": {p: {"kind": d.kind, "symbols": d.symbols,
                             "qualified_symbols": d.qualified_symbols,
                             "symbol_table": d.symbol_table,
                             "imports": d.imports,
                             "chunks": d.chunks[:MAX_CHUNKS],
                             "mtime": d.mtime, "size": d.size,
                             "recency": d.recency, "git": d.git,
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

    def _git_file_meta(self, rel: str) -> dict:
        """Per-file git metadata: recent commits, change count, author/date."""
        try:
            log = subprocess.run(
                ["git", "-C", str(self.root), "log",
                 "--pretty=format:%H|%an|%ad", "--date=short",
                 "-n", "5", "--", rel],
                text=True, capture_output=True, timeout=30).stdout.strip()
        except OSError:
            return {}
        if not log:
            return {}
        rows = [l.split("|") for l in log.splitlines() if "|" in l]
        if not rows:
            return {}
        return {"commits": [r[0][:12] for r in rows],
                "change_count": len(rows) + _git_older_count(self.root, rel),
                "last_author": rows[0][1], "last_date": rows[0][2]}

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
            if (cur and not force and cur.mtime == st.st_mtime
                    and cur.size == st.st_size):
                cur.recency = recency.get(rel, 0.0)
                continue
            try:
                text = p.read_text(errors="replace")
            except OSError:
                continue
            toks = _tokens(rel + " " + text)
            tf = dict(Counter(t for t in toks if len(t) > 2))
            table = parse_symbols(text, p.suffix.lower())
            entry = DocEntry(
                path=rel, kind=p.suffix.lower() or p.name,
                symbols=[s["name"] for s in table][:32],
                qualified_symbols=[s["qualified"] for s in table][:32],
                symbol_table=table,
                imports=normalize_imports(text),
                chunks=chunk_text(text, rel),
                mtime=st.st_mtime, size=st.st_size,
                recency=recency.get(rel, 0.0),
                git=self._git_file_meta(rel),
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
    def _bm25(self, q: Counter) -> tuple[dict[str, float], dict]:
        n = len(self.docs)
        df: Counter = Counter()
        for d in self.docs.values():
            for t in set(d.tf) & set(q):
                df[t] += 1
        scores: dict[str, float] = {}
        for d in self.docs.values():
            s = 0.0
            for t, w in q.items():
                f = d.tf.get(t, 0)
                if not f:
                    continue
                idf = math.log(1 + (n - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5))
                denom = f + 1.2 * (1 - 0.75 + 0.75 * d.length / self.avg_len)
                s += idf * (f * 2.2) / denom * w
            syms = {x.lower() for x in d.symbols}
            s += sum(2.0 * w for t, w in q.items() if t in syms)
            s *= (1 + 0.25 * d.recency)
            if s:
                scores[d.path] = s
        return scores, df

    def search(self, query: str, top_k: int = 8,
               mode: str = "text") -> list[dict]:
        """Query modes: text | symbol | path | implementation | test | recent.

        - symbol: rank by symbol-table name match first.
        - path: substring match on file path.
        - implementation: symbol match, test files demoted.
        - test: test files promoted.
        - recent: git recency order (query still filters via BM25).
        """
        q = Counter(t for t in _tokens(query) if len(t) > 2)
        if not self.docs:
            return []
        if mode == "path":
            ql = query.lower()
            hits = [d for d in self.docs.values() if ql in d.path.lower()]
            hits.sort(key=lambda d: (len(d.path), d.path))
            return [self._hit(d, 1.0) for d in hits[:top_k]]
        if mode == "recent" and not q:
            ranked = sorted(self.docs.values(),
                            key=lambda d: (-d.recency, d.path))
            return [self._hit(d, d.recency) for d in ranked[:top_k]]
        if not q:
            if mode == "recent":
                ranked = sorted(self.docs.values(),
                                key=lambda d: (-d.recency, d.path))
                return [self._hit(d, d.recency) for d in ranked[:top_k]]
            return []
        scores, _ = self._bm25(q)
        if mode == "recent":
            # Recency order wins; BM25 only filters when it hits.
            ranked_docs = sorted(self.docs.values(),
                                 key=lambda d: (-d.recency, d.path))
            if scores:
                ranked_docs.sort(
                    key=lambda d: (d.path not in scores, -d.recency, d.path))
            return [self._hit(d, scores.get(d.path, d.recency))
                    for d in ranked_docs[:top_k]]
        if mode == "symbol":
            for d in self.docs.values():
                syms = {x.lower() for x in d.symbols}
                qsyms = {x.lower() for x in d.qualified_symbols}
                bonus = sum(4.0 * w for t, w in q.items()
                            if t in syms or t in qsyms)
                if bonus:
                    scores[d.path] = scores.get(d.path, 0.0) + bonus
        if mode in ("implementation", "test"):
            for d in self.docs.values():
                if d.path not in scores:
                    continue
                is_test = ("test" in d.path.lower()
                           or d.path.startswith("tests/"))
                if mode == "implementation" and is_test:
                    scores[d.path] *= 0.25
                elif mode == "test" and is_test:
                    scores[d.path] *= 8.0
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        return [self._hit(self.docs[p], s) for p, s in ranked[:top_k]]

    def _hit(self, d: DocEntry, s: float) -> dict:
        return {"path": d.path, "score": round(s, 3),
                "symbols": d.symbols[:12], "imports": d.imports[:8],
                "recency": round(d.recency, 3),
                "content": "\n".join(d.chunks)[:5000]}

    # ------------------------------------------------------- graph + metadata
    def dependencies(self, path: str) -> dict:
        """Direct imports + reverse index (who imports this module)."""
        d = self.docs.get(path)
        return {"imports": list(d.imports) if d else [],
                "imported_by": self.imported_by(path)}

    def imported_by(self, module: str) -> list[str]:
        """Files whose imports reference `module` (path or dotted form)."""
        mod = module.replace(".py", "").replace(".", "/").strip("/")
        out = []
        for d in self.docs.values():
            if d.path == module:
                continue
            for imp in d.imports:
                norm = imp.replace(".py", "").replace(".", "/").strip("/")
                if norm == mod or norm.endswith("/" + mod) or mod.endswith(norm):
                    out.append(d.path)
                    break
        return sorted(out)

    def references(self, symbol: str) -> list[dict]:
        """Files mentioning `symbol` (definition + call sites)."""
        pat = re.compile(r"\b" + re.escape(symbol) + r"\b")
        out = []
        for d in self.docs.values():
            n = sum(len(pat.findall(c)) for c in d.chunks)
            if n:
                out.append({"path": d.path, "mentions": n,
                            "symbols": d.symbols[:12]})
        out.sort(key=lambda r: (-r["mentions"], r["path"]))
        return out

    def stats(self) -> dict:
        return {"docs": len(self.docs),
                "symbols": sum(len(d.symbols) for d in self.docs.values()),
                "chunks": sum(len(d.chunks) for d in self.docs.values()),
                "avg_len": round(self.avg_len, 1),
                "embeddings": self.embeddings.available()}


def _git_older_count(root: Path, rel: str) -> int:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-list", "--count", "HEAD", "--", rel],
            text=True, capture_output=True, timeout=30).stdout.strip()
        return max(0, int(out or 0) - 5)
    except (OSError, ValueError):
        return 0
