#!/usr/bin/env bash
set -euo pipefail
BONSAI_URL="${BONSAI_URL:-http://127.0.0.1:8091/v1}"
HERMES_PORT="${HERMES_PORT:-8642}"
HERMES_KEY="${HERMES_KEY:-bonsai-local}"
python3 -m pip install --user -U hermes-agent
command -v node >/dev/null || { echo "Node.js is required for Paperclip"; exit 1; }
mkdir -p "$HOME/.hermes"
cat > "$HOME/.hermes/.env.bonsai-local" <<EOF
OPENAI_API_KEY=local
OPENAI_BASE_URL=$BONSAI_URL
API_SERVER_ENABLED=true
API_SERVER_KEY=$HERMES_KEY
API_SERVER_PORT=$HERMES_PORT
TERMINAL_LOCAL_PERSISTENT=true
EOF
echo "Hermes local env written to ~/.hermes/.env.bonsai-local"
echo "Paperclip onboarding:"
echo "  npx paperclipai onboard --yes"
echo "Then inspect Hermes adapter schema:"
echo "  npx paperclipai llm agent-configuration:adapter hermes_gateway"
