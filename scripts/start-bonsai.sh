#!/usr/bin/env bash
# Managed launcher for the Bonsai (PrismML llama.cpp) model server.
#
# Usage:
#   ./scripts/start-bonsai.sh [start|stop|restart|status|logs] [--profile benchmark|agent]
#
# Flags were validated against the installed llama-server --help
# (--ctx-size, -fa/--flash-attn, --mmproj, --jinja, -ngl, --alias,
#  --image-min-tokens, --host, --port, --parallel). doctor.sh re-checks them.
#
# Context profiles (never silently altered):
#   benchmark -> BONSAI_CTX_BENCHMARK (default 16384)
#   agent     -> BONSAI_CTX_AGENT     (default 65536; set 32768 explicitly in
#               .env if 65536 is unstable on this GPU — we never downgrade for you)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# Preserve caller-provided overrides: `set -a; source .env` would clobber them.
_CALLER_EXTRA="${BONSAI_EXTRA_ARGS-__unset__}"
[[ -f "$ROOT/.env" ]] && { set -a; # shellcheck disable=SC1091
  source "$ROOT/.env"; set +a; }
[[ "$_CALLER_EXTRA" != "__unset__" ]] && BONSAI_EXTRA_ARGS="$_CALLER_EXTRA"
unset _CALLER_EXTRA

LLAMA_SERVER="${BONSAI_LLAMA_SERVER:-/home/plasmion/git/bonsai/llama.cpp/build/bin/llama-server}"
MODEL="${BONSAI_MODEL:-/media/plasmion/Models/ternary_bonsai/Ternary-Bonsai-2-27B-PQ2_0.gguf}"
MMPROJ="${BONSAI_MMPROJ:-/media/plasmion/Models/ternary_bonsai/Ternary-Bonsai-2-27B-mmproj-Q8_0.gguf}"
HOST="${BONSAI_HOST:-127.0.0.1}"
PORT="${BONSAI_PORT:-8091}"
NGL="${BONSAI_NGL:-99}"
FA="${BONSAI_FLASH_ATTN:-on}"
THREADS="${BONSAI_THREADS:-4}"
PARALLEL="${BONSAI_PARALLEL:-1}"
PROFILE="${BONSAI_PROFILE:-benchmark}"
LOG_DIR="${LOG_DIR:-.logs}"
PID_FILE="$LOG_DIR/bonsai.pid"
LOG_FILE="$LOG_DIR/bonsai.log"
MODEL_ID="${BONSAI_MODEL_ID:-Ternary-Bonsai-2-27B-PQ2_0}"

ACTION="start"
EXTRA_PROFILE=""
for arg in "$@"; do
  case "$arg" in
    start|stop|restart|status|logs) ACTION="$arg" ;;
    --profile) EXTRA_PROFILE="next" ;;
    next) PROFILE=""; ;;   # value consumed below
    benchmark|agent) PROFILE="$arg" ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done
[[ -z "$PROFILE" ]] && PROFILE="${BONSAI_PROFILE:-benchmark}"

case "$PROFILE" in
  benchmark) CTX="${BONSAI_CTX_BENCHMARK:-16384}"
             KV="${BONSAI_KV_CACHE_BENCHMARK:-}" ;;
  agent)     CTX="${BONSAI_CTX_AGENT:-65536}"
             # 65536 f16 KV (~4 GiB) OOMs on this 12 GB GPU alongside weights;
             # quantized KV fits. Override via BONSAI_KV_CACHE_AGENT=f16 to test.
             KV="${BONSAI_KV_CACHE_AGENT:-q4_0}" ;;
  *) echo "unknown profile '$PROFILE' (use benchmark|agent)" >&2; exit 2 ;;
esac
KV_ARGS=()
[[ -n "$KV" && "$KV" != "f16" ]] && KV_ARGS=( -ctk "$KV" -ctv "$KV" )

mkdir -p "$LOG_DIR"

pid_running() { [[ -n "${1:-}" ]] && kill -0 "$1" 2>/dev/null; }
current_pid() {
  if [[ -f "$PID_FILE" ]] && pid_running "$(cat "$PID_FILE" 2>/dev/null)"; then
    cat "$PID_FILE"
  else
    pgrep -f "llama-server.*--port $PORT" 2>/dev/null | head -1 || true
  fi
}

wait_healthy() {
  local tries="${1:-60}"
  for _ in $(seq 1 "$tries"); do
    if curl -fsS -m 2 "http://$HOST:$PORT/health" 2>/dev/null | grep -q '"status":"ok"'; then
      return 0
    fi
    sleep 1
  done
  return 1
}

do_status() {
  local pid; pid="$(current_pid)"
  if [[ -n "$pid" ]] && pid_running "$pid"; then
    echo "running pid=$pid port=$PORT profile=$PROFILE ctx=$CTX"
    curl -fsS -m 2 "http://$HOST:$PORT/health" 2>/dev/null && echo || echo "health: unreachable"
  else
    echo "stopped (port $PORT)"
    return 1
  fi
}

do_stop() {
  local pid; pid="$(current_pid)"
  if [[ -z "$pid" ]]; then echo "already stopped"; return 0; fi
  echo "stopping pid=$pid (SIGTERM)"
  kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 30); do pid_running "$pid" || break; sleep 1; done
  if pid_running "$pid"; then
    echo "still running after 30s, sending SIGKILL"
    kill -KILL "$pid" 2>/dev/null || true
    sleep 1
  fi
  [[ -f "$PID_FILE" ]] && rm -f "$PID_FILE"
  echo "stopped (log retained: $LOG_FILE)"
}

do_start() {
  command -v "$LLAMA_SERVER" >/dev/null 2>&1 || { echo "llama-server not found: $LLAMA_SERVER (set BONSAI_LLAMA_SERVER)" >&2; exit 1; }
  [[ -f "$MODEL" ]]   || { echo "GGUF missing: $MODEL (set BONSAI_MODEL)" >&2; exit 1; }
  [[ -f "$MMPROJ" ]]  || { echo "mmproj missing: $MMPROJ (set BONSAI_MMPROJ)" >&2; exit 1; }

  local existing; existing="$(current_pid)"
  if [[ -n "$existing" ]] && pid_running "$existing"; then
    if curl -fsS -m 2 "http://$HOST:$PORT/health" 2>/dev/null | grep -q ok; then
      echo "already running pid=$existing (use restart to apply profile=$PROFILE ctx=$CTX)"
      return 0
    fi
    echo "process $existing alive but unhealthy — restarting"
    do_stop
  fi

  echo "starting llama-server: profile=$PROFILE ctx=$CTX port=$PORT" | tee -a "$LOG_FILE"
  echo "  model:  $MODEL" | tee -a "$LOG_FILE"
  echo "  mmproj: $MMPROJ" | tee -a "$LOG_FILE"
  [[ ${#KV_ARGS[@]} -gt 0 ]] && echo "  kv-cache: $KV (quantized)" | tee -a "$LOG_FILE"

  # shellcheck disable=SC2206
  EXTRA=( ${BONSAI_EXTRA_ARGS:-} )
  nohup "$LLAMA_SERVER" \
    -m "$MODEL" --mmproj "$MMPROJ" \
    -ngl "$NGL" -fa "$FA" -c "$CTX" -np "$PARALLEL" -t "$THREADS" \
    --image-min-tokens 1024 \
    --jinja \
    --alias "$MODEL_ID" \
    --host "$HOST" --port "$PORT" \
    ${KV_ARGS[@]+"${KV_ARGS[@]}"} \
    ${EXTRA[@]+"${EXTRA[@]}"} \
    >>"$LOG_FILE" 2>&1 &
  local pid=$!
  echo "$pid" > "$PID_FILE"
  echo "spawned pid=$pid (logs: $LOG_FILE)"

  if wait_healthy 90; then
    echo "healthy: http://$HOST:$PORT/health"
    curl -fsS -m 3 "http://$HOST:$PORT/v1/models" 2>/dev/null | head -c 400; echo
    return 0
  fi
  echo "FAIL: server did not become healthy in 90s — last log lines:" >&2
  tail -30 "$LOG_FILE" >&2 || true
  do_stop >&2 || true
  exit 1
}

case "$ACTION" in
  start)   do_start ;;
  stop)    do_stop ;;
  restart) do_stop; do_start ;;
  status)  do_status ;;
  logs)    tail -n "${LINES:-100}" -f "$LOG_FILE" ;;
esac
