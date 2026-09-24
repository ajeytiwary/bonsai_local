#!/usr/bin/env bash
set -euo pipefail
LLAMA_DIR="${LLAMA_DIR:-/home/plasmion/git/bonsai/llama.cpp}"
MODEL="${MODEL:-/media/plasmion/Models/ternary_bonsai/Ternary-Bonsai-2-27B-PQ2_0.gguf}"
MMPROJ="${MMPROJ:-/media/plasmion/Models/ternary_bonsai/Ternary-Bonsai-2-27B-mmproj-Q8_0.gguf}"
PORT="${PORT:-8091}"
AGENT_CTX="${AGENT_CTX:-65536}"
REASONING_BUDGET="${REASONING_BUDGET:-16384}"
exec "$LLAMA_DIR/build/bin/llama-server" -m "$MODEL" --mmproj "$MMPROJ" -ngl 99 -fa on -c "$AGENT_CTX" -np 1 --jinja --reasoning-budget "$REASONING_BUDGET" --host 127.0.0.1 --port "$PORT"
