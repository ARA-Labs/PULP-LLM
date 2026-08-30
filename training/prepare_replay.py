"""Build the ~8% general-text replay mix (wikitext-103 articles) for DAPT.

Usage: python prepare_replay.py --corpus data/pulp_corpus.jsonl --out data/replay.jsonl
"""
import argparse
import json

from datasets import load_dataset


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="data/pulp_corpus.jsonl")
    ap.add_argument("--out", default="data/replay.jsonl")
    ap.add_argument("--frac", type=float, default=0.08)
    a = ap.parse_args()
    n_chars = sum(len(json.loads(l)["text"]) for l in open(a.corpus))
    want = int(n_chars * a.frac / (1 - a.frac))
    ds = load_dataset("Salesforce/wikitext", "wikitext-103-raw-v1", split="train", streaming=True)
    got, buf, doc = 0, [], []
    for r in ds:
        t = r["text"]
        if t.startswith(" = ") and doc:              # article boundary
            txt = "".join(doc)
            if len(txt) > 500:
                buf.append(txt)
                got += len(txt)
            doc = []
            if got >= want:
                break
        doc.append(t)
    with open(a.out, "w") as f:
        for t in buf:
            f.write(json.dumps({"text": t}) + "\n")
    print(f"corpus={n_chars/1e6:.1f}M chars  replay={got/1e6:.1f}M chars ({len(buf)} docs)")


if __name__ == "__main__":
    main()
