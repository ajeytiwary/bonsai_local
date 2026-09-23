from __future__ import annotations
import math,re
from collections import Counter
from pathlib import Path
SKIP={".git",".agent",".bonsai","node_modules",".venv","venv","dist","build","__pycache__"}
TEXT_EXT={".py",".js",".ts",".tsx",".jsx",".go",".rs",".java",".kt",".md",".toml",".yaml",".yml",".json",".sql",".sh",".html",".css"}
class RepoRetriever:
    def __init__(self,root:Path): self.root=root.resolve()
    def files(self):
        for p in self.root.rglob("*"):
            if p.is_file() and not any(x in SKIP for x in p.parts) and (p.suffix.lower() in TEXT_EXT or p.name in {"Dockerfile","Makefile"}): yield p
    def repo_map(self,max_chars=12000):
        rows=[]
        for p in self.files():
            try: text=p.read_text(errors="replace")[:12000]
            except OSError: continue
            symbols=re.findall(r"^(?:class|def|async def|function|export function|interface|type)\s+([A-Za-z_][\w]*)",text,re.M)
            rows.append(f"{p.relative_to(self.root)} :: {', '.join(symbols[:12])}")
        return "\n".join(rows)[:max_chars]
    def search(self,query,top_k=8,chunk_chars=5000):
        terms=[x.lower() for x in re.findall(r"[A-Za-z_][\w.-]+",query) if len(x)>2]; q=Counter(terms); scored=[]
        for p in self.files():
            try: text=p.read_text(errors="replace")
            except OSError: continue
            tf=Counter(re.findall(r"[a-z_][\w.-]+",text.lower()))
            score=sum((1+math.log1p(tf[t]))*w for t,w in q.items() if tf[t])
            if score: scored.append((score,p,text))
        scored.sort(reverse=True,key=lambda x:x[0])
        return [{"path":str(p.relative_to(self.root)),"score":round(s,3),"content":text[:chunk_chars]} for s,p,text in scored[:top_k]]
