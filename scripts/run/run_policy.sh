#!/usr/bin/env bash
set -e

# Run a trained ACT model on the follower arm. Ctrl+C to stop.
#
# Usage: scripts/run/run_policy.sh [options] <plastic|metal> <model>
#   <model> is a Hugging Face repo id or a local pretrained_model folder:
#   scripts/run/run_policy.sh plastic cleany-ai/setupv2_act_plastic_20261020_1926
#   scripts/run/run_policy.sh plastic outputs/train/act_plastic_20261020_0133/checkpoints/last/pretrained_model
#   scripts/run/run_policy.sh --max-velocity 60 --duration 30 metal outputs/models/<repo_name>
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
POSITIONAL=()
set -- "${ARGS[@]}"
while [ $# -gt 0 ]; do
    case "$1" in
        --duration) DURATION_S="$2"; shift ;;
        --duration=*) DURATION_S="${1#*=}" ;;
        --device) DEVICE="$2"; shift ;;
        --device=*) DEVICE="${1#*=}" ;;
        --*) echo "Error: unknown option $1"; exit 1 ;;
        *) POSITIONAL+=("$1") ;;
    esac
    shift
done

if [ ${#POSITIONAL[@]} -ne 2 ]; then
    echo "Usage: $0 [--duration S] [--device cuda|cpu] [--max-velocity DEG_S] [--acceleration N] [--max-step DEG] <plastic|metal> <model>"
    exit 1
fi
resolve_dataset "${POSITIONAL[0]}"
POLICY_PATH="${POSITIONAL[1]}"
if [ -z "$DEVICE" ]; then
    DEVICE="$(python -c 'import torch; print("cuda" if torch.cuda.is_available() else "cpu")')"
fi

require_devices FOLLOWER_PORT FRONT_CAMERA WRIST_CAMERA
configure_cameras

echo "Model: $POLICY_PATH ($MODEL, task: $TASK) on $DEVICE, ${DURATION_S}s"
echo "Motion limits: ${SERVO_MAX_VELOCITY_DEG} deg/s, acceleration ${SERVO_ACCELERATION}, ${MAX_STEP_DEG} deg/step"

# ACT predicts a chunk of actions per inference, so plain synchronous inference is enough
# (RTC is for flow-matching models like SmolVLA). The base strategy records nothing.
python "$PROJECT_ROOT/scripts/common/lerobot_wide_fov.py" rollout \
  --strategy.type=base \
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
  2> >(filter_jpeg_warnings)
