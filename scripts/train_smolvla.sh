#!/usr/bin/env bash
set -e

# Fine-tune SmolVLA (lerobot/smolvla_base) on the recorded dataset.
#
# Usage: scripts/train_smolvla.sh [extra lerobot-train args...]
#   scripts/train_smolvla.sh --steps=2000            # quick smoke test
#   scripts/train_smolvla.sh --resume=true --config_path=outputs/train/<job>/checkpoints/last/pretrained_model/train_config.json
#
# Env overrides: DATASET_REPO_ID, JOB_NAME, BATCH_SIZE, STEPS
# BATCH_SIZE=4 targets a 4 GB GPU; on a 24 GB+ GPU use BATCH_SIZE=64.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

source "$SCRIPT_DIR/config/hardware.sh"
require_venv

DATASET_REPO_ID="${DATASET_REPO_ID:-local/cleany_trash_sorting}"
DATASET_ROOT="$PROJECT_ROOT/data/${DATASET_REPO_ID#*/}"
JOB_NAME="${JOB_NAME:-smolvla_$(date +%Y%m%d_%H%M)}"
BATCH_SIZE="${BATCH_SIZE:-4}"
STEPS="${STEPS:-20000}"

# Keep outputs/ out of git without touching the root .gitignore
mkdir -p "$PROJECT_ROOT/outputs"
echo "*" > "$PROJECT_ROOT/outputs/.gitignore"

if [ ! -d "$DATASET_ROOT" ]; then
    echo "Error: dataset not found at $DATASET_ROOT. Record it with scripts/record_dataset.sh"
    exit 1
fi

lerobot-train \
  --policy.path=lerobot/smolvla_base \
  --policy.device=cuda \
  --policy.push_to_hub=false \
  --policy.empty_cameras=1 \
  --rename_map="$POLICY_RENAME_MAP" \
  --dataset.repo_id="$DATASET_REPO_ID" \
  --dataset.root="$DATASET_ROOT" \
  --dataset.image_transforms.enable=true \
  --batch_size="$BATCH_SIZE" \
  --steps="$STEPS" \
  --save_freq=5000 \
  --num_workers=4 \
  --output_dir="outputs/train/$JOB_NAME" \
  --job_name="$JOB_NAME" \
  "$@"
