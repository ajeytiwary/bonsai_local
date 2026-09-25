#!/usr/bin/env bash
# End-to-end smoke test of the local workforce stack.
# Layers: unit tests -> Bonsai health -> chat+tool round-trip ->
#         agent single-step (offline fixture) -> Hermes/Paperclip when installed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ -f "$ROOT/.env" ]] && { set -a; # shellcheck disable=SC1091
  source "$ROOT/.env"; set +a; }

BONSAI_BASE_URL="${BONSAI_BASE_URL:-http://127.0.0.1:8091}"
HERMES_PORT="${HERMES_PORT:-8642}"
STEP="${1:-all}"
PASS=0; FAIL=0
ok()  { printf '  PASS  %s\n' "$*"; PASS=$((PASS+1)); }
bad() { printf '  FAIL  %s\n' "$*"; FAIL=$((FAIL+1)); }

PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3)"

echo "== 1. unit tests =="
if "$PY" -m pytest -q >/tmp/bonsai-smoke-tests.log 2>&1; then
  ok "$(tail -1 /tmp/bonsai-smoke-tests.log)"
else
  bad "pytest failed — see /tmp/bonsai-smoke-tests.log"
fi

echo "== 2. Bonsai health =="
if curl -fsS -m 5 "$BONSAI_BASE_URL/health" 2>/dev/null | grep -q '"status":"ok"'; then
  ok "GET /health"
else
  bad "Bonsai not healthy at $BONSAI_BASE_URL — ./scripts/start-bonsai.sh"
fi

echo "== 3. Bonsai chat + native tool-call round-trip =="
MODEL_ID="$(curl -fsS -m 5 "$BONSAI_BASE_URL/v1/models" 2>/dev/null \
  | "$PY" -c "import json,sys;print((json.load(sys.stdin).get('data') or [{}])[0].get('id',''))" 2>/dev/null || true)"
if [[ -n "$MODEL_ID" ]]; then
  ok "/v1/models -> $MODEL_ID"
  CHAT="$(curl -fsS -m 60 "$BONSAI_BASE_URL/v1/chat/completions" -H 'Content-Type: application/json' -d '{
    "model":"'"$MODEL_ID"'",
    "messages":[{"role":"user","content":"Reply with exactly: SMOKE_OK"}],
    "max_tokens":16}' 2>/dev/null || true)"
  grep -q '"choices"' <<<"$CHAT" && ok "chat completion" || bad "chat completion returned no choices"
  TOOLS="$(curl -fsS -m 90 "$BONSAI_BASE_URL/v1/chat/completions" -H 'Content-Type: application/json' -d '{
    "model":"'"$MODEL_ID"'",
    "messages":[{"role":"user","content":"Get the time."}],
    "tools":[{"type":"function","function":{"name":"get_time","description":"Get current time","parameters":{"type":"object","properties":{},"required":[]}}}],
    "tool_choice":"auto","max_tokens":128}' 2>/dev/null || true)"
  grep -q 'tool_calls' <<<"$TOOLS" && ok "native tool-call support" \
    || echo "  NOTE  no tool_calls emitted this sample (template may need a clearer prompt)"
else
  bad "no model id from /v1/models"
fi

echo "== 4. agent offline wiring (mock LLM) =="
if "$PY" - <<'EOF' >/tmp/bonsai-smoke-agent.log 2>&1
import json, tempfile, subprocess, sys
from pathlib import Path
sys.path.insert(0, ".")
from bonsai_agent.agent import Agent
from bonsai_agent.llm import BonsaiLLM

class MockLLM(BonsaiLLM):
    def __init__(self):
        super().__init__("http://127.0.0.1:1", "mock")
        self.calls = 0
    def json(self, system, user, max_tokens=800, expected=None, retries=0, reasoning_budget=None):
        if expected == "plan":
            return {"tasks": [{"title": "smoke", "description": "write hello", "acceptance": "file exists", "depends_on": []}]}
        return {"verdict": "PASS", "reason": "mock", "repair": ""}
    def tool_turn(self, messages, **kw):
        # First turn: perform the edit; later turns: finish so verify() runs.
        if self.calls == 0:
            self.calls += 1
            return {"content": "", "tool_calls": [{"id": "c1", "name": "write_file",
                    "args": {"path": "hello.txt", "content": "hi"}, "raw_arguments": "{}"}],
                    "finish_reason": "tool_calls"}
        return {"content": "done", "tool_calls": [], "finish_reason": "stop"}
    def chat(self, messages, max_tokens=3000, temperature=0.2, **kw): return "ok"

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "hello.txt").write_text("old")
    a = Agent(root, MockLLM(), tests="true", max_steps=3, auto_commit=False, verify_tests_only=True)
    rid = a.start("smoke objective")
    a.run(rid)
    st = a.status(rid)
    assert st["run"]["status"] == "complete", st["run"]
    assert (root / "hello.txt").read_text() == "hi"
print("agent wiring OK")
EOF
then
  ok "$(tail -1 /tmp/bonsai-smoke-agent.log)"
else
  bad "agent wiring smoke failed — see /tmp/bonsai-smoke-agent.log"
fi

echo "== 5. Hermes (optional) =="
if command -v hermes >/dev/null 2>&1; then
  if curl -fsS -m 3 "http://127.0.0.1:$HERMES_PORT/health" >/dev/null 2>&1 \
     || curl -fsS -m 3 "http://127.0.0.1:$HERMES_PORT/" >/dev/null 2>&1; then
    ok "Hermes gateway responding on :$HERMES_PORT"
  else
    bad "hermes installed but gateway down — ./scripts/start-hermes.sh"
  fi
else
  echo "  SKIP  hermes not installed (INSTALL_HERMES=1 ./scripts/bootstrap.sh)"
fi

echo "== 6. Paperclip (optional) =="
if command -v npx >/dev/null 2>&1 && [[ -d "${PAPERCLIP_WORKDIR:-$HOME/.paperclip}" ]]; then
  ok "Paperclip present: ${PAPERCLIP_WORKDIR:-$HOME/.paperclip}"
else
  echo "  SKIP  Paperclip not onboarded (./scripts/start-paperclip.sh)"
fi

echo
echo "== Smoke summary: $PASS PASS, $FAIL FAIL =="
if [[ "$STEP" == "unit" ]]; then exit "$FAIL"; fi
exit $(( FAIL > 0 ? 1 : 0 ))
