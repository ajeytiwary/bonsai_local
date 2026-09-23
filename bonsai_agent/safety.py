from __future__ import annotations
import re
from dataclasses import dataclass
@dataclass
class SafetyDecision:
    allowed: bool
    reason: str=""
class CommandPolicy:
    DENY=[r"(^|\s)sudo(\s|$)",r"rm\s+-rf\s+/(\s|$)",r"mkfs\b",r"\bdd\s+if=",r"curl\b.*\|\s*(sh|bash)",r"wget\b.*\|\s*(sh|bash)",r"git\s+push\s+.*--force",r"git\s+reset\s+--hard",r"git\s+clean\s+-[a-zA-Z]*f",r"shutdown\b",r"reboot\b"]
    def __init__(self,unsafe=False): self.unsafe=unsafe
    def check(self,command):
        if self.unsafe: return SafetyDecision(True,"unsafe-shell override")
        for pat in self.DENY:
            if re.search(pat,command,re.I): return SafetyDecision(False,"blocked by policy: "+pat)
        return SafetyDecision(True,"allowed")
