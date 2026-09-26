# Abliteration A/B benchmark

This benchmark compares a parent llama.cpp server with a candidate abliterated server under identical prompts and decoding parameters. It records refusal transitions, empty/length-terminated outputs, throughput and wall time. Keep the existing 40-task repository benchmark as the capability-retention gate.

## Recommended Bonsai-2 setup

The candidate model card recommends thinking mode `medium`. Run two servers so the A/B can be executed without repeatedly unloading weights. On a single 12 GB GPU you generally cannot keep both 7.2 GB packs resident simultaneously; use two servers only if you have enough VRAM/system offload, otherwise run the same command twice and preserve the first result directory.

Parent:

    ./build/bin/llama-server -m /path/Ternary-Bonsai-2-27B-PQ2_0.gguf -ngl 999 -fa on -c 32768 --jinja --temp 1.0 --top-p 0.95 --top-k 20 --chat-template-kwargs '{"reasoning_effort":"medium"}' --port 8091

Candidate:

    ./build/bin/llama-server -m /path/Ternary-Bonsai-2-27B-Abliterated-PQ2_0.gguf -ngl 999 -fa on -c 32768 --jinja --temp 1.0 --top-p 0.95 --top-k 20 --chat-template-kwargs '{"reasoning_effort":"medium"}' --port 8092

Run:

    bonsai-ablation --parent-url http://127.0.0.1:8091 --candidate-url http://127.0.0.1:8092 --out ablation-results

Outputs:

- `samples.json`: full responses/reasoning and telemetry per prompt
- `samples.csv`: analysis-friendly rows
- `summary.json`: transition matrix, refusal/empty deltas and bootstrap confidence intervals
- `report.md`: compact human-readable comparison

The included prompt set is deliberately safe and tests harmless behavior, instruction following, coding, reasoning, agentic planning, termination and boundary behavior. For refusal-specific red-team research, provide a private local prompt JSON using the same schema rather than committing sensitive prompts to the repository.

## Capability-retention gate

Run the frozen coding benchmark against both models separately:

    python benchmarks/generate_fixtures.py
    bonsai-bench --split test --url http://127.0.0.1:8091 --model Ternary-Bonsai-2-27B-PQ2_0 --out parent-coding.json
    bonsai-bench --split test --url http://127.0.0.1:8092 --model Ternary-Bonsai-2-27B-Abliterated-PQ2_0 --out candidate-coding.json

Do not tune on the held-out test split. Use train/validation while changing prompts or agent parameters.

## Interpreting results

A successful candidate should show the intended behavioral transition without a meaningful increase in EMPTY/BROKEN/length-terminated generations. More importantly for bonsai_local, coding pass rate, verified tasks per GPU-hour, repair count and tool reliability should remain close to or improve over the parent. Abliteration success alone is not evidence of a better coding agent.
