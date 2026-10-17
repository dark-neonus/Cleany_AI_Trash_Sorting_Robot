#!/usr/bin/env bash
# Shared hardware config. Source it from scripts after PROJECT_ROOT is set:
#   source "$SCRIPT_DIR/config/hardware.sh"

FOLLOWER_PORT="/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B79031690-if00"
LEADER_PORT="/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B79034180-if00"
FRONT_CAMERA="/dev/v4l/by-id/usb-046d_0825_A0006B50-video-index0"
WRIST_CAMERA="/dev/v4l/by-id/usb-Alpha_Imaging_Tech._Corp._SEMIC_Camera-video-index0"
CALIB_DIR="$PROJECT_ROOT/calibration"

# 640x480 is a center crop on both cameras. Capture in full-FOV modes instead and
# let lerobot_wide_fov.py downscale frames to the width/height in ROBOT_CAMERAS.
# Wrist sensor is 16:9, so its full view is squeezed horizontally into 4:3.
export CAMERA_CAPTURE_MODES="{
  \"$FRONT_CAMERA\": [800, 600],
  \"$WRIST_CAMERA\": [1280, 720]
}"

ROBOT_CAMERAS="{
  \"front\": {
    \"type\": \"opencv\",
    \"index_or_path\": \"$FRONT_CAMERA\",
    \"width\": 640,
    \"height\": 480,
    \"fps\": 30,
    \"fourcc\": \"MJPG\",
    \"warmup_s\": 6
  },
  \"wrist\": {
    \"type\": \"opencv\",
    \"index_or_path\": \"$WRIST_CAMERA\",
    \"width\": 640,
    \"height\": 480,
    \"fps\": 30,
    \"fourcc\": \"MJPG\",
    \"warmup_s\": 5
  }
}"

# smolvla_base was pretrained on cameras named camera1..camera3; map ours onto them.
POLICY_RENAME_MAP='{"observation.images.front": "observation.images.camera1", "observation.images.wrist": "observation.images.camera2"}'

# Follower motion limits (applied by lerobot_wide_fov.py). Usage: parse_motion_flags "$@"
# Consumes --max-velocity DEG_PER_S, --acceleration 0-254 and --max-step DEG (also as
# --flag=value), exports SERVO_MAX_VELOCITY_DEG / SERVO_ACCELERATION / MAX_STEP_DEG,
# and leaves every other argument in the ARGS array. Env values act as defaults.
parse_motion_flags() {
    SERVO_MAX_VELOCITY_DEG="${SERVO_MAX_VELOCITY_DEG:-90}"
    SERVO_ACCELERATION="${SERVO_ACCELERATION:-40}"
    MAX_STEP_DEG="${MAX_STEP_DEG:-10}"
    ARGS=()
    while [ $# -gt 0 ]; do
        case "$1" in
            --max-velocity) SERVO_MAX_VELOCITY_DEG="$2"; shift ;;
            --max-velocity=*) SERVO_MAX_VELOCITY_DEG="${1#*=}" ;;
            --acceleration) SERVO_ACCELERATION="$2"; shift ;;
            --acceleration=*) SERVO_ACCELERATION="${1#*=}" ;;
            --max-step) MAX_STEP_DEG="$2"; shift ;;
            --max-step=*) MAX_STEP_DEG="${1#*=}" ;;
            *) ARGS+=("$1") ;;
        esac
        shift
    done
    if ! [[ "$SERVO_MAX_VELOCITY_DEG" =~ ^[0-9]+(\.[0-9]+)?$ ]] \
        || ! [[ "$SERVO_ACCELERATION" =~ ^[0-9]+$ ]] || [ "$SERVO_ACCELERATION" -gt 254 ] \
        || ! [[ "$MAX_STEP_DEG" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
        echo "Error: --max-velocity and --max-step must be numbers, --acceleration an integer 0-254"
        exit 1
    fi
    export SERVO_MAX_VELOCITY_DEG SERVO_ACCELERATION MAX_STEP_DEG
}

# Usage: require_devices FOLLOWER_PORT LEADER_PORT ...
require_devices() {
    local name
    for name in "$@"; do
        if [ ! -e "${!name}" ]; then
            echo "Error: $name not found at ${!name}"
            exit 1
        fi
    done
}

require_venv() {
    if [ ! -f "$PROJECT_ROOT/.venv/bin/lerobot-record" ]; then
        echo "Error: .venv not found or lerobot is not installed."
        echo "Please run scripts/config/install_lerobot.sh first."
        exit 1
    fi
    export PATH="$PROJECT_ROOT/.venv/bin:$PATH"
}
