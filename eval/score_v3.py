"""Score a v3 answers file (claude -p runner output) against eval_pulp_v3.jsonl, by layer/type.
Same normalization as modal_dapt.py::_norm (mc letter extraction, word, hex, bits, int)."""
import argparse
import json
import re
from collections import defaultdict


def norm(kind, s):
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


def ok_for(q, raw):
    r, g = norm(q["kind"], raw), norm(q["kind"], q["a"])
    if q["kind"] == "bits" and ":" not in g and ":" in r:
        hi, lo = r.split(":")
        r = hi if hi == lo else r
    return r == g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default="eval_pulp_v3.jsonl")
    ap.add_argument("--answers", required=True)
    ap.add_argument("--raw-key", default="raw")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    qs = {json.loads(l)["id"]: json.loads(l) for l in open(a.questions)}
    ans = [json.loads(l) for l in open(a.answers)]
    by = defaultdict(lambda: [0, 0])
    tot = [0, 0]
    unk = 0
    for x in ans:
        q = qs[x["id"]]
        ok = ok_for(q, x[a.raw_key])
        unk += x[a.raw_key].strip().upper().startswith("UNKNOWN")
        for k in (q["layer"], q["layer"] + "/" + q["type"]):
            by[k][0] += ok
            by[k][1] += 1
        tot[0] += ok
        tot[1] += 1
    print(f"{a.answers}: {tot[0]}/{tot[1]} = {tot[0]/tot[1]:.1%}  (UNKNOWN {unk})")
    for k in sorted(by):
        c, n = by[k]
        print(f"  {k:<24}{c}/{n}  {c/n:.0%}")
    if a.out:
        json.dump({"total": f"{tot[0]}/{tot[1]}", "acc": tot[0] / tot[1],
                   **{k: f"{c}/{n}" for k, (c, n) in by.items()}}, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
