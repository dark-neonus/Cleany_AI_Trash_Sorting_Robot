#!/usr/bin/env bash
set -e

# Record the pick dataset (hover to item lifted) with both arms, the doors, YOLO and DINO.
# See docs/pick-dataset.md (how to record) and scripts/dataset/record_pick.py.
#
# Usage: scripts/dataset/record_pick.sh [--push] [--door none] [options]
#   scripts/dataset/record_pick.sh                 # appends to data/cleany_pick
#   scripts/dataset/record_pick.sh --push          # upload to the Hub when done
#   scripts/dataset/record_pick.sh --door none     # no drop mechanism: empty the tray by hand
#
# Options: --max-velocity DEG_S, --acceleration N, --max-step DEG (as run_box_pipeline.sh: the
# follower moves with the same limits as in the pipeline), --device cpu.
# Settings: config/pick_recording.yaml. Poses: config/poses.yaml (scripts/tools/capture_poses.sh).
# Env overrides: YOLO_MODEL (.pt).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/scripts/config/hardware.sh"
require_venv
export YOLO_AUTOINSTALL=false  # an ultralytics auto-install breaks lerobot's opencv

PUSH=false
if [ "$1" = "--push" ]; then
    PUSH=true
    shift
fi
parse_motion_flags "$@"

require_devices FOLLOWER_PORT LEADER_PORT FRONT_CAMERA WRIST_CAMERA
require_video_encoder
configure_cameras
export VIDEO_CODEC VIDEO_QUALITY VIDEO_EXTRA_OPTIONS

# Keep data/ and logs/ out of git without touching the root .gitignore
mkdir -p "$PROJECT_ROOT/data"
echo "*" > "$PROJECT_ROOT/data/.gitignore"

YOLO_MODEL="${YOLO_MODEL:-$(python "$PROJECT_ROOT/scripts/common/models.py" yolo)}"
echo "Motion limits: ${SERVO_MAX_VELOCITY_DEG} deg/s, acceleration ${SERVO_ACCELERATION}, ${MAX_STEP_DEG} deg/step"
echo "The tray is emptied by the doors at start: keep hands out of the box until READY."

python "$SCRIPT_DIR/record_pick.py" --yolo "$YOLO_MODEL" \
    --robot-port "$FOLLOWER_PORT" --leader-port "$LEADER_PORT" --calibration-dir "$CALIB_DIR" \
    --cameras "$ROBOT_CAMERAS" --max-step "$MAX_STEP_DEG" "${ARGS[@]}" \
    2> >(filter_jpeg_warnings)

if [ "$PUSH" = true ]; then
    "$PROJECT_ROOT/scripts/dataset/sync.sh" push pick
fi
