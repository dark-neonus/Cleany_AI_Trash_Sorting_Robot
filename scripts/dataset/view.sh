#!/usr/bin/env bash
set -e

# Browse an episode of an ACT dataset (camera videos, joint states, actions) in Rerun.
# No robot needed.
#
# Usage: scripts/dataset/view.sh <plastic|metal> [episode]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/scripts/config/hardware.sh"
source "$PROJECT_ROOT/scripts/config/datasets.sh"
resolve_dataset "$1"
require_venv

EPISODE="${2:-0}"
if [ ! -f "$DATASET_ROOT/meta/info.json" ]; then
    echo "Error: dataset not found at $DATASET_ROOT. Record it or run: scripts/dataset/sync.sh pull $MODEL"
    exit 1
fi

lerobot-dataset-viz \
  --repo-id="$DATASET_REPO_ID" \
  --root="$DATASET_ROOT" \
  --episode-index="$EPISODE"
