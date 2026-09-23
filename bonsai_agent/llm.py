from __future__ import annotations
import json
import requests

class BonsaiLLM:
    def __init__(self, base_url='http://127.0.0.1:8091', model='Ternary-Bonsai-2-27B-PQ2_0', timeout=900):
        self.url=base_url.rstrip('/')+'/v1/chat/completions'; self.model=model; self.timeout=timeout

    def chat(self,messages,max_tokens=3000,temperature=0.2):
        payload={'model':self.model,'messages':messages,'temperature':temperature,'top_p':0.95,'max_tokens':max_tokens,'stream':False}
        res=requests.post(self.url,json=payload,timeout=self.timeout); res.raise_for_status()
        msg=res.json()['choices'][0]['message']
        return msg.get('content') or msg.get('reasoning_content') or msg.get('reasoning') or ''

    def json(self,system,user,max_tokens=2500):
        text=self.chat([{'role':'system','content':system},{'role':'user','content':user}],max_tokens,0.1).strip()
        if text.startswith('```'):
            text=text.split('\n',1)[1].rsplit('```',1)[0]
            if text.lstrip().startswith('json'): text=text.lstrip()[4:].lstrip()
        candidates=[]
        for op,cl in (('{','}'),('[',']')):
            a,b=text.find(op),text.rfind(cl)
            if a>=0 and b>a: candidates.append(text[a:b+1])
        for candidate in sorted(candidates,key=len,reverse=True):
            try: return json.loads(candidate)
            except json.JSONDecodeError: pass
        raise ValueError('No parseable JSON: '+text[:1000])
