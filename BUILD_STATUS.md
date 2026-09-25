# BUILD STATUS — Bonsai Local Workforce

Current milestone: **M1 complete** (M0 baseline + M1 reproducible runtime).

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

## Commands actually run
```
python -m pytest -q                      # 24 passed
./scripts/bootstrap.sh                   # exit 0
./scripts/doctor.sh                      # exit 0 (20 PASS / 0 FAIL / 2 WARN)
./scripts/smoke-stack.sh                 # exit 0 (7 PASS / 0 FAIL)
bash -n scripts/*.sh                     # all six syntax OK
llama-server --help                      # flags validated (see M1)
```

## Blockers
- hermes CLI not installed (`INSTALL_HERMES=1 ./scripts/bootstrap.sh` pending — deferred to M2 to keep milestone commits internally consistent).
- Paperclip gateway E2E requires hermes first (M3).
- Currently running server uses `bonsai-abliterated-mtp` variant (env override), not the default stock model — supported by design (`BONSAI_MODEL`/`BONSAI_MODEL_ID`).

## Next concrete step
M2 — Hermes: install hermes-agent, validate gateway against installed CLI, direct coding E2E through Hermes → Bonsai; implement mandatory editing layer (apply_patch / replace_in_file with unique-match precondition / ranged reads / explicit full replacement) and persistent shell (cwd/venv/env preservation) with tests.
