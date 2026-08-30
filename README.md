# Chip-Knowledge DAPT: Injecting a Hardware Platform's Knowledge into a 9B LLM

**A 9B open model, domain-adaptively pretrained for ~$20 of GPU time, answers closed-book
factual questions about the [PULP](https://pulp-platform.org/) Carfield/Cheshire SoC platform
better than Claude Opus 5: 92.8% vs 72.0%** on a 125-question layered audit benchmark —
and **81.6% vs 41.2%** (base model) on the full 1,776-question bank, of which only 125
questions were ever seen during development.

The headline is not the score — it is *what was required to get it*. Raw-corpus DAPT
(the naive recipe) produced **zero** gain on memorization questions despite the training
loss dropping from 0.80 to 0.35. Every point of improvement came from a **knowledge-rewriting
augmentation** stage whose design principles are the actual contribution of this repo.

- Model weights: **[AgentNativeResearchLab/Qwen3.5-9B-PULP-DAPT](https://huggingface.co/AgentNativeResearchLab/Qwen3.5-9B-PULP-DAPT)** (Hugging Face)
- Base model: [Qwen/Qwen3.5-9B-Base](https://huggingface.co/Qwen/Qwen3.5-9B-Base)
- Source platform: [pulp-platform/carfield](https://github.com/pulp-platform/carfield) (git submodule under `third_party/`)

---

## 1. Problem setup

Chip companies want an LLM that *knows their chip* — its register map, memory map, build
system, drivers, and issue history — none of which is in any pretraining corpus
(the [ChipNeMo](https://arxiv.org/abs/2311.00176) setting, use case 1: internal knowledge assistant).
Two questions decide whether this is feasible:

1. Can domain-adaptive pretraining (DAPT) actually inject *retrievable* knowledge into an
   open model, at small scale, on a real (not synthetic) hardware corpus?
2. Can the result beat a frontier closed model — the alternative a chip team would
   otherwise use — on that internal knowledge?

As a public, license-clean proxy for a proprietary chip we use the **PULP Carfield/Cheshire**
platform (ETH Zürich): a real, actively-developed heterogeneous RISC-V SoC whose facts are
public *but obscure enough* that frontier models know them only partially (Opus 5: 72.0%
closed-book on our benchmark), while a base 9B model knows almost nothing (43.2%, with
memorization layers near guess level: 7/40 on L1 facts).

Everything is **closed-book**: no retrieval, no context, 3-shot answer-format priming only.

## 2. What works (findings)

| # | Finding | Evidence |
|---|---------|----------|
| 1 | **Raw-corpus DAPT learns the distribution, not extractable facts.** 3 epochs on 31M tokens of RTL/docs/drivers: loss 0.80→0.35, register-offset accuracy **1/42 → 1/42**. A fact that appears in a single surface form (one `#define` line) is not QA-extractable — an empirical reproduction of [Physics of LM 3.1](https://arxiv.org/abs/2309.14316). | v1 ablation |
| 2 | **Knowledge-rewriting augmentation is the enabling step, not an optimization.** Restating each fact in many surface forms makes it extractable: +aug v2 lifted the same benchmark 24.4% → 51.3%. | v2 ablation |
| 3 | **Augmentation coverage determines the extractable scope.** A model whose augmentation covered only the 461 quizzed facts (v2) gained *only* on those layers; on uncovered layers (dependency pins 0/8, region sizes 1/8, driver↔register 4/15) it scored exactly at base level. Augment **all** facts; treat the benchmark as a sampled audit. | dapt2 on the audit set: 55.2% |
| 4 | **Diversity beats repetition.** 24 LLM-written templates × 6 repeats (v3) ≫ 6 hand templates × 8 repeats (v2): the naive-aug model recalls 4/10 sampled register offsets, the full recipe **323/333 (97%) of all offsets**. Include ~1/3 *reversed* forms ("At 0x14 sits CTRL") to dodge the reversal curse, and **whole-table narrative documents** (the full register map as prose/table/header, several traversal orders) so similar facts serve as each other's context instead of interfering. | dapt2 vs dapt3 |
| 5 | **Similar-fact interference, not exposure count, is the bottleneck.** At identical exposure, 9 distinctive base addresses were memorized 8/9 while 339 near-identical offsets managed 9/42. Countermeasure = distinctive context (finding 4). | v2 by-type |
| 6 | **Auto-generated benchmarks need auditing too.** (a) MC questions leak lexically: our first L3 questions were solvable by word overlap between description and register name (Opus scored 100% without knowledge) — fix: keep an MC question only if every distractor's lexical-overlap score ≥ the answer's (`mc_nonleaky`); RTL instance→module proved unfixable and was dropped. (b) Few-shot exemplars must cover every answer format — a shot set without a hex example made models answer offsets in decimal and depressed scores. (c) Issue number↔title recall turned out to be pure arbitrary-mapping memorization with no engineering value (every model ≤27%) and was removed from the bank. | leaky vs fixed baselines |

## 3. Data recipe

**Corpus (31.2M tokens)** — `data/crawl_pulp.py`

1. Clone all 259 non-fork repos of the `pulp-platform` GitHub org + issues/PRs of the top 60.
2. Filter: drop toolchain forks (binutils/glibc/newlib — 168M chars of noise), NN example
   repos, `tests/golden/vectors` payloads; dedupe by content hash.
3. Keep RTL (`.sv/.v`), register definitions (`.hjson`), docs (`.md/.rst`), C drivers/headers,
   build manifests (`Bender.yml`), issue threads → JSONL, one `{"text": ...}` doc per file.

**Knowledge-rewriting augmentation (3.49M tokens ≈ 10% of corpus)** — `data/gen_templates.py` + `data/gen_aug_v3.py`

1. Enumerate *every* fact from structured sources (not just quizzed ones): all ~340 register
   offsets from generated C headers, all hjson fields (bits/swaccess/desc), both memory maps,
   Bender dependency pins, RTL instantiations, driver-function↔register-macro pairs (static
   analysis), all issue number↔title pairs.
2. Generate **24 paraphrase templates per fact type** (10 types) with one LLM call each
   (~$0.30 total): datasheet prose, table rows, C comments, forum answers, quiz Q/A,
   changelogs — ≥1/3 in reversed order. Validate placeholders programmatically.
3. Emit each fact through every template; add whole-table narrative docs per register block /
   memory map / dependency list in 4 formats; pack 12 statements per document; repeat 6×
   (2-3× for issues/tables). Exact benchmark phrasings are never emitted.
4. Mix: `corpus : augmentation : wikitext replay ≈ 31.2M : 3.49M : 2.5M` (replay ≈ 8%, ChipNeMo-style).

## 4. Training recipe

`training/modal_dapt.py` (runs on [Modal](https://modal.com); adaptable to any 4-GPU node)

| Item | Value |
|---|---|
| Base model | Qwen/Qwen3.5-9B-Base (base, **not** instruct — ChipNeMo rule) |
| Method | Continued pretraining (`stage=pt`), **full-parameter**, bf16 |
| Framework | LLaMA-Factory 0.9.5 + DeepSpeed ZeRO-3 + transformers 5.6 |
| LR | 5e-6, cosine, warmup 1% (ChipNeMo-scale small LR) |
| Batch | global 16 = 4 GPUs × micro-batch 2 × grad-accum 2, packing at cutoff 4096 |
| Epochs | 2 |
| Hardware | 4×H100-80GB, **77 minutes**, ≈ $20 |

Performance notes that mattered (2.2× total speedup, measured):
- `flash-linear-attention` is **required** for Qwen3.5's gated-delta-net layers (25 → 7.4 s/it).
- ZeRO-3 + micro-batch 2 (or equivalently ZeRO-2): 7.43 → **3.41 s/it**.
- `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` to tame allocator fragmentation.
- Eval: vLLM with `enable_prefix_caching=True` (all questions share the few-shot prefix).

## 5. Evaluation setup

`eval/` — all questions are auto-generated from authoritative sources and machine-checkable
(exact match after normalization, or 4-way MC with auto-generated distractors; zero human or
LLM judging). The benchmark is **layered by the kind of knowledge an engineer actually needs**,
with an anti-lexical-leak constraint on every MC question (finding 6):

| Layer | Share | Content | Source |
|---|---|---|---|
| L1 facts | 30% | register offsets, base addresses, field bits, sw access | generated C headers, hjson, `reg_pkg.sv` |
| L2 structure | 20% | memory-map region ownership & sizes, dependency pins | memory maps, `Bender.yml` |
| L3 behavior | 25% | documentation description ↔ register/field (MC) | hjson `desc` |
| L4 cross-source | 15% | which driver function touches which register | static analysis of `sw/**/*.c` |
| L5 engineering | 6% | issue title → repository (MC) | GitHub issues |

Files: `questions_pulp_v3.jsonl` (full bank, 1,776), `eval_pulp_v3.jsonl` (stratified
125-question audit subset used for all model comparisons), `fewshot_pulp_v3.jsonl` (3 shots
covering each answer format), `score_v3.py` (scorer). Protocol: 3-shot completion, greedy,
`max_tokens=24`.

## 6. Results

**125-question layered audit subset** (closed-book; the only questions ever inspected during
development):

| Model | Total | L1 facts (40) | L2 struct (26) | L3 behav (32) | L4 cross (20) | L5 eng (7) |
|---|---|---|---|---|---|---|
| Qwen3.5-9B-Base | 43.2% | 7/40 | 4/26 | 29/32 | 11/20 | 3/7 |
| dapt2 (naive augmentation, ablation) | 55.2% | 20/40 | 4/26 | 31/32 | 9/20 | 5/7 |
| Claude Opus 5 | 72.0% | 23/40 | 18/26 | 32/32 | 11/20 | 6/7 |
| **Qwen3.5-9B-PULP-DAPT (this repo)** | **92.8%** | **40/40** | **19/26** | **32/32** | **20/20** | 5/7 |

**Full bank — all 1,776 auto-generated questions** (1,651 of them never seen during
development; frontier baseline omitted for cost):

| Model | Total | L1 (419) | L2 (53) | L3 (53) | L4 (25) | L5 (1,226) |
|---|---|---|---|---|---|---|
| Qwen3.5-9B-Base | 41.2% | 30/419 (7%) | 17/53 | 47/53 | 13/25 | 625/1226 (51%) |
| **Qwen3.5-9B-PULP-DAPT** | **81.6%** | **406/419 (97%)** | 36/53 | **53/53** | **25/25** | 930/1226 (76%) |

The full-bank run is the anti-overfitting check: L1 accuracy on the 379 never-inspected fact
questions (97%) matches the audit subset (100%), so the subset result is not sample luck.

Known limits (stated, not hidden): L3 multiple-choice is largely solvable by semantic
name-matching for strong models (all models >90%) — it does not differentiate; the DAPT
model's remaining weakness is numeric range-membership reasoning (L2 region ownership,
11/27 full-bank) — range queries need reasoning over the map, not fact recall; no
catastrophic-forgetting audit (e.g. MMLU) has been run yet. Per-model result files:
`eval/results/*_subset125.json`, `*_fullbank1776.json`.

## 7. Reproduce

```bash
git clone --recursive https://github.com/ARA-Labs/chip-knowledge-dapt
cd chip-knowledge-dapt

# 1) corpus (needs gh CLI for issues)
python data/crawl_pulp.py clone && python data/crawl_pulp.py issues --top 60 && python data/crawl_pulp.py corpus

# 2) question bank + augmentation
python data/gen_pulp_v3.py --eval-n 130
python data/gen_templates.py                      # one claude -p call per fact type (~$0.30)
python data/gen_aug_v3.py                         # -> dapt_corpus/aug3.jsonl

# 3) train on Modal (4xH100, ~77 min)
modal volume put pulp-dapt dapt_corpus/pulp_hw.jsonl /data/pulp_corpus.jsonl
modal volume put pulp-dapt dapt_corpus/aug3.jsonl  /data/aug3.jsonl
modal run training/modal_dapt.py::prepare
TRAIN_GPU=H100:4 modal run --detach training/modal_dapt.py::train --run-name dapt3 --epochs 2 --datasets pulp,replay,aug3 --zero 3 --pdbs 2

# 4) evaluate
modal run training/modal_dapt.py::evaluate --model /vol/models/dapt3 --tag dapt3 \
  --questions-b64 "$(base64 -w0 eval/eval_pulp_v3.jsonl)" --fewshot-b64 "$(base64 -w0 eval/fewshot_pulp_v3.jsonl)"
```

Total cost of the final pipeline: **≈ $55** (corpus free, templates $0.30, training ~$20,
evals ~$5, frontier baselines ~$3, config smoke tests ~$5, plus the ablation rounds that
produced findings 1-5 bring the whole project to ≈ $125).

## 8. Repo layout

```
data/       corpus crawler, fact extraction, LLM template generation, augmentation builder
training/   Modal app: DAPT training + vLLM closed-book evaluation
eval/       question bank (full + audit subset), scorer, per-model results
third_party/carfield   git submodule -> pulp-platform/carfield (the evaluated platform)
```

## Acknowledgements & license

Built on the open hardware of the [PULP platform](https://pulp-platform.org/) (ETH Zürich &
University of Bologna; SolderPad/Apache licenses) — referenced as a submodule, not copied.
Base model by Qwen. Recipe inspiration: NVIDIA ChipNeMo; extraction theory: Allen-Zhu & Li,
*Physics of Language Models 3.1*.

Code and question bank: Apache-2.0. Model weights inherit the Qwen3.5 license.
