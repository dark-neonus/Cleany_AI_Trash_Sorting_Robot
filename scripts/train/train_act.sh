#!/usr/bin/env bash
set -e

# Train the ACT model of one material on its local dataset.
#
# Usage: scripts/train/train_act.sh <plastic|metal> [extra lerobot-train args...]
#   scripts/train/train_act.sh plastic --steps=2000     # quick smoke test
#   scripts/train/train_act.sh metal --resume=true --config_path=outputs/train/<job>/checkpoints/last/pretrained_model/train_config.json
#
# Env overrides: JOB_NAME, BATCH_SIZE, STEPS

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/scripts/config/hardware.sh"
source "$PROJECT_ROOT/scripts/config/datasets.sh"
resolve_dataset "$1"
shift
require_venv

JOB_NAME="${JOB_NAME:-act_${MODEL}_$(date +%Y%m%d_%H%M)}"
BATCH_SIZE="${BATCH_SIZE:-8}"
STEPS="${STEPS:-100000}"

# Keep outputs/ out of git without touching the root .gitignore
mkdir -p "$PROJECT_ROOT/outputs"
echo "*" > "$PROJECT_ROOT/outputs/.gitignore"

if [ ! -f "$DATASET_ROOT/meta/info.json" ]; then
    echo "Error: dataset not found at $DATASET_ROOT. Record it or run: scripts/dataset/sync.sh pull $MODEL"
    exit 1
fi

lerobot-train \
  --policy.type=act \
  --policy.device=cuda \
  --policy.push_to_hub=false \
  --dataset.repo_id="$DATASET_REPO_ID" \
  --dataset.root="$DATASET_ROOT" \
  --batch_size="$BATCH_SIZE" \
  --steps="$STEPS" \
  --save_freq=10000 \
  --num_workers=4 \
  --output_dir="outputs/train/$JOB_NAME" \
  --job_name="$JOB_NAME" \
  "$@"
