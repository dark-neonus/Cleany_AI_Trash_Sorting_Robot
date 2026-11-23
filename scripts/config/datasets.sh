#!/usr/bin/env bash
# Per-model dataset config. Source it after hardware.sh:
#   source "$PROJECT_ROOT/scripts/config/datasets.sh"
#   resolve_dataset pick

# Hugging Face namespace (user or org) the datasets are pushed to.
HF_NAMESPACE="${HF_NAMESPACE:-cleany-ai}"

# Prefix of uploaded model names. Models only work with the physical setup (box, cameras,
# lighting, arm calibration) they were trained on: change it whenever that setup changes.
# setupv2 was the open table with two ACT policies (its datasets and models stay on the Hub).
SETUP_NAME="${SETUP_NAME:-setupv3}"

# The box pipeline's pick dataset for all materials (recorded with scripts/dataset/record_pick.sh, docs/pick-dataset.md).
MODELS=(pick)
MODELS_USAGE="$(IFS="|"; echo "${MODELS[*]}")"

declare -A MODEL_TASKS=(
    [pick]="Pick up the item"
)

# The pick dataset is two repos: the episodes (cleany_pick, data/pick/episodes) and the items side
# (cleany_pick_items, data/pick/items: records, registry, crops, YOLO frames), synced together.
PICK_ITEMS_REPO="$HF_NAMESPACE/cleany_pick_items"
PICK_ITEMS_ROOT="$PROJECT_ROOT/data/pick/items"

# Datasets whose positions are normalised (docs/pick-dataset.md), not in degrees: lerobot's
# record and replay would mix them up with degrees. Usage: refuse_normalised_dataset "<what>"
refuse_normalised_dataset() {
    if [ "$MODEL" = "pick" ]; then
        echo "Error: the pick dataset stores normalised positions, not degrees: $1 cannot use it."
        echo "Record it with scripts/dataset/record_pick.sh (see docs/pick-dataset.md)."
        exit 1
    fi
}

# Usage: resolve_dataset <model>
# Sets MODEL, DATASET_REPO_ID, DATASET_ROOT and TASK (env TASK overrides the default).
resolve_dataset() {
    MODEL="$1"
    if [ -z "$MODEL" ] || [ -z "${MODEL_TASKS[$MODEL]}" ]; then
        echo "Error: model must be one of: $MODELS_USAGE (got '$MODEL')"
        exit 1
    fi
    DATASET_REPO_ID="$HF_NAMESPACE/cleany_$MODEL"
    DATASET_ROOT="$PROJECT_ROOT/data/cleany_$MODEL"
    if [ "$MODEL" = "pick" ]; then DATASET_ROOT="$PROJECT_ROOT/data/pick/episodes"; fi
    TASK="${TASK:-${MODEL_TASKS[$MODEL]}}"
}
