#!/usr/bin/env bash
set -e

# Replay an episode of an ACT dataset (or any local LeRobot dataset) on the follower arm.
#
# Usage: scripts/dataset/replay.sh [options] <plastic|metal|dataset_dir>
#   scripts/dataset/replay.sh --episode 3 plastic
#   scripts/dataset/replay.sh --speed 0.5 recordings/rollout_<model>_<timestamp>
#
# Options:
#   --speed X             Playback speed, e.g. 0.5 = half speed (default 1)
#   --episode N           Episode to replay (default 0)
#   --max-velocity DEG_S  Max joint speed in deg/s
#   --acceleration N      Servo acceleration 0-254
#   --max-step DEG        Max joint change per control step in deg
# Motion limits default to the ones stored in the recording's rollout_info.json.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/scripts/config/hardware.sh"
source "$PROJECT_ROOT/scripts/config/datasets.sh"
require_venv
require_devices FOLLOWER_PORT

# Find the dataset dir first so a recording's stored motion limits become the defaults.
for arg in "$@"; do
    if [ -n "${MODEL_TASKS[$arg]}" ]; then
        resolve_dataset "$arg"
        RECORDING_ROOT="$DATASET_ROOT"
    elif [ -d "$arg" ]; then
        RECORDING_ROOT="$(realpath "$arg")"
    fi
done
INFO="$RECORDING_ROOT/rollout_info.json"
if [ -f "$INFO" ]; then
    read_info() { python -c "import json, sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])" "$INFO" "$1"; }
    SERVO_MAX_VELOCITY_DEG="${SERVO_MAX_VELOCITY_DEG:-$(read_info servo_max_velocity_deg)}"
    SERVO_ACCELERATION="${SERVO_ACCELERATION:-$(read_info servo_acceleration)}"
    MAX_STEP_DEG="${MAX_STEP_DEG:-$(read_info max_step_deg)}"
fi

parse_motion_flags "$@"

SPEED=1
EPISODE=0
POSITIONAL=()
i=0
while [ $i -lt ${#ARGS[@]} ]; do
    arg="${ARGS[$i]}"
    case "$arg" in
        --speed) i=$((i + 1)); SPEED="${ARGS[$i]}" ;;
        --speed=*) SPEED="${arg#*=}" ;;
        --episode) i=$((i + 1)); EPISODE="${ARGS[$i]}" ;;
        --episode=*) EPISODE="${arg#*=}" ;;
        --*) echo "Error: unknown option $arg"; exit 1 ;;
        *) POSITIONAL+=("$arg") ;;
    esac
    i=$((i + 1))
done

if [ -z "$RECORDING_ROOT" ] || [ ! -f "$RECORDING_ROOT/meta/info.json" ]; then
    echo "Usage: $0 [--speed X] [--episode N] [--max-velocity DEG_S] [--acceleration N] [--max-step DEG] <$MODELS_USAGE|dataset_dir>"
    exit 1
fi
if ! [[ "$SPEED" =~ ^[0-9]*\.?[0-9]+$ ]] || ! python -c "import sys; sys.exit(not 0 < float(sys.argv[1]) <= 1)" "$SPEED"; then
    echo "Error: --speed must be in (0, 1]; the servo limits cap anything faster anyway"
    exit 1
fi

export REPLAY_SPEED="$SPEED"
export REPLAY_FPS="$(python -c "import json, sys; print(json.load(open(sys.argv[1]))['fps'])" "$RECORDING_ROOT/meta/info.json")"

echo "Replaying episode $EPISODE of $RECORDING_ROOT at ${SPEED}x"
echo "Motion limits: ${SERVO_MAX_VELOCITY_DEG} deg/s, acceleration ${SERVO_ACCELERATION}, ${MAX_STEP_DEG} deg/step"

python "$PROJECT_ROOT/scripts/common/lerobot_wide_fov.py" replay \
  --robot.type=so101_follower \
  --robot.port="$FOLLOWER_PORT" \
  --robot.id=follower_arm \
  --robot.calibration_dir="$CALIB_DIR" \
  --robot.max_relative_target="$MAX_STEP_DEG" \
  --dataset.repo_id="local/$(basename "$RECORDING_ROOT")" \
  --dataset.root="$RECORDING_ROOT" \
  --dataset.episode="$EPISODE"
