# Paperclip / Hermes configuration

Paperclip currently ships built-in `hermes_local` and `hermes_gateway` adapters. Prefer gateway mode: Hermes stays warm and Paperclip sends heartbeat work to it.

## Hermes

Install with `python3 -m pip install --user -U hermes-agent` or in a dedicated venv.

The setup script writes `~/.hermes/.env.bonsai-local`. Merge the generated values into your active Hermes environment if your installed Hermes version does not load that filename.

Required intent:
- OpenAI-compatible base URL: `http://127.0.0.1:8091/v1`
- local dummy API key
- Bonsai model id from `GET /v1/models`
- persistent local terminal enabled
- Hermes API server enabled on port 8642

Start with `./scripts/start_hermes_gateway.sh`.

## Paperclip

Install/onboard:
`npx paperclipai onboard --yes`

Run (server on :3100):
`npx paperclipai run` (from `$PAPERCLIP_WORKDIR`)
or `./scripts/start-paperclip.sh` (checks Hermes health, verifies the
`hermes_gateway` adapter schema, refuses placeholder `HERMES_KEY`).

Provision the example company + employees (idempotent):
`./scripts/provision-paperclip.sh`

### Example company + employees (M3, verified 2026-09-26)

- Company `bonsai-local` (Paperclip stays a control plane — never the
  coding shell/file harness).
- Employees, all on the `hermes_gateway` adapter
  (`apiBaseUrl=http://127.0.0.1:8642`, `apiKey` = strong `HERMES_KEY`
  stored as a Paperclip secret reference, `sessionKeyStrategy=issue`,
  `timeoutSec=600`):
  - `Bonsai Coder` (role `engineer`) — small localized patches in a
    dedicated workspace, runs tests, returns files-changed + results.
  - `Bonsai Researcher` (role `researcher`) — evidence-backed findings
    with file paths and citations.
  - `Bonsai QA` (role `qa`) — runs acceptance/test commands, reports
    PASS/FAIL with evidence.
- Canonical payload builders: `bonsai_agent/paperclip.py`
  (`employee_templates()`, `build_gateway_adapter()`,
  `build_employee_payload()`); unit-tested in
  `tests/test_m3_paperclip.py`. The script provisions from that module,
  so CLI payloads never drift from the tested schema.

### Task contract (SPEC M3)

Every task carries: task id, objective, acceptance criteria,
workspace/repo, permissions, verification/test command, result summary,
final status. `TaskContract.to_issue()` renders this as a Paperclip
issue; checkout assigns it to an employee, and the wake creates a
Hermes run (`POST /v1/runs`, `Idempotency-Key` = Paperclip run id,
`X-Hermes-Session-Key` issue-scoped) whose SSE events stream back into
the Paperclip run log.

Dispatch a task (proven order — checkout is the binding step):
```
paperclipai issue create -C $CID --title ... --description ... --assignee-agent-id $CODER
paperclipai issue checkout <issueId> --agent-id $CODER   # binds issue (in_progress), creates execution run
paperclipai run get <runId>      # status / executionStage
paperclipai run log <runId>      # [hermes-gateway] events incl. run created: run_<id>
paperclipai issue get <id>       # final / audit state
```
Notes: `agent wake` alone (without checkout) creates an unassigned
fallback-workspace run that wanders — always checkout first. Keep smoke
tasks tiny and reply-only; a broad "explore + list files" smoke wandered
(browser/terminal/file-listing, 570K input tokens) and hit the 600s
config timeout. A minimal reply-only task completed in ~1 min
(18.5K in / 7 out, `run.completed` both sides).

Use a dedicated working directory/worktree per coding employee.

## Context

The PrismML reference Hermes demo uses very long context. On a 12 GB RTX 3060 start at 65536 for the Hermes profile and measure actual stability. Set `AGENT_CTX=32768` if memory pressure prevents stable operation. Do not trade correctness for throughput.

## OpenJEV extension

OpenJEV should be added as a decision MCP/service after the base stack is stable. Keep Bonsai responsible for open-ended reasoning/code; use OpenJEV for closed-set routing, risk gates, test-scope selection and verification confidence.
