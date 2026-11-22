#!/usr/bin/env bash
set -e

# Move the follower arm between the named poses to look at them. The arm moves by itself, like the
# pipeline does: see scripts/tools/show_poses.py and docs/box-pipeline.md (Poses).
#
# Usage: scripts/tools/show_poses.sh <walk|slideshow|go> [pose ...] [options]
#   scripts/tools/show_poses.sh walk                  # every pose in order, 1 s at each, then home
#   scripts/tools/show_poses.sh walk --delay 3 --loop # 3 s at each, again and again (Ctrl+C: home)
#   scripts/tools/show_poses.sh slideshow             # Enter: next pose, b: back, q: quit
#   scripts/tools/show_poses.sh go hover              # one pose; then another name, or Enter to finish
#   scripts/tools/show_poses.sh walk home hover transit   # only these poses
#   scripts/tools/show_poses.sh walk --dry-run        # no arm: the route and the timing
#
# Options: --delay S, --loop, --gripper closed|open|pose, --no-home, --from-anywhere, --yes,
# --max-velocity DEG_S (default 120), --acceleration N, --max-step DEG (default 20): the follower's limits,
# --speed DEG_S (mean joint speed of the moves, default 60; the plan slows smoothly if the arm lags).
# The arm must start at a captured pose, normally home. Keep hands and cables out of the box.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/scripts/config/hardware.sh"
require_venv

if [[ " $* " == *" --dry-run "* ]]; then
    exec python "$SCRIPT_DIR/show_poses.py" "$@"
fi

# A bit faster than the pipeline's defaults (velocity limit 90, step limit 10): the follower tracked
# the plan too slowly with those. The flags below override.
SERVO_MAX_VELOCITY_DEG="${SERVO_MAX_VELOCITY_DEG:-120}"
MAX_STEP_DEG="${MAX_STEP_DEG:-20}"
parse_motion_flags "$@"
require_devices FOLLOWER_PORT
python "$SCRIPT_DIR/show_poses.py" --robot-port "$FOLLOWER_PORT" --calibration-dir "$CALIB_DIR" \
    --max-step "$MAX_STEP_DEG" "${ARGS[@]}" \
    2> >(filter_jpeg_warnings)
