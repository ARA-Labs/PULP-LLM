"""
PULP question bank v2: hjson-derived questions (from probe.py, questions_pulp.jsonl) plus
C-header-derived facts (reggen sw headers: <BLK>_<REG>_REG_OFFSET / field _OFFSET+_MASK)
and absolute base addresses from carfield's car_memory_map.h.

Outputs:
  questions_pulp_v2.jsonl   full bank
  eval_pulp.jsonl           stratified eval subset (--eval-n), memory-heavy, guessables capped
  fewshot_pulp.jsonl        3 fixed few-shot examples (disjoint from eval)
"""
from __future__ import annotations

import argparse
import glob
import json
import random
import re
from collections import defaultdict

BLOCK_DIFF = {"axi_llc": "medium", "safety_soc_ctrl": "hard", "spatz_cluster_peripheral": "hard",
              "chs_xilinx": "hard", "carfield": "medium", "idma": "medium", "axi_rt": "hard",
              "axi_vga": "hard", "cheshire": "easy", "soc_ctrl": "medium", "clic": "medium"}


def parse_header(path: str):
    """Block prefix comes from the filename (axi_llc_regs.h -> AXI_LLC), not from guessing the split."""
    import os
    stem = os.path.basename(path)[:-2]
    for suf in ("_regs", "_reg", "_peripheral"):
        if stem.endswith(suf) and suf != "_peripheral":
            stem = stem[: -len(suf)]
    prefixes = {stem.upper()}
    txt = open(path, errors="ignore").read()
    # also accept the most common prefix actually present in the file
    cnt = defaultdict(int)
    for m in re.finditer(r"#define\s+([A-Z0-9_]+)_REG_OFFSET\s", txt):
        parts = m.group(1).split("_")
        for k in range(1, min(4, len(parts))):
            cnt["_".join(parts[:k])] += 1
    if cnt:
        prefixes.add(max(cnt, key=lambda k: (cnt[k], len(k))))
    blocks = defaultdict(dict)
    for pref in sorted(prefixes, key=len, reverse=True):
        for m in re.finditer(rf"#define\s+{re.escape(pref)}_([A-Z0-9_]+?)_REG_OFFSET\s+(0x[0-9a-fA-F]+|\d+)", txt):
            reg, off = m.group(1), int(m.group(2), 0)
            if reg not in blocks[pref.lower()]:
                blocks[pref.lower()][reg] = off
        if blocks.get(pref.lower()):
            break
    return blocks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hjson-questions", default="questions_pulp.jsonl")
    ap.add_argument("--eval-n", type=int, default=120)
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    qs = []

    # 1) keep hjson-derived (drop nothing; cap swaccess later at sampling)
    for l in open(a.hjson_questions):
        qs.append(json.loads(l))

    # 2) C-header register offsets (blocks beyond the 5 hjson ones)
    seen_offs = {(q.get("ip"), q.get("reg")) for q in qs if q["type"] == "T1"}
    hdrs = [p for p in glob.glob("carfield/sw/include/regs/*.h") + glob.glob("pulp/*/sw/include/regs/*.h")
            + glob.glob("pulp/*/sw/include/*_regs.h") + glob.glob("pulp/*/sw/snRuntime/include/*_peripheral.h")]
    blk_regs = defaultdict(dict)
    for h in hdrs:
        for blk, regs in parse_header(h).items():
            blk_regs[blk].update(regs)
    for blk, regs in sorted(blk_regs.items()):
        diff = BLOCK_DIFF.get(blk, "hard")
        for reg, off in sorted(regs.items()):
            if (blk, reg) in seen_offs:
                continue
            qs.append(dict(type="T1h", diff=diff, ip=blk, reg=reg, kind="hex", a=f"0x{off:x}",
                           q=f"In the PULP Carfield/Cheshire platform (ETH Zurich), what is the byte offset of the {reg} register within the {blk} register block (as defined in its generated C header, {blk.upper()}_{reg}_REG_OFFSET)?",
                           src=f"reggen C header {blk}"))

    # 3) absolute base addresses (car_memory_map.h numeric defines)
    mm = open("carfield/sw/include/car_memory_map.h", errors="ignore").read()
    for m in re.finditer(r"#define\s+(CAR_[A-Z0-9_]+_BASE_ADDR)\s+(0x[0-9a-fA-F]+)", mm):
        name, addr = m.group(1), int(m.group(2), 16)
        qs.append(dict(type="T7h", diff="medium", ip="carfield", reg=name, kind="hex", a=f"0x{addr:x}",
                       q=f"In the PULP Carfield SoC memory map (car_memory_map.h), what is the value of {name}?",
                       src="car_memory_map.h"))

    for i, q in enumerate(qs):
        q["id"] = i
    with open("questions_pulp_v2.jsonl", "w") as f:
        for q in qs:
            f.write(json.dumps(q) + "\n")

    # ---- eval subset: memory-heavy, cap guessable types
    caps = {"T4": 8, "T9": 2, "T5": 4}        # guessable / tiny types capped
    weight = {"T1": 3, "T1h": 3, "T7h": 3, "T2": 3, "T3": 2, "T6": 1, "T6n": 1}
    byt = defaultdict(list)
    for q in qs:
        byt[q["type"]].append(q)
    for t in byt:
        rng.shuffle(byt[t])
    picked = []
    for t, lst in sorted(byt.items(), key=lambda kv: -weight.get(kv[0], 1)):
        n = min(len(lst), caps.get(t, int(a.eval_n * weight.get(t, 1) / sum(weight.get(x, 1) for x in byt))))
        picked += lst[:n]
    picked = picked[: a.eval_n]
    few = [q for q in qs if q not in picked and q["type"] in ("T1h", "T7h", "T3")][:3]
    with open("eval_pulp.jsonl", "w") as f:
        for q in picked:
            f.write(json.dumps(q) + "\n")
    with open("fewshot_pulp.jsonl", "w") as f:
        for q in few:
            f.write(json.dumps(q) + "\n")
    from collections import Counter
    print("bank:", len(qs), dict(Counter(q["type"] for q in qs)))
    print("eval:", len(picked), dict(Counter(q["type"] for q in picked)))
    print("eval diff:", dict(Counter(q["diff"] for q in picked)))


if __name__ == "__main__":
    main()
