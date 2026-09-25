#!/usr/bin/env bash
# Health/diagnostic check for the Bonsai local workforce stack.
# Checks: Python, Node/npm/npx, NVIDIA/VRAM, llama-server, GGUF/mmproj,
# Hermes, Paperclip, Git, curl, ports, dependencies and running services.
# Every failure prints an actionable fix. Exit 0 only if all required checks pass.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ -f "$ROOT/.env" ]] && { set -a; # shellcheck disable=SC1091
  source "$ROOT/.env"; set +a; }

PASS=0; FAIL=0; WARN=0
ok()   { printf '  PASS  %s\n' "$*"; PASS=$((PASS+1)); }
bad()  { printf '  FAIL  %s\n' "$*"; FAIL=$((FAIL+1)); }
warn() { printf '  WARN  %s\n' "$*"; WARN=$((WARN+1)); }
section() { printf '\n== %s ==\n' "$*"; }

BONSAI_LLAMA_SERVER="${BONSAI_LLAMA_SERVER:-/home/plasmion/git/bonsai/llama.cpp/build/bin/llama-server}"
BONSAI_MODEL="${BONSAI_MODEL:-/media/plasmion/Models/ternary_bonsai/Ternary-Bonsai-2-27B-PQ2_0.gguf}"
BONSAI_MMPROJ="${BONSAI_MMPROJ:-/media/plasmion/Models/ternary_bonsai/Ternary-Bonsai-2-27B-mmproj-Q8_0.gguf}"
BONSAI_HOST="${BONSAI_HOST:-127.0.0.1}"
BONSAI_PORT="${BONSAI_PORT:-8091}"
BONSAI_BASE_URL="${BONSAI_BASE_URL:-http://$BONSAI_HOST:$BONSAI_PORT}"
HERMES_PORT="${HERMES_PORT:-8642}"
PAPERCLIP_CMD="${PAPERCLIP_CMD:-npx paperclipai}"

section "Python"
if command -v python3 >/dev/null 2>&1; then
  PYV="$(python3 -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])')"
  if python3 -c 'import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)'; then
    ok "python3 $PYV (>= 3.10)"
  else
    bad "python3 $PYV < 3.10 — install Python >= 3.10 (e.g. pyenv/uv), then re-run ./scripts/bootstrap.sh"
  fi
else
  bad "python3 not found — install Python >= 3.10"
fi
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  ok "project venv present: $("$ROOT/.venv/bin/python" --version 2>&1)"
else
  bad ".venv missing — run: ./scripts/bootstrap.sh"
fi
if [[ -x "$ROOT/.venv/bin/bonsai-agent" ]]; then
  ok "bonsai-agent entry point installed"
else
  bad "bonsai-agent not installed — run: ./scripts/bootstrap.sh"
fi
if "$ROOT/.venv/bin/python" -c 'import pytest, requests' 2>/dev/null; then
  ok "dependencies: pytest, requests importable"
else
  bad "python deps missing (pytest/requests) — run: ./scripts/bootstrap.sh"
fi

section "Git / curl"
command -v git  >/dev/null 2>&1 && ok "git $(git --version | awk '{print $3}')" \
  || bad "git not found — install git (required for worktree isolation and baselines)"
command -v curl >/dev/null 2>&1 && ok "curl present" \
  || bad "curl not found — install curl (required for service health checks)"

section "Node toolchain (Paperclip)"
for tool in node npm npx; do
  if command -v "$tool" >/dev/null 2>&1; then
    ok "$tool $("$tool" --version 2>/dev/null | head -1)"
  else
    warn "$tool not found — Paperclip will not run; install Node.js >= 20 (nvm) then re-run"
  fi
done

section "NVIDIA / VRAM"
if command -v nvidia-smi >/dev/null 2>&1; then
  GPU_LINE="$(nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader 2>/dev/null | head -1)"
  if [[ -n "$GPU_LINE" ]]; then
    ok "GPU: $GPU_LINE"
    VRAM_TOTAL="$(echo "$GPU_LINE" | awk -F',' '{gsub(/[^0-9]/,"",$2); print $2}')"
    VRAM_USED="$(echo "$GPU_LINE"  | awk -F',' '{gsub(/[^0-9]/,"",$3); print $3}')"
    if [[ -n "$VRAM_TOTAL" && -n "$VRAM_USED" ]] && (( VRAM_USED * 100 / VRAM_TOTAL > 95 )); then
      warn "VRAM ${VRAM_USED}/${VRAM_TOTAL} MiB >95% used — llama-server may fail to allocate; free VRAM first"
    fi
  else
    bad "nvidia-smi returned no GPU — check driver (nvidia-smi)"
  fi
else
  bad "nvidia-smi not found — install NVIDIA driver (required for GPU inference)"
fi

section "llama-server binary + flags"
if [[ -x "$BONSAI_LLAMA_SERVER" ]]; then
  ok "llama-server: $BONSAI_LLAMA_SERVER"
  HELP="$("$BONSAI_LLAMA_SERVER" --help 2>&1 || true)"
  MISSING=""
  for flag in --ctx-size --flash-attn --mmproj --jinja --host --port --alias --image-min-tokens; do
    grep -q -- "$flag" <<<"$HELP" || MISSING="$MISSING $flag"
  done
  # -ngl / --gpu-layers: accept either spelling
  grep -qE -- '(-ngl|--gpu-layers)' <<<"$HELP" || MISSING="$MISSING -ngl"
  if [[ -z "$MISSING" ]]; then
    ok "required flags present in installed --help"
  else
    bad "llama-server --help missing flags:$MISSING — your PrismML fork may be outdated; rebuild llama.cpp or adjust scripts/start-bonsai.sh"
  fi
else
  bad "llama-server not found/executable at $BONSAI_LLAMA_SERVER — set BONSAI_LLAMA_SERVER or build PrismML llama.cpp"
fi

section "Model files"
if [[ -f "$BONSAI_MODEL" ]]; then
  SIZE_B="$(stat -c%s "$BONSAI_MODEL" 2>/dev/null || echo 0)"
  SIZE_GB="$(awk -v b="$SIZE_B" 'BEGIN{printf "%.1f", b/1073741824}')"
  ok "GGUF: $BONSAI_MODEL (${SIZE_GB} GB)"
else
  bad "GGUF missing: $BONSAI_MODEL — set BONSAI_MODEL in .env (file must exist)"
fi
if [[ -f "$BONSAI_MMPROJ" ]]; then
  ok "mmproj: $BONSAI_MMPROJ"
else
  bad "mmproj missing: $BONSAI_MMPROJ — set BONSAI_MMPROJ in .env (vision projector required)"
fi

section "Ports"
check_port() {  # name port required?
  local name="$1" port="$2" required="$3"
  if command -v ss >/dev/null 2>&1; then
    if ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$port\$"; then
      ok "$name port $port: LISTENING"
      return
    fi
  fi
  if [[ "$required" == "required" ]]; then
    warn "$name port $port: not listening — start it (scripts/start-${name}.sh)"
  else
    warn "$name port $port: not listening"
  fi
}
check_port bonsai "$BONSAI_PORT" required
check_port hermes "$HERMES_PORT" optional

section "Bonsai service health"
HEALTH="$(curl -fsS -m 5 "$BONSAI_BASE_URL/health" 2>/dev/null)"
if [[ "$HEALTH" == *'"status":"ok"'* ]]; then
  ok "$BONSAI_BASE_URL/health -> ok"
  MODELS_JSON="$(curl -fsS -m 5 "$BONSAI_BASE_URL/v1/models" 2>/dev/null)"
  if [[ -n "$MODELS_JSON" ]]; then
    MODEL_ID="$(python3 -c "import json,sys;d=json.load(sys.stdin);print((d.get('data') or [{}])[0].get('id',''))" <<<"$MODELS_JSON" 2>/dev/null || true)"
    ok "/v1/models -> ${MODEL_ID:-<empty>}"
    # Smoke: one tiny completion incl. tool schema support
    SMOKE="$(curl -fsS -m 30 "$BONSAI_BASE_URL/v1/chat/completions" -H 'Content-Type: application/json' \
      -d '{"model":"'"${MODEL_ID:-x}"'","messages":[{"role":"user","content":"Reply exactly: OK"}],"max_tokens":8}' 2>/dev/null)"
    if grep -q '"choices"' <<<"$SMOKE"; then
      ok "chat completion round-trip works"
    else
      bad "chat completion failed — check llama-server log in .logs/"
    fi
  else
    bad "/v1/models unreachable despite health ok — check server"
  fi
else
  bad "$BONSAI_BASE_URL/health unreachable — start it: ./scripts/start-bonsai.sh (log: .logs/bonsai.log)"
fi

section "Hermes harness"
if command -v hermes >/dev/null 2>&1; then
  ok "hermes CLI: $(hermes --version 2>/dev/null | head -1 || echo present)"
  GW="$(curl -fsS -m 3 "http://127.0.0.1:$HERMES_PORT/health" 2>/dev/null || curl -fsS -m 3 "http://127.0.0.1:$HERMES_PORT/" 2>/dev/null || true)"
  if [[ -n "$GW" ]]; then
    ok "Hermes gateway responding on :$HERMES_PORT"
  else
    warn "Hermes gateway not responding on :$HERMES_PORT — start: ./scripts/start-hermes.sh"
  fi
else
  warn "hermes CLI not found — install: INSTALL_HERMES=1 ./scripts/bootstrap.sh (or: python -m pip install --user -U hermes-agent)"
fi

section "Paperclip control plane"
if command -v npx >/dev/null 2>&1; then
  if [[ -d "${PAPERCLIP_WORKDIR:-$HOME/.paperclip}" ]]; then
    ok "Paperclip workdir present: ${PAPERCLIP_WORKDIR:-$HOME/.paperclip}"
  else
    warn "Paperclip not onboarded — run: ./scripts/start-paperclip.sh (onboards on first run)"
  fi
else
  warn "npx not found — Paperclip unavailable until Node.js is installed"
fi

section "Runaway/duplicate processes"
DUP="$(pgrep -fc "llama-server.*--port $BONSAI_PORT" 2>/dev/null || echo 0)"
if (( DUP > 1 )); then
  warn "$DUP llama-server processes claim port $BONSAI_PORT — stop duplicates: ./scripts/start-bonsai.sh stop"
elif (( DUP == 1 )); then
  ok "1 llama-server process on port $BONSAI_PORT"
else
  warn "no llama-server process found for port $BONSAI_PORT"
fi

printf '\n== Summary: %d PASS, %d FAIL, %d WARN ==\n' "$PASS" "$FAIL" "$WARN"
if (( FAIL > 0 )); then
  printf 'Fix FAIL items above, then re-run ./scripts/doctor.sh\n'
  exit 1
fi
printf 'Stack is healthy.\n'
exit 0
