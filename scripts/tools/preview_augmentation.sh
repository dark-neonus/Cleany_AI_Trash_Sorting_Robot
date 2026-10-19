#!/usr/bin/env bash
set -e

# Show the training image augmentations (scripts/config/augmentation.json) on one episode:
# each augmentation at both ends of its range, grayscale, and random combinations as training
# samples them, for frames from the start, middle and end of the episode. No robot needed.
#
# Usage: scripts/tools/preview_augmentation.sh <plastic|metal> <episode>
#   scripts/tools/preview_augmentation.sh plastic 49
# Images are written to outputs/augmentation_preview/.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/scripts/config/hardware.sh"
source "$PROJECT_ROOT/scripts/config/datasets.sh"
resolve_dataset "$1"
require_venv

EPISODE="$2"
if [ -z "$EPISODE" ]; then
    echo "Usage: $0 <$MODELS_USAGE> <episode>"
    exit 1
fi
if [ ! -f "$DATASET_ROOT/meta/info.json" ]; then
    echo "Error: dataset not found at $DATASET_ROOT. Record it or run: scripts/dataset/sync.sh pull $MODEL"
    exit 1
fi

mkdir -p "$PROJECT_ROOT/outputs"
echo "*" > "$PROJECT_ROOT/outputs/.gitignore"
python "$SCRIPT_DIR/preview_augmentation.py" "$DATASET_REPO_ID" "$DATASET_ROOT" "$EPISODE" \
    "$PROJECT_ROOT/outputs/augmentation_preview"
