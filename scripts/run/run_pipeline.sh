#!/usr/bin/env bash
set -e

# Run the sorting pipeline: YOLO picks the material, the matching ACT model moves the item.
# Ctrl+C or typing exit + Enter stops it and eases the arm back to its start pose.
# See scripts/run/sort_pipeline.py.
#
# Usage: scripts/run/run_pipeline.sh --recording true|false [options] [sort_pipeline.py options...]
#   scripts/run/run_pipeline.sh --recording false --dry-run --display   # no arm: front camera + YOLO only
#   scripts/run/run_pipeline.sh --recording true --max-velocity 60 --display
#
# Required:
#   --recording true|false  Whether to record the front and wrist cameras. If true, the run is
#                         saved in recordings/pipeline_<YYYYmmdd_HHMMSS>/ and, after it ends,
#                         showcase.mp4 is made there: front view in 720p, wrist view in the
#                         corner, YOLO boxes and the running model. No default: choose every time.
#
# Options:
#   --dry-run             No arm: front camera, YOLO and the state machine only; ACT runs are
#                         simulated. Add --source <video|image> to use a file instead of the camera.
#   --max-velocity DEG_S  Max joint speed in deg/s (default 90)
#   --acceleration N      Servo acceleration 0-254 (default 40)
#   --max-step DEG        Max joint change per control step in deg (default 10)
#   Anything else goes to sort_pipeline.py (e.g. --display, --conf 0.6, --lock-seconds 3).
#
# Models (env overrides): PLASTIC_MODEL, METAL_MODEL (Hub repo id or local pretrained_model
# folder), YOLO_MODEL (.pt file). The defaults come from config/default.yaml.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/scripts/config/hardware.sh"
source "$PROJECT_ROOT/scripts/config/datasets.sh"
require_venv
# A normal ultralytics auto-install pulls an opencv that breaks the one lerobot uses
export YOLO_AUTOINSTALL=false

MODELS="$PROJECT_ROOT/scripts/common/models.py"
PLASTIC_MODEL="${PLASTIC_MODEL:-$(python "$MODELS" act_plastic)}"
METAL_MODEL="${METAL_MODEL:-$(python "$MODELS" act_metal)}"
YOLO_MODEL="${YOLO_MODEL:-$(python "$MODELS" yolo)}"  # downloaded from the Hub on first use

parse_motion_flags "$@"
DRY_RUN=false
RECORDING=""
PIPELINE_ARGS=()
set -- "${ARGS[@]}"
while [ $# -gt 0 ]; do
    case "$1" in
        --recording) RECORDING="$2"; shift ;;
        --recording=*) RECORDING="${1#*=}" ;;
        --dry-run) DRY_RUN=true; PIPELINE_ARGS+=("$1") ;;
        *) PIPELINE_ARGS+=("$1") ;;
    esac
    shift
done
if [ "$RECORDING" != true ] && [ "$RECORDING" != false ]; then
    echo "Error: --recording true|false is required (got '${RECORDING}'): choose whether to record this run's cameras."
    echo "Usage: $0 --recording true|false [--dry-run] [--display] [options]"
    exit 1
fi

ROBOT_ARGS=()
if [ "$DRY_RUN" = true ]; then
    # Front camera unless --source was given
    if [[ " ${PIPELINE_ARGS[*]} " != *" --source "* ]]; then
        require_devices FRONT_CAMERA
        configure_cameras
        ROBOT_ARGS=(--source "$FRONT_CAMERA")
    fi
else
    require_devices FOLLOWER_PORT FRONT_CAMERA WRIST_CAMERA
    configure_cameras
    echo "Motion limits: ${SERVO_MAX_VELOCITY_DEG} deg/s, acceleration ${SERVO_ACCELERATION}, ${MAX_STEP_DEG} deg/step"
    echo "Put the arm in its rest pose: that pose is where every ACT run starts and ends."
    ROBOT_ARGS=(--robot-port "$FOLLOWER_PORT" --calibration-dir "$CALIB_DIR" --cameras "$ROBOT_CAMERAS"
                --max-step "$MAX_STEP_DEG")
fi

if [ "$RECORDING" = true ]; then
    # Keep recordings/ out of git without touching the root .gitignore
    mkdir -p "$PROJECT_ROOT/recordings"
    echo "*" > "$PROJECT_ROOT/recordings/.gitignore"
    RECORD_DIR="$PROJECT_ROOT/recordings/pipeline_$(date +%Y%m%d_%H%M%S)"
    ROBOT_ARGS+=(--record-dir "$RECORD_DIR")
fi

python "$SCRIPT_DIR/sort_pipeline.py" \
    --plastic-model "$PLASTIC_MODEL" --metal-model "$METAL_MODEL" --yolo "$YOLO_MODEL" \
    --plastic-task "${MODEL_TASKS[plastic]}" --metal-task "${MODEL_TASKS[metal]}" \
    "${ROBOT_ARGS[@]}" "${PIPELINE_ARGS[@]}" \
    2> >(filter_jpeg_warnings)
