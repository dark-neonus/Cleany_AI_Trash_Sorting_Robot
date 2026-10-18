#!/usr/bin/env bash
set -e

# Record teleoperated episodes into the dataset of one ACT model.
#
# Usage: scripts/dataset/record.sh [--push] <plastic|metal> [num_episodes]
#   scripts/dataset/record.sh plastic 10
#   scripts/dataset/record.sh --push metal 5    # upload to the Hub when done
#
# Run it again to append episodes to the same dataset (data/cleany_<model>).
# Env overrides: TASK, EPISODE_TIME_S, RESET_TIME_S, HF_NAMESPACE, DISPLAY_DATA
#
# Keys while recording: → finish episode early, ← re-record episode, Esc stop.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/scripts/config/hardware.sh"
source "$PROJECT_ROOT/scripts/config/datasets.sh"

PUSH=false
if [ "$1" = "--push" ]; then
    PUSH=true
    shift
fi
if [ -z "$1" ]; then
    echo "Usage: $0 [--push] <$MODELS_USAGE> [num_episodes]"
    exit 1
fi
resolve_dataset "$1"
NUM_EPISODES="${2:-10}"
EPISODE_TIME_S="${EPISODE_TIME_S:-30}"
RESET_TIME_S="${RESET_TIME_S:-10}"

require_venv
require_devices FOLLOWER_PORT LEADER_PORT FRONT_CAMERA WRIST_CAMERA
require_video_encoder
configure_cameras

# Keep data/ out of git without touching the root .gitignore
mkdir -p "$PROJECT_ROOT/data"
echo "*" > "$PROJECT_ROOT/data/.gitignore"

RESUME=false
if [ -d "$DATASET_ROOT" ]; then
    RESUME=true
    echo "Appending to existing dataset at $DATASET_ROOT"
fi

echo "Model: $MODEL ($DATASET_REPO_ID)"
echo "Task: $TASK"
echo "Episodes: $NUM_EPISODES (${EPISODE_TIME_S}s each, ${RESET_TIME_S}s reset)"

# No `yes '' |` here: on Wayland the →/←/Esc keys are read from stdin, so it must stay
# a TTY. If asked about calibration, press ENTER to use the files in calibration/.
python "$PROJECT_ROOT/scripts/common/lerobot_wide_fov.py" record \
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
  --dataset.push_to_hub=false \
  --dataset.streaming_encoding=true \
  --dataset.encoder_threads=2 \
  "${VIDEO_ENCODER_ARGS[@]}" \
  --resume="$RESUME" \
  "${DISPLAY_ARGS[@]}" \
  2> >(filter_jpeg_warnings)

if [ "$PUSH" = true ]; then
    "$PROJECT_ROOT/scripts/dataset/sync.sh" push "$MODEL"
else
    echo "Upload with: scripts/dataset/sync.sh push $MODEL"
fi
