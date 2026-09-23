from __future__ import annotations
import subprocess
from pathlib import Path

class Workspace:
    def __init__(self, root: Path, command_timeout: int = 300):
        self.root = root.resolve()
        self.command_timeout = command_timeout

    def _path(self, path: str) -> Path:
        p = (self.root / path).resolve()
        if p != self.root and self.root not in p.parents:
            raise ValueError("path escapes workspace")
        return p

    def read(self, path: str, max_chars: int = 30000) -> str:
        return self._path(path).read_text(errors="replace")[:max_chars]

    def write(self, path: str, content: str) -> str:
        p = self._path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"wrote {path}"

    def list(self, path: str = ".") -> str:
        p = self._path(path)
        return "\n".join(
            str(x.relative_to(self.root))
            for x in sorted(p.rglob("*"))
            if ".git" not in x.parts and ".bonsai" not in x.parts
        )[:30000]

    def run(self, command: str, timeout: int | None = None) -> str:
        cp = subprocess.run(
            command, shell=True, cwd=self.root, text=True,
            capture_output=True, timeout=timeout or self.command_timeout
        )
        return f"exit={cp.returncode}\nSTDOUT:\n{cp.stdout[-20000:]}\nSTDERR:\n{cp.stderr[-20000:]}"

    def git_diff(self) -> str:
        return self.run("git diff -- .")

    def git_status(self) -> str:
        return self.run("git status --short")

    def test(self, command: str) -> str:
        return self.run(command, timeout=max(self.command_timeout, 600))

    def execute(self, call: dict) -> str:
        name, args = call.get("tool"), call.get("args", {})
        if name == "read_file": return self.read(args["path"])
        if name == "write_file": return self.write(args["path"], args["content"])
        if name == "list_files": return self.list(args.get("path", "."))
        if name == "run_command": return self.run(args["command"])
        if name == "git_diff": return self.git_diff()
        if name == "git_status": return self.git_status()
        if name == "run_tests": return self.test(args["command"])
        raise ValueError(f"unknown tool {name}")
