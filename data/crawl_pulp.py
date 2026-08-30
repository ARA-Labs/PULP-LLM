"""
Build the PULP-org DAPT corpus: shallow-clone every pulp-platform repo, extract text files,
fetch issues/PRs via `gh`, dedupe, and emit LLaMA-Factory `stage=pt` JSONL ({"text": ...}).

Usage:
  python crawl_pulp.py clone   --dst pulp_org --min-kb 20 --max-kb 300000
  python crawl_pulp.py issues  --dst pulp_org --top 40
  python crawl_pulp.py corpus  --dst pulp_org --out dapt_corpus --max-file-kb 400
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

TEXT_EXT = {".sv", ".svh", ".v", ".vhd", ".hjson", ".md", ".rst", ".c", ".h", ".S", ".py", ".tcl",
            ".yml", ".yaml", ".rdl", ".dts", ".ld", ".mk", ".txt", ".json", ".cfg", ".core", ".toml"}
SKIP_DIR = re.compile(r"/(\.git|vendor|\.github|__pycache__|node_modules|build|install)(/|$)")
SKIP_REPO = {"pulpino", "pulp-sdk", "pulp-rt-examples", "hero", "llvm-project", "gcc", "binutils-gdb",
             "riscv-gnu-toolchain", "pulp-llvm", "qemu", "linux", "opentitan", "u-boot", "openocd",
             "buildroot", "freertos", "pulp-freertos", "ml-tests", "training", "docs"}


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, **kw)


def list_repos():
    out = sh(["gh", "api", "orgs/pulp-platform/repos", "--paginate", "-q",
              ".[] | {name, size, fork, archived, language}"])
    return [json.loads(l) for l in out.stdout.splitlines() if l.strip()]


def cmd_clone(a):
    repos = list_repos()
    os.makedirs(a.dst, exist_ok=True)
    pick = [r for r in repos if not r["fork"] and r["name"] not in SKIP_REPO
            and a.min_kb <= r["size"] <= a.max_kb]
    print(f"org repos={len(repos)} picked={len(pick)} (skip forks/toolchains/{a.min_kb}KB..{a.max_kb}KB)")

    def clone(r):
        d = f"{a.dst}/{r['name']}"
        if os.path.isdir(d):
            return r["name"], "cached"
        c = sh(["git", "clone", "-q", "--depth", "1", f"https://github.com/pulp-platform/{r['name']}.git", d])
        return r["name"], "ok" if c.returncode == 0 else "FAIL"

    with ThreadPoolExecutor(max_workers=8) as ex:
        for i, f in enumerate(as_completed([ex.submit(clone, r) for r in pick])):
            n, st = f.result()
            if st == "FAIL" or i % 20 == 0:
                print(f"[{i}/{len(pick)}] {n}: {st}", flush=True)
    print("done cloning")


def cmd_issues(a):
    repos = sorted((r["name"] for r in list_repos() if not r["fork"] and r["name"] not in SKIP_REPO))
    # take the biggest cloned repos first (issues concentrate there); cap per-repo for rate sanity
    have = [r for r in repos if os.path.isdir(f"{a.dst}/{r}")]
    os.makedirs(f"{a.dst}/_issues", exist_ok=True)
    for name in have[: a.top] if a.top > 0 else have:
        out_p = f"{a.dst}/_issues/{name}.jsonl"
        if os.path.exists(out_p):
            continue
        rows = []
        for kind in ("issues", "prs"):
            q = f"repos/pulp-platform/{name}/{'issues' if kind == 'issues' else 'pulls'}?state=all&per_page=100"
            r = sh(["gh", "api", "--paginate", q, "-q",
                    '.[] | {number, title, body, state, kind: "' + kind + '"}'])
            rows += [json.loads(l) for l in r.stdout.splitlines() if l.strip()]
        with open(out_p, "w") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
        print(f"{name}: {len(rows)} issues/prs", flush=True)


def cmd_corpus(a):
    os.makedirs(a.out, exist_ok=True)
    seen, stats = set(), Counter()
    out_f = open(f"{a.out}/pulp_corpus.jsonl", "w")
    nbytes = 0
    for p in glob.glob(f"{a.dst}/**/*", recursive=True):
        if SKIP_DIR.search(p) or not os.path.isfile(p):
            continue
        ext = os.path.splitext(p)[1]
        if ext not in TEXT_EXT or os.path.getsize(p) > a.max_file_kb * 1024:
            continue
        try:
            txt = open(p, errors="ignore").read()
        except Exception:
            continue
        hs = hashlib.sha1(txt.encode()).hexdigest()
        if hs in seen or len(txt) < 200:
            continue
        seen.add(hs)
        rel = os.path.relpath(p, a.dst)
        out_f.write(json.dumps({"text": f"// FILE: {rel}\n{txt}"}) + "\n")
        stats[ext] += 1; nbytes += len(txt)
    # issues as documents
    for ip in glob.glob(f"{a.dst}/_issues/*.jsonl"):
        repo = os.path.basename(ip)[:-6]
        for l in open(ip):
            d = json.loads(l)
            body = (d.get("body") or "").strip()
            if len(body) < 80:
                continue
            txt = f"# {repo} {d['kind'][:-1]} #{d['number']}: {d['title']}\nStatus: {d['state']}\n\n{body}"
            hs = hashlib.sha1(txt.encode()).hexdigest()
            if hs in seen:
                continue
            seen.add(hs)
            out_f.write(json.dumps({"text": txt}) + "\n")
            stats[".issue"] += 1; nbytes += len(txt)
    out_f.close()
    print("docs:", sum(stats.values()), "| by ext:", dict(stats.most_common(12)))
    print(f"chars={nbytes/1e6:.1f}M  ≈{nbytes/3.5/1e6:.1f}M tokens")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    c = sp.add_parser("clone"); c.add_argument("--dst", default="pulp_org"); c.add_argument("--min-kb", type=int, default=20); c.add_argument("--max-kb", type=int, default=300000)
    i = sp.add_parser("issues"); i.add_argument("--dst", default="pulp_org"); i.add_argument("--top", type=int, default=40)
    o = sp.add_parser("corpus"); o.add_argument("--dst", default="pulp_org"); o.add_argument("--out", default="dapt_corpus"); o.add_argument("--max-file-kb", type=int, default=400)
    a = ap.parse_args(); {"clone": cmd_clone, "issues": cmd_issues, "corpus": cmd_corpus}[a.cmd](a)
