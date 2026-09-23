# Evolution laboratory

Bonsai Local records task trajectories and objective evidence so prompts and agent parameters can be optimized rather than tuned by intuition.

The benchmark manifest contains 40 frozen definitions: 24 train, 8 validation, 8 held-out test. Populate the fixture directories locally and keep the split frozen. Run train and validation during optimization; use test only for promotion.

Commands:

    bonsai-bench --split train
    bonsai-bench --split val --out val.json
    bonsai-evolve --export-gepa val.json --out gepa-dataset.json
    pip install -e '.[evolution]'

GEPA/DSPy should evolve planner, worker and verifier instructions plus bounded knobs such as retrieval K, repair budget and compaction interval. Primary fitness is immutable-test pass rate. Secondary objectives are wall time, completion tokens, tool calls, repairs and GPU Wh. Safety violations are hard failures.

The benchmark runner copies fixtures into disposable temporary Git repositories. In a hardened deployment, benchmark tests should be mounted read-only so the agent cannot improve its score by modifying tests.
