#!/usr/bin/env bash
# Bootstrap a project-local environment for the Bonsai local workforce.
# Idempotent. Never installs system-wide packages without explicit opt-in.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

log()  { printf '[bootstrap] %s\n' "$*"; }
fail() { printf '[bootstrap] FAIL: %s\n' "$*" >&2; exit 1; }

# Load .env when present (never commit secrets).
[[ -f "$ROOT/.env" ]] && { set -a; # shellcheck disable=SC1091
  source "$ROOT/.env"; set +a; log "loaded .env"; }

PYTHON="${PYTHON:-python3}"
command -v "$PYTHON" >/dev/null 2>&1 || fail "python3 not found (install Python >= 3.10)"
"$PYTHON" - <<'EOF' || fail "Python >= 3.10 required"
import sys
sys.exit(0 if sys.version_info >= (3, 10) else 1)
EOF
log "python: $("$PYTHON" --version 2>&1) ($(command -v "$PYTHON"))"

# Git is mandatory (worktree isolation, baselines, protected tests).
command -v git >/dev/null 2>&1 || fail "git not found"
log "git: $(git --version)"

# Node toolchain is required only for Paperclip; warn, do not fail.
for tool in node npm npx; do
  if command -v "$tool" >/dev/null 2>&1; then
    log "$tool: $("$tool" --version 2>/dev/null | head -1)"
  else
    log "WARN: $tool missing — Paperclip (scripts/start-paperclip.sh) will not work"
  fi
done

# Project-local venv (never modifies system site-packages).
if [[ ! -d "$ROOT/.venv" ]]; then
  log "creating .venv"
  "$PYTHON" -m venv "$ROOT/.venv"
fi
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
log "venv: python $(python --version 2>&1) at $ROOT/.venv"

# Some venvs are created without pip (e.g. --without-pip or distro quirks).
if ! python -m pip --version >/dev/null 2>&1; then
  log "venv has no pip — bootstrapping via ensurepip"
  python -m ensurepip --upgrade >/dev/null 2>&1 || python "$ROOT/.venv/lib/"*/site-packages/../../bin/ensurepip 2>/dev/null || true
  python -m pip --version >/dev/null 2>&1 || fail "pip unavailable in venv — recreate with: rm -rf .venv && ./scripts/bootstrap.sh"
fi

log "installing package (editable) + dev deps"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -e ".[dev]"
python -m pip install --quiet pytest

log "verifying entry points"
command -v bonsai-agent >/dev/null 2>&1 || fail "bonsai-agent console script missing after install"
command -v bonsai-bench >/dev/null 2>&1 || fail "bonsai-bench console script missing after install"

# Optional: Hermes harness (execution layer). Opt-in via INSTALL_HERMES=1 because
# it is an external package with its own upgrade cadence.
# Resolution (recorded): hermes-agent requires Python >= 3.11 but the project
# venv may be 3.10 (package floor). Hermes therefore gets its own interpreter
# at .venv-hermes (project-local, never system-wide): created from python3 when
# the venv interpreter is < 3.11, otherwise reused from .venv.
if [[ "${INSTALL_HERMES:-0}" == "1" ]]; then
  log "installing hermes-agent (INSTALL_HERMES=1)"
  HERMES_VENV="$ROOT/.venv-hermes"
  VENV_PY_MAJOR="$(python -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
  HERMES_NEEDS_OWN_VENV=0
  VENV_PY_MINOR="${VENV_PY_MAJOR#*.}"
  [[ "$VENV_PY_MAJOR" == "3" && "$VENV_PY_MINOR" -lt 11 ]] && HERMES_NEEDS_OWN_VENV=1

  if [[ "$HERMES_NEEDS_OWN_VENV" == "1" ]]; then
    log "venv python is $VENV_PY_MAJOR (< 3.11, hermes-agent needs >= 3.11) — using $HERMES_VENV"
    HERMES_PY="$PYTHON"
    "$HERMES_PY" - <<'EOF' || HERMES_PY=""
import sys
sys.exit(0 if sys.version_info >= (3, 11) else 1)
EOF
    [[ -z "$HERMES_PY" ]] && fail "no Python >= 3.11 available for hermes-agent (install python3.11+)"
    [[ -d "$HERMES_VENV" ]] || { log "creating .venv-hermes"; "$HERMES_PY" -m venv "$HERMES_VENV"; }
    # shellcheck disable=SC1091
    source "$HERMES_VENV/bin/activate"
    python -m pip install --quiet --upgrade pip
    python -m pip install --quiet -U hermes-agent
    HERMES_BIN="$HERMES_VENV/bin/hermes"
    deactivate 2>/dev/null || true
    # Restore the project venv for the rest of the script.
    # shellcheck disable=SC1091
    source "$ROOT/.venv/bin/activate"
  else
    python -m pip install --quiet -U hermes-agent
    HERMES_BIN="$(command -v hermes || true)"
  fi

  if [[ -n "${HERMES_BIN:-}" && -x "$HERMES_BIN" ]]; then
    log "hermes: $("$HERMES_BIN" --version 2>/dev/null | head -1) at $HERMES_BIN"
  else
    log "WARN: hermes console script not found after install"
  fi
else
  log "skipping hermes-agent install (set INSTALL_HERMES=1 to install)"
fi

log "running unit tests"
python -m pytest -q

log "OK — environment ready. Next: ./scripts/doctor.sh"
