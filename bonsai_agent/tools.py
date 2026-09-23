from __future__ import annotations
import os,subprocess
from pathlib import Path
from .safety import CommandPolicy
class WorkspaceTools:
    def __init__(self,root:Path,command_timeout=300,unsafe_shell=False): self.root=root.resolve(); self.command_timeout=command_timeout; self.policy=CommandPolicy(unsafe_shell)
    def _path(self,p):
        x=(self.root/p).resolve()
        if x!=self.root and self.root not in x.parents: raise ValueError("path escapes workspace")
        return x
    def read_file(self,path,max_chars=30000): return self._path(path).read_text(errors="replace")[:max_chars]
    def write_file(self,path,content):
        p=self._path(path); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(content); return "wrote "+str(p.relative_to(self.root))
    def list_files(self,path=".",limit=500):
        out=[]
        for x in self._path(path).rglob("*"):
            if x.is_file() and not any(d in x.parts for d in (".git",".agent",".bonsai","node_modules",".venv")):
                out.append(str(x.relative_to(self.root)))
                if len(out)>=limit: break
        return "\n".join(out)
    def search_files(self,query): return self.run_command("grep -RIn --exclude-dir=.git --exclude-dir=.agent -- "+subprocess.list2cmdline([query])+" .")
    def run_command(self,command):
        d=self.policy.check(command)
        if not d.allowed: return "BLOCKED: "+d.reason
        c=subprocess.run(command,cwd=self.root,shell=True,text=True,capture_output=True,timeout=self.command_timeout,env={**os.environ,"PYTHONUNBUFFERED":"1"})
        return "exit="+str(c.returncode)+"\nSTDOUT:\n"+c.stdout[-20000:]+"\nSTDERR:\n"+c.stderr[-10000:]
    def git_diff(self): return self.run_command("git diff -- . ':!.agent'")
    def git_status(self): return self.run_command("git status --short")
    def run_tests(self,command): return self.run_command(command)
    def verified_commit(self,message):
        status=self.git_status()
        if status.startswith("exit=0") and not status.split("STDOUT:\n",1)[-1].split("\nSTDERR:",1)[0].strip(): return "no changes to commit"
        a=self.run_command("git add -A -- . ':!.agent'")
        if not a.startswith("exit=0"): return "commit skipped: "+a[-500:]
        c=self.run_command("git -c user.name='Bonsai Agent' -c user.email='bonsai@local' commit -m "+subprocess.list2cmdline([message]))
        return c[-1000:]
    def execute(self,name,args):
        allowed={"read_file","write_file","list_files","search_files","run_command","git_diff","git_status","run_tests"}
        if name not in allowed: raise ValueError("unknown tool "+str(name))
        return getattr(self,name)(**args)
