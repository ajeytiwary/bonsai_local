from __future__ import annotations
import os,subprocess,tempfile
from pathlib import Path
from .safety import CommandPolicy
from .editing import Editor, EditError
from .shell import PersistentShell, ShellClosed

class WorkspaceTools:
    def __init__(self,root:Path,command_timeout=300,unsafe_shell=False,persistent_shell=True):
        self.root=root.resolve(); self.command_timeout=command_timeout; self.policy=CommandPolicy(unsafe_shell)
        self.editor=Editor(self.root,resolve=self._path)
        self._shell=PersistentShell(self.root) if persistent_shell else None
    def _path(self,p):
        x=(self.root/p).resolve()
        if x!=self.root and self.root not in x.parents: raise ValueError("path escapes workspace")
        return x
    def read_file(self,path,max_chars=30000): return self._path(path).read_text(errors="replace")[:max_chars]
    def read_range(self,path,start_line=1,end_line=None,context=0,max_chars=30000):
        return self.editor.read_range(path,start_line,end_line,context,max_chars)
    def replace_in_file(self,path,old,new,occurrence=None):
        return self.editor.replace_in_file(path,old,new,occurrence).to_text()
    def apply_patch(self,patch,path=None):
        return self.editor.apply_patch(patch,path).to_text()
    def create_file(self,path,content):
        return self.editor.create_file(path,content).to_text()
    def write_file(self,path,content):
        if not isinstance(content,str) or not content.strip():
            raise ValueError("refusing empty or whitespace-only file content")
        p=self._path(path); p.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix=".bonsai-write-",dir=p.parent)
        try:
            with os.fdopen(fd,"w") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(name,p.stat().st_mode & 0o777 if p.exists() else 0o644)
            os.replace(name,p)
        finally:
            if os.path.exists(name): os.unlink(name)
        return "wrote "+str(p.relative_to(self.root))
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
        if self._shell is not None:
            try:
                r=self._shell.run(command,timeout=self.command_timeout)
            except ShellClosed:
                # restart once and retry — session death must not kill the run
                self._shell=PersistentShell(self.root)
                r=self._shell.run(command,timeout=self.command_timeout)
            if r.error: return "exit=none\nSTDOUT:\n"+r.stdout[-20000:]+"\nSTDERR:\n"+r.stderr[-10000:]+"\nERROR: "+r.error
            return "exit="+str(r.exit_code)+"\nSTDOUT:\n"+r.stdout[-20000:]+"\nSTDERR:\n"+r.stderr[-10000:]
        c=subprocess.run(command,cwd=self.root,shell=True,text=True,capture_output=True,timeout=self.command_timeout,env={**os.environ,"PYTHONUNBUFFERED":"1"})
        return "exit="+str(c.returncode)+"\nSTDOUT:\n"+c.stdout[-20000:]+"\nSTDERR:\n"+c.stderr[-10000:]
    def close(self):
        if self._shell is not None:
            self._shell.close(); self._shell=None
    def __del__(self):
        try: self.close()
        except Exception: pass
    # git reads are anchored to the workspace root regardless of session cwd
    # (the session cwd must stay worker-controlled for venv/cd persistence).
    def git_diff(self): return self.run_command("git -C "+subprocess.list2cmdline([str(self.root)])+" diff -- . ':!.agent'")
    def git_status(self): return self.run_command("git -C "+subprocess.list2cmdline([str(self.root)])+" status --short")
    def run_tests(self,command): return self.run_command(command)
    def verified_commit(self,message):
        g="git -C "+subprocess.list2cmdline([str(self.root)])
        status=self.git_status()
        if status.startswith("exit=0") and not status.split("STDOUT:\n",1)[-1].split("\nSTDERR:",1)[0].strip(): return "no changes to commit"
        a=self.run_command(g+" add -A -- . ':!.agent' ':!**/__pycache__' ':!**/*.pyc' ':!.pytest_cache'")
        if not a.startswith("exit=0"): return "commit skipped: "+a[-500:]
        c=self.run_command(g+" -c user.name='Bonsai Agent' -c user.email='bonsai@local' commit -m "+subprocess.list2cmdline([message]))
        return c[-1000:]
    def execute(self,name,args):
        allowed={"read_file","read_range","write_file","replace_in_file","apply_patch","create_file","list_files","search_files","run_command","git_diff","git_status","run_tests"}
        if name not in allowed: raise ValueError("unknown tool "+str(name))
        return getattr(self,name)(**args)
