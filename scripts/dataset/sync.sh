#!/usr/bin/env bash
set -e

# Sync ACT datasets with their private Hugging Face Hub repos (<HF_NAMESPACE>/cleany_<model>). `pick` also
# syncs its items side (<HF_NAMESPACE>/cleany_pick_items: records, registry, crops, YOLO frames).
#
# Usage: scripts/dataset/sync.sh <push|pull|status> [plastic|metal|all] [--force]
#   scripts/dataset/sync.sh status             # episode counts, local vs Hub, for every model
#   scripts/dataset/sync.sh push plastic       # upload after recording
#   scripts/dataset/sync.sh pull all           # fetch before recording or training
#
# Transfers are refused when they would overwrite a copy with more episodes;
# --force skips that check. Log in once with: hf auth login

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/scripts/config/hardware.sh"
source "$PROJECT_ROOT/scripts/config/datasets.sh"
require_venv

COMMAND="$1"
TARGET="${2:-all}"
FORCE=()
if [ "$3" = "--force" ]; then FORCE=(--force); fi

case "$COMMAND" in
    push|pull|status) ;;
    *) echo "Usage: $0 <push|pull|status> [$MODELS_USAGE|all] [--force]"; exit 1 ;;
esac

if [ "$TARGET" = "all" ]; then TARGETS=("${MODELS[@]}"); else TARGETS=("$TARGET"); fi

mkdir -p "$PROJECT_ROOT/data"
echo "*" > "$PROJECT_ROOT/data/.gitignore"

# Keep going when one model fails so `all` still syncs the others.
STATUS=0
for target in "${TARGETS[@]}"; do
    unset TASK
    resolve_dataset "$target"
    python "$PROJECT_ROOT/scripts/common/dataset_sync.py" "$COMMAND" "$DATASET_REPO_ID" "$DATASET_ROOT" "${FORCE[@]}" || STATUS=1
    if [ "$target" = "pick" ]; then  # the items side of the pick dataset goes with its episodes
        python "$PROJECT_ROOT/scripts/common/items_sync.py" "$COMMAND" "$PICK_ITEMS_REPO" "$PICK_ITEMS_ROOT" \
            --registry "$PROJECT_ROOT/config/items.yaml" --registry "$PROJECT_ROOT/config/item_labels.yaml" "${FORCE[@]}" || STATUS=1
    fi
done
exit $STATUS
