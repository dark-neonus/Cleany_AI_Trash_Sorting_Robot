#!/usr/bin/env bash
set -e

# Train the metal/plastic YOLO on our own labeled front-camera frames.
#
# Usage: scripts/yolo/train.sh [extra ultralytics args...]
#   scripts/yolo/train.sh                     # fine-tune the current model, 150 epochs
#   scripts/yolo/train.sh epochs=5            # quick smoke test
#   BASE=yolo/weights/yolo26n.pt scripts/yolo/train.sh epochs=300   # from the COCO base instead
#
# Builds yolo/dataset_cleany/ from the labeled first frames in yolo/frames/ plus the extra
# frames before the arm reaches the item (extra_frames.py, yolo/frames_extra/), then trains
# into outputs/yolo/<JOB_NAME>/ (best weights: weights/best.pt).
#
# Tried on 2026-10-20 and worse on an unseen photo: adding the Kaggle photos, and the bigger
# yolo26s model (both added false or missed detections). Fine-tuning yolo26n it is.
#
# Env overrides: JOB_NAME, BASE (starting weights), EPOCHS, BATCH

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/scripts/config/hardware.sh"
require_venv
# A normal ultralytics auto-install pulls an opencv that breaks the one lerobot uses
export YOLO_AUTOINSTALL=false

JOB_NAME="${JOB_NAME:-yolo_cleany_$(date +%Y%m%d_%H%M)}"
BASE="${BASE:-models/yolo/yolo_kaggle_best.pt}"
EPOCHS="${EPOCHS:-150}"
BATCH="${BATCH:-8}"

python "$SCRIPT_DIR/extra_frames.py"
python "$SCRIPT_DIR/prepare_dataset.py"

mkdir -p "$PROJECT_ROOT/outputs"
echo "*" > "$PROJECT_ROOT/outputs/.gitignore"

# Augmentation: the material, not the label colour, should decide the class, so hue
# (0.1 instead of 0.015), saturation and brightness vary a lot. Small rotations and
# left/right flips are fine for detection; mosaic (default) multiplies the few frames we have.
yolo detect train \
    model="$BASE" \
    data="$PROJECT_ROOT/yolo/dataset_cleany/dataset.yaml" \
    project="$PROJECT_ROOT/outputs/yolo" name="$JOB_NAME" \
    epochs="$EPOCHS" batch="$BATCH" imgsz=640 patience=50 \
    hsv_h=0.1 hsv_s=0.7 hsv_v=0.5 degrees=10 fliplr=0.5 \
    workers=4 plots=True \
    "$@"

echo "Best weights: outputs/yolo/$JOB_NAME/weights/best.pt"
