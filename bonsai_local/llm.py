from __future__ import annotations
import json, requests
from typing import Any

class Bonsai:
    def __init__(self, base_url="http://127.0.0.1:8091", model="Ternary-Bonsai-2-27B-PQ2_0", timeout=1800):
        self.url=base_url.rstrip("/")+"/v1/chat/completions"; self.model=model; self.timeout=timeout
    def chat(self, system:str, user:str, max_tokens:int=3000, temperature:float=0.2)->str:
        p={"model":self.model,"messages":[{"role":"system","content":system},{"role":"user","content":user}],
           "temperature":temperature,"top_p":0.9,"max_tokens":max_tokens,"stream":False}
        r=requests.post(self.url,json=p,timeout=self.timeout); r.raise_for_status()
        data=r.json(); choice=data["choices"][0]
        msg=choice.get("message",{})
        return msg.get("content") or msg.get("reasoning_content") or msg.get("reasoning") or ""
    def json(self, system:str, user:str, max_tokens:int=3000)->Any:
        text=self.chat(system,user,max_tokens)
        s=text.find("{"); a=text.find("[")
        start=min([x for x in (s,a) if x>=0],default=-1)
        if start<0: raise ValueError("Model returned no JSON: "+text[:500])
        close="}" if text[start]=="{" else "]"; end=text.rfind(close)
        return json.loads(text[start:end+1])
