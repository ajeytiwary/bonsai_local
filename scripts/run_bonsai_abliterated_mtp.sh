#!/usr/bin/env bash
set -euo pipefail
: "${BONSAI_MTP_DIR:?Set BONSAI_MTP_DIR to the directory containing the MTP GGUF}"
LLAMA_SERVER="${LLAMA_SERVER:-llama-server}"
MODEL_DIR="${MODEL_DIR:-/media/plasmion/Models/ternary_bonsai}"
BONSAI_MTP_DIR="$MODEL_DIR/abli/mtp/Ternary-Bonsai-2-27B-Abliterated-PQ2_0-MTP.gguf|bonsai-abliterated-mtp|--reasoning off --reasoning-budget 0 --spec-type draft-mtp --spec-draft-n-max 2"

MODEL="${BONSAI_MTP_DIR%/}/Ternary-Bonsai-2-27B-Abliterated-PQ2_0-MTP.gguf"
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
  --spec-type draft-mtp --spec-draft-n-max 2 \
  --alias bonsai-abliterated-mtp \
  --host 127.0.0.1 --port "$PORT"
