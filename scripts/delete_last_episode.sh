#!/usr/bin/env bash
set -e

# Delete the last recorded episode from the local dataset.
#
# Usage: scripts/delete_last_episode.sh
# Env overrides: DATASET_REPO_ID

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

source "$SCRIPT_DIR/config/hardware.sh"
require_venv

DATASET_REPO_ID="${DATASET_REPO_ID:-local/cleany_trash_sorting}"
DATASET_ROOT="$PROJECT_ROOT/data/${DATASET_REPO_ID#*/}"
EDITED_ROOT="$DATASET_ROOT.edited"
BACKUP_ROOT="$DATASET_ROOT.before_delete"

if [ ! -d "$DATASET_ROOT" ]; then
    echo "Error: dataset not found at $DATASET_ROOT"
    exit 1
fi

LAST_EPISODE=$(python -c "import json; print(json.load(open('$DATASET_ROOT/meta/info.json'))['total_episodes'] - 1)")
if [ "$LAST_EPISODE" -lt 1 ]; then
    echo "Dataset has a single episode; delete $DATASET_ROOT instead."
    exit 1
fi

echo "Deleting episode $LAST_EPISODE from $DATASET_ROOT"
rm -rf "$EDITED_ROOT"
lerobot-edit-dataset \
  --repo_id="$DATASET_REPO_ID" \
  --root="$DATASET_ROOT" \
  --new_root="$EDITED_ROOT" \
  --operation.type=delete_episodes \
  --operation.episode_indices="[$LAST_EPISODE]"

# Keep the previous version until the next delete, in case of a mistake.
rm -rf "$BACKUP_ROOT"
mv "$DATASET_ROOT" "$BACKUP_ROOT"
mv "$EDITED_ROOT" "$DATASET_ROOT"
echo "Done. Previous version kept at $BACKUP_ROOT"
