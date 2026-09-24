#!/usr/bin/env bash
set -euo pipefail
ENVFILE="${HERMES_ENV:-$HOME/.hermes/.env.bonsai-local}"
if [[ -f "$ENVFILE" ]]; then set -a; source "$ENVFILE"; set +a; fi
exec hermes gateway
