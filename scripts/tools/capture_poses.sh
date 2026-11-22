#!/usr/bin/env bash
set -e

# Capture the named arm poses of the box into config/poses.yaml, with a panel that draws the arm
# live over the box. What each pose is and how it looks: docs/box-pipeline.md (Poses),
# assets/poses_workspace.svg, scripts/tools/capture_poses.py.
#
# Usage: scripts/tools/capture_poses.sh [options] [pose]
#   scripts/tools/capture_poses.sh              # panel; the follower follows the leader arm
#   scripts/tools/capture_poses.sh --hand       # torque off: move the follower by hand
#   scripts/tools/capture_poses.sh transit      # start on one pose
#   scripts/tools/capture_poses.sh --list       # what is captured / wrong / missing (no arm needed)
#   scripts/tools/capture_poses.sh --migrate    # old pose names -> new ones (no arm needed)
#   scripts/tools/capture_poses.sh --demo       # try the panel with a fake arm (no arm needed)
# Then draw them: python scripts/tools/draw_poses.py --png
#
# The follower moves with the same limits as in the pipeline (--max-velocity DEG_S,
# --acceleration N, --max-step DEG as run_box_pipeline.sh).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/scripts/config/hardware.sh"
require_venv

for arg in "$@"; do
    case "$arg" in
        --list|--migrate|--demo)
            python "$SCRIPT_DIR/capture_poses.py" "$@"
            exit $?
            ;;
    esac
done

parse_motion_flags "$@"
require_devices FOLLOWER_PORT

LEADER_ARGS=()
if [ -e "$LEADER_PORT" ]; then
    LEADER_ARGS=(--leader-port "$LEADER_PORT")
else
    echo "Leader arm not found at $LEADER_PORT: falling back to --hand (torque off, move the follower by hand)."
    ARGS+=(--hand)
fi
WRIST_ARGS=()
if [ -e "$WRIST_CAMERA" ]; then
    configure_cameras
    WRIST_ARGS=(--wrist "$WRIST_CAMERA")
fi
mkdir -p "$PROJECT_ROOT/outputs"
echo "*" > "$PROJECT_ROOT/outputs/.gitignore"

python "$SCRIPT_DIR/capture_poses.py" --robot-port "$FOLLOWER_PORT" --calibration-dir "$CALIB_DIR" \
    --max-step "$MAX_STEP_DEG" "${LEADER_ARGS[@]}" "${WRIST_ARGS[@]}" "${ARGS[@]}" \
    2> >(filter_jpeg_warnings)
