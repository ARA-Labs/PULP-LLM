"""
DAPT of Qwen3.5-9B-Base on the PULP-org corpus (Modal), then closed-book eval on eval_pulp.jsonl.

Stack: LLaMA-Factory 0.9.5 (supports qwen3_5, transformers<=5.6) + DeepSpeed ZeRO-3; vLLM 0.28 for eval.
Recipe (ChipNeMo-style DAPT): stage=pt on raw text, full params, LR 5e-6 cosine, 3 epochs, bf16,
cutoff 4096 with packing, ~8% general replay (wikitext-103) mixed in.

Budget guard: TRAIN_GPU defaults to H100:4 (~$12/h); function timeout caps the spend.

  modal run modal_dapt.py::prepare                       # replay + dataset_info (corpus uploaded via `modal volume put`)
  TRAIN_GPU=H100:4 modal run --detach modal_dapt.py::train --max-steps 10 --run-name smoke
  TRAIN_GPU=H100:4 modal run --detach modal_dapt.py::train --run-name dapt1
  modal run modal_dapt.py::evaluate --model Qwen/Qwen3.5-9B-Base --tag base9b
  modal run modal_dapt.py::evaluate --model /vol/models/dapt1 --tag dapt1
"""
from __future__ import annotations

import json
import os
import re
import subprocess

import modal

app = modal.App("pulp-dapt")
vol = modal.Volume.from_name("pulp-dapt", create_if_missing=True)
VOL = "/vol"
HF_CACHE = f"{VOL}/hf_cache"
DATA = f"{VOL}/data"
MODELS = f"{VOL}/models"
OUT = f"{VOL}/outputs"
BASE = "Qwen/Qwen3.5-9B-Base"

common_env = {"HF_HOME": HF_CACHE, "HF_HUB_ENABLE_HF_TRANSFER": "1", "TOKENIZERS_PARALLELISM": "false"}
hf_secret = modal.Secret.from_dict(
    {"HF_TOKEN": open(os.path.expanduser("~/.cache/huggingface/token")).read().strip()}
    if os.path.exists(os.path.expanduser("~/.cache/huggingface/token")) else {})

train_image = (
    modal.Image.from_registry("nvidia/cuda:12.4.1-devel-ubuntu22.04", add_python="3.11")
    .apt_install("git", "build-essential", "ninja-build")
    .pip_install("wheel", "setuptools")
    .pip_install("llamafactory[metrics]==0.9.5", "transformers==5.6.0", "deepspeed==0.16.7",
                 "hf_transfer", "huggingface_hub", "datasets")
    .run_commands(
        "pip install ninja && pip install flash-linear-attention --no-build-isolation || echo FLA_INSTALL_FAILED",
        "python -c 'import llamafactory, transformers, torch; print(transformers.__version__, torch.__version__)'",
        "python -c 'import fla; print(\"fla\", fla.__version__)' || echo 'no fla'",
    )
    .env(common_env)
)
vllm_image = (
    modal.Image.from_registry("nvidia/cuda:12.4.1-devel-ubuntu22.04", add_python="3.11")
    .pip_install("vllm==0.28.0", "hf_transfer", "huggingface_hub")
    .env(common_env)
)
cpu_image = modal.Image.debian_slim(python_version="3.11").pip_install("datasets", "hf_transfer", "huggingface_hub").env(common_env)

DS3 = {"train_batch_size": "auto", "train_micro_batch_size_per_gpu": "auto", "gradient_accumulation_steps": "auto",
       "gradient_clipping": "auto", "zero_allow_untested_optimizer": True, "bf16": {"enabled": "auto"},
       "zero_optimization": {"stage": 3, "overlap_comm": True, "contiguous_gradients": True,
                             "reduce_bucket_size": "auto", "stage3_prefetch_bucket_size": "auto",
                             "stage3_param_persistence_threshold": "auto",
                             "stage3_gather_16bit_weights_on_model_save": True}}


@app.function(image=cpu_image, volumes={VOL: vol}, secrets=[hf_secret], timeout=3600, cpu=4, memory=16384)
def prepare(replay_frac: float = 0.08):
    """Assumes pulp_corpus.jsonl was uploaded to /vol/data. Adds wikitext replay + dataset_info.json."""
    from datasets import load_dataset
    corpus = f"{DATA}/pulp_corpus.jsonl"
    assert os.path.exists(corpus), "upload first: modal volume put pulp-dapt dapt_corpus/pulp_corpus.jsonl /data/pulp_corpus.jsonl"
    n_chars = sum(len(json.loads(l)["text"]) for l in open(corpus))
    want = int(n_chars * replay_frac / (1 - replay_frac))
    ds = load_dataset("Salesforce/wikitext", "wikitext-103-raw-v1", split="train", streaming=True)
    got, buf, doc = 0, [], []
    for r in ds:
        t = r["text"]
        if t.startswith(" = ") and doc:                # article boundary
            txt = "".join(doc)
            if len(txt) > 500: buf.append(txt); got += len(txt)
            doc = []
            if got >= want: break
        doc.append(t)
    with open(f"{DATA}/replay.jsonl", "w") as f:
        for t in buf: f.write(json.dumps({"text": t}) + "\n")
    info = {"pulp": {"file_name": "pulp_corpus.jsonl", "columns": {"prompt": "text"}},
            "replay": {"file_name": "replay.jsonl", "columns": {"prompt": "text"}}}
    json.dump(info, open(f"{DATA}/dataset_info.json", "w"), indent=2)
    from huggingface_hub import snapshot_download
    snapshot_download(BASE, allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "*.jinja"])
    vol.commit()
    print(f"corpus={n_chars/1e6:.1f}M chars  replay={got/1e6:.1f}M chars ({len(buf)} docs)  base model cached")


TRAIN_GPU = os.environ.get("TRAIN_GPU", "H100:4")
GLOBAL_BATCH = 16


@app.function(image=train_image, gpu=TRAIN_GPU, volumes={VOL: vol}, secrets=[hf_secret],
              timeout=8 * 3600, cpu=32, memory=256 * 1024)
def train(run_name: str = "dapt1", max_steps: int = -1, epochs: float = 3.0, lr: str = "5.0e-6",
          save_steps: int = 2000, datasets: str = "pulp,replay", zero: int = 3, pdbs: int = 1):
    import torch
    n = torch.cuda.device_count(); ga = max(1, GLOBAL_BATCH // (n * pdbs))
    out = f"{MODELS}/{run_name}"; os.makedirs(out, exist_ok=True)
    ds_cfg = dict(DS3)
    if zero == 2:
        ds_cfg = {k: v for k, v in DS3.items() if k != "zero_optimization"}
        ds_cfg["zero_optimization"] = {"stage": 2, "overlap_comm": True, "contiguous_gradients": True,
                                       "reduce_bucket_size": "auto"}
    json.dump(ds_cfg, open(f"{out}/ds3.json", "w"))
    cmd = ["torchrun", f"--nproc_per_node={n}", "--master_port=29400", "-m", "llamafactory.launcher",
           "--deepspeed", f"{out}/ds3.json", "--stage", "pt", "--do_train",
           "--model_name_or_path", BASE, "--dataset", datasets, "--dataset_dir", DATA,
           "--template", "default", "--finetuning_type", "full", "--output_dir", out,
           "--overwrite_cache", "--overwrite_output_dir", "--cutoff_len", "4096", "--packing", "true",
           "--preprocessing_num_workers", "16",
           "--per_device_train_batch_size", str(pdbs), "--gradient_accumulation_steps", str(ga),
           "--learning_rate", lr, "--lr_scheduler_type", "cosine", "--warmup_ratio", "0.01",
           "--num_train_epochs", str(epochs), "--logging_steps", "5", "--save_steps", str(save_steps),
           "--save_total_limit", "1", "--bf16", "--report_to", "none", "--plot_loss"]
    if max_steps > 0: cmd += ["--max_steps", str(max_steps)]
    print("GPUs:", n, "ga:", ga); print(" ".join(cmd), flush=True)
    rc = subprocess.call(cmd, env={**os.environ, "PYTHONUNBUFFERED": "1", "FORCE_TORCHRUN": "1",
                                   "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"})
    vol.commit()
    if rc != 0: raise RuntimeError(f"train rc={rc}")
    print("saved:", sorted(os.listdir(out))[:24])


def _norm(kind, s):
    s = (s or "").strip().strip("`'\"").split("\n")[0].strip().rstrip(".").lower()
    if kind == "mc":
        m = re.search(r"\b([abcd])\b", s.replace("(", " ").replace(")", " ")[:8])
        return m.group(1).upper() if m else s.upper()
    if kind == "word":
        return re.sub(r"[^a-z0-9._\-]", "", s.split()[0]) if s.split() else s
    if kind == "hex":
        m = re.search(r"(?:0x)?([0-9a-f_]+)h?$", s.replace(" ", ""))
        try: return f"0x{int(m.group(1).replace('_',''),16):x}" if m else s
        except Exception: return s
    if kind == "int":
        m = re.search(r"-?\d+", s); return m.group(0) if m else s
    if kind == "bits":
        s = s.replace("[", "").replace("]", "").replace(" ", "")
        m = re.search(r"(\d+):(\d+)", s)
        if m: return f"{m.group(1)}:{m.group(2)}"
        m = re.search(r"\d+", s); return m.group(0) if m else s
    return s


@app.function(image=vllm_image, gpu="H100:1", volumes={VOL: vol}, secrets=[hf_secret],
              timeout=3600, cpu=8, memory=64 * 1024)
def evaluate(model: str, tag: str, questions_b64: str = "", fewshot_b64: str = "", questions_path: str = ""):
    """Closed-book few-shot completion eval. Questions via base64 (small) or a /vol path (large)."""
    import base64
    from vllm import LLM, SamplingParams
    vol.reload()
    if questions_path:
        qtxt = open(questions_path).read()
    else:
        qtxt = base64.b64decode(questions_b64).decode()
    qs = [json.loads(l) for l in qtxt.splitlines() if l.strip()]
    few = [json.loads(l) for l in base64.b64decode(fewshot_b64).decode().splitlines() if l.strip()]
    shots = "".join(f"Q: {f['q']}\nA: {f['a']}\n\n" for f in few)
    header = ("The following are factual questions about the PULP Carfield/Cheshire hardware platform "
              "(ETH Zurich). Answer each with only the value (or the option letter for multiple-choice), on one line.\n\n")
    prompts = [header + shots + f"Q: {q['q']}\nA:" for q in qs]
    llm = LLM(model=model, dtype="bfloat16", max_model_len=4096, gpu_memory_utilization=0.9,
              enable_prefix_caching=True)
    outs = llm.generate(prompts, SamplingParams(temperature=0.0, max_tokens=24))
    rows, correct = [], 0
    from collections import Counter
    by = Counter(); byok = Counter()
    for q, o in zip(qs, outs):
        raw = o.outputs[0].text
        ok = _norm(q["kind"], raw) == _norm(q["kind"], q["a"])
        correct += ok; by[q["type"]] += 1; byok[q["type"]] += ok
        rows.append({"id": q["id"], "raw": raw.strip()[:80], "ok": ok})
    os.makedirs(f"{OUT}/{tag}", exist_ok=True)
    summary = {"tag": tag, "model": model, "n": len(qs), "acc": correct / len(qs),
               "by_type": {t: f"{byok[t]}/{by[t]}" for t in by}}
    json.dump({"summary": summary, "rows": rows}, open(f"{OUT}/{tag}/eval.json", "w"), indent=1)
    vol.commit()
    print(json.dumps(summary, indent=1))
    return summary
