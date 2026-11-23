#!/usr/bin/env bash
set -e

# Run the box pipeline: background trigger, YOLO boxes + DINO material, one grasp model,
# scripted moves between named poses, ESP32 doors for everything that cannot be sorted.
# See docs/box-pipeline.md and scripts/run/box_pipeline.py.
#
# Usage: scripts/run/run_box_pipeline.sh --recording true|false [options] [box_pipeline.py options...]
#   scripts/run/run_box_pipeline.sh --recording false --dry-run --display        # no arm, front camera
#   scripts/run/run_box_pipeline.sh --recording false --dry-run --source <video|image>
#   scripts/run/run_box_pipeline.sh --recording true --display                    # scripted grasp
#   scripts/run/run_box_pipeline.sh --recording true --grasp policy --display     # pick model
#
# Required:
#   --recording true|false  Record the cameras to recordings/box_<YYYYmmdd_HHMMSS>/ and make
#                           showcase.mp4 there after the run.
#
# Options:
#   --dry-run              No arm: simulated arm and door, front camera (or --source <file>)
#   --grasp scripted|policy  Fake grasp at the captured `grasp` pose (default), or the pick model
#   --door esp32|simulated|none  Default: esp32 on the arm, simulated in --dry-run
#   --max-velocity DEG_S, --acceleration N, --max-step DEG   Arm speed limits 
#   Anything else goes to box_pipeline.py (e.g. --display, --grasp-model <repo>, --device cpu).
#
# Settings: config/box_pipeline.yaml. Poses: config/poses.yaml (scripts/tools/capture_poses.sh).
# Model env overrides: YOLO_MODEL (.pt), GRASP_MODEL (Hub repo or pretrained_model folder).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/scripts/config/hardware.sh"
require_venv
export YOLO_AUTOINSTALL=false  # an ultralytics auto-install breaks lerobot's opencv

YOLO_MODEL="${YOLO_MODEL:-$(python "$PROJECT_ROOT/scripts/common/models.py" yolo)}"

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
    echo "Error: --recording true|false is required (got '${RECORDING}')."
    echo "Usage: $0 --recording true|false [--dry-run] [--grasp scripted|policy] [--display] [options]"
    exit 1
fi
if [ -n "$GRASP_MODEL" ]; then PIPELINE_ARGS+=(--grasp-model "$GRASP_MODEL"); fi

ROBOT_ARGS=()
if [ "$DRY_RUN" = true ]; then
    if [[ " ${PIPELINE_ARGS[*]} " != *" --source "* ]]; then
        require_devices FRONT_CAMERA
        configure_cameras
        ROBOT_ARGS=(--source "$FRONT_CAMERA")
    fi
else
    require_devices FOLLOWER_PORT FRONT_CAMERA WRIST_CAMERA
    configure_cameras
    echo "Motion limits: ${SERVO_MAX_VELOCITY_DEG} deg/s, acceleration ${SERVO_ACCELERATION}, ${MAX_STEP_DEG} deg/step"
    echo "The tray must be empty at start: the empty-tray reference is taken once the doors are closed."
    ROBOT_ARGS=(--robot-port "$FOLLOWER_PORT" --calibration-dir "$CALIB_DIR" --cameras "$ROBOT_CAMERAS"
                --max-step "$MAX_STEP_DEG")
fi

if [ "$RECORDING" = true ]; then
    mkdir -p "$PROJECT_ROOT/recordings"
    echo "*" > "$PROJECT_ROOT/recordings/.gitignore"
    ROBOT_ARGS+=(--record-dir "$PROJECT_ROOT/recordings/box_$(date +%Y%m%d_%H%M%S)")
fi

python "$SCRIPT_DIR/box_pipeline.py" --yolo "$YOLO_MODEL" "${ROBOT_ARGS[@]}" "${PIPELINE_ARGS[@]}" \
    2> >(filter_jpeg_warnings)
