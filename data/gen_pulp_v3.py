"""
PULP question bank v3 — layered by engineer-knowledge type (answers the streetlight critique).

Layers and target eval distribution (research/10):
  L1 facts      30%  offsets/bases/bits/swaccess     <- questions_pulp_v2.jsonl (sampled)
  L2 structure  20%  Bender dep versions, memory-map region ownership, RTL instantiations
  L3 behavior   25%  hjson `desc` <-> register/field (4-way MC, distractors from same block)
  L4 cross-src  15%  driver C function <-> register offset macro (static analysis)
  L5 engineering10%  GitHub issue number<->title, issue title->repo (4-way MC)

Every question is machine-checkable: kind in {hex,int,bits,word,mc}. MC options are embedded
in the question text itself (self-contained), answer is the letter -> works unchanged for both
the claude -p runner (probe.py run --mode closed) and modal_dapt.py::evaluate.

Outputs: questions_pulp_v3.jsonl (bank), eval_pulp_v3.jsonl (--eval-n, stratified 30/20/25/15/10),
         fewshot_pulp_v3.jsonl (3 shots disjoint from eval: hex + mc + word).
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

rng = random.Random(23)

HJSON_BLOCKS = [
    ("carfield", "carfield/hw/regs/carfield_regs.hjson"),
    ("axi_llc", "pulp/axi_llc/data/axi_llc_regs.hjson"),
    ("safety_soc_ctrl", "pulp/safety_island/rtl/soc_ctrl/safety_soc_ctrl_regs.hjson"),
    ("chs_xilinx", "pulp/cheshire/target/xilinx/src/regs/chs_xilinx_regs.hjson"),
    ("spatz_cluster_peripheral", "pulp/spatz/hw/system/spatz_cluster/src/spatz_cluster_peripheral/spatz_cluster_peripheral_reg.hjson"),
]


def _toks(name):
    parts = re.split(r"[_\W]+", name.lower())
    return {p for p in parts if len(p) >= 3}


def lexscore(name: str, text: str) -> int:
    """How many name tokens are lexically recoverable from the text (prefix-3 word match)."""
    words = {w for w in re.split(r"[_\W]+", text.lower()) if len(w) >= 3}
    return sum(1 for t in _toks(name) if any(w.startswith(t[:3]) or t.startswith(w[:3]) for w in words))


def leaks(name: str, text: str) -> bool:
    return lexscore(name, text) >= 1


def mc_nonleaky(qtext: str, cue: str, answer: str, pool: list, n=4):
    """MC where lexical similarity to the cue text cannot single out the answer:
    prefer distractors whose lexscore vs the cue is >= the answer's score."""
    a_sc = lexscore(answer, cue)
    cands = [p for p in dict.fromkeys(pool) if p != answer]
    strong = [p for p in cands if lexscore(p, cue) >= a_sc]
    rng.shuffle(strong)
    if len(strong) < n - 1:
        return None
    opts = [answer] + strong[: n - 1]
    rng.shuffle(opts)
    letter = "ABCD"[opts.index(answer)]
    text = qtext + " Answer with the letter only. " + " ".join(
        f"({L}) {o}" for L, o in zip("ABCD", opts))
    return text, letter


def mc(qtext: str, answer: str, pool: list, n=4):
    """Build a self-contained 4-way MC question dict fragment; returns (text, letter)."""
    distract = [p for p in dict.fromkeys(pool) if p != answer]
    rng.shuffle(distract)
    opts = [answer] + distract[: n - 1]
    if len(opts) < n:
        return None
    rng.shuffle(opts)
    letter = "ABCD"[opts.index(answer)]
    text = qtext + " Answer with the letter only. " + " ".join(
        f"({L}) {o}" for L, o in zip("ABCD", opts))
    return text, letter


# --------------------------------------------------------------------------- L1: facts (from v2)
def l1_from_v2(path="questions_pulp_v2.jsonl"):
    qs = [json.loads(l) for l in open(path)]
    for q in qs:
        q["layer"] = "L1"
    return qs


# --------------------------------------------------------------------------- L2: structure
def l2_bender():
    out = []
    txt = open("carfield/Bender.yml").read()
    deps = re.findall(r"^\s{2}(\w+):\s*\{\s*git:.*?version:\s*([0-9][\w.\-]*)", txt, re.M)
    for name, ver in deps:
        out.append(dict(layer="L2", type="L2_bender", diff="medium", ip="carfield", reg=name,
                        kind="word", a=ver,
                        q=f"In the PULP Carfield platform's Bender.yml manifest, which version of the '{name}' dependency is pinned? Answer with the version number only.",
                        src="carfield/Bender.yml"))
    return out


def l2_memmap():
    """Region ownership + sizes, from carfield's numeric bases and cheshire_addrmap_pkg.sv."""
    out = []
    # carfield: numeric bases only; probe just above the base, distractors = neighbours
    t = open("carfield/sw/include/car_memory_map.h", errors="ignore").read()
    bases = sorted((int(m.group(2), 16), m.group(1)) for m in
                   re.finditer(r"#define\s+CAR_([A-Z0-9_]+)_BASE_ADDR\s+(0x[0-9a-fA-F]+)", t))
    for i, (b, name) in enumerate(bases):
        probe = b + 0x40
        nxt = bases[i + 1][0] if i + 1 < len(bases) else b + (1 << 30)
        # distractors must not plausibly contain the probe address (their [base, next_base) range)
        ok_names = [n for j, (bb, n) in enumerate(bases) if n != name and not
                    (bb <= probe < (bases[j + 1][0] if j + 1 < len(bases) else bb + (1 << 30)))]
        if probe >= nxt:
            continue
        m = mc(f"In the Carfield SoC memory map (car_memory_map.h), address {probe:#x} falls inside which region?",
               name, ok_names)
        if m:
            out.append(dict(layer="L2", type="L2_region", diff="medium", ip="carfield", reg=name,
                            kind="mc", a=m[1], q=m[0], src="car_memory_map.h"))
    # cheshire: BASE_ADDR + SIZE pairs from the addrmap package
    ct = open("pulp/cheshire/hw/cheshire_addrmap_pkg.sv", errors="ignore").read()
    cb = {m.group(1): int(m.group(2).replace("_", ""), 16) for m in
          re.finditer(r"localparam longint unsigned ([A-Z0-9_]+)_BASE_ADDR\s*=\s*64'h([0-9a-f_]+);", ct)}
    cs = {m.group(1): int(m.group(2).replace("_", ""), 16) for m in
          re.finditer(r"localparam longint unsigned ([A-Z0-9_]+)_SIZE\s*=\s*64'h([0-9a-f_]+);", ct)}
    peris = sorted(k for k in cb if k in cs)
    for name in peris:
        b, s = cb[name], cs[name]
        probe = b + s // 2
        ok_peris = [p for p in peris if p != name and not (cb[p] <= probe < cb[p] + cs[p])]
        m = mc(f"In the Cheshire SoC address map (cheshire_addrmap_pkg.sv, PULP platform), address {probe:#x} belongs to which peripheral/region?",
               name, ok_peris)
        if m:
            out.append(dict(layer="L2", type="L2_region", diff="medium", ip="cheshire", reg=name,
                            kind="mc", a=m[1], q=m[0], src="cheshire_addrmap_pkg.sv"))
        out.append(dict(layer="L2", type="L2_size", diff="hard", ip="cheshire", reg=name,
                        kind="hex", a=f"{s:#x}",
                        q=f"In the Cheshire SoC address map (cheshire_addrmap_pkg.sv), what is the size in bytes (hex) of the {name} region ({name}_SIZE)?",
                        src="cheshire_addrmap_pkg.sv"))
    return out


def l2_instances():
    """Single-line instantiations in carfield.sv: `module_type i_name (`."""
    txt = open("carfield/hw/carfield.sv").read()
    inst = re.findall(r"^\s*([a-z][a-z0-9_]+)\s+(i_[a-z0-9_]+)\s*\(", txt, re.M)
    skip = {"assign", "logic", "else", "if", "for", "always_comb", "always_ff", "input", "output"}
    inst = [(m, i) for m, i in inst if m not in skip and not leaks(m, i)]
    mods = sorted({m for m, _ in inst})
    out = []
    for m_, i_ in inst:
        r = mc(f"In the top-level RTL file carfield.sv of the PULP Carfield platform, the instance named '{i_}' is an instantiation of which module?",
               m_, mods)
        if r:
            out.append(dict(layer="L2", type="L2_inst", diff="medium", ip="carfield", reg=i_,
                            kind="mc", a=r[1], q=r[0], src="carfield.sv"))
    return out


# --------------------------------------------------------------------------- L3: behavior (hjson desc)
def _load_block(path):
    try:
        return hjson.load(open(path, errors="ignore"))
    except Exception:
        return None


def clean_desc(d):
    d = re.sub(r"\s+", " ", str(d or "")).strip().rstrip(".")
    return d


def l3_desc():
    out = []
    for blk, path in HJSON_BLOCKS:
        h = _load_block(path)
        if not h:
            continue
        regs = [(r["name"], r) for r in h.get("registers", [])
                if isinstance(r, dict) and "name" in r and "fields" in r]
        regnames = [n for n, _ in regs]
        # desc -> which register
        for name, r in regs:
            d = clean_desc(r.get("desc"))
            if len(d) < 18:
                continue
            m = mc_nonleaky(f"In the {blk} register block of the PULP Carfield/Cheshire platform, which register is described in the documentation as: \"{d}\"?",
                            d, name, regnames)
            if m:
                out.append(dict(layer="L3", type="L3_desc2reg", diff="medium", ip=blk, reg=name,
                                kind="mc", a=m[1], q=m[0], src=path))
        # register -> which desc (reverse direction)
        descs = [clean_desc(r.get("desc")) for _, r in regs]
        descs = [d for d in descs if len(d) >= 18]
        for name, r in regs:
            d = clean_desc(r.get("desc"))
            if len(d) < 18:
                continue
            m = mc_nonleaky(f"In the {blk} register block, what does the documentation say the {name} register does?",
                            name, d, descs)
            if m:
                out.append(dict(layer="L3", type="L3_reg2desc", diff="medium", ip=blk, reg=name,
                                kind="mc", a=m[1], q=m[0], src=path))
        # field desc -> field name (within a register with >=2 documented fields, pool = block fields)
        fieldpool = []
        fielditems = []
        for name, r in regs:
            for f in r.get("fields", []):
                fn, fd = f.get("name"), clean_desc(f.get("desc"))
                if fn and len(fd) >= 20:
                    fielditems.append((name, fn, fd))
                if fn:
                    fieldpool.append(fn)
        for regname, fn, fd in fielditems:
            m = mc_nonleaky(f"In the {blk} block's {regname} register, which field is described as: \"{fd}\"?",
                            fd, fn, fieldpool)
            if m:
                out.append(dict(layer="L3", type="L3_field", diff="hard", ip=blk, reg=regname,
                                field=fn, kind="mc", a=m[1], q=m[0], src=path))
    return out


# --------------------------------------------------------------------------- L4: driver <-> register
C_GLOBS = ["carfield/sw/tests/bare-metal/*/*.c", "carfield/sw/lib/*.c",
           "pulp/cheshire/sw/lib/**/*.c", "pulp/axi_llc/sw/lib/*.c",
           "pulp/safety_island/sw/tests/*/*.c", "pulp/cheshire/sw/tests/*.c"]
FN_RE = re.compile(r"^[A-Za-z_][\w\s\*]*?\b([a-z_]\w*)\s*\([^;{]*\)\s*\{", re.M)


def l4_driver():
    out = []
    files = []
    for g in C_GLOBS:
        files += glob.glob(g, recursive=True)
    for path in sorted(set(files)):
        txt = open(path, errors="ignore").read()
        if "_REG_OFFSET" not in txt:
            continue
        # map char position -> enclosing function
        fns = [(m.start(), m.group(1)) for m in FN_RE.finditer(txt)
               if m.group(1) not in ("if", "while", "for", "switch", "return", "sizeof")]
        if not fns:
            continue
        macro2fn = defaultdict(set)
        fn_macros = defaultdict(set)
        for m in re.finditer(r"\b([A-Z][A-Z0-9_]+_REG_OFFSET)\b", txt):
            pos = m.start()
            enclosing = None
            for s, f in fns:
                if s < pos:
                    enclosing = f
                else:
                    break
            if enclosing:
                macro2fn[m.group(1)].add(enclosing)
                fn_macros[enclosing].add(m.group(1))
        rel = path.split("knowledge_probe/")[-1]
        short = "/".join(rel.split("/")[-3:])
        repo = "carfield" if rel.startswith("carfield") else rel.split("/")[1]
        allfns = sorted(fn_macros)
        allmacros = sorted(macro2fn)
        # macro referenced by exactly one function -> exact-answer question
        for macro, fset in sorted(macro2fn.items()):
            if len(fset) == 1 and len(allfns) >= 3:
                out.append(dict(layer="L4", type="L4_macro2fn", diff="hard", ip=repo, reg=macro,
                                kind="word", a=next(iter(fset)),
                                q=f"In the {repo} repository of the PULP platform, source file {short} references the register macro {macro}. Which C function in that file uses it? Answer with the function name only.",
                                src=rel))
        # function using exactly one offset macro -> MC over macros in same file
        for fn, mset in sorted(fn_macros.items()):
            if len(mset) == 1 and len(allmacros) >= 4:
                m = mc_nonleaky(f"In {short} ({repo} repository, PULP platform), the C function {fn}() accesses which register offset macro?",
                                fn, next(iter(mset)), allmacros)
                if m:
                    out.append(dict(layer="L4", type="L4_fn2macro", diff="hard", ip=repo, reg=fn,
                                    kind="mc", a=m[1], q=m[0], src=rel))
    return out


# --------------------------------------------------------------------------- L5: engineering (issues)
def l5_issues():
    out = []
    all_titles = []
    repo_issues = {}
    for f in sorted(glob.glob("pulp_org/_issues/*.jsonl")):
        repo = os.path.basename(f)[:-6]
        items = []
        for l in open(f):
            try:
                d = json.loads(l)
            except Exception:
                continue
            if d.get("kind") != "issues" or not d.get("title"):
                continue
            t = d["title"].strip()
            if len(t) < 15 or repo.lower() in t.lower():
                continue
            items.append((int(d["number"]), t))
        if items:
            repo_issues[repo] = items
            all_titles += [(repo, n, t) for n, t in items]
    repos = sorted(repo_issues)
    # issue number -> title (MC over same repo's titles)
    for repo, items in repo_issues.items():
        if len(items) < 5:
            continue
        for n, t in items:
            m = mc(f"In the pulp-platform/{repo} repository on GitHub, what is the title of issue #{n}?",
                   t, [x[1] for x in items])
            if m:
                out.append(dict(layer="L5", type="L5_num2title", diff="hard", ip=repo, reg=str(n),
                                kind="mc", a=m[1], q=m[0], src=f"_issues/{repo}.jsonl"))
    # title -> repo (MC over repos)
    for repo, n, t in all_titles:
        if len(t) < 25:
            continue
        m = mc(f"A GitHub issue titled \"{t}\" was filed against which pulp-platform repository?",
               repo, repos)
        if m:
            out.append(dict(layer="L5", type="L5_title2repo", diff="medium", ip=repo, reg=str(n),
                            kind="mc", a=m[1], q=m[0], src=f"_issues/{repo}.jsonl"))
    return out


# --------------------------------------------------------------------------- assemble
TARGET = {"L1": 0.30, "L2": 0.20, "L3": 0.25, "L4": 0.15, "L5": 0.10}
# within-layer type quotas for the eval subset (fractions of the layer's slot)
L1_MIX = {"T1": 0.20, "T1h": 0.25, "T7h": 0.15, "T3": 0.25, "T4": 0.15}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-n", type=int, default=130)
    a = ap.parse_args()
    bank = l1_from_v2() + l2_bender() + l2_memmap() + l2_instances() + l3_desc() + l4_driver() + l5_issues()
    for i, q in enumerate(bank):
        q["id"] = i
        q.setdefault("mc_options", None)
    with open("questions_pulp_v3.jsonl", "w") as f:
        for q in bank:
            f.write(json.dumps(q) + "\n")

    byl = defaultdict(list)
    for q in bank:
        byl[q["layer"]].append(q)
    picked = []
    for layer, frac in TARGET.items():
        want = round(a.eval_n * frac)
        pool = byl[layer]
        if layer == "L1":
            byt = defaultdict(list)
            for q in pool:
                byt[q["type"]].append(q)
            for t, tf in L1_MIX.items():
                lst = byt.get(t, [])
                rng.shuffle(lst)
                picked += lst[: round(want * tf)]
        else:
            byt = defaultdict(list)
            for q in pool:
                byt[q["type"]].append(q)
            types = sorted(byt)
            per = max(1, want // len(types)) if types else 0
            got = []
            for t in types:
                lst = byt[t]
                rng.shuffle(lst)
                got += lst[:per]
            # top up round-robin
            leftovers = [q for t in types for q in byt[t][per:]]
            rng.shuffle(leftovers)
            got += leftovers[: max(0, want - len(got))]
            picked += got[:want]
    seen = set()
    picked = [q for q in picked if not (q["id"] in seen or seen.add(q["id"]))]
    with open("eval_pulp_v3.jsonl", "w") as f:
        for q in picked:
            f.write(json.dumps(q) + "\n")
    pids = {q["id"] for q in picked}
    few = []
    for kind in ("hex", "mc", "word"):
        cand = [q for q in bank if q["kind"] == kind and q["id"] not in pids]
        if cand:
            few.append(rng.choice(cand))
    with open("fewshot_pulp_v3.jsonl", "w") as f:
        for q in few:
            fs = dict(q)
            if q["kind"] == "mc":
                fs["a"] = q["a"]  # letter
            f.write(json.dumps(fs) + "\n")
    from collections import Counter
    print("bank:", len(bank), dict(Counter(q["type"] for q in bank)))
    print("eval:", len(picked), dict(Counter(q["layer"] for q in picked)))
    print("eval types:", dict(Counter(q["type"] for q in picked)))
    print("eval kinds:", dict(Counter(q["kind"] for q in picked)))


if __name__ == "__main__":
    main()
