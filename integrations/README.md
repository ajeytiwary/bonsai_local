# Bonsai + Hermes + Paperclip

Production-oriented local stack:

Paperclip -> Hermes Agent -> PrismML llama.cpp -> Bonsai 2 27B

Paperclip owns goals, agents, heartbeats and governance. Hermes owns the execution loop, patch/file/terminal/browser/MCP tools, memory and sessions. Bonsai is the local reasoning/tool-calling model.

## Quick start

1. Start Bonsai:
   `./scripts/start_bonsai_hermes.sh`
2. Install/configure dependencies:
   `./scripts/setup_hermes_paperclip.sh`
3. Smoke-test the Bonsai OpenAI endpoint:
   `./scripts/smoke_bonsai.sh`
4. Start Hermes gateway:
   `./scripts/start_hermes_gateway.sh`
5. Start Paperclip:
   `npx paperclipai run`
6. In Paperclip create an agent using `hermes_gateway` (recommended) or `hermes_local`.

Defaults assume the user's existing PrismML llama.cpp checkout and PQ2 model paths. Override every path/port with environment variables.

## Reliability policy

Accuracy and resilience are primary. Energy/token/latency telemetry remains diagnostic only. Use isolated worktrees for autonomous coding, patch edits instead of whole-file rewrites, focused tests during iteration, full acceptance tests at completion, and never stage unrelated files.

See `integrations/paperclip-hermes.md` for configuration.
