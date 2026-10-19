#!/usr/bin/env bash
set -e

# Train the ACT model of one material on its local dataset.
#
# Usage: scripts/train/train_act.sh <plastic|metal> [extra lerobot-train args...]
#   scripts/train/train_act.sh plastic --steps=2000     # quick smoke test
#   scripts/train/train_act.sh metal --resume=true --config_path=outputs/train/<job>/checkpoints/last/pretrained_model/train_config.json
#
# Env overrides: JOB_NAME, BATCH_SIZE, STEPS, SAVE_FREQ, AUGMENT=false (no image augmentation)

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
# ACT trains fast, so save often enough to pick a good intermediate checkpoint. Each checkpoint
# (weights + optimizer state) is ~0.6 GB: 20 per 100k-step run with the default.
SAVE_FREQ="${SAVE_FREQ:-5000}"

# Keep outputs/ out of git without touching the root .gitignore
mkdir -p "$PROJECT_ROOT/outputs"
echo "*" > "$PROJECT_ROOT/outputs/.gitignore"

# Image augmentation, so the models ignore colour and lighting: YOLO already picks the
# material, the ACT only needs the item's position and shape. The transforms live in
# scripts/config/augmentation.json (preview them with scripts/tools/preview_augmentation.sh).
# Each training frame gets 3 of them, picked by weight; the recorded dataset is not changed:
#   brightness/contrast 0.75-1.25, saturation 0.5-1.5, sharpness 0.5-1.5
#   hue +-0.15: the one that actually changes an object's colour (LeRobot's default is +-0.05)
#   grayscale: weight 0.15, about 11% of frames
# LeRobot's default random shift/rotation ("affine") is left out on purpose: ACT maps pixel
# positions to arm motions and our cameras are fixed, so shifted images teach wrong positions.
AUGMENT="${AUGMENT:-true}"
AUGMENTATIONS="$(cat "$PROJECT_ROOT/scripts/config/augmentation.json")"
AUGMENT_ARGS=(--dataset.image_transforms.enable="$AUGMENT")
if [ "$AUGMENT" = true ]; then
    AUGMENT_ARGS+=(--dataset.image_transforms.tfs="$AUGMENTATIONS")
fi

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
  "${AUGMENT_ARGS[@]}" \
  --batch_size="$BATCH_SIZE" \
  --steps="$STEPS" \
  --save_freq="$SAVE_FREQ" \
  --num_workers=4 \
  --output_dir="outputs/train/$JOB_NAME" \
  --job_name="$JOB_NAME" \
  "$@"
