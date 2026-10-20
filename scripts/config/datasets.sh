#!/usr/bin/env bash
# Per-model dataset config. Source it after hardware.sh:
#   source "$PROJECT_ROOT/scripts/config/datasets.sh"
#   resolve_dataset plastic

# Hugging Face namespace (user or org) the datasets are pushed to.
HF_NAMESPACE="${HF_NAMESPACE:-cleany-ai}"

# Prefix of uploaded model names. Models only work with the physical setup (box, cameras,
# lighting, arm calibration) they were trained on: change it whenever that setup changes.
SETUP_NAME="${SETUP_NAME:-setupv2}"

# One ACT model, and so one dataset, per material.
MODELS=(plastic metal)
MODELS_USAGE="$(IFS="|"; echo "${MODELS[*]}")"

declare -A MODEL_TASKS=(
    [plastic]="Put the plastic item into the right hole"
    [metal]="Put the metal item into the left hole"
)

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
    TASK="${TASK:-${MODEL_TASKS[$MODEL]}}"
}
