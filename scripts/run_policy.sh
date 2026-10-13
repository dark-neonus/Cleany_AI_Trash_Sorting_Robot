#!/usr/bin/env bash
set -e

# Run a trained policy on the follower arm.
#
# Usage: scripts/run_policy.sh <checkpoint> "<task instruction>" [duration_s]
#   scripts/run_policy.sh outputs/train/<job>/checkpoints/last/pretrained_model \
#       "Put the plastic bottle into the plastic bin" 60

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

source "$SCRIPT_DIR/config/hardware.sh"
require_venv
require_devices FOLLOWER_PORT FRONT_CAMERA WRIST_CAMERA

POLICY_PATH="$1"
TASK="$2"
DURATION_S="${3:-60}"
if [ -z "$POLICY_PATH" ] || [ -z "$TASK" ]; then
    echo "Usage: $0 <checkpoint> \"<task instruction>\" [duration_s]"
    exit 1
fi

# RTC keeps the arm moving smoothly while the next action chunk is being inferred.
python "$SCRIPT_DIR/lerobot_wide_fov.py" rollout \
  --strategy.type=base \
  --policy.path="$POLICY_PATH" \
  --rename_map="$POLICY_RENAME_MAP" \
  --inference.type=rtc \
  --inference.rtc.execution_horizon=10 \
  --inference.rtc.max_guidance_weight=10.0 \
  --robot.type=so101_follower \
  --robot.port="$FOLLOWER_PORT" \
  --robot.id=follower_arm \
  --robot.calibration_dir="$CALIB_DIR" \
  --robot.cameras="$ROBOT_CAMERAS" \
  --task="$TASK" \
  --duration="$DURATION_S" \
  --display_data=true
