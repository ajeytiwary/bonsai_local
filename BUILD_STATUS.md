# BUILD STATUS — Bonsai Local Workforce

Current milestone: **M2 complete** (persistent shell + patch editing + Hermes E2E).

## Completed acceptance checks

### M0 baseline (2026-09-25)
- `python -m pytest -q` → **24 passed** (before and after M1 changes).
- Tier 0 gate (B25–B32) last recorded run: `benchmarks/results/validation-20260924.json` → **8/8 clean**, pass_rate 1.0.
- Behavior documented in README (unchanged runner semantics).

### M1 runtime (2026-09-25)
- `./scripts/bootstrap.sh` → exit 0; project-local venv, editable install, ensurepip fallback for pip-less venvs, entry points verified, unit tests pass.
- `./scripts/doctor.sh` → **20 PASS / 0 FAIL / 2 WARN** (WARN: hermes CLI not installed, gateway not running — both actionable). Checks Python, Node/npm/npx, NVIDIA/VRAM, llama-server + required flags vs installed `--help`, GGUF/mmproj, ports 8091/8642, live `/health`, `/v1/models`, chat round-trip, Hermes, Paperclip, duplicate processes.
- `./scripts/start-bonsai.sh` → start/stop/restart/status/logs with PID file + retained logs; profiles `benchmark` (ctx 16384) and `agent` (ctx 65536 default, explicit override only — never silently altered); flags validated against installed `llama-server --help` (`--ctx-size`, `-fa`, `--mmproj`, `--jinja`, `-ngl`, `--alias`, `--image-min-tokens`, `--host`, `--port`, `--parallel` all present).
- `./scripts/start-hermes.sh` → detects hermes CLI presence + gateway subcommand, discovers model via `/v1/models`, writes env file (no secrets).
- `./scripts/start-paperclip.sh` → onboards once, verifies `hermes_gateway` adapter schema via CLI, refuses to guess.
- `./scripts/smoke-stack.sh` → **7 PASS / 0 FAIL**: unit tests, health, models, chat, native tool-call round-trip, agent offline wiring (mock LLM), Paperclip presence; Hermes skipped until installed.
- `.env.example` committed; `.env` gitignored.

### M2 Hermes + editing layer (2026-09-26)
- `python -m pytest -q` → **55 passed** (24 existing + 31 new in `tests/test_m2_editing_shell.py`).
- `./scripts/smoke-stack.sh` → **7 PASS / 0 FAIL** (unit step now runs 55 tests).
- Persistent shell (`bonsai_agent/shell.py`): `bash --noprofile --norc` + `start_new_session` + `set -m`; SIGTERM-to-pgid cancel; sentinel `<<<BONSAI_DONE:token:rc=N:cwd=...>>>`; exit-shadowed so `exit N` can't kill the session; cwd/env/venv persist across calls; timeout survives; truncation keeps last 200k chars.
- Patch editing (`bonsai_agent/editing.py`): `replace_in_file` (unique-match precondition, AmbiguityError with line numbers, occurrence selector), `apply_patch` (unified-diff verify-then-write, atomic, rejects deletions/no-ops), `read_range` (numbered lines), `create_file` (new-only). Wired into `tools.py`/`llm.py`/`agent.py` (EDIT_TOOLS repair loop).
- **8642 resolution (recorded)**: the 8642 API server is the gateway's `api_server` platform adapter (`gateway/platforms/api_server.py`, DEFAULT_PORT=8642), enabled by `API_SERVER_ENABLED`/`API_SERVER_KEY` env vars (`gateway/config.py`); it is NOT `hermes serve` (9119 JSON-RPC). Started via `hermes gateway run`. Key must be ≥16 chars (gateway refuses placeholders — terminal-capable endpoint).
- **hermes-install resolution (recorded)**: hermes-agent needs Python ≥3.11; project venv is 3.10 → project-local `.venv-hermes` (Python 3.12.3, hermes-agent 0.19.0), codified in `bootstrap.sh` INSTALL_HERMES block.
- **64K context-gate resolution (recorded)**: Hermes hard-requires ≥64000 context; benchmark profile serves 16384. f16 KV at 65536 OOMs on the 12 GB GPU (4 GiB KV + weights + mmproj). Agent profile 65536 + `-ctk/-ctv q4_0` fits (11012/12288 MiB) and is healthy. `start-bonsai.sh` now applies profile-scoped `BONSAI_KV_CACHE_AGENT=q4_0` (overridable), preserves caller-passed `BONSAI_EXTRA_ARGS` over `.env`, and logs the KV choice. Context is never silently altered — profile choice is explicit.
- `hermes chat -q "Reply with exactly: BONSAI_OK" -Q` → **BONSAI_OK** (round-trip through 8091).
- 8642 E2E: `POST /v1/chat/completions` → **HERMES_8642_OK** (~24s, 13.6K prompt tokens).
- **Direct Hermes coding E2E (SPEC acceptance A)**: failing B01 fixture in a temp git repo → Hermes inspected, patched `max(hi,x)`→`min(hi,x)`, ran focused test → `test_app.py` 1 passed, full suite 2 passed, protected-test hashes unchanged, `git diff --stat` shows only `app.py` (1 insertion, 1 deletion). Clean exit rc=0.

## Commands actually run
```
python -m pytest -q                      # M0/M1: 24 passed; M2: 55 passed
./scripts/bootstrap.sh                   # exit 0
./scripts/doctor.sh                      # exit 0 (20 PASS / 0 FAIL / 2 WARN)
./scripts/smoke-stack.sh                 # exit 0 (7 PASS / 0 FAIL)
bash -n scripts/*.sh                     # all six syntax OK
llama-server --help                      # flags validated (see M1)
./scripts/start-bonsai.sh start --profile agent   # 65536 + q4_0 KV, healthy (11012/12288 MiB)
hermes chat -q "Reply with exactly: BONSAI_OK" -Q # BONSAI_OK
curl POST :8642/v1/chat/completions      # HERMES_8642_OK (~24s)
hermes chat ... B01 fix ... --yolo       # E2E: patch -> 1 passed focused, 2 passed full
```

## Blockers
- None for M2. Paperclip gateway E2E requires hermes first (M3 — now unblocked).
- Running server is on the agent profile (65536 + q4_0 KV) for Hermes work; restore the benchmark profile (16384) before benchmark runs: `./scripts/start-bonsai.sh restart --profile benchmark`.

## Next concrete step
M3 — Paperclip: employee templates (coding/research/QA-verifier), task contract, adapter inspection, real Paperclip→Hermes→Bonsai smoke task, E2E acceptance B.
