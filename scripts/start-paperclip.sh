#!/usr/bin/env bash
# Start (and on first run, onboard) the Paperclip control plane.
# Paperclip must stay a control plane — never the coding shell/file harness.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ -f "$ROOT/.env" ]] && { set -a; # shellcheck disable=SC1091
  source "$ROOT/.env"; set +a; }

PAPERCLIP_CMD="${PAPERCLIP_CMD:-npx paperclipai}"
PAPERCLIP_WORKDIR="${PAPERCLIP_WORKDIR:-$HOME/.paperclip}"
HERMES_PORT="${HERMES_PORT:-8642}"
HERMES_KEY="${HERMES_KEY:-}"
# The Hermes 8642 endpoint dispatches terminal-capable agent work: refuse to
# start employees against a placeholder/short key (gateway refuses <16 chars).
if [[ ${#HERMES_KEY} -lt 16 || "$HERMES_KEY" == "bonsai-local" || "$HERMES_KEY" == "replace-with-openssl-rand-hex-32" ]]; then
  echo "ERROR: HERMES_KEY must be a strong secret (>=16 chars, not the placeholder)." >&2
  echo "Generate one:  openssl rand -hex 32   (set HERMES_KEY in .env)" >&2
  exit 1
fi

command -v npx >/dev/null 2>&1 || { echo "npx not found — install Node.js >= 20" >&2; exit 1; }

# Hermes gateway must be up for Paperclip to dispatch work.
if ! curl -fsS -m 3 "http://127.0.0.1:$HERMES_PORT/" >/dev/null 2>&1 \
   && ! curl -fsS -m 3 "http://127.0.0.1:$HERMES_PORT/health" >/dev/null 2>&1; then
  echo "WARN: Hermes gateway not responding on :$HERMES_PORT — run ./scripts/start-hermes.sh first" >&2
fi

mkdir -p "$PAPERCLIP_WORKDIR"

# Onboard once (non-interactive).
if [[ ! -f "$PAPERCLIP_WORKDIR/config.json" && ! -d "$PAPERCLIP_WORKDIR/.paperclip" ]]; then
  echo "first run: onboarding Paperclip in $PAPERCLIP_WORKDIR"
  (cd "$PAPERCLIP_WORKDIR" && $PAPERCLIP_CMD onboard --yes) || {
    echo "onboarding failed — inspect: $PAPERCLIP_CMD --help" >&2; exit 1; }
fi

echo "starting Paperclip (adapter: hermes_gateway -> http://127.0.0.1:$HERMES_PORT)"
cd "$PAPERCLIP_WORKDIR"
if $PAPERCLIP_CMD llm agent-configuration:adapter hermes_gateway >/dev/null 2>&1; then
  echo "adapter schema verified: hermes_gateway"
else
  echo "WARN: could not verify hermes_gateway adapter schema — inspect with:" >&2
  echo "  $PAPERCLIP_CMD llm agent-configuration:adapter hermes_gateway" >&2
fi
exec $PAPERCLIP_CMD run
