from pathlib import Path
import json,shutil

ROOT=Path(__file__).parent/"fixtures"
TASKS=json.loads((Path(__file__).parent/"tasks.json").read_text())["tasks"]
TEMPLATES={
 "python-bugfix":("def clamp(x,lo,hi):\n    return max(lo,max(hi,x))\n","from app import clamp\ndef test_clamp():\n assert clamp(5,0,10)==5\n assert clamp(-1,0,10)==0\n assert clamp(20,0,10)==10\n","Fix clamp so it correctly bounds values."),
 "python-feature":("def slugify(s):\n    raise NotImplementedError\n","from app import slugify\ndef test_slugify():\n assert slugify('Hello, World!')=='hello-world'\n assert slugify('  A  B ')=='a-b'\n","Implement slugify using only the standard library."),
 "refactor":("def total(xs):\n s=0\n for x in xs:s+=x\n return s\n","from app import total\ndef test_total():\n assert total([1,2,3])==6\n assert total([])==0\n","Refactor total cleanly without changing behavior."),
 "serialization":("import json\ndef encode(x): return str(x)\ndef decode(s): return s\n","from app import encode,decode\ndef test_roundtrip():\n x={'a':[1,2]}; assert decode(encode(x))==x\n","Implement JSON round-trip serialization."),
 "sqlite":("import sqlite3\ndef init(db):\n pass\n","import sqlite3\nfrom app import init\ndef test_init():\n c=sqlite3.connect(':memory:'); init(c); c.execute('insert into items(name) values (?)',('x',)); assert c.execute('select name from items').fetchone()[0]=='x'\n","Create the items table with integer primary key and non-null name."),
 "filesystem":("from pathlib import Path\ndef atomic_write(path,text):\n Path(path).write_text(text)\n","import os\nfrom pathlib import Path\nfrom app import atomic_write\ndef test_write(tmp_path,monkeypatch):\n p=tmp_path/'x.txt'; calls=[]; original=os.replace\n def track(source,target):\n  calls.append((Path(source),Path(target))); return original(source,target)\n monkeypatch.setattr(os,'replace',track)\n atomic_write(p,'ok')\n assert p.read_text()=='ok'\n assert calls and calls[-1][1]==p and calls[-1][0].parent==p.parent\n assert list(tmp_path.iterdir())==[p]\n","Implement robust atomic_write using a temporary sibling and replace."),
 "cli":("def parse_port(s): return s\n","import pytest\nfrom app import parse_port\ndef test_port():\n assert parse_port('8091')==8091\n with pytest.raises(ValueError): parse_port('0')\n with pytest.raises(ValueError): parse_port('70000')\n","Implement parse_port accepting integer ports 1..65535."),
 "api":("def paginate(items,page,size): return items\n","from app import paginate\ndef test_page():\n assert paginate(list(range(10)),2,3)==[3,4,5]\n assert paginate(list(range(3)),3,2)==[]\n","Implement one-indexed pagination."),
 "git":("from pathlib import Path\ndef ignored(path):\n return False\n","from app import ignored\ndef test_ignored():\n assert ignored('.agent/state.db')\n assert ignored('module.pyc')\n assert not ignored('app.py')\n","Implement ignored(path) for .agent files and Python bytecode files."),
 "tests":("def square(x): return x*x\n","from app import square\ndef test_square():\n assert square(2)==4\n","Add tests for square's negative and zero inputs in a new test file; do not modify test_app.py."),
}

def main():
 if ROOT.exists(): shutil.rmtree(ROOT)
 ROOT.mkdir(parents=True)
 for task in TASKS:
  directory=ROOT/task["id"]; directory.mkdir()
  app,test,description=TEMPLATES[task["category"]]
  (directory/"app.py").write_text(app)
  (directory/"test_app.py").write_text(test)
  (directory/"TASK.md").write_text(f"# Task {task['id']}\n\n{description}\n\nDo not modify test_app.py.\n")
 print("generated",len(TASKS),"fixtures in",ROOT)

if __name__=="__main__": main()
