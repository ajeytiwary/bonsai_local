#!/usr/bin/env bash
set -euo pipefail
: "${BONSAI_MODEL_DIR:?Set BONSAI_MODEL_DIR to the directory containing the abliterated GGUF}"
LLAMA_SERVER="${LLAMA_SERVER:-llama-server}"
MODEL="${BONSAI_MODEL_DIR%/}/Ternary-Bonsai-2-27B-Abliterated-PQ2_0.gguf"
PORT="${PORT:-8091}"
CONTEXT="${CONTEXT:-16384}"
NGL="${NGL:-99}"
THREADS="${THREADS:-4}"
if [[ ! -f "$MODEL" ]]; then
  printf 'Model file not found: %s\n' "$MODEL" >&2
  exit 1
fi
exec "$LLAMA_SERVER" \
  -m "$MODEL" -ngl "$NGL" -fa on -c "$CONTEXT" -np 1 -t "$THREADS" \
  --jinja --reasoning off --reasoning-budget 0 \
  --alias bonsai-abliterated \
  --host 127.0.0.1 --port "$PORT"
