#!/usr/bin/env bash
# Continued pretraining (DAPT) of Qwen3.5-9B-Base on the PULP corpus + augmentation.
# Runs on any 4-GPU node (tested on 4x80GB). Requires:
#   pip install "llamafactory[metrics]==0.9.5" "transformers==5.6.0" deepspeed==0.16.7
#   pip install ninja && pip install flash-linear-attention --no-build-isolation   # REQUIRED for qwen3_5 (3.4x)
#
# DATA_DIR must contain: pulp_corpus.jsonl, aug3.jsonl, replay.jsonl (see prepare_replay.py)
# and dataset_info.json:
#   { "pulp":   {"file_name": "pulp_corpus.jsonl", "columns": {"prompt": "text"}},
#     "replay": {"file_name": "replay.jsonl",      "columns": {"prompt": "text"}},
#     "aug3":   {"file_name": "aug3.jsonl",        "columns": {"prompt": "text"}} }
set -euo pipefail

DATA_DIR=${DATA_DIR:-./data}
OUT=${OUT:-./out/dapt3}
BASE=${BASE:-Qwen/Qwen3.5-9B-Base}
NGPU=${NGPU:-4}
EPOCHS=${EPOCHS:-2}

mkdir -p "$OUT"
cp "$(dirname "$0")/ds_zero3.json" "$OUT/ds3.json"

# global batch 16 = NGPU x micro-batch 2 x grad-accum 2 (adjust grad-accum if NGPU != 4)
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export FORCE_TORCHRUN=1

torchrun --nproc_per_node="$NGPU" --master_port=29400 -m llamafactory.launcher \
  --deepspeed "$OUT/ds3.json" --stage pt --do_train \
  --model_name_or_path "$BASE" \
  --dataset pulp,replay,aug3 --dataset_dir "$DATA_DIR" \
  --template default --finetuning_type full --output_dir "$OUT" \
  --overwrite_cache --overwrite_output_dir \
  --cutoff_len 4096 --packing true --preprocessing_num_workers 16 \
  --per_device_train_batch_size 2 --gradient_accumulation_steps 2 \
  --learning_rate 5.0e-6 --lr_scheduler_type cosine --warmup_ratio 0.01 \
  --num_train_epochs "$EPOCHS" --logging_steps 5 --save_steps 2000 \
  --save_total_limit 1 --bf16 --report_to none --plot_loss
