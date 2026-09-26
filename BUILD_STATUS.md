# BUILD STATUS — Bonsai Local Workforce

Current milestone: **M6 complete** (benchmark expansion: Tiers 1-6 fixtures + harness adapters + structured reports; 124 passed).

## Completed acceptance checks

### M6 benchmark expansion (2026-09-26)
- `python -m pytest -q` → **124 passed** (104 existing + 20 new in `tests/test_m6_benchmark.py`).
- Tier definitions (`bonsai_agent/tiers.py`): T101-T501 (tiers 1-5) + T601-T608 (tier 6 adversarial); Tier 0 (B25-B32) untouched/frozen. `benchmarks/tiers.json` written by `write_tiers_json`.
- Fixtures (`benchmarks/generate_tiers.py`, idempotent): T101 ~600-line ledger + 2 bugs; T201 pkg with 15 decoys + cross-file surcharge; T301 git history with regressing commit + REPRO.md; T401 store/model/api stubs; T501 parse/validate/summarize stubs. T201/T401 ship `conftest.py` pinning `sys.path` to the fixture dir (pytest rootdir insertion otherwise breaks `tests/` imports). Every fixture fails its baseline (asserted) and passes after the known-good fix.
- Harness adapters (`bonsai_agent/harness.py`): `run_bonsai_local` (fixture→tmp→git init unless fixture ships `.git`→baseline fails→Agent single-task verify-tests-only→verify incl hidden_check→protected intact→clean per SPEC promotion ordering); `hermes_cmd` (M2-proven direct-mode argv); `paperclip_contract` (TaskContract workspace/verification → issue title/body); `compare_reports` (clean → pass_rate → clean_exit → tests_unchanged → tokens → seconds). All 5 tier tasks go clean via ScriptedLLM (no model needed).
- Structured reports (`bonsai_agent/reporting.py`): `write_report` → `{results, clean_count, pass_rate, total_seconds, total_tokens, tiers, promotion}`.
- Tier 6 (mock-level, no LLM): 503-retry, malformed-args rejection, oversized truncation, flaky recovery, unrelated-dirt preservation, test-tampering detection, checkpoint resume, conflicting-edit rejection — all against the real M2/M4 modules.
- Fixes during development: harness `_git_init` keeps fixture `.git` (T301 history); ScriptedLLM unique tool_call ids; `quarantine_reset(root, paths)` 2-arg signature; `Editor.replace_in_file` via Editor class; read_file caps at max_chars (no truncation marker); harness `__main__` guard exists so `--help` exits 0.

### M5 repository intelligence (2026-09-26)
- `python -m pytest -q` → **104 passed** (92 existing + 12 new in `tests/test_m5_repo_index.py`).
- `bonsai_agent/repo_index.py` (M5): versioned `m5` schema at `.agent/repo-index.json`; regex symbol tables per language (Python class/def/method with `Engine.start` qualification via indent stack; JS/TS function/class/arrow; C-like fn/struct/type); overlapping chunks (`FILE path [chars a-b]` headers, 2000 chars / 200 overlap / 8 max); normalized imports + reverse index (`imported_by` handles dotted + slashed forms); `references(symbol)` word-boundary mention counts; per-file git meta (commits/change_count/author/date via `log -n5` + `rev-list --count`); BM25 (k1=1.2, b=0.75) + symbol boost + recency; query modes text|symbol|path|implementation|test|recent (implementation demotes tests ×0.25, test promotes ×8.0, recent orders by recency); `EmbeddingProvider`/`NullEmbeddings` interface (default null, injectable); incremental refresh keyed on mtime+size (second refresh returns 0/0/0); persistence round-trip preserves qualified symbols + git meta.
- Agent wiring: `Agent.repo_map()` reads the persistent index (path :: symbols :: imports) with naive-TF fallback; `start()` plans from `repo_map()`; `execute_task` refreshes incrementally and searches with mode=test when the task mentions tests else implementation.
- CLI: `--index-stats` (stats JSON), `--index-search QUERY` (top hits); `python -m bonsai_agent.cli` works via new `__main__.py`.
- Stdlib-only: no tree-sitter hard dependency (absent in env); regex fallback is the parser.

### M4 reliability (2026-09-26)
- `python -m pytest -q` → **92 passed** (66 existing + 26 new in `tests/test_m4_reliability.py`).
- Inference resilience (`bonsai_agent/resilience.py`): tuple timeouts (connect 10s, read = model timeout), bounded exponential backoff+jitter (base 0.5s, max 8s) for 429/5xx/timeout/connection errors, no-retry for deterministic malformed 4xx (400/401/403/404/422), per-attempt `X-Request-Id`, sanitized error metadata + body excerpt (secrets redacted, 500-char cap), optional health/restart hook on exhaustion. Wired into `BonsaiLLM._post` (validates transcript before send, sends tuple timeout + request-id header, raises sanitized `RuntimeError`).
- Native tool transcript validation (`bonsai_agent/transcripts.py`): roles restricted to system/user/assistant/tool, assistant `tool_calls` require unique string ids, every tool result must match a preceding call id (no orphans either direction), `truncate_transcript` keeps system+user + last N complete groups (never splits a group).
- Context budget (`bonsai_agent/context.py`): token-based `ContextBudget` (default total 65536, reserves for system/task/durable/repo/reasoning/output), `fit_to_budget` progressively keeps 8→1 recent groups + prepends DURABLE SUMMARY, `usage_of().show()` reports `context tok/bud (pct%)` pressure. `agent.execute_task` uses `fit_to_budget` instead of message-count trim.
- Streaming/live progress + observability (`bonsai_agent/progress.py`): `Progress` emits `[elapsed run= harness/model]` phase/request/tool/test/retry/context/final lines (all sanitized); `EventLog` appends sanitized JSONL to `.agent/events.jsonl` + `summary()` returns benchmark-compatible `{results, clean_count, total_tasks, pass_rate, total_seconds, total_tokens}`.
- Task-owned git (`bonsai_agent/gitwork.py`): `capture_baseline` (HEAD + porcelain dirt + branch), `changed_vs_baseline` (worktree + index + untracked), `task_owned` (minus pre-existing dirt), `commit_paths` (explicit `git add -- paths`, never blind `add -A`), `quarantine_reset` (unlinks task-owned untracked first, then reset+checkout tracked only — pre-existing user edits untouched), `create_worktree`/`remove_worktree` for isolation.
- Checkpoint/resume (`bonsai_agent/checkpoints.py`): `Checkpoint` dataclass (objective/acceptance/baseline/task-owned/completed/unresolved/diff/tests/summary/next_action/file_hashes), `write_checkpoint` hashes task-owned files to `.agent/checkpoints/run-{id}.json`, `revalidate` checks baseline commit reachable + hashes unchanged. `agent.compact()` writes file checkpoint; `agent.resume(rid)` revalidates and reports (CLI `--resume` prints report).
- Incremental repo index (`bonsai_agent/repo_index.py`): persistent `.agent/repo-index.json`, mtime-skipped refresh, BM25 (k1=1.2, b=0.75) + 2x symbol boost + recency from last-20 git log, `search` returns path/score/symbols/imports/recency/content. Primary in `execute_task`, naive TF scan kept as fallback.
- Test scopes (`bonsai_agent/testscope.py`): `protected_test_files` (test*.py/*_test.py minus .agent/.venv/node_modules/__pycache__), `snapshot_protected`/`verify_protected` (sha256, fails task on modification), `focused_tests_for` (same-dir test_* + tests/test_* fallback). `agent.verify` fails the task if protected tests were modified.
- SPEC required-tests mapping: patch exactness/ambiguity (M2), protected-test hashes ✅, task-owned staging ✅, dirty isolation/rollback ✅, persistent shell state (M2), token compaction ✅, tool transcript integrity ✅, retry/backoff + no-retry 4xx ✅, checkpoint/resume ✅, incremental repo index ✅, focused-test selection ✅, Hermes config generation (M2), Paperclip adapter + health (M3).

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
python -m pytest -q                      # M0/M1: 24 passed; M2: 55 passed; M3: 66 passed; M4: 92 passed; M5: 104 passed; M6: 124 passed
python benchmarks/generate_tiers.py      # 5 tier fixtures regenerated (T101-T501)
./scripts/bootstrap.sh                   # exit 0
./scripts/doctor.sh                      # exit 0 (20 PASS / 0 FAIL / 2 WARN)
./scripts/smoke-stack.sh                 # exit 0 (7 PASS / 0 FAIL)
bash -n scripts/*.sh                     # all syntax OK (incl. provision-paperclip.sh)
llama-server --help                      # flags validated (see M1)
./scripts/start-bonsai.sh start --profile agent   # 65536 + q4_0 KV, healthy (11012/12288 MiB)
hermes chat -q "Reply with exactly: BONSAI_OK" -Q # BONSAI_OK
curl POST :8642/v1/chat/completions      # HERMES_8642_OK (~24s)
hermes chat ... B01 fix ... --yolo       # E2E: patch -> 1 passed focused, 2 passed full
./scripts/provision-paperclip.sh         # idempotent (company exists + 3 employees exist on re-run)
paperclipai issue create/checkout/run get/issue get  # BON-2 E2E: succeeded, BONSAI_PC_OK, issue done
```

## Blockers
- None for M6. Four test-to-code mismatches during development (fixture .git clobber, duplicate tool ids, quarantine/Editor signatures, missing conftest sys.path) fixed before commit.
- Running server is on the agent profile (65536 + q4_0 KV) for Hermes work; restore the benchmark profile (16384) before benchmark runs: `./scripts/start-bonsai.sh restart --profile benchmark`.

## Next concrete step
M7 — OpenJEV decision provider per SPEC: `DecisionProvider.choose(question, choices, evidence)` returning choice/probabilities/confidence; `task_route`, `tool_route`, `risk_gate`, `test_scope`, `completion_gate`, `verify_result`; generic OpenJEV then OpenJEV-Compliance without changing the orchestration API.

### M3 Paperclip control plane (2026-09-26)
- `python -m pytest -q` → **66 passed** (55 existing + 11 new in `tests/test_m3_paperclip.py`: adapter required fields, rejects short key/bad URL/bad strategy, redact never leaks, employee payload schema, rejects bad role, templates coding/research/qa, contract requires fields, to_issue has all tokens, health result shape).
- `bash -n scripts/provision-paperclip.sh scripts/start-paperclip.sh` → syntax OK.
- `./scripts/provision-paperclip.sh` → idempotent: company `bonsai-local` reused on second run, 3 employees exist (verified by re-run).
- `./scripts/start-paperclip.sh` → added strong-key guard refusing placeholder/short `HERMES_KEY` (mirrors `start-hermes.sh`).
- Canonical payload builders: `bonsai_agent/paperclip.py` (`build_gateway_adapter()`, `build_employee_payload()`, `employee_templates()`, `TaskContract`, `paperclip_health()`, `hermes_gateway_health()`); secrets never logged (`redact_adapter()`).
- Live control plane: company `bonsai-local` (`21a5b393-...`); employees `Bonsai Coder` (engineer), `Bonsai Researcher` (researcher), `Bonsai QA` (qa) — all `hermes_gateway`, `apiBaseUrl=http://127.0.0.1:8642`, `sessionKeyStrategy=issue`, `timeoutSec=600`, apiKey as Paperclip secret reference.
- **E2E acceptance B — PASS (BON-2)**: `issue create` (assignee coder) → `issue checkout` (binds `in_progress`, creates execution run `c735c812-...`) → Hermes run `run_f97a58c4-...` → `run completed` on both sides → result `BONSAI_PC_OK` → issue `done`, recovery resolved (`restored`), coder back to `idle`. Usage 18.5K in / 7 out, `timeoutFired: false`. Correct dispatch order is create→checkout→(wake creates execution run); `agent wake` alone makes an unassigned fallback-workspace run that wanders.
- Negative evidence (BON-1): broad "report workspace + list files" smoke wandered (browser/terminal/file-listing, 570K input tokens) and hit the 600s config timeout → `timed_out dispatching`, issue `blocked`. Lesson recorded in `integrations/paperclip-hermes.md`: keep smoke tasks tiny and reply-only.
- Controlled interruption demonstrated: BON-1 Hermes run cancelled via gateway (`run.cancelled`), Paperclip run recorded `timed_out` + `recovery_needed` with retry metadata; coder session reset via `agent runtime-state:reset-session`, issue released via `issue force-release`, retry BON-2 on fresh session succeeded.
