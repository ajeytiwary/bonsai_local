#!/usr/bin/env bash
# Provision the Paperclip control plane for the Bonsai local workforce (M3).
# Creates the example local company + reusable coding/research/QA-verifier
# employees wired to the Hermes gateway (hermes_gateway adapter).
# Paperclip stays a control plane — never the coding shell/file harness.
#
# Requires: Paperclip server on :3100 (`paperclipai run` in $PAPERCLIP_WORKDIR),
# Hermes gateway on $HERMES_PORT with a strong HERMES_KEY (>=16 chars).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ -f "$ROOT/.env" ]] && { set -a; # shellcheck disable=SC1091
  source "$ROOT/.env"; set +a; }

PAPERCLIP_CMD="${PAPERCLIP_CMD:-npx -y paperclipai}"
PAPERCLIP_WORKDIR="${PAPERCLIP_WORKDIR:-$HOME/.paperclip}"
HERMES_PORT="${HERMES_PORT:-8642}"
HERMES_KEY="${HERMES_KEY:-}"
COMPANY_NAME="${PAPERCLIP_COMPANY:-bonsai-local}"

if [[ ${#HERMES_KEY} -lt 16 ]]; then
  echo "ERROR: HERMES_KEY must be a strong secret (>=16 chars). Set it in .env." >&2
  exit 1
fi
if ! curl -fsS -m 3 "http://127.0.0.1:$HERMES_PORT/health" >/dev/null 2>&1; then
  echo "ERROR: Hermes gateway not healthy on :$HERMES_PORT — run ./scripts/start-hermes.sh first" >&2
  exit 1
fi
if ! curl -fsS -m 3 "http://127.0.0.1:3100/api/health" >/dev/null 2>&1; then
  echo "ERROR: Paperclip server not healthy on :3100 — run ./scripts/start-paperclip.sh first" >&2
  exit 1
fi

# Adapter schema check (SPEC: inspect with its CLI).
(cd "$PAPERCLIP_WORKDIR" && $PAPERCLIP_CMD llm agent-configuration:adapter hermes_gateway >/dev/null) \
  || { echo "ERROR: hermes_gateway adapter schema not available" >&2; exit 1; }
echo "adapter schema verified: hermes_gateway"

# Company: reuse if it already exists.
CID="$((cd "$PAPERCLIP_WORKDIR" && $PAPERCLIP_CMD company list --json 2>/dev/null) \
  | python3 -c "
import json,sys,os
try:
    rows = json.load(sys.stdin)
except Exception:
    rows = []
want = os.environ.get('COMPANY_NAME', 'bonsai-local')
for c in rows if isinstance(rows, list) else []:
    if c.get('name') == want:
        print(c.get('id')); break
")"
export COMPANY_NAME
if [[ -z "$CID" ]]; then
  CID="$(cd "$PAPERCLIP_WORKDIR" && $PAPERCLIP_CMD company create \
    --payload-json "{\"name\":\"$COMPANY_NAME\",\"description\":\"Local-first AI engineering workforce: Paperclip control plane, Hermes gateway, Bonsai model\"}" \
    --json 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))")"
  echo "company created: $COMPANY_NAME ($CID)"
else
  echo "company exists: $COMPANY_NAME ($CID)"
fi

# Employees from the canonical templates in bonsai_agent/paperclip.py
# (single source of truth; payloads match POST /api/companies/{id}/agents).
export CID HERMES_PORT HERMES_KEY PAPERCLIP_WORKDIR PAPERCLIP_CMD
python3 - "$CID" <<'EOF'
import json, os, subprocess, sys
sys.path.insert(0, os.environ.get("ROOT", "."))
from bonsai_agent.paperclip import employee_templates, redact_adapter

cid, port, key = sys.argv[1], os.environ["HERMES_PORT"], os.environ["HERMES_KEY"]
workdir, cmd = os.environ["PAPERCLIP_WORKDIR"], os.environ["PAPERCLIP_CMD"].split()
base = f"http://127.0.0.1:{port}"

existing = subprocess.run(cmd + ["agent", "list", "-C", cid, "--json"],
                          capture_output=True, text=True, cwd=workdir)
names = set()
try:
    for a in json.loads(existing.stdout):
        names.add(a.get("name"))
except Exception:
    pass

for t in employee_templates(base, key):
    if t["name"] in names:
        print(f"employee exists: {t['name']}")
        continue
    p = subprocess.run(cmd + ["agent", "create", "-C", cid,
                              "--payload-json", json.dumps(t), "--json"],
                       capture_output=True, text=True, cwd=workdir)
    try:
        d = json.loads(p.stdout)
        print(f"employee created: {d.get('name')} ({d.get('id')}) "
              f"adapter={d.get('adapterType')}")
    except Exception:
        print(f"FAILED to create {t['name']}: {(p.stdout + p.stderr)[:500]}")
        sys.exit(1)
EOF
echo "provision complete: company=$CID"
