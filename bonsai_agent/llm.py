from __future__ import annotations
import json,time
import requests

SCHEMAS={
 "plan":{"type":"object","properties":{"tasks":{"type":"array","minItems":1,"maxItems":6,"items":{"type":"object","properties":{"title":{"type":"string"},"description":{"type":"string"},"acceptance":{"type":"string"},"depends_on":{"type":"array","items":{"type":"integer"}}},"required":["title","description","acceptance","depends_on"],"additionalProperties":False}}},"required":["tasks"],"additionalProperties":False},
 "action":{"type":"object","properties":{"tool":{"type":"string","enum":["read_file","write_file","list_files","search_files","run_command","git_diff","git_status","run_tests"]},"args":{"type":"object"},"done":{"type":"boolean"},"summary":{"type":"string"},"note":{"type":"string"}},"additionalProperties":False},
 "verdict":{"type":"object","properties":{"verdict":{"type":"string","enum":["PASS","FAIL","BLOCKED"]},"reason":{"type":"string"},"repair":{"type":"string"}},"required":["verdict","reason","repair"],"additionalProperties":False}
}
class BonsaiLLM:
 def __init__(self,base_url='http://127.0.0.1:8091',model='Ternary-Bonsai-2-27B-PQ2_0',timeout=900):
  self.url=base_url.rstrip('/')+'/v1/chat/completions'; self.model=model; self.timeout=timeout; self.observer=None; self.role="unknown"
 def bind(self,observer=None,role="unknown"): self.observer=observer; self.role=role; return self
 def chat(self,messages,max_tokens=3000,temperature=0.2,response_schema=None):
  payload={'model':self.model,'messages':messages,'temperature':temperature,'top_p':0.95,'max_tokens':max_tokens,'stream':False}
  if response_schema:
   # llama.cpp currently documents schema-constrained chat output as json_object + schema.
   payload['response_format']={'type':'json_object','schema':response_schema}
   payload['json_schema']=response_schema # compatibility with older/forked servers
  start=time.perf_counter(); res=requests.post(self.url,json=payload,timeout=self.timeout); elapsed=time.perf_counter()-start
  res.raise_for_status(); data=res.json(); usage=data.get('usage') or {}; timings=data.get('timings') or {}
  if self.observer:self.observer({'role':self.role,'usage':usage,'timings':timings,'seconds':elapsed,'max_tokens':max_tokens,'temperature':temperature,'constrained':bool(response_schema)})
  msg=data['choices'][0]['message']; return msg.get('content') or msg.get('reasoning_content') or msg.get('reasoning') or ''
 @staticmethod
 def _balanced(text,op='{',cl='}'):
  out=[]; depth=0; start=None; string=False; esc=False
  for i,ch in enumerate(text):
   if string:
    if esc:esc=False
    elif ch=='\\':esc=True
    elif ch=='"':string=False
    continue
   if ch=='"':string=True;continue
   if ch==op:
    if depth==0:start=i
    depth+=1
   elif ch==cl and depth:
    depth-=1
    if depth==0 and start is not None:out.append(text[start:i+1]);start=None
  return out
 @classmethod
 def parse_json(cls,text,expected=None):
  text=(text or '').strip(); candidates=[]
  try:candidates.append(json.loads(text))
  except Exception:pass
  for raw in cls._balanced(text,'{','}')+cls._balanced(text,'[',']'):
   try:candidates.append(json.loads(raw))
   except Exception:pass
  def valid(x):
   if expected=="plan":return isinstance(x,dict) and isinstance(x.get("tasks"),list)
   if expected=="action":return isinstance(x,dict) and (x.get("done") is True or (isinstance(x.get("tool"),str) and isinstance(x.get("args"),dict)))
   if expected=="verdict":return isinstance(x,dict) and x.get("verdict") in {"PASS","FAIL","BLOCKED"}
   return isinstance(x,(dict,list))
  good=[x for x in candidates if valid(x)]
  if good:return good[-1]
  raise ValueError('No valid '+str(expected or 'JSON')+': '+text[:1000])
 def json(self,system,user,max_tokens=800,expected=None,retries=0):
  schema=SCHEMAS.get(expected)
  text=self.chat([{'role':'system','content':system},{'role':'user','content':user}],max_tokens,0.0,response_schema=schema)
  return self.parse_json(text,expected)
