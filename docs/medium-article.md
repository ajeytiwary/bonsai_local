# How I Turned a 16K-Context Local 27B Model Into a Long-Horizon Coding Agent

Running a capable model locally creates an interesting mismatch. The model may be fast enough to write code interactively, but a real software project lasts far longer than one context window.

On my RTX 3060, Ternary Bonsai 2 27B can be served through the PrismML llama.cpp fork. The important realization was that making the context window larger is not the same thing as giving the model durable memory.

The solution is to move project state out of the model.

## Context is RAM, not a database

A coding agent needs to remember which tasks exist, what has already passed, what failed, why an architectural choice was made, and which tests are authoritative. Replaying all of that as chat history is expensive and eventually destructive: useful context competes with stale logs and old reasoning.

Bonsai Local Agent therefore treats the model's context as a temporary working set. SQLite stores durable state. Git stores source history. The filesystem stores artifacts. Tests provide objective evidence.

The model gets only the slice needed for the current task.

## The architecture

The system uses three logical roles built on the same local model.

The **planner** decomposes a large objective into bounded tasks with acceptance criteria. The **worker** executes one task through filesystem, shell, Git and test tools. The **verifier** receives the resulting diff and test output and decides whether the evidence satisfies the task.

A failed verification becomes another bounded repair attempt rather than an invitation to generate a longer explanation.

```text
Objective -> Planner -> SQLite task queue
                         |
                         v
                      Worker
                  / file shell git \
                         |
                       Tests
                         |
                      Verifier
                     /        \
                   pass       fail
                    |           |
               checkpoint     repair
                    |
                 next task
```

This loop can continue much longer than the physical model context because completed work is represented by compact state rather than accumulated conversation.

## Why verification matters

Language models are excellent at producing plausible completion statements. That is not the same as completing software.

The runner therefore does not accept "done" as evidence. After the worker declares completion, Python runs the configured test command. The verifier sees the actual test output and Git diff. The task is marked complete only if tests exit successfully and the verifier returns PASS.

This turns tests into part of the agent's control plane.

## Checkpoints are lossy on purpose

Long-horizon systems need forgetting.

After several completed tasks, the runner asks Bonsai to compress the project state. The checkpoint preserves interfaces, architectural decisions, failures and remaining work while dropping repetitive execution chatter.

The complete history still exists in SQLite and Git. The prompt does not need it.

That distinction is important: **storage can be lossless while context is deliberately lossy**.

## Why I kept the implementation small

There are sophisticated agent frameworks available, but a local experiment benefits from transparency. The core system needs only Python, requests, SQLite, subprocess, Git, and a model endpoint.

The model communicates with the orchestrator using a constrained JSON protocol. Tool execution happens in Python. The model never directly mutates SQLite state or decides whether a test process actually succeeded.

That makes failures inspectable.

## Running it

With llama.cpp listening on localhost:8091:

```bash
git clone https://github.com/ajeytiwary/bonsai_local.git
cd bonsai_local
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest
pytest -q
```

Then point it at another repository:

```bash
bonsai-agent --repo ~/git/my_project --test "pytest -q" \
  "Implement the requested feature, add tests, and update documentation"
```

The runner creates `.bonsai/agent.db` inside the target project. That database contains the plan, task status, execution events and compact checkpoints.

## What makes this useful for long prompts

Large specifications should not be pasted into every turn. They can be converted into a task plan and acceptance criteria. Each worker call then receives only the relevant task, compact state, and evidence from recent tool calls.

The same pattern scales to large repositories: search and retrieval can select relevant files instead of injecting the entire codebase. A future version can add embeddings or lexical/AST retrieval without changing the control loop.

## Security is the uncomfortable part

A useful coding agent needs the ability to run commands, and a model-generated shell command is not inherently safe.

The current runner confines direct file tools to the configured repository root, but shell commands execute with the Python process's OS permissions. I therefore use a dedicated branch/worktree and recommend a container or disposable VM for unattended execution. Production secrets should not be available to the agent process.

The long-term design should add command policies and human approval gates for destructive or network-sensitive actions.

## What comes next

The foundation is deliberately boring: durable tasks, bounded contexts, tools, tests, verification and repair. The next valuable capabilities are resume/recovery, dependency-aware scheduling, semantic code retrieval, Git worktree isolation, streaming telemetry, approval policies and automatic commits after verified checkpoints.

The important lesson is broader than Bonsai: **long-horizon agency is mostly a systems problem, not a context-window problem**.

A finite-context local model can work on a project for hours if the surrounding software owns memory, evidence and control flow.
