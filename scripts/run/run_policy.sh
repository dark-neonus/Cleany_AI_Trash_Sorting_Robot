#!/usr/bin/env bash
set -e

# Run a trained ACT model on the follower arm. Ctrl+C to stop.
#
# Usage: scripts/run/run_policy.sh --record true|false [options] <plastic|metal> <model>
#   <model> is a Hugging Face repo id or a local pretrained_model folder:
#   scripts/run/run_policy.sh --record false plastic cleany-ai/setupv2_act_plastic_20261020_1926
#   scripts/run/run_policy.sh --record true plastic outputs/train/act_plastic_20261020_0133/checkpoints/last/pretrained_model
#   scripts/run/run_policy.sh --record false --max-velocity 60 --duration 30 metal outputs/models/<repo_name>
#
# Required:
#   --record true|false   Whether to save the run (camera videos, joint states, actions) as a
#                         LeRobot dataset in recordings/rollout_<model>_<YYYYmmdd_HHMMSS>/, to
#                         review (scripts/dataset/view.sh <dir>) or replay it (replay.sh <dir>).
#                         No default: choose every time.
#
# Options:
#   --duration S          Stop after S seconds (default 60; 0 = run until Ctrl+C)
#   --device DEV          cuda (default when available) or cpu, e.g. while the GPU is training
#   --max-velocity DEG_S  Max joint speed in deg/s (default 90)
#   --acceleration N      Servo acceleration 0-254 (default 40)
#   --max-step DEG        Max joint change per control step in deg (default 10)
#
# The model runs without YOLO: put one item of the model's material in the start zone first.
# Stay next to the arm on the first runs of a new model.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/scripts/config/hardware.sh"
source "$PROJECT_ROOT/scripts/config/datasets.sh"
require_venv

parse_motion_flags "$@"
DURATION_S=60
DEVICE=""
RECORD=""
POSITIONAL=()
set -- "${ARGS[@]}"
while [ $# -gt 0 ]; do
    case "$1" in
        --duration) DURATION_S="$2"; shift ;;
        --duration=*) DURATION_S="${1#*=}" ;;
        --device) DEVICE="$2"; shift ;;
        --device=*) DEVICE="${1#*=}" ;;
        --record) RECORD="$2"; shift ;;
        --record=*) RECORD="${1#*=}" ;;
        --*) echo "Error: unknown option $1"; exit 1 ;;
        *) POSITIONAL+=("$1") ;;
    esac
    shift
done

if [ "$RECORD" != true ] && [ "$RECORD" != false ]; then
    echo "Error: --record true|false is required (got '${RECORD}'): choose whether to save this run's camera views."
    echo "Usage: $0 --record true|false [options] <plastic|metal> <model>"
    exit 1
fi
if [ ${#POSITIONAL[@]} -ne 2 ]; then
    echo "Usage: $0 --record true|false [--duration S] [--device cuda|cpu] [--max-velocity DEG_S] [--acceleration N] [--max-step DEG] <plastic|metal> <model>"
    exit 1
fi
resolve_dataset "${POSITIONAL[0]}"
POLICY_PATH="${POSITIONAL[1]}"
if [ -z "$DEVICE" ]; then
    DEVICE="$(python -c 'import torch; print("cuda" if torch.cuda.is_available() else "cpu")')"
fi

require_devices FOLLOWER_PORT FRONT_CAMERA WRIST_CAMERA
configure_cameras

STRATEGY_ARGS=(--strategy.type=base)  # runs the model, records nothing
if [ "$RECORD" = true ]; then
    require_video_encoder
    # Model id for the folder name: repo name, or <run>_<step> for a local checkpoint
    if [ -d "$POLICY_PATH" ] && [ "$(basename "$(dirname "$(dirname "$(realpath "$POLICY_PATH")")")")" = checkpoints ]; then
        CHECKPOINT_DIR="$(dirname "$(realpath "$POLICY_PATH")")"
        MODEL_ID="$(basename "$(dirname "$(dirname "$CHECKPOINT_DIR")")")_$(basename "$(realpath "$CHECKPOINT_DIR")")"
    else
        MODEL_ID="$(basename "$POLICY_PATH")"
    fi
    MODEL_ID="$(echo "$MODEL_ID" | tr -c 'A-Za-z0-9_.\n-' '_')"
    RECORDING_NAME="rollout_${MODEL}_${MODEL_ID}_$(date +%Y%m%d_%H%M%S)"
    RECORDING_ROOT="$PROJECT_ROOT/recordings/$RECORDING_NAME"

    # Keep recordings/ out of git without touching the root .gitignore
    mkdir -p "$PROJECT_ROOT/recordings"
    echo "*" > "$PROJECT_ROOT/recordings/.gitignore"

    # Sentry records continuously and saves the last episode on exit. It pushes to the Hub
    # every N episodes even with push_to_hub=false, so make N unreachable.
    STRATEGY_ARGS=(
        --strategy.type=sentry
        --strategy.upload_every_n_episodes=1000000
        --dataset.repo_id="local/$RECORDING_NAME"
        --dataset.root="$RECORDING_ROOT"
        --dataset.single_task="$TASK"
        --dataset.push_to_hub=false
        --dataset.no_stamp=true
        --dataset.streaming_encoding=true
        --dataset.encoder_threads=2
        "${VIDEO_ENCODER_ARGS[@]}"
    )
    echo "Recording this run to $RECORDING_ROOT"
fi

echo "Model: $POLICY_PATH ($MODEL, task: $TASK) on $DEVICE, ${DURATION_S}s"
echo "Motion limits: ${SERVO_MAX_VELOCITY_DEG} deg/s, acceleration ${SERVO_ACCELERATION}, ${MAX_STEP_DEG} deg/step"

# ACT predicts a chunk of actions per inference, so plain synchronous inference is enough
# (RTC is for flow-matching models like SmolVLA).
STATUS=0
python "$PROJECT_ROOT/scripts/common/lerobot_wide_fov.py" rollout \
  "${STRATEGY_ARGS[@]}" \
  --policy.path="$POLICY_PATH" \
  --policy.device="$DEVICE" \
  --inference.type=sync \
  --robot.type=so101_follower \
  --robot.port="$FOLLOWER_PORT" \
  --robot.id=follower_arm \
  --robot.calibration_dir="$CALIB_DIR" \
  --robot.cameras="$ROBOT_CAMERAS" \
  --robot.max_relative_target="$MAX_STEP_DEG" \
  --task="$TASK" \
  --duration="$DURATION_S" \
  "${DISPLAY_ARGS[@]}" \
  2> >(filter_jpeg_warnings) || STATUS=$?

if [ "$RECORD" = true ] && [ -f "$RECORDING_ROOT/meta/info.json" ]; then
    # Read by scripts/dataset/replay.sh: replays use the motion limits the run had.
    cat > "$RECORDING_ROOT/rollout_info.json" <<EOF
{
  "model": "$MODEL",
  "policy_path": "$POLICY_PATH",
  "task": "$TASK",
  "duration_s": $DURATION_S,
  "servo_max_velocity_deg": $SERVO_MAX_VELOCITY_DEG,
  "servo_acceleration": $SERVO_ACCELERATION,
  "max_step_deg": $MAX_STEP_DEG
}
EOF
    echo "Saved recording: $RECORDING_ROOT"
    echo "  watch it:  scripts/dataset/view.sh $RECORDING_ROOT"
    echo "  replay it: scripts/dataset/replay.sh --speed 0.5 $RECORDING_ROOT"
elif [ "$RECORD" = true ]; then
    echo "Warning: nothing was recorded to $RECORDING_ROOT"
fi
exit $STATUS
