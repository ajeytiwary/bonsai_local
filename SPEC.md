# Bonsai Local Workforce — Build Specification

## Mission
Build a production-usable local-first AI engineering/research workforce. Implement the system; do not merely write a plan.

Core stack:
- Bonsai 2 27B on the user's PrismML llama.cpp fork = primary reasoning/coding model.
- Hermes Agent = execution harness: native tools, patch/edit, persistent terminal, sessions/memory, streaming/progress, browser/MCP where supported.
- Paperclip = control plane: companies, goals, employees, tasks, heartbeats, approvals, audit/governance.
- OpenJEV/OpenJEV-Compliance = optional Phase-2 typed decision layer for routing, risk/test/completion/verification decisions.
- bonsai_local = integration, reliability, benchmark and adaptation layer.

## Priorities
Strict order: correctness; clean completion; recovery; external verification; repeatability; capability; usability/observability; performance; token/energy optimization. Never trade correctness for speed/power/tokens. Record efficiency metrics diagnostically.

## Existing workstation defaults
- Linux; NVIDIA RTX 3060 12 GB; about 62 GB RAM.
- PrismML llama.cpp: /home/plasmion/git/bonsai/llama.cpp
- model: /media/plasmion/Models/ternary_bonsai/Ternary-Bonsai-2-27B-PQ2_0.gguf
- mmproj: /media/plasmion/Models/ternary_bonsai/Ternary-Bonsai-2-27B-mmproj-Q8_0.gguf
- Bonsai endpoint: http://127.0.0.1:8091/v1
- Hermes gateway target: http://127.0.0.1:8642
All paths/ports/model/context values must be environment-overridable. Keep vision/mmproj.

## Target architecture
USER -> PAPERCLIP (organization/task lifecycle) -> HERMES (execution/session/tools) -> BONSAI (reason/code/research) -> patch/git/persistent shell/tests/browser.
Optional OpenJEV sits beside Bonsai as a closed-set decision provider. Paperclip must not become the coding shell/file harness.

## Reproducible runtime
Converge on these commands:
- ./scripts/bootstrap.sh
- ./scripts/doctor.sh
- ./scripts/start-bonsai.sh
- ./scripts/start-hermes.sh
- ./scripts/start-paperclip.sh
- ./scripts/smoke-stack.sh
Provide .env.example; never commit secrets. Scripts use set -euo pipefail.
doctor.sh must check Python, Node/npm/npx, NVIDIA/VRAM, llama-server, GGUF/mmproj, Hermes, Paperclip, Git, curl, ports, dependencies and running-service health, with actionable failures.
Do not silently install destructive/system-wide dependencies; prefer project-local environments.

## Bonsai server
Validate flags against the installed PrismML llama-server --help before relying on them.
Requirements: OpenAI-compatible chat completions; native Jinja/tool calling; mmproj; flash attention if supported; initially one slot; configurable GPU layers/context/reasoning; PID/log management; health; graceful stop/restart; retained stdout/stderr.
Profiles: benchmark context=16384; agent target=65536. If 65536 is unstable, clearly require/configure 32768; never silently alter context.

## Hermes
Hermes is the primary execution harness. Detect installed CLI/config version rather than assuming stale syntax.
Requirements: discover Bonsai model via /v1/models where possible; persistent terminal; patch/edit for existing files; full-file write only for new/intentional replacement; streaming/progress; sessions; working-directory control; retry/recovery; logs/traces; gateway health; direct coding smoke test.

## Paperclip
Use Paperclip above Hermes. Prefer hermes_gateway when the installed version supports it; inspect Paperclip's adapter schema with its CLI.
Create reusable coding, research and QA/verifier employee templates plus an example local company and a real Paperclip -> Hermes -> Bonsai smoke task.
Task contract: task id, objective, acceptance criteria, workspace/repo, permissions, verification/test command, result summary, final status.
Use dedicated worktree/workspace per autonomous coding task where practical.

## Editing — mandatory
Eliminate write_file-only editing.
Provide: apply_patch/unified diff; exact replace_in_file(old,new) with strict unique-match precondition unless occurrence explicitly selected; range reads; new-file creation; explicit full replacement.
Every edit reports files changed, diff/stat, precondition match and ambiguity/error. Never rewrite a large source file for a localized change.

## Persistent shell — mandatory
Session preserves cwd, activated venv and exported environment variables. Commands expose timeout, stdout/stderr, exit status and cancellation.
Acceptance sequence: cd project; source .venv/bin/activate; export FOO=bar; pytest; subsequent command must still see cwd/venv/FOO.

## Context budget — mandatory
Do not trim by message count. Budget system instructions, task/acceptance, durable summary, repo context, recent turns/tool results, reasoning reserve and output reserve.
Use model/server tokenizer if available, otherwise conservative labelled approximation.
Never split assistant tool_calls from matching tool results. Under pressure: compact old verbose outputs first; preserve objective/acceptance, unresolved errors, current diff/relevant code, tool-group integrity; write durable checkpoint. Show context usage.

## Repository retrieval/index
Replace naive TF scanning for real repos with persistent incremental index: files/types, symbols, chunks, imports/dependencies, references where feasible, git recency/change metadata, BM25 or equivalent length-normalized lexical ranking. Optional embeddings behind an interface.
Prefer tree-sitter/language parsers with safe fallback. Support symbol/text/path/implementation/test/recent-change queries. Do not full-rescan on every task.

## Git — first-class and safe
Expose status, diff, diff-vs-baseline, log, show, blame, changed files and recent commits touching path.
Lifecycle: capture baseline and pre-existing dirt; isolate worktree/branch; track task-owned files; verify; commit explicit task-owned paths only after PASS; quarantine/reset failed task changes without touching unrelated user work.
Never blind git add -A. Failed-task changes must not bleed into the next task.

## Tests
Three scopes: focused during iteration; task acceptance before success; broad regression at final checkpoint/PR/risk trigger.
Cache expensive unchanged checks safely. Hash protected benchmark/acceptance tests before and after; any protected-test modification is failure.

## Inference resilience
Implement connect/read timeouts; bounded exponential backoff+jitter for connection failures, timeout, 429 and 5xx; do not retry deterministic malformed 4xx; request ids; sanitized error metadata/body excerpt; optional health/restart hook.
Validate native tool transcripts before send: assistant calls preserved, every result matches a preceding call id, all calls get results, truncation never cuts a group, content is chat-template compatible.

## Streaming/live operation
Use streaming where supported. Show run/task id, model/harness, phase, request start/end, tool, command/edit target, test result, retry, context usage, elapsed time and final status. Do not expose hidden reasoning. Ctrl-C must not corrupt task state.

## Checkpoint/resume
Persist objective, acceptance, baseline commit, task-owned files, completed steps, unresolved failures, diff, tests, compact context summary and next action. Resume must revalidate filesystem/git state. Test recovery after CLI, Hermes and llama-server restart.

## OpenJEV — Phase 2
Do not block base Hermes/Paperclip completion.
Create DecisionProvider.choose(question, choices, evidence) returning choice, probabilities and confidence.
Initial decisions: task_route, tool_route, risk_gate, test_scope, completion_gate, verify_result.
Bonsai keeps open-ended reasoning/code/research/explanations. OpenJEV only handles closed-set decisions. Low-confidence/high-risk results escalate to Bonsai/human. Support generic OpenJEV then OpenJEV-Compliance without changing orchestration API.

## Benchmark hierarchy
Preserve B25-B32 as Tier 0 harness gate. Acceptance: 8/8 pass, 8/8 clean exits, protected tests unchanged, no task contamination. Do not tune solely to these tiny fixtures.
Tier 1 editing: 300-1000-line files, localized/multiple patches, hidden tests.
Tier 2 repo reasoning: many irrelevant files, cross-file imports, implementation/test discovery.
Tier 3 debugging/history: stack trace, reproduce, git history, focused then regression tests.
Tier 4 multi-file feature: domain/model/API/persistence/tests/config.
Tier 5 long horizon: 10-30 meaningful steps, context pressure, persistent shell, checkpoints/restart/resume.
Tier 6 adversarial: 500/503, malformed tool args, oversized output, flaky command, unrelated dirt, test-tampering attempt, interrupted session, conflicting edit.

## Harness adapters/metrics
Run identical tasks through custom bonsai_local, Hermes/Bonsai, optionally Aider/Bonsai, and Paperclip->Hermes->Bonsai.
Record clean task success, pass rate, clean exit, protected-test integrity, acceptance/regression, repairs, tool/model calls, tokens, wall/inference time, context high-water mark, server errors/retries, files/diff, optional GPU/energy.
Promotion ordering: clean task success; pass rate; clean exit/recovery; protected-test integrity; only then efficiency.

## Observability
Write structured JSONL events plus human-readable log. Include timestamp, run/task, phase/event, duration, success and safe metadata. Never log secrets. Produce summary JSON compatible with existing benchmark outputs.

## Safety boundaries
Require explicit approval/policy for deletion outside workspace, history rewrite/force push, credential access, publication/deployment, production DB mutation, privileged/system-destructive commands. Prevent path escape from workspace unless authorized.

## Required tests
Add unit/integration tests for patch exactness/ambiguity, protected-test hashes, task-owned staging, dirty isolation/rollback, persistent shell state, token compaction, tool transcript integrity, retry/backoff and no-retry malformed 4xx, checkpoint/resume, incremental repo index, focused-test selection, Hermes config generation, Paperclip adapter generation and service health.
Mock unavailable external services in CI; mark real-stack tests separately.

## End-to-end acceptance
A Direct Hermes coding: failing fixture -> inspect -> patch -> focused test -> acceptance -> clean exit -> protected tests unchanged -> only intended files changed.
B Paperclip E2E: create/assign task -> Hermes gateway receives it -> Bonsai works -> progress/result returns -> Paperclip final/audit state -> controlled interruption can resume.
C Inference failure: inject HTTP 503 -> retry -> transcript remains valid -> no duplicate destructive edit -> clean success.
D Impossible task: honest FAIL -> no PASS commit -> next task clean baseline -> unrelated files untouched.

## Developer experience
Update README with Local Workforce quickstart, architecture, install, env vars, startup/shutdown, doctor, logs/troubleshooting, Tier 0/harder benchmarks, Paperclip onboarding, Hermes direct mode and optional OpenJEV mode. Commands must be copy/pasteable.

## Implementation rules for the coding agent
Inspect before editing. Make localized patches. Add/update tests. Run focused and relevant integration tests. Inspect git diff. Commit only internally consistent milestones. Preserve working benchmark functionality. Never replace working code with placeholders/TODOs. Never claim tests ran if they did not. For upstream CLI/API mismatch inspect installed help/source and adapt, recording exact resolution.

## Milestones
M0 baseline: existing tests pass; Tier 0 remains 8/8; behavior documented.
M1 runtime: doctor/bootstrap; validated Bonsai launcher; health/log/start/stop; reproducible env.
M2 Hermes: Bonsai through Hermes; persistent shell; patch editing; progress; direct coding E2E.
M3 Paperclip: Paperclip + gateway adapter + employee templates + Paperclip->Hermes->Bonsai E2E.
M4 reliability: worktree isolation, safe staging, protected tests, test scopes, retry/recovery, checkpoints/resume, token budget.
M5 repository intelligence: persistent symbol/chunk/BM25/dependency/git index with incremental refresh.
M6 benchmark expansion: Tiers 1-6, harness adapters, structured reports.
M7 OpenJEV: DecisionProvider, local adapter, routing/gating/test/verification, calibrated escalation, optional Compliance profile.

## Definition of done
On the real workstation all must pass: doctor; Bonsai+mmproj health; Hermes->Bonsai; persistent shell; patch editing; Paperclip->Hermes->Bonsai; Tier 0 8/8 clean; failed-task isolation; injected 503 recovery; checkpoint/resume; protected tests. Then successfully run at least one Tier 1/2 real-repository task.

## Start now
Inspect Git status, tests, integrations/, scripts/, and bonsai_agent/. Implement M0 then M1 and continue through milestones without asking for confirmation unless credentials, destructive action, external authorization, or a genuine unresolved design ambiguity requires it.
Maintain BUILD_STATUS.md with current milestone, completed acceptance checks, commands/tests actually run, blockers and next concrete step.