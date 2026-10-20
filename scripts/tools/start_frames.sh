#!/usr/bin/env bash
set -e

# Make one image per dataset with the first front (ambient) camera frame of every episode, to
# see at a glance which start positions are covered and which are missing. No robot needed.
#
# Usage: scripts/tools/start_frames.sh [plastic|metal|all]   (default: all)
# Images are written to outputs/start_frames/<model>.jpg.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/scripts/config/hardware.sh"
source "$PROJECT_ROOT/scripts/config/datasets.sh"
require_venv

TARGET="${1:-all}"
if [ "$TARGET" = "all" ]; then TARGETS=("${MODELS[@]}"); else TARGETS=("$TARGET"); fi

mkdir -p "$PROJECT_ROOT/outputs"
echo "*" > "$PROJECT_ROOT/outputs/.gitignore"

for target in "${TARGETS[@]}"; do
    unset TASK
    resolve_dataset "$target"
    if [ ! -f "$DATASET_ROOT/meta/info.json" ]; then
        echo "Skipping $MODEL: no dataset at $DATASET_ROOT"
        continue
    fi
    python "$SCRIPT_DIR/start_frames.py" "$DATASET_REPO_ID" "$DATASET_ROOT" \
        "$PROJECT_ROOT/outputs/start_frames/$MODEL.jpg"
done
