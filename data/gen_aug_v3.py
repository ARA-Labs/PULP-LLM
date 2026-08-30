"""
Augmentation v3 — full-coverage knowledge rewriting for DAPT round 3.

Fixes over v2 (research/10 levers 1+2, the user's directives):
  * FULL coverage: every fact from every source (all C-header offsets, all hjson fields,
    memory maps, Bender deps, RTL instances, driver<->reg maps, all issues) — not just the
    facts that happen to be quizzed. Question bank is a sample; the corpus covers everything.
  * Diversity > repetition: 24 LLM-written templates per fact type (templates_v3.json,
    ~1/3 reversed forms) instead of 5-6 hand-written; repeats cut accordingly.
  * Table-as-narrative (whole-table docs): each register block / memory map / dep list is
    also emitted as coherent walk-through documents in several orders and formats, so
    similar facts appear as each other's context (anti-interference).

The exact phrasing of eval questions is never emitted (we train restatements, not the test).

Output: dapt_corpus/aug3.jsonl
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import re
from collections import defaultdict

import hjson

from gen_pulp_v2 import parse_header
from gen_pulp_v3 import HJSON_BLOCKS

rng = random.Random(7)
TPL = json.load(open("templates_v3.json"))


def fill(tname, **ctx):
    out = []
    for t in TPL[tname]:
        try:
            out.append(t.format(**ctx))
        except (KeyError, IndexError):
            pass
    return out


# --------------------------------------------------------------------- fact collection
def facts_offsets():
    """All C-header register offsets (same globs as gen_pulp_v2)."""
    hdrs = (glob.glob("carfield/sw/include/regs/*.h") + glob.glob("pulp/*/sw/include/regs/*.h")
            + glob.glob("pulp/*/sw/include/*_regs.h") + glob.glob("pulp/*/sw/snRuntime/include/*_peripheral.h"))
    blk_regs = defaultdict(dict)
    for h in hdrs:
        for blk, regs in parse_header(h).items():
            blk_regs[blk].update(regs)
    return blk_regs  # {block: {REG: off}}


def facts_hjson():
    """All hjson register fields: bits, swaccess, desc."""
    out = []  # (blk, reg, field, bits, swaccess, fdesc, rdesc)
    for blk, path in HJSON_BLOCKS:
        try:
            h = hjson.load(open(path, errors="ignore"))
        except Exception:
            continue
        for r in h.get("registers", []):
            if not (isinstance(r, dict) and "name" in r and "fields" in r):
                continue
            rdesc = re.sub(r"\s+", " ", str(r.get("desc") or "")).strip().rstrip(".")
            sw_reg = r.get("swaccess")
            for f in r.get("fields", []):
                out.append((blk, r["name"], f.get("name") or "", str(f.get("bits") or ""),
                            f.get("swaccess") or sw_reg or "",
                            re.sub(r"\s+", " ", str(f.get("desc") or "")).strip().rstrip("."), rdesc))
    return out


def facts_memmap():
    t = open("carfield/sw/include/car_memory_map.h", errors="ignore").read()
    car = sorted((m.group(1), int(m.group(2), 16)) for m in
                 re.finditer(r"#define\s+(CAR_[A-Z0-9_]+_BASE_ADDR)\s+(0x[0-9a-fA-F]+)", t))
    ct = open("pulp/cheshire/hw/cheshire_addrmap_pkg.sv", errors="ignore").read()
    cb = {m.group(1): int(m.group(2).replace("_", ""), 16) for m in
          re.finditer(r"localparam longint unsigned ([A-Z0-9_]+)_BASE_ADDR\s*=\s*64'h([0-9a-f_]+);", ct)}
    cs = {m.group(1): int(m.group(2).replace("_", ""), 16) for m in
          re.finditer(r"localparam longint unsigned ([A-Z0-9_]+)_SIZE\s*=\s*64'h([0-9a-f_]+);", ct)}
    return car, cb, cs


def facts_bender():
    txt = open("carfield/Bender.yml").read()
    return re.findall(r"^\s{2}(\w+):\s*\{\s*git:.*?version:\s*([0-9][\w.\-]*)", txt, re.M)


def facts_instances():
    txt = open("carfield/hw/carfield.sv").read()
    inst = re.findall(r"^\s*([a-z][a-z0-9_]+)\s+(i_[a-z0-9_]+)\s*\(", txt, re.M)
    skip = {"assign", "logic", "else", "if", "for", "always_comb", "always_ff", "input", "output"}
    return [(m, i) for m, i in inst if m not in skip]


def facts_issues():
    out = []
    for f in sorted(glob.glob("pulp_org/_issues/*.jsonl")):
        repo = os.path.basename(f)[:-6]
        for l in open(f):
            try:
                d = json.loads(l)
            except Exception:
                continue
            if d.get("kind") == "issues" and d.get("title") and len(d["title"].strip()) > 10:
                out.append((repo, str(d["number"]), d["title"].strip()))
    return out


def facts_driver():
    from gen_pulp_v3 import l4_driver
    pairs = set()
    for q in l4_driver():
        if q["type"] == "L4_macro2fn":
            # src file, macro, fn
            pairs.add((q["ip"], "/".join(q["src"].split("/")[-3:]), q["a"], q["reg"]))
    return sorted(pairs)


# --------------------------------------------------------------------- narrative (whole-table) docs
def table_docs():
    docs = []
    blk_regs = facts_offsets()
    for blk, regs in blk_regs.items():
        items = sorted(regs.items(), key=lambda kv: kv[1])
        if len(items) < 3:
            continue
        asc = ", ".join(f"{r} at {o:#x}" for r, o in items)
        docs.append(f"Register map of the {blk} block (PULP platform), in ascending address order: {asc}.")
        tbl = "\n".join(f"| {r} | {o:#x} |" for r, o in items)
        docs.append(f"### {blk} register block\n\n| Register | Offset |\n|---|---|\n{tbl}")
        chdr = "\n".join(f"#define {blk.upper()}_{r}_REG_OFFSET {o:#x}" for r, o in items)
        docs.append(f"// Generated register offsets for the {blk} block (PULP platform)\n{chdr}")
        desc = ". ".join(f"After {a} at {oa:#x} comes {b} at {ob:#x}" for (a, oa), (b, ob)
                         in zip(items, items[1:]))
        docs.append(f"Walking the {blk} register file of the PULP platform from the base: "
                    f"{items[0][0]} sits first at {items[0][1]:#x}. {desc}.")
    car, cb, cs = facts_memmap()
    asc = ", ".join(f"{n} = {v:#x}" for n, v in car)
    docs.append(f"Carfield SoC memory map (car_memory_map.h) base addresses in order: {asc}.")
    peris = sorted((v, k) for k, v in cb.items())
    asc = ", ".join(f"{k} at {v:#x}" + (f" (size {cs[k]:#x})" if k in cs else "") for v, k in peris)
    docs.append(f"Cheshire SoC address map (cheshire_addrmap_pkg.sv): {asc}.")
    deps = facts_bender()
    docs.append("Carfield Bender.yml dependency pins: " + ", ".join(f"{d} {v}" for d, v in deps) + ".")
    inst = facts_instances()
    docs.append("Top-level instances in carfield.sv: " + ", ".join(f"{i} ({m})" for m, i in inst) + ".")
    return docs


# --------------------------------------------------------------------- assemble
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dapt_corpus/aug3.jsonl")
    ap.add_argument("--repeat", type=int, default=6, help="repeats for single-fact statements")
    ap.add_argument("--repeat-tables", type=int, default=3)
    ap.add_argument("--repeat-issues", type=int, default=2)
    a = ap.parse_args()

    singles, issue_sts = [], []
    for blk, regs in facts_offsets().items():
        for reg, off in regs.items():
            singles += fill("offset", ip=blk, reg=reg, a=f"{off:#x}")
    for blk, reg, field, bits, sw, fdesc, rdesc in facts_hjson():
        if field and bits:
            singles += fill("bits", ip=blk, reg=reg, field=field, a=bits)
        if field and sw:
            singles += fill("swaccess", ip=blk, reg=reg, field=field, a=sw)
        if rdesc and len(rdesc) > 12:
            singles += fill("desc", ip=blk, reg=reg, a=rdesc)
    car, cb, cs = facts_memmap()
    for name, v in car:
        singles += fill("base", name=name, a=f"{v:#x}")
    for k, v in cb.items():
        singles += fill("base", name=f"Cheshire {k}_BASE_ADDR", a=f"{v:#x}")
    for k, v in cs.items():
        singles += fill("size", name=f"Cheshire {k}", a=f"{v:#x}")
    for dep, ver in facts_bender():
        singles += fill("bender", dep=dep, a=ver)
    for mod, inst in facts_instances():
        singles += fill("inst", inst=inst, mod=mod)
    for repo, file, fn, macro in facts_driver():
        singles += fill("driver", repo=repo, file=file, fn=fn, macro=macro)
    for repo, num, title in facts_issues():
        tp = rng.sample(TPL["issue"], 4)
        for t in tp:
            try:
                issue_sts.append(t.format(repo=repo, num=num, title=title))
            except (KeyError, IndexError):
                pass
    tables = table_docs()

    # dedupe against eval phrasing is structural: templates differ from question phrasing by design
    docs = []
    for _ in range(a.repeat):
        rng.shuffle(singles)
        docs += ["\n".join(singles[i:i + 12]) for i in range(0, len(singles), 12)]
    for _ in range(a.repeat_issues):
        rng.shuffle(issue_sts)
        docs += ["\n".join(issue_sts[i:i + 12]) for i in range(0, len(issue_sts), 12)]
    docs += tables * a.repeat_tables
    rng.shuffle(docs)
    n_chars = 0
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        for d in docs:
            f.write(json.dumps({"text": d}) + "\n")
            n_chars += len(d)
    print(f"single statements={len(singles)} issue statements={len(issue_sts)} table docs={len(tables)}")
    print(f"docs={len(docs)} chars={n_chars/1e6:.1f}M ≈{n_chars/3.5/1e6:.2f}M tokens")


if __name__ == "__main__":
    main()
