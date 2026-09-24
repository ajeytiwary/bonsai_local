#!/usr/bin/env bash
# Run the bonsai benchmark end-to-end for the three model variants, sequentially.
#   normal      -> Ternary-Bonsai-2-27B-PQ2_0.gguf            (stock)
#   abliterated -> Ternary-Bonsai-2-27B-Abliterated-PQ2_0.gguf
#   mtp         -> Ternary-Bonsai-2-27B-Abliterated-PQ2_0-MTP.gguf (speculative MTP)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LLAMA_SERVER="${LLAMA_SERVER:-/home/plasmion/git/bonsai/llama.cpp/build/bin/llama-server}"
MODEL_DIR="${MODEL_DIR:-/media/plasmion/Models/ternary_bonsai}"
BENCH="${BENCH:-$ROOT/.venv/bin/bonsai-bench}"
PORT="${PORT:-8091}"
SPLIT="${SPLIT:-val}"
TIMEOUT="${TIMEOUT:-1800}"
OUTDIR="${OUTDIR:-$ROOT/benchmarks/results}"
STAMP="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$OUTDIR"

declare -A MODELS=(
  [normal]="$MODEL_DIR/Ternary-Bonsai-2-27B-PQ2_0.gguf|Ternary-Bonsai-2-27B-PQ2_0|--reasoning on --reasoning-effort medium"
  [abliterated]="$MODEL_DIR/abli/Ternary-Bonsai-2-27B-Abliterated-PQ2_0.gguf|bonsai-abliterated|--reasoning off --reasoning-budget 0"
  [mtp]="$MODEL_DIR/abli/mtp/Ternary-Bonsai-2-27B-Abliterated-PQ2_0-MTP.gguf|bonsai-abliterated-mtp|--reasoning off --reasoning-budget 0 --spec-type draft-mtp --spec-draft-n-max 2"
)

stop_server() {
  pkill -f "llama-server.*--port $PORT" 2>/dev/null || true
  for _ in $(seq 1 30); do
    if ! pgrep -f "llama-server.*--port $PORT" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "WARN: could not stop existing llama-server on port $PORT" >&2
}

start_server() {
  local model="$1" alias="$2" extra="$3"
  echo "Starting llama-server: $(basename "$model") (alias=$alias)"
  # shellcheck disable=SC2086
  nohup "$LLAMA_SERVER" \
    -m "$model" -ngl 99 -fa on -c 16384 -np 1 -t 4 \
    --jinja \
    --alias "$alias" \
    --host 127.0.0.1 --port "$PORT" \
    $extra >"$OUTDIR/server-$alias.log" 2>&1 &
  SERVER_PID=$!
  echo "server pid $SERVER_PID"
}

wait_ready() {
  local alias="$1"
  for _ in $(seq 1 120); do
    if curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1; then
      local name
      name="$(curl -s "http://127.0.0.1:$PORT/v1/models" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['data'][0]['id'] if d.get('data') else '')" 2>/dev/null || true)"
      if [[ -n "$name" ]]; then
        echo "Server ready: $name"
        return 0
      fi
    fi
    sleep 2
  done
  echo "ERROR: server did not become ready for $alias" >&2
  tail -20 "$OUTDIR/server-$alias.log" >&2 || true
  return 1
}

run_variant() {
  local variant="$1"
  local entry="${MODELS[$variant]}"
  local model="${entry%%|*}" alias extra
  IFS='|' read -r model alias extra <<<"$entry"
  local out="$OUTDIR/$variant-$STAMP.json"

  echo ""
  echo "============================================================"
  echo "VARIANT: $variant  (model=$(basename "$model"), alias=$alias)"
  echo "============================================================"

  stop_server
  start_server "$model" "$alias" "$extra"
  wait_ready "$alias"

  echo "Running benchmark (split=$SPLIT, timeout=$TIMEOUT)..."
  "$BENCH" --tasks "$ROOT/benchmarks/tasks.json" --split "$SPLIT" \
    --out "$out" --url "http://127.0.0.1:$PORT" --model "$alias" --timeout "$TIMEOUT"
  echo "Results written to $out"
}

for v in normal abliterated mtp; do
  run_variant "$v"
done

echo ""
echo "ALL VARIANTS DONE. Results in $OUTDIR/*-$STAMP.json"