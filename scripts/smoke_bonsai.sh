#!/usr/bin/env bash
set -euo pipefail
BASE="${BONSAI_BASE:-http://127.0.0.1:8091}"
curl -fsS "$BASE/v1/models" | python3 -m json.tool
curl -fsS "$BASE/v1/chat/completions" -H 'Content-Type: application/json' -d '{"model":"Ternary-Bonsai-2-27B-PQ2_0","messages":[{"role":"user","content":"Reply exactly: BONSAI_OK"}],"max_tokens":64}' | python3 -m json.tool
