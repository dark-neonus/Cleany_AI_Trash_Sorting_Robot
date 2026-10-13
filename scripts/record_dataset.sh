#!/usr/bin/env bash
set -e

# Record teleoperated episodes into a LeRobot dataset.
#
# Usage: scripts/record_dataset.sh "<task instruction>" [num_episodes]
#   scripts/record_dataset.sh "Put the plastic bottle into the plastic bin" 10
#
# Run it again with another task to append episodes to the same dataset.
# Env overrides: DATASET_REPO_ID, EPISODE_TIME_S, RESET_TIME_S, PUSH_TO_HUB
#
# Keys while recording: → finish episode early, ← re-record episode, Esc stop.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

source "$SCRIPT_DIR/config/hardware.sh"
require_venv
require_devices FOLLOWER_PORT LEADER_PORT FRONT_CAMERA WRIST_CAMERA

TASK="$1"
NUM_EPISODES="${2:-10}"
if [ -z "$TASK" ]; then
    echo "Usage: $0 \"<task instruction>\" [num_episodes]"
    exit 1
fi

DATASET_REPO_ID="${DATASET_REPO_ID:-local/cleany_trash_sorting}"
DATASET_ROOT="$PROJECT_ROOT/data/${DATASET_REPO_ID#*/}"
EPISODE_TIME_S="${EPISODE_TIME_S:-30}"
RESET_TIME_S="${RESET_TIME_S:-10}"
PUSH_TO_HUB="${PUSH_TO_HUB:-false}"

# Keep data/ out of git without touching the root .gitignore
mkdir -p "$PROJECT_ROOT/data"
echo "*" > "$PROJECT_ROOT/data/.gitignore"

RESUME=false
if [ -d "$DATASET_ROOT" ]; then
    RESUME=true
    echo "Appending to existing dataset at $DATASET_ROOT"
fi

echo "Task: $TASK"
echo "Episodes: $NUM_EPISODES (${EPISODE_TIME_S}s each, ${RESET_TIME_S}s reset)"

# No `yes '' |` here: on Wayland the →/←/Esc keys are read from stdin, so it must stay
# a TTY. If asked about calibration, press ENTER to use the files in calibration/.
python "$SCRIPT_DIR/lerobot_wide_fov.py" record \
  --robot.type=so101_follower \
  --robot.port="$FOLLOWER_PORT" \
  --robot.id=follower_arm \
  --robot.calibration_dir="$CALIB_DIR" \
  --robot.cameras="$ROBOT_CAMERAS" \
  --teleop.type=so101_leader \
  --teleop.port="$LEADER_PORT" \
  --teleop.id=leader_arm \
  --teleop.calibration_dir="$CALIB_DIR" \
  --dataset.repo_id="$DATASET_REPO_ID" \
  --dataset.root="$DATASET_ROOT" \
  --dataset.single_task="$TASK" \
  --dataset.num_episodes="$NUM_EPISODES" \
  --dataset.episode_time_s="$EPISODE_TIME_S" \
  --dataset.reset_time_s="$RESET_TIME_S" \
  --dataset.push_to_hub="$PUSH_TO_HUB" \
  --dataset.streaming_encoding=true \
  --dataset.encoder_threads=2 \
  --resume="$RESUME" \
  --display_data=true
