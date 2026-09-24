# Bonsai Local Agent

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
  --test "pytest -q" \
  "Add a health endpoint, tests, and documentation"
```

State is stored by default in:

```text
<target repo>/.bonsai/agent.db
```

Add `.bonsai/` to the target repository's `.gitignore`.

You can also run without installing the console script:

```bash
python -m bonsai_local.cli --repo ~/git/my_project "your objective"
```

## How the long-horizon loop works

### 1. Planning

The planner receives the objective plus repository tree and emits 3–12 bounded tasks. Every task has a title, implementation description, and acceptance criteria. The plan is persisted before execution starts.

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

Every three completed tasks, the model creates a checkpoint that preserves decisions, interfaces, failures, and remaining work. Later calls use that checkpoint rather than replaying the entire history.

This is the central long-horizon design: **external state grows; model context stays bounded**.

## CLI

```text
bonsai-agent [options] OBJECTIVE...

--repo PATH          target repository (default: .)
--url URL            llama.cpp base URL
--model NAME         model identifier
--db PATH            SQLite state path (default: .bonsai/agent.db)
--test COMMAND       verification test command (default: pytest -q)
--max-steps N        worker iterations per task (default: 20)
--max-repairs N      verification repair rounds (default: 3)
```

For a Node project:

```bash
bonsai-agent --repo ~/git/app --test "npm test" "Implement tenant-aware project CRUD"
```

For a mixed project:

```bash
bonsai-agent --repo ~/git/app \
  --test "python -m pytest -q && npm test" \
  "Implement the feature and make all existing tests pass"
```

## Inspecting a run

```bash
sqlite3 ~/git/my_project/.bonsai/agent.db
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
bonsai-agent --repo . --test "pytest -q" \
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

This first version is intentionally small. Shell execution is not container-sandboxed. Resume-from-existing-run, dependency graphs, semantic repository retrieval, streaming reasoning capture, token/cost telemetry, automatic Git commits/worktrees, and human approval gates for destructive commands are natural next additions.

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
