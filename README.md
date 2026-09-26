# Bonsai Local Agent

## Local Workforce quickstart (M1–M7)

Production-usable local-first AI engineering/research workforce: Bonsai model
server → `bonsai_agent` runner → Hermes execution harness → Paperclip control
plane → optional OpenJEV decision layer. All inference stays on this
workstation (`127.0.0.1`); no cloud calls.

```text
Paperclip :3100 (control plane: company/employees/issues)
   | hermes_gateway adapter → Hermes gateway :8642 (api_server adapter)
   | provider=custom → Bonsai :8091 /v1 (llama.cpp, alias bonsai-abliterated-mtp)
   |
bonsai_agent (direct mode: planner/worker/verifier, SQLite, tools, tests)
   | optional --openjev (generic|compliance closed-set decisions)
```

### 1. Install

```bash
cp .env.example .env          # then set HERMES_KEY=$(openssl rand -hex 32)
./scripts/bootstrap.sh        # project venv, editable install, entry points, unit tests
source .venv/bin/activate
```

Requires: Python 3.10+ (3.12 for Hermes venv), Node ≥ 20 (`npx`), Git,
NVIDIA GPU + GGUF + mmproj paths in `.env`. Secrets live only in gitignored
`.env` — never commit it.

### 2. Start / stop the stack

```bash
./scripts/start-bonsai.sh start --profile benchmark   # :8091 ctx 16384 (benchmarks)
./scripts/start-bonsai.sh start --profile agent       # :8091 ctx 65536 (agent runs)
./scripts/start-bonsai.sh status
./scripts/start-bonsai.sh logs
./scripts/start-bonsai.sh stop
./scripts/start-hermes.sh                             # gateway :8642 (needs HERMES_KEY ≥ 16 chars)
./scripts/start-paperclip.sh                          # Paperclip :3100 + hermes_gateway adapter check
```

Order matters: Bonsai → Hermes → Paperclip. Restore the `benchmark` profile
before benchmark runs; the running server may be on the `agent` profile.

### 3. Doctor + smoke

```bash
./scripts/doctor.sh        # 20 checks: python/node/GPU/llama flags/GGUF/ports/health/chat/Hermes/Paperclip
./scripts/smoke-stack.sh   # unit tests → health → chat+tool round-trip → offline agent → Hermes/Paperclip
```

### 4. Run the agent (Hermes direct mode)

```bash
source .venv/bin/activate
bonsai-agent --repo ~/git/my_project --tests "pytest -q" "Add a health endpoint, tests, and docs"
python -m bonsai_agent.cli --repo ~/git/my_project --tests "pytest -q" "Fix the failing test"
# benchmark-style single task with test-backed verdict (no model verifier):
bonsai-agent --repo /tmp/fixture --tests "pytest -q" --single-task --verify-tests-only "Fix app.py"
```

Hermes direct mode (model round-trip without the agent loop):

```bash
.venv-hermes/bin/hermes chat -q "Reply with exactly: BONSAI_OK" -Q --yolo --model bonsai-abliterated-mtp
curl -fsS http://127.0.0.1:8642/health
```

### 5. Optional OpenJEV mode (M7)

Closed-set decisions only (`task_route`, `tool_route`, `risk_gate`,
`test_scope`, `completion_gate`, `verify_result`). Bonsai keeps all
open-ended reasoning/code/research. Low-confidence/high-risk escalates;
unknown questions fail closed. Same `choose()` API for both profiles.

```bash
bonsai-agent --repo ~/git/my_project --tests "pytest -q" --openjev "Implement feature X"
bonsai-agent --repo ~/git/my_project --tests "pytest -q" --openjev --openjev-profile compliance "Implement feature X"
python -m bonsai_agent.cli --index-stats
python -m bonsai_agent.cli --index-search "Engine.start"
```

Generic threshold 0.55; compliance 0.70 + forces `test_scope=both`,
escalates mutating shell (`rm`/`git push`/`commit`/`chmod`/`curl`),
blocks `complete` on dirty protected tests. Default (no flag) = heuristics
unchanged.

### 6. Paperclip onboarding (M3 control plane)

```bash
./scripts/provision-paperclip.sh   # company bonsai-local + Coder/Researcher/QA employees
```

Paperclip order per issue: create → checkout → wake (wake alone wanders).
Paperclip never edits files directly — it dispatches through Hermes → Bonsai.

### 7. Benchmarks

Tier 0 frozen (B25–B32, 8 fixtures in `benchmarks/fixtures/`):

```bash
bonsai-bench --split val --out validation.json   # expect 8/8 clean
```

Harder tiers (M6, `benchmarks/tiers.json` + `tiers_fixtures/` generated):

```bash
python benchmarks/generate_tiers.py              # materialize T101–T501 (idempotent)
python -m bonsai_agent.harness --help            # run_bonsai_local / hermes / paperclip adapters
python -m pytest tests/test_m6_benchmark.py -q
```

Tier 6 adversarial scenarios (T601–T608) run mock-level, no LLM needed.
Promotion order: clean → pass_rate → clean_exit → tests_unchanged → tokens → seconds.

### 8. Logs / troubleshooting

```bash
./scripts/start-bonsai.sh logs
sqlite3 ~/git/my_project/.agent/state.db "SELECT id,title,status,attempts FROM tasks ORDER BY id;"
tail -5 ~/git/my_project/.agent/events.jsonl
curl -fsS http://127.0.0.1:8091/v1/models
curl -fsS http://127.0.0.1:8642/health
```

| Symptom | Fix |
|---|---|
| `hermes` not on PATH | use `.venv-hermes/bin/hermes` (hermes-agent needs Python ≥ 3.11) |
| 8642 refused | `hermes gateway run` via `start-hermes.sh`; check `HERMES_KEY` ≥ 16 chars |
| 64K OOM on 12 GB GPU | agent profile uses `-ctk/-ctv q4_0` KV quant (see `start-bonsai.sh`); or set `BONSAI_CTX_AGENT=32768` explicitly |
| `ModuleNotFoundError: pkg/store` in tier fixtures | fixture `conftest.py` pins `sys.path` — regenerate via `generate_tiers.py` |
| Paperclip wake wanders | use create → checkout → wake order |
| Context pressure | `usage_of().show()` → `context tok/bud (pct%)`; checkpoints compact every 5 tasks |

### 9. Env vars (see `.env.example`)

`BONSAI_LLAMA_SERVER`, `BONSAI_MODEL`, `BONSAI_MMPROJ`, `BONSAI_HOST/PORT`,
`BONSAI_PROFILE` (benchmark|agent), `BONSAI_CTX_BENCHMARK/AGENT`,
`BONSAI_MODEL_ID`, `HERMES_PORT/KEY`, `OPENAI_BASE_URL` (local endpoint),
`PAPERCLIP_CMD/WORKDIR`, `BONSAI_CONNECT_TIMEOUT/READ_TIMEOUT/MAX_RETRIES`,
`LOG_DIR`, `STATE_DIR`. Caller-passed `BONSAI_EXTRA_ARGS` always wins over `.env`.

---

## Original design notes (M0 runtime)

A small, persistent long-horizon coding agent for **Ternary Bonsai 2** served by the PrismML/llama.cpp OpenAI-compatible API. It is designed for a single local workstation: the model reasons, while Python owns durable state, filesystem changes, shell/git execution, tests, checkpoints, and verification.

## Why this exists

A 16K context window should be treated as working memory, not project memory. Long jobs fail when the entire conversation, repository, test history, and decisions are repeatedly pushed back into the model. This runner stores the authoritative task state in SQLite and reconstructs a compact context for each bounded step.

The loop is:

```text
objective
   |
 planner -> ordered tasks -> SQLite
   |                         |
   +------> worker <---------+---- latest checkpoint
              |
       file / shell / git tools
              |
          run tests
              |
           verifier
          /        \
       PASS        FAIL
        |            |
   mark done      repair loop
        |
 checkpoint/compact
        |
     next task
```

## Requirements

- Python 3.10+
- Git
- A target Git repository to work on
- PrismML/llama.cpp server running locally
- Ternary Bonsai 2 27B (or another model exposed through the same API)

Recommended server configuration for an RTX 3060 12 GB:

```bash
./build/bin/llama-server \
  -m "/media/plasmion/Models/ternary_bonsai/Ternary-Bonsai-2-27B-PQ2_0.gguf" \
  --mmproj "/media/plasmion/Models/ternary_bonsai/Ternary-Bonsai-2-27B-mmproj-Q8_0.gguf" \
  -ngl 99 -fa on -c 16384 -np 1 \
  --image-min-tokens 1024 --reasoning-preserve \
  --host 127.0.0.1 --port 8091
```

For autonomous coding, keep the server bound to loopback unless you deliberately add authentication/network controls.

## Install

```bash
git clone https://github.com/ajeytiwary/bonsai_local.git
cd bonsai_local
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest
pytest -q
```

Check the model server separately:

```bash
curl http://127.0.0.1:8091/v1/models
```

## First run

Point the runner at a **separate target repository**. The target is where Bonsai is allowed to read/write and execute commands.

```bash
bonsai-agent \
  --repo ~/git/my_project \
  --url http://127.0.0.1:8091 \
  --model Ternary-Bonsai-2-27B-PQ2_0 \
  --tests "pytest -q" \
  "Add a health endpoint, tests, and documentation"
```

State is stored by default in:

```text
<target repo>/.agent/state.db
```

Add `.agent/` to the target repository's `.gitignore`.

You can also run without installing the console script:

```bash
python -m bonsai_local.cli --repo ~/git/my_project "your objective"
```

## How the long-horizon loop works

### 1. Planning

The planner receives the objective plus repository tree and emits up to six bounded tasks. Every task has a title, implementation description, and acceptance criteria. The plan is persisted before execution starts.

### 2. Durable SQLite state

SQLite contains runs, tasks, events, and checkpoints. Model output is never the source of truth for completion. A process crash therefore does not erase the historical execution record.

### 3. Bounded worker iterations

The worker gets only the objective, current task, compact project state/checkpoint, and recent tool results. It can request:

- `read_file`
- `write_file`
- `list_files`
- `run_command`
- `git_diff`
- `git_status`
- `run_tests`

The workspace layer prevents file paths from escaping the configured repository root.

### 4. Automatic verification

When the worker claims a task is done, the orchestrator runs the configured test command itself. A separate verifier prompt sees the task, test output, and Git diff. A task passes only when the verifier says PASS **and** the test process reports exit code 0.

### 5. Repair loops

Failed verification generates explicit repair instructions. The worker receives the failure evidence and gets a bounded repair budget. It cannot turn a red test suite into a completed task merely by saying that it succeeded.

### 6. Context compaction

Every five completed tasks, the model creates a checkpoint that preserves decisions, interfaces, failures, and remaining work. Later calls use that checkpoint rather than replaying the entire history.

This is the central long-horizon design: **external state grows; model context stays bounded**.

## CLI

```text
bonsai-agent [options] OBJECTIVE...

--repo PATH          target repository (default: .)
--url URL            llama.cpp base URL
--model NAME         model identifier
--tests COMMAND       verification test command (default: pytest -q)
--max-steps N        task attempts per run (default: 100)
--max-repairs N      verification repair rounds (default: 3)
```

For a Node project:

```bash
bonsai-agent --repo ~/git/app --tests "bun test" "Implement tenant-aware project CRUD"
```

For a mixed project:

```bash
bonsai-agent --repo ~/git/app \
  --tests "pytest -q && bun test" \
  "Implement the feature and make all existing tests pass"
```

## Inspecting a run

```bash
sqlite3 ~/git/my_project/.agent/state.db
```

Useful queries:

```sql
SELECT id, title, status, attempts FROM tasks ORDER BY id;
SELECT id, kind, created_at FROM events ORDER BY id DESC LIMIT 30;
SELECT id, created_at, summary FROM checkpoints ORDER BY id DESC LIMIT 5;
```

Also inspect the repository normally:

```bash
cd ~/git/my_project
git status
git diff
pytest -q
```

## Safety model

This is a **local coding agent with shell access**. That is powerful and intentionally not sandbox-equivalent.

Use it on a dedicated repository/worktree, review diffs, do not run it as root, and do not expose production credentials in the environment. A command requested by the model executes with the permissions of the Python process. The path guard protects file-tool paths, but shell commands can access anything the OS user can access.

For stronger isolation, run the agent in a container or disposable VM and mount only the target repository. Production credentials should not be present.

## Recommended workflow for multi-hour tasks

Start with a clean branch/worktree:

```bash
git checkout -b bonsai/feature
pytest -q
bonsai-agent --repo . --tests "pytest -q" \
  "Implement <specific objective>. Preserve compatibility and add tests."
```

While it runs, inspect SQLite events and Git changes in another terminal. For very large objectives, prefer milestones that can each be objectively tested. Keep model output budgets modest; long-horizon reliability comes from repeated bounded steps, not 8K-token monologues.

## Architecture choices

**SQLite instead of chat history:** deterministic, inspectable, crash-resistant state.

**Planner/worker/verifier separation:** reduces self-certification. The worker that made a change does not get sole authority to declare it correct.

**Tests outside the model:** test exit codes are objective evidence.

**Compact checkpoints:** old details are summarized while the repository and database preserve the complete ground truth.

**Simple JSON tool protocol:** no framework is required. The runner works against the OpenAI-compatible llama.cpp endpoint you already have.

## Current limitations

Shell execution is not container-sandboxed. The command policy is a denylist, not a security boundary. The default model planner and verifier have not passed a repeatable day-to-day reliability gate; supervise runs, review commits, and use a dedicated worktree. The eight-case validation gate uses test-backed verification rather than the default model verifier.

The runner should be treated as an engineering foundation rather than an unattended production deployment.

## Tests

```bash
pytest -q
```

The included tests cover SQLite task lifecycle, workspace reads/writes, and path traversal protection.

## License

No license has been selected yet. Add one before redistributing or accepting outside contributions.


## v0.2 — long-horizon + evolution laboratory

The canonical package is `bonsai_agent`. v0.2 adds resumability, dependency-aware tasks, lexical repo-map retrieval, command safety policy, automatic verified commits, SQLite trajectories, GPU telemetry, a 40-task benchmark and evolution helpers.

Generate fixtures and benchmark:

```bash
python benchmarks/generate_fixtures.py
bonsai-bench --split train --out train.json
bonsai-bench --split val --out val.json
```

The frozen split is 24 train / 8 validation / 8 held-out test. Never tune on test.

Resume after interruption with `bonsai-agent --repo ~/git/my_project --resume 3`; inspect with `--status 3`. Verified tasks commit automatically only after tests exit 0 and the verifier returns PASS. GPU samples go to `.agent/telemetry-<run>.csv`.

Install optimization support with `pip install -e '.[evolution]'`. Export evidence using `bonsai-evolve --export-gepa val.json --out gepa-dataset.json`. See `docs/EVOLUTION.md`.

### Validation gate

Regenerate the local fixtures after editing `benchmarks/generate_fixtures.py`, then run `bonsai-bench --split val --out validation.json` against a healthy local model server. The eight validation fixtures are single acceptance tasks. The runner calls the agent with `--single-task --verify-tests-only`; normal CLI runs still use model planning and model verification.

A benchmark case is clean only when the agent exits successfully, its run and all tasks finish, the configured tests pass, and the original benchmark test files are unchanged. Every validation fixture fails its test before the agent runs. Generated Python and pytest caches are excluded from benchmark commits. Treat 8/8 clean validation cases as the first reliability gate before performance tuning.

### Abliterated Bonsai deployment

The abliterated PQ2_0 model has a separate launcher at `scripts/run_bonsai_abliterated.sh`. Set `BONSAI_MODEL_DIR` to the directory containing `Ternary-Bonsai-2-27B-Abliterated-PQ2_0.gguf` and `LLAMA_SERVER` to the llama.cpp server binary, then run the script. It binds to `127.0.0.1:8091` by default and serves model alias `bonsai-abliterated`.

```bash
BONSAI_MODEL_DIR=/path/to/abliterated/files \
LLAMA_SERVER=/path/to/llama-server \
./scripts/run_bonsai_abliterated.sh
```

Run the stock and abliterated deployments sequentially when one GPU cannot hold both. The abliterated launcher uses the regular GGUF with thinking off. It does not enable the MTP head or speculative decoding. The MTP GGUF needs a patched runtime and has its own validation results below.

```bash
bonsai-agent --repo /path/to/project --model bonsai-abliterated --tests 'pytest -q' \
  'Implement a specific, testable change'
```

The stock and abliterated models each completed all eight validation fixtures in one sequential run on this workstation. This is a narrow coding benchmark: it uses `--single-task --verify-tests-only`, and does not validate the default model planner and verifier for longer daily work. Use a dedicated Git branch or worktree, keep the target test command explicit, and review each result and commit.

### Abliterated MTP deployment

The optional MTP launcher is `scripts/run_bonsai_abliterated_mtp.sh`. It uses the MTP GGUF, thinking off, and `--spec-type draft-mtp --spec-draft-n-max 2`. Set `BONSAI_MTP_DIR` to the directory containing the MTP GGUF and `LLAMA_SERVER` to a PrismML llama.cpp build with the Qwen3.5 MTP Hadamard inverse fix. The local checkout used for validation already includes that fix, so the supplied patch must not be applied again.

```bash
BONSAI_MTP_DIR=/path/to/mtp/files \
LLAMA_SERVER=/path/to/patched/llama-server \
./scripts/run_bonsai_abliterated_mtp.sh

bonsai-agent --repo /path/to/project --model bonsai-abliterated-mtp \
  --tests 'pytest -q' 'Implement a specific, testable change'
```

Run the regular and MTP deployments sequentially on a GPU that cannot hold both. The MTP deployment completed all eight validation fixtures in one run; longer-project reliability is assessed separately.

### Long-project reliability gate

`benchmarks/long_projects/run_gate.sh` copies this repository into a disposable workspace and asks the normal planner, worker, and model verifier to implement server model auto-discovery across the client and CLI. The acceptance baseline must fail; visible and hidden behavioral tests, source changes, unchanged tests, and completed task state are required for a clean result. Set `MODEL_ALIAS` to test another deployment and `RESULT_PATH` to retain its report.

```bash
MODEL_ALIAS=bonsai-abliterated-mtp ./benchmarks/long_projects/run_gate.sh
```

The MTP deployment produced one clean end-to-end long-project run on 2026-09-24, recorded in `benchmarks/results/long-project-gate.json`. Earlier exploratory runs failed when the worker exhausted its tool calls or the test harness imported the wrong project copy. One clean run is useful evidence, but repeatable reliability for unfamiliar day-to-day projects remains unproven; run this gate repeatedly and supervise real work before relying on unattended edits.

### Large worker edits and safe file writes

Worker and repair calls default to 8192 output tokens. Use `--worker-output-tokens 12288` for a task that needs larger whole-file writes, while keeping the server context large enough for both the prompt and the response (`CONTEXT` in the launcher defaults to 16384). Raising this limit does not improve the model's coding judgment; it only gives a valid tool call room to finish.

The client rejects malformed tool arguments and any tool call whose response ended because it hit `max_tokens`. `write_file` also rejects empty or whitespace-only content and replaces files atomically, preserving existing permissions. These guards protect direct `write_file` calls; commands run through `run_command` still need review because shell redirection can write files independently.
