#!/usr/bin/env bash
set -euo pipefail
source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
agent="${BONSAI_AGENT:-$source_root/.venv/bin/bonsai-agent}"
pytest="${PYTEST:-$source_root/.venv/bin/pytest}"
model="${MODEL_ALIAS:-bonsai-abliterated-mtp}"
result="${RESULT_PATH:-$source_root/benchmarks/results/long-project-gate.json}"
work="$(mktemp -d /tmp/bonsai-long-gate-XXXXXX)"
cp -a "$source_root/bonsai_agent" "$source_root/tests" "$source_root/pyproject.toml" "$work/"
cp "$source_root/benchmarks/long_projects/TASK.md" "$work/TASK.md"
cp "$source_root/benchmarks/long_projects/test_model_auto_acceptance.py" "$work/tests/"
git -C "$work" init -q
git -C "$work" add .
git -C "$work" -c user.name=Bonsai -c user.email=bonsai@local commit -qm baseline
set +e
(cd "$work" && PYTHONPATH="$work" "$pytest" -q -p no:cacheprovider tests/test_model_auto_acceptance.py) > "$work/baseline.log" 2>&1
baseline_exit=$?
set -e
if [[ "$baseline_exit" -eq 0 ]]; then
  printf 'Acceptance baseline unexpectedly passes: %s\n' "$work" >&2
  exit 1
fi
cd "$source_root"
set +e
PATH="$(dirname "$pytest"):$PATH" PYTHONDONTWRITEBYTECODE=1 timeout 1800 "$agent" \
  --repo "$work" --model "$model" --tests "PYTHONPATH=$work $pytest -q -p no:cacheprovider" \
  --max-steps 12 --compact-every 2 --no-auto-commit \
  'Implement TASK.md model discovery across the LLM client and CLI. Keep tests unchanged and satisfy the full suite.' \
  > "$work/agent.log" 2>&1
agent_exit=$?
(cd "$work" && PYTHONPATH="$work" "$pytest" -q -p no:cacheprovider) > "$work/visible.log" 2>&1
visible_exit=$?
(cd "$work" && PYTHONPATH="$work" "$pytest" -q -p no:cacheprovider "$source_root/benchmarks/long_projects/test_model_auto_hidden.py") > "$work/hidden.log" 2>&1
hidden_exit=$?
"$agent" --repo "$work" --status 1 > "$work/status.json" 2> "$work/status.err"
status_exit=$?
set -e
if cmp -s "$source_root/benchmarks/long_projects/test_model_auto_acceptance.py" "$work/tests/test_model_auto_acceptance.py" && git -C "$work" diff --quiet -- tests/test_core.py tests/test_v02.py; then tests_unchanged=true; else tests_unchanged=false; fi
if git -C "$work" diff --quiet -- bonsai_agent/llm.py bonsai_agent/cli.py; then source_changed=false; else source_changed=true; fi
if [[ "$status_exit" -eq 0 ]] && jq -e '.run.status=="complete" and (.tasks|length>0) and all(.tasks[]; .status=="done")' "$work/status.json" >/dev/null; then run_complete=true; else run_complete=false; fi
if [[ "$agent_exit" -eq 0 && "$visible_exit" -eq 0 && "$hidden_exit" -eq 0 && "$tests_unchanged" == true && "$source_changed" == true && "$run_complete" == true ]]; then clean=true; else clean=false; fi
mkdir -p "$(dirname "$result")"
jq -n --arg model "$model" --arg work "$work" --argjson baseline_exit "$baseline_exit" --argjson agent_exit "$agent_exit" --argjson visible_exit "$visible_exit" --argjson hidden_exit "$hidden_exit" --argjson tests_unchanged "$tests_unchanged" --argjson source_changed "$source_changed" --argjson run_complete "$run_complete" --argjson clean "$clean" \
  '{model:$model,workdir:$work,baseline_failed:($baseline_exit!=0),agent_exit:$agent_exit,visible_tests_pass:($visible_exit==0),hidden_tests_pass:($hidden_exit==0),tests_unchanged:$tests_unchanged,source_changed:$source_changed,run_complete:$run_complete,clean:$clean}' > "$result"
cat "$result"
[[ "$clean" == true ]]
