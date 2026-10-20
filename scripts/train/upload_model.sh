#!/usr/bin/env bash
set -e

# Upload a trained ACT checkpoint to a private Hugging Face model repo named
#   <HF_NAMESPACE>/<SETUP_NAME>_act_<model>_<YYYYmmdd_HHMM>
# where the timestamp is when the checkpoint's last training step finished.
#
# Usage: scripts/train/upload_model.sh <plastic|metal> [run_dir] [--checkpoint STEP] [--dry-run]
#   scripts/train/upload_model.sh plastic                       # last checkpoint of the latest run
#   scripts/train/upload_model.sh plastic outputs/train/act_plastic_20261020_1400 --checkpoint 50000
#   scripts/train/upload_model.sh plastic --dry-run             # show what would be uploaded
#
# Env overrides: HF_NAMESPACE, SETUP_NAME (see scripts/config/datasets.sh)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/scripts/config/hardware.sh"
source "$PROJECT_ROOT/scripts/config/datasets.sh"
resolve_dataset "$1"
shift
require_venv

RUN_DIR=""
CHECKPOINT="last"
EXTRA=()
while [ $# -gt 0 ]; do
    case "$1" in
        --checkpoint) CHECKPOINT="$2"; shift ;;
        --checkpoint=*) CHECKPOINT="${1#*=}" ;;
        --dry-run) EXTRA+=(--dry-run) ;;
        --*) echo "Error: unknown option $1"; exit 1 ;;
        *) RUN_DIR="$1" ;;
    esac
    shift
done

if [ -z "$RUN_DIR" ]; then
    # Most recently modified run of this model that has a checkpoint
    for dir in $(ls -dt "$PROJECT_ROOT"/outputs/train/act_"${MODEL}"_* 2>/dev/null); do
        if [ -e "$dir/checkpoints/last" ]; then RUN_DIR="$dir"; break; fi
    done
    if [ -z "$RUN_DIR" ]; then
        echo "Error: no trained run found in outputs/train/act_${MODEL}_*"
        exit 1
    fi
fi

if [ "$CHECKPOINT" = "last" ]; then
    CHECKPOINT_DIR="$RUN_DIR/checkpoints/last"
else
    # Checkpoint folders are zero-padded (050000); accept 50000 too
    CHECKPOINT_DIR=""
    for dir in "$RUN_DIR"/checkpoints/[0-9]*; do
        if [ "$((10#$(basename "$dir")))" = "$((10#$CHECKPOINT))" ]; then CHECKPOINT_DIR="$dir"; fi
    done
    if [ -z "$CHECKPOINT_DIR" ]; then
        echo "Error: no checkpoint $CHECKPOINT in $RUN_DIR/checkpoints ($(ls "$RUN_DIR/checkpoints" | tr '\n' ' '))"
        exit 1
    fi
fi

python "$PROJECT_ROOT/scripts/common/model_upload.py" "$(realpath "$CHECKPOINT_DIR")" \
    "$HF_NAMESPACE/${SETUP_NAME}_act_${MODEL}" "${EXTRA[@]}"
