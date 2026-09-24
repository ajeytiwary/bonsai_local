from __future__ import annotations
import json,time
import requests

SCHEMAS={
 "plan":{"type":"object","properties":{"tasks":{"type":"array","minItems":1,"maxItems":6,"items":{"type":"object","properties":{"title":{"type":"string"},"description":{"type":"string"},"acceptance":{"type":"string"},"depends_on":{"type":"array","items":{"type":"integer"}}},"required":["title","description","acceptance","depends_on"],"additionalProperties":False}}},"required":["tasks"],"additionalProperties":False},
 "verdict":{"type":"object","properties":{"verdict":{"type":"string","enum":["PASS","FAIL","BLOCKED"]},"reason":{"type":"string"},"repair":{"type":"string"}},"required":["verdict","reason","repair"],"additionalProperties":False}
}

TOOL_SCHEMAS=[
 {"type":"function","function":{"name":"read_file","description":"Read a UTF-8 text file in the workspace.","parameters":{"type":"object","properties":{"path":{"type":"string"},"max_chars":{"type":"integer"}},"required":["path"]}}},
 {"type":"function","function":{"name":"write_file","description":"Write complete text content to a workspace file.","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}}},
 {"type":"function","function":{"name":"list_files","description":"List files below a workspace path.","parameters":{"type":"object","properties":{"path":{"type":"string"},"limit":{"type":"integer"}}}}},
 {"type":"function","function":{"name":"search_files","description":"Search workspace text files for a query.","parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}},
 {"type":"function","function":{"name":"run_command","description":"Run a safe shell command in the workspace.","parameters":{"type":"object","properties":{"command":{"type":"string"}},"required":["command"]}}},
 {"type":"function","function":{"name":"git_diff","description":"Show the current source diff.","parameters":{"type":"object","properties":{}}}},
 {"type":"function","function":{"name":"git_status","description":"Show git status.","parameters":{"type":"object","properties":{}}}},
 {"type":"function","function":{"name":"run_tests","description":"Run a focused test command.","parameters":{"type":"object","properties":{"command":{"type":"string"}},"required":["command"]}}}
]

class BonsaiLLM:
 def __init__(self,base_url='http://127.0.0.1:8091',model='Ternary-Bonsai-2-27B-PQ2_0',timeout=900):
  self.url=base_url.rstrip('/')+'/v1/chat/completions'; self.model=model; self.timeout=timeout; self.observer=None; self.role="unknown"
 def bind(self,observer=None,role="unknown"): self.observer=observer; self.role=role; return self
 def _post(self,payload,max_tokens,temperature,constrained=False):
  start=time.perf_counter(); res=requests.post(self.url,json=payload,timeout=self.timeout); elapsed=time.perf_counter()-start
  res.raise_for_status(); data=res.json(); usage=data.get('usage') or {}; timings=data.get('timings') or {}
  choice=(data.get('choices') or [{}])[0]; msg=choice.get('message') or {}
  if self.observer:self.observer({'role':self.role,'usage':usage,'timings':timings,'seconds':elapsed,'max_tokens':max_tokens,'temperature':temperature,'constrained':constrained,'finish_reason':choice.get('finish_reason'),'tool_calls':len(msg.get('tool_calls') or [])})
  return data
 def chat(self,messages,max_tokens=3000,temperature=0.2,response_schema=None,reasoning_budget=None):
  payload={'model':self.model,'messages':messages,'temperature':temperature,'top_p':0.95,'max_tokens':max_tokens,'stream':False}
  if reasoning_budget is not None: payload['thinking_budget_tokens']=reasoning_budget
  if response_schema: payload['response_format']={'type':'json_object','schema':response_schema}
  data=self._post(payload,max_tokens,temperature,bool(response_schema)); msg=data['choices'][0]['message']
  return msg.get('content') or msg.get('reasoning_content') or msg.get('reasoning') or ''
 def tool_turn(self,messages,max_tokens=900,temperature=0.2,reasoning_budget=2048,tools=None,tool_choice="auto"):
  available_tools=tools or TOOL_SCHEMAS
  if isinstance(tool_choice,dict):
   name=(tool_choice.get("function") or {}).get("name")
   available_tools=[item for item in available_tools if (item.get("function") or {}).get("name")==name]
   if not available_tools: raise ValueError("Unknown required tool: "+str(name))
   tool_choice="required"
  payload={"model":self.model,"messages":messages,"temperature":temperature,"top_p":0.95,"max_tokens":max_tokens,"stream":False,"tools":available_tools,"tool_choice":tool_choice}
  if reasoning_budget is not None: payload['thinking_budget_tokens']=reasoning_budget
  data=self._post(payload,max_tokens,temperature,False); choice=data['choices'][0]; msg=choice.get('message') or {}
  calls=[]
  for tc in msg.get('tool_calls') or []:
   fn=tc.get('function') or {}; raw=fn.get('arguments') or '{}'
   error=None
   try:
    args=json.loads(raw) if isinstance(raw,str) else raw
    if not isinstance(args,dict):
     error="Tool arguments must be a JSON object"; args={}
   except (TypeError,ValueError) as exc:
    args={}; error="Invalid or incomplete JSON tool arguments: "+str(exc)
   call={"id":tc.get("id") or "call_"+str(len(calls)+1),"name":fn.get("name"),"args":args,"raw_arguments":raw if isinstance(raw,str) else json.dumps(raw)}
   if error: call["argument_error"]=error
   calls.append(call)
  return {'content':msg.get('content') or '','reasoning_content':msg.get('reasoning_content') or msg.get('reasoning') or '','tool_calls':calls,'finish_reason':choice.get('finish_reason')}
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
 def json(self,system,user,max_tokens=800,expected=None,retries=0,reasoning_budget=None):
  schema=SCHEMAS.get(expected)
  text=self.chat([{'role':'system','content':system},{'role':'user','content':user}],max_tokens,0.0,response_schema=schema,reasoning_budget=reasoning_budget)
  try:return self.parse_json(text,expected)
  except ValueError:
   if retries<=0:raise
   repair='Return ONLY one compact JSON object matching this schema: '+json.dumps(schema,separators=(',',':'))+'\nPrevious output:\n'+text[-2500:]
   text=self.chat([{'role':'system','content':'Output JSON only.'},{'role':'user','content':repair}],max_tokens,0.0,response_schema=schema,reasoning_budget=0)
   return self.parse_json(text,expected)
