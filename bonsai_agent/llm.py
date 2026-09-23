from __future__ import annotations
import json,time
import requests

class BonsaiLLM:
    def __init__(self, base_url='http://127.0.0.1:8091', model='Ternary-Bonsai-2-27B-PQ2_0', timeout=900):
        self.url=base_url.rstrip('/')+'/v1/chat/completions'; self.model=model; self.timeout=timeout
        self.observer=None; self.role="unknown"
    def bind(self,observer=None,role="unknown"): self.observer=observer; self.role=role; return self
    def chat(self,messages,max_tokens=3000,temperature=0.2):
        payload={'model':self.model,'messages':messages,'temperature':temperature,'top_p':0.95,'max_tokens':max_tokens,'stream':False}
        start=time.perf_counter(); res=requests.post(self.url,json=payload,timeout=self.timeout); elapsed=time.perf_counter()-start
        res.raise_for_status(); data=res.json(); usage=data.get('usage') or {}; timings=data.get('timings') or {}
        if self.observer: self.observer({'role':self.role,'usage':usage,'timings':timings,'seconds':elapsed,'max_tokens':max_tokens,'temperature':temperature})
        msg=data['choices'][0]['message']; return msg.get('content') or msg.get('reasoning_content') or msg.get('reasoning') or ''
    @staticmethod
    def _balanced(text,op='{',cl='}'):
        out=[]; depth=0; start=None; string=False; esc=False
        for i,ch in enumerate(text):
            if string:
                if esc: esc=False
                elif ch=='\\': esc=True
                elif ch=='"': string=False
                continue
            if ch=='"': string=True; continue
            if ch==op:
                if depth==0: start=i
                depth+=1
            elif ch==cl and depth:
                depth-=1
                if depth==0 and start is not None: out.append(text[start:i+1]); start=None
        return out
    @classmethod
    def parse_json(cls,text,expected=None):
        text=(text or '').strip()
        candidates=[]
        try: candidates.append(json.loads(text))
        except Exception: pass
        for raw in cls._balanced(text,'{','}')+cls._balanced(text,'[',']'):
            try: candidates.append(json.loads(raw))
            except Exception: pass
        def valid(x):
            if expected=="plan": return isinstance(x,dict) and isinstance(x.get("tasks"),list)
            if expected=="action": return isinstance(x,dict) and (x.get("done") is True or (isinstance(x.get("tool"),str) and isinstance(x.get("args"),dict)))
            if expected=="verdict": return isinstance(x,dict) and x.get("verdict") in {"PASS","FAIL","BLOCKED"}
            return isinstance(x,(dict,list))
        good=[x for x in candidates if valid(x)]
        if good: return good[-1]
        raise ValueError('No valid '+str(expected or 'JSON')+': '+text[:1000])
    def json(self,system,user,max_tokens=2500,expected=None,retries=1):
        text=self.chat([{'role':'system','content':system},{'role':'user','content':user}],max_tokens,0.1)
        try: return self.parse_json(text,expected)
        except ValueError:
            if retries<=0: raise
            repair="Return exactly ONE valid JSON object only. No prose, markdown or tool tags. Preserve the requested schema. Previous malformed output:\n"+text[-6000:]
            text2=self.chat([{'role':'system','content':system},{'role':'user','content':user},{'role':'assistant','content':text},{'role':'user','content':repair}],min(max_tokens,1200),0.0)
            return self.parse_json(text2,expected)
