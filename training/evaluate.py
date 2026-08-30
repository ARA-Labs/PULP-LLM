"""Closed-book few-shot evaluation of a (base-style) model on the PULP benchmark.

Usage:
  python evaluate.py --model AgentNativeResearchLab/Qwen3.5-9B-PULP-DAPT \
      --questions ../eval/eval_pulp_v3.jsonl --fewshot ../eval/fewshot_pulp_v3.jsonl \
      --out results.json

Protocol: 3-shot completion, greedy decoding, max 24 tokens; vLLM with prefix caching
(all prompts share the header + few-shot prefix). Requires: pip install vllm
"""
import argparse
import json
import re
from collections import Counter


def _norm(kind, s):
    s = (s or "").strip().strip("`'\"").split("\n")[0].strip().rstrip(".").lower()
    if kind == "mc":
        m = re.search(r"\b([abcd])\b", s.replace("(", " ").replace(")", " ")[:8])
        return m.group(1).upper() if m else s.upper()
    if kind == "word":
        return re.sub(r"[^a-z0-9._\-]", "", s.split()[0]) if s.split() else s
    if kind == "hex":
        m = re.search(r"(?:0x)?([0-9a-f_]+)h?$", s.replace(" ", ""))
        try:
            return f"0x{int(m.group(1).replace('_', ''), 16):x}" if m else s
        except Exception:
            return s
    if kind == "int":
        m = re.search(r"-?\d+", s)
        return m.group(0) if m else s
    if kind == "bits":
        s = s.replace("[", "").replace("]", "").replace(" ", "")
        m = re.search(r"(\d+):(\d+)", s)
        if m:
            return f"{m.group(1)}:{m.group(2)}"
        m = re.search(r"\d+", s)
        return m.group(0) if m else s
    return s


def correct(q, raw):
    r, g = _norm(q["kind"], raw), _norm(q["kind"], q["a"])
    if q["kind"] == "bits" and ":" not in g and ":" in r:
        hi, lo = r.split(":")
        r = hi if hi == lo else r
    return r == g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--questions", required=True)
    ap.add_argument("--fewshot", required=True)
    ap.add_argument("--out", default="results.json")
    a = ap.parse_args()
    from vllm import LLM, SamplingParams
    qs = [json.loads(l) for l in open(a.questions)]
    few = [json.loads(l) for l in open(a.fewshot)]
    shots = "".join(f"Q: {f['q']}\nA: {f['a']}\n\n" for f in few)
    header = ("The following are factual questions about the PULP hardware platform "
              "(ETH Zurich). Answer each with only the value (or the option letter for "
              "multiple-choice), on one line.\n\n")
    prompts = [header + shots + f"Q: {q['q']}\nA:" for q in qs]
    llm = LLM(model=a.model, dtype="bfloat16", max_model_len=4096,
              gpu_memory_utilization=0.9, enable_prefix_caching=True)
    outs = llm.generate(prompts, SamplingParams(temperature=0.0, max_tokens=24))
    rows, n_ok = [], 0
    by, byok = Counter(), Counter()
    for q, o in zip(qs, outs):
        raw = o.outputs[0].text
        ok = correct(q, raw)
        n_ok += ok
        key = q.get("layer", q["type"])
        by[key] += 1
        byok[key] += ok
        rows.append({"id": q["id"], "raw": raw.strip()[:80], "ok": ok})
    summary = {"model": a.model, "n": len(qs), "acc": n_ok / len(qs),
               "by_layer": {t: f"{byok[t]}/{by[t]}" for t in sorted(by)}}
    json.dump({"summary": summary, "rows": rows}, open(a.out, "w"), indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
