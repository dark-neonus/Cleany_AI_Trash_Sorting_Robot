#!/usr/bin/env bash
set -e

# Capture the named poses of the box pipeline into config/poses.yaml by moving the follower
# by hand (torque off). See scripts/tools/capture_poses.py for what each pose is.
#
# Usage: scripts/tools/capture_poses.sh [names...]      (default: all poses)
#   scripts/tools/capture_poses.sh                     # home hover centre metal_bin plastic_bin grasp
#   scripts/tools/capture_poses.sh hover               # redo one pose, keep the others
# Also saves a wrist photo at hover to outputs/poses/hover_wrist.jpg when the wrist camera is in.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/scripts/config/hardware.sh"
require_venv
require_devices FOLLOWER_PORT

WRIST_ARGS=()
if [ -e "$WRIST_CAMERA" ]; then
    configure_cameras
    WRIST_ARGS=(--wrist "$WRIST_CAMERA")
fi
mkdir -p "$PROJECT_ROOT/outputs"
echo "*" > "$PROJECT_ROOT/outputs/.gitignore"

python "$SCRIPT_DIR/capture_poses.py" --robot-port "$FOLLOWER_PORT" --calibration-dir "$CALIB_DIR" \
    "${WRIST_ARGS[@]}" "$@"
