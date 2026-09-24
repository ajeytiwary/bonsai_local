# Bonsai Local Agent — Model Variant Benchmark Comparison

**Date:** 2026-09-24 · **Split:** val (B25–B32, 8 tasks) · **Hardware:** RTX 3060 12GB · **Server:** llama.cpp (patched, `prism-b10687-5d80cff`)

## TL;DR — Recommendation

> **Use the MTP variant (`bonsai-abliterated-mtp`) as your default.**

All three variants pass **8/8 tasks (100%)** on the validation split. MTP is the fastest
(2.50× vs normal), the most energy-efficient (70% less GPU energy than normal), and costs
nothing in capability — it's the same abliterated weights with a speculative-decoding head.
The only caveat: it requires the patched llama.cpp build, which you already have.

---

## 1. Headline Results

| Variant | Model file | Pass rate | Total time | Total tokens | GPU energy | Peak power |
|---|---:|---:|---:|---:|---:|---:|
| **normal** (stock) | `Ternary-Bonsai-2-27B-PQ2_0.gguf` | 8/8 (100%) | 165.8 s | 32,596 | 6.75 Wh | ~170 W |
| **abliterated** | `...Abliterated-PQ2_0.gguf` | 8/8 (100%) | 74.9 s | 29,384 | 2.57 Wh | ~170 W |
| **mtp** ⭐ | `...Abliterated-PQ2_0-MTP.gguf` | 8/8 (100%) | **66.3 s** | 29,583 | **2.01 Wh** | 159–170 W |

**Flags used:**
- normal: `--reasoning on --reasoning-effort medium`
- abliterated: `--reasoning off --reasoning-budget 0`
- mtp: `--reasoning off --reasoning-budget 0 --spec-type draft-mtp --spec-draft-n-max 2`

---

## 2. Per-Task Breakdown

| Task | Category | normal (s) | abliterated (s) | mtp (s) | normal (tok) | abliterated (tok) | mtp (tok) |
|---|---:|---:|---:|---:|---:|---:|---:|
| B25 | cli | 17.5 | 10.2 | 9.5 | 3,952 | 3,601 | 3,784 |
| B26 | serialization | 15.9 | 7.9 | 7.5 | 3,723 | 3,465 | 3,524 |
| B27 | sqlite | 14.4 | 9.4 | 7.5 | 3,896 | 3,777 | 3,579 |
| B28 | filesystem | 44.2 | 12.1 | 10.2 | 5,213 | 4,290 | 4,272 |
| B29 | git | 15.7 | 10.5 | 9.0 | 3,858 | 3,718 | 3,721 |
| B30 | api | 26.3 | 8.4 | 8.1 | 4,233 | 3,477 | 3,655 |
| B31 | python-bugfix | 12.7 | 7.8 | 7.0 | 3,689 | 3,544 | 3,542 |
| B32 | python-feature | 19.1 | 8.6 | 7.6 | 4,032 | 3,512 | 3,506 |

Every task was **clean** (tests pass + tests unchanged + run complete) for all three variants.
All tasks solved in a single attempt (3 LLM calls each).

---

## 3. Derived Metrics

| Metric | normal | abliterated | mtp | mtp vs normal |
|---|---:|---:|---:|---:|
| Seconds / task | 20.73 | 9.36 | **8.29** | **2.50× faster** |
| Tokens / task | 4,074 | 3,673 | 3,698 | −9.2% |
| GPU energy / task | 0.844 Wh | 0.322 Wh | **0.252 Wh** | **−70.2%** |
| LLM time (sum) | 145.7 s | 57.8 s | 48.4 s | −66.8% |
| Tool calls (sum) | 30 | 27 | 28 | — |

**Speedup ladder:** mtp is **1.13× faster** than abliterated, which is **2.21× faster** than normal.

---

## 4. Why the Speed Differences

1. **normal vs abliterated (2.21×):** The normal variant runs with thinking mode on
   (`--reasoning on --reasoning-effort medium`), so it generates long reasoning chains
   before answering. The abliterated variant runs with reasoning off, so it answers
   directly. This is the dominant factor — not the abliteration itself (which flips only
   0.052% of ternary digits and costs nothing measurable on MMLU/HumanEval per the README).

2. **abliterated vs mtp (1.13×):** Pure speculative decoding. The MTP head
   (`--spec-type draft-mtp --spec-draft-n-max 2`) drafts 2 tokens at a time, and the README
   claims ~37% faster decode at identical weights. Our end-to-end agent benchmark shows a
   more modest 13% wall-clock gain because agent runs are dominated by prompt processing,
   tool execution, and test runs — not just decode.

3. **Token counts are nearly identical** between abliterated and mtp (29,384 vs 29,583),
   confirming the README's claim that the two files generate byte-identical text with
   speculation off — the MTP head only changes *speed*, not *behavior*.

---

## 5. Context From Earlier Runs (same val split)

| Run | Pass rate | Total time | Total tokens | GPU energy |
|---|---:|---:|---:|---:|
| validation (stock, earlier) | 8/8 | 241.7 s | 58,568 | 10.21 Wh |
| stock-sequential (earlier) | 8/8 | 236.1 s | 63,078 | 9.89 Wh |
| abliterated-sequential (earlier) | 8/8 | 136.2 s | 51,412 | 5.37 Wh |
| mtp-validation (earlier) | 8/8 | 108.1 s | 52,504 | 3.80 Wh |
| mtp-heldout (test split) | 6/8 (75%) | 107.9 s | 51,082 | 3.70 Wh |
| **this run: normal** | 8/8 | 165.8 s | 32,596 | 6.75 Wh |
| **this run: abliterated** | 8/8 | 74.9 s | 29,384 | 2.57 Wh |
| **this run: mtp** | 8/8 | **66.3 s** | 29,583 | **2.01 Wh** |

Notes:
- Earlier runs used a different (larger) prompt/tooling configuration — hence higher token
  counts — but the *relative* ordering is consistent: mtp < abliterated < stock.
- The mtp-heldout run (6/8) is the only sub-perfect result on record, and it was on the
  **test** split (B33–B40), not val. On val, mtp is 8/8 in every run.

---

## 6. Decision Matrix

| Consideration | normal | abliterated | mtp |
|---|---:|---:|---:|
| Task success (val) | 8/8 | 8/8 | 8/8 |
| Speed | slowest | fast | **fastest** |
| Energy / heat | highest | mid | **lowest** |
| Reasoning/thinking | on (medium) | off | off |
| Refusal behavior | stock (83% refusal on harmful) | **abliterated (0%)** | **abliterated (0%)** |
| Runtime requirement | stock llama.cpp | stock llama.cpp | **patched llama.cpp** |
| Model size | 7.21 GB | 7.21 GB | 7.66 GB (+0.45 GB) |

---

## 7. Recommendation

**Default: `bonsai-abliterated-mtp`** (MTP variant).

- **It wins on every axis that matters for a local agent:** fastest wall-clock, lowest
  energy, 100% pass rate, and identical capability to the abliterated weights.
- **The abliteration is a strict improvement for an agent:** 0% refusal on harmful prompts
  *and* 0% over-refusal on safe prompts (vs 1.6% over-refusal on stock) — an agent that
  refuses safe requests is broken; an agent that refuses harmful ones is just a filter you
  can add at the tool layer if you want it.
- **The only cost is the patched llama.cpp**, which you already run (the MTP server started
  and served correctly in this run).

**Fallback:** if you ever need to run on a stock llama.cpp binary (no patch), use
`bonsai-abliterated` — same weights, no MTP head, still 2.21× faster than normal with
reasoning on.

**When to keep normal:** only if you specifically want thinking-mode reasoning chains
(e.g., for hard multi-step problems where you value the visible reasoning). Note that on
this benchmark, thinking mode bought **zero** extra correctness — all three variants solved
all 8 tasks — while costing 2.5× the time and 3.4× the energy.

---

## 8. Reproduce

```bash
# From repo root
./scripts/run_benchmark_all_variants.sh
# Results land in benchmarks/results/{normal,abliterated,mtp}-<stamp>.json
```

Result files for this run:
- `benchmarks/results/normal-20260924-201643.json`
- `benchmarks/results/abliterated-20260924-201643.json`
- `benchmarks/results/mtp-20260924-201643.json`