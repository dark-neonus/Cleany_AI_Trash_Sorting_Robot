#!/usr/bin/env bash
set -e

# Browse an episode of an ACT dataset or of a recorded model run (camera videos, joint
# states, actions) in Rerun. No robot needed.
#
# Usage: scripts/dataset/view.sh <recording_dir> [episode]
#   scripts/dataset/view.sh pick 9
#   scripts/dataset/view.sh recordings/rollout_<model>_<timestamp>

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/scripts/config/hardware.sh"
source "$PROJECT_ROOT/scripts/config/datasets.sh"
if [ -d "$1" ]; then  # a recording folder, e.g. a run recorded by the box pipeline
    DATASET_ROOT="$(realpath "$1")"
    DATASET_REPO_ID="local/$(basename "$DATASET_ROOT")"
else
    resolve_dataset "$1"
fi
require_venv

EPISODE="${2:-0}"
if [ ! -f "$DATASET_ROOT/meta/info.json" ]; then
    echo "Error: no dataset at $DATASET_ROOT (record it with record_pick.sh, or: scripts/dataset/sync.sh pull pick)"
    exit 1
fi

lerobot-dataset-viz \
  --repo-id="$DATASET_REPO_ID" \
  --root="$DATASET_ROOT" \
  --episode-index="$EPISODE"
