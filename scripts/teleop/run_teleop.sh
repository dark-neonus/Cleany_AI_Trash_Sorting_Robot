#!/usr/bin/env bash
set -e

# Drive the follower arm with the leader arm, cameras shown in Rerun. Ctrl+C to stop.
#
# Usage: scripts/teleop/run_teleop.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/scripts/config/hardware.sh"
require_venv
require_devices FOLLOWER_PORT LEADER_PORT FRONT_CAMERA WRIST_CAMERA
configure_cameras

echo "Starting teleoperation (auto-accepting calibration)..."

# Same cameras, full-FOV capture and soft torque start as recording (lerobot_wide_fov.py).
# Pipe empty newlines into standard input to auto-confirm calibration.
yes '' | python "$PROJECT_ROOT/scripts/common/lerobot_wide_fov.py" teleoperate \
  --robot.type=so101_follower \
  --robot.port="$FOLLOWER_PORT" \
  --robot.id=follower_arm \
  --robot.calibration_dir="$CALIB_DIR" \
  --robot.cameras="$ROBOT_CAMERAS" \
  --teleop.type=so101_leader \
  --teleop.port="$LEADER_PORT" \
  --teleop.id=leader_arm \
  --teleop.calibration_dir="$CALIB_DIR" \
  "${DISPLAY_ARGS[@]}" \
  2> >(filter_jpeg_warnings)
