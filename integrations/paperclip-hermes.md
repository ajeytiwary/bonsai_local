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

Run:
`npx paperclipai run`

Create a Paperclip agent with adapter `hermes_gateway`, API base `http://127.0.0.1:8642`, and the same Hermes API key. If gateway configuration differs in your Paperclip version, inspect it with:
`npx paperclipai llm agent-configuration:adapter hermes_gateway`

Use a dedicated working directory/worktree per coding employee.

## Context

The PrismML reference Hermes demo uses very long context. On a 12 GB RTX 3060 start at 65536 for the Hermes profile and measure actual stability. Set `AGENT_CTX=32768` if memory pressure prevents stable operation. Do not trade correctness for throughput.

## OpenJEV extension

OpenJEV should be added as a decision MCP/service after the base stack is stable. Keep Bonsai responsible for open-ended reasoning/code; use OpenJEV for closed-set routing, risk gates, test-scope selection and verification confidence.
