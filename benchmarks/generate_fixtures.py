from pathlib import Path
import json,shutil
ROOT=Path(__file__).parent/"fixtures"
TASKS=json.loads((Path(__file__).parent/"tasks.json").read_text())["tasks"]
TEMPLATES=[
("bugfix","def clamp(x,lo,hi):\n    return min(lo,max(hi,x))\n","from app import clamp\ndef test_clamp():\n assert clamp(5,0,10)==5\n assert clamp(-1,0,10)==0\n assert clamp(20,0,10)==10\n","Fix clamp so it correctly bounds values."),
("feature","def slugify(s):\n    raise NotImplementedError\n","from app import slugify\ndef test_slugify():\n assert slugify('Hello, World!')=='hello-world'\n assert slugify('  A  B ')=='a-b'\n","Implement slugify using only the standard library."),
("refactor","def total(xs):\n s=0\n for x in xs:s+=x\n return s\n","from app import total\ndef test_total():\n assert total([1,2,3])==6\n assert total([])==0\n","Refactor total cleanly without changing behavior."),
("serialization","import json\ndef encode(x): return str(x)\ndef decode(s): return s\n","from app import encode,decode\ndef test_roundtrip():\n x={'a':[1,2]}; assert decode(encode(x))==x\n","Implement JSON round-trip serialization."),
("sqlite","import sqlite3\ndef init(db):\n pass\n","import sqlite3\nfrom app import init\ndef test_init():\n c=sqlite3.connect(':memory:'); init(c); c.execute('insert into items(name) values (?)',('x',)); assert c.execute('select name from items').fetchone()[0]=='x'\n","Create the items table with integer primary key and non-null name."),
("filesystem","from pathlib import Path\ndef atomic_write(path,text):\n Path(path).write_text(text)\n","from app import atomic_write\ndef test_write(tmp_path):\n p=tmp_path/'x.txt'; atomic_write(p,'ok'); assert p.read_text()=='ok'\n","Implement robust atomic_write using a temporary sibling and replace."),
("cli","def parse_port(s): return s\n","import pytest\nfrom app import parse_port\ndef test_port():\n assert parse_port('8091')==8091\n with pytest.raises(ValueError): parse_port('0')\n with pytest.raises(ValueError): parse_port('70000')\n","Implement parse_port accepting integer ports 1..65535."),
("api","def paginate(items,page,size): return items\n","from app import paginate\ndef test_page():\n assert paginate(list(range(10)),2,3)==[3,4,5]\n assert paginate(list(range(3)),3,2)==[]\n","Implement one-indexed pagination."),
]
def main():
 if ROOT.exists(): shutil.rmtree(ROOT)
 ROOT.mkdir(parents=True)
 for i,t in enumerate(TASKS):
  d=ROOT/t["id"]; d.mkdir()
  kind,app,test,desc=TEMPLATES[i%len(TEMPLATES)]
  (d/"app.py").write_text(app)
  (d/"test_app.py").write_text(test)
  (d/"TASK.md").write_text("# Task "+t["id"]+"\n\n"+desc+"\n\nDo not modify test_app.py.\n")
 print("generated",len(TASKS),"fixtures in",ROOT)
if __name__=="__main__": main()
