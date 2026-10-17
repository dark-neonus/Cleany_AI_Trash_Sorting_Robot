#!/usr/bin/env bash
set -e

# Run a trained policy on the follower arm.
#
# Usage: scripts/run_policy.sh [options] <checkpoint> "<task instruction>" [duration_s]
#   scripts/run_policy.sh --max-velocity 60 outputs/train/<job>/checkpoints/last/pretrained_model \
#       "Put the plastic bottle into the plastic bin" 60
#
# Options:
#   --record              Save camera video, joint states and actions as a LeRobot dataset in
#                         recordings/rollout_<model>_<YYYYmmdd_HHMMSS>/ for analysis and replay.
#   --max-velocity DEG_S  Max joint speed in deg/s (default 90, 0 = unlimited)
#   --acceleration N      Servo acceleration 0-254, units of 100 steps/s^2 (default 40, lerobot uses 254)
#   --max-step DEG        Max joint change per control step in deg (default 10)
# The env vars SERVO_MAX_VELOCITY_DEG, SERVO_ACCELERATION and MAX_STEP_DEG set the defaults.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

source "$SCRIPT_DIR/config/hardware.sh"
require_venv
require_devices FOLLOWER_PORT FRONT_CAMERA WRIST_CAMERA

parse_motion_flags "$@"

RECORD=false
POSITIONAL=()
for arg in "${ARGS[@]}"; do
    case "$arg" in
        --record) RECORD=true ;;
        --*) echo "Error: unknown option $arg"; exit 1 ;;
        *) POSITIONAL+=("$arg") ;;
    esac
done

POLICY_PATH="${POSITIONAL[0]}"
TASK="${POSITIONAL[1]}"
DURATION_S="${POSITIONAL[2]:-60}"
if [ -z "$POLICY_PATH" ] || [ -z "$TASK" ]; then
    echo "Usage: $0 [--record] [--max-velocity DEG_S] [--acceleration N] [--max-step DEG] <checkpoint> \"<task instruction>\" [duration_s]"
    exit 1
fi

STRATEGY_ARGS=(--strategy.type=base)
if [ "$RECORD" = true ]; then
    # Model id: <job>_<step> for local checkpoints (resolving "last"), else the path's name.
    CHECKPOINT_DIR="$(realpath "$(dirname "$POLICY_PATH")" 2>/dev/null || true)"
    if [ "$(basename "$(dirname "$CHECKPOINT_DIR")")" = "checkpoints" ]; then
        MODEL_ID="$(basename "$(dirname "$(dirname "$CHECKPOINT_DIR")")")_$(basename "$CHECKPOINT_DIR")"
    else
        MODEL_ID="$(basename "$POLICY_PATH")"
    fi
    MODEL_ID="$(echo "$MODEL_ID" | tr -c 'A-Za-z0-9_.\n-' '_')"
    RECORDING_NAME="rollout_${MODEL_ID}_$(date +%Y%m%d_%H%M%S)"
    RECORDING_ROOT="$PROJECT_ROOT/recordings/$RECORDING_NAME"

    # Keep recordings/ out of git without touching the root .gitignore
    mkdir -p "$PROJECT_ROOT/recordings"
    echo "*" > "$PROJECT_ROOT/recordings/.gitignore"

    echo "Recording to $RECORDING_ROOT"
    # Sentry pushes to the Hub every N episodes regardless of push_to_hub, so make N unreachable.
    STRATEGY_ARGS=(
        --strategy.type=sentry
        --strategy.upload_every_n_episodes=1000000
        --dataset.repo_id="local/$RECORDING_NAME"
        --dataset.root="$RECORDING_ROOT"
        --dataset.single_task="$TASK"
        --dataset.push_to_hub=false
        --dataset.no_stamp=true
        --dataset.encoder_threads=2
    )
fi

echo "Motion limits: ${SERVO_MAX_VELOCITY_DEG} deg/s, acceleration ${SERVO_ACCELERATION}, ${MAX_STEP_DEG} deg/step"

# RTC keeps the arm moving smoothly while the next action chunk is being inferred.
STATUS=0
python "$SCRIPT_DIR/lerobot_wide_fov.py" rollout \
  "${STRATEGY_ARGS[@]}" \
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
  --robot.max_relative_target="$MAX_STEP_DEG" \
  --task="$TASK" \
  --duration="$DURATION_S" \
  --display_data=true || STATUS=$?

if [ "$RECORD" = true ] && [ -d "$RECORDING_ROOT" ]; then
    cat > "$RECORDING_ROOT/rollout_info.json" <<EOF
{
  "policy_path": "$POLICY_PATH",
  "policy_resolved": "$(realpath "$POLICY_PATH" 2>/dev/null || echo "$POLICY_PATH")",
  "model_id": "$MODEL_ID",
  "task": "$TASK",
  "duration_s": $DURATION_S,
  "servo_max_velocity_deg": $SERVO_MAX_VELOCITY_DEG,
  "servo_acceleration": $SERVO_ACCELERATION,
  "max_step_deg": $MAX_STEP_DEG
}
EOF
    echo "Saved recording: $RECORDING_ROOT"
    echo "Replay it on the arm (add --speed 0.5 for half speed):"
    echo "  scripts/replay_recording.sh $RECORDING_ROOT"
fi

exit $STATUS
