#!/usr/bin/env bash
# Shared hardware config. Source it from scripts after PROJECT_ROOT is set:
#   source "$PROJECT_ROOT/scripts/config/hardware.sh"

FOLLOWER_PORT="/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B79031690-if00"
LEADER_PORT="/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B79034180-if00"
FRONT_CAMERA="/dev/v4l/by-id/usb-046d_0825_A0006B50-video-index0"
WRIST_CAMERA="/dev/v4l/by-id/usb-Alpha_Imaging_Tech._Corp._SEMIC_Camera-video-index0"
CALIB_DIR="$PROJECT_ROOT/calibration"

# 640x480 is a center crop on the front camera. Capture it in its full-FOV 800x600 mode
# instead and let the *_wide_fov.py wrapper downscale frames to 640x480 (same 4:3 view).
# The wrist camera's 640x360 mode is already its full 16:9 view (and has lower latency
# than 1280x720), so it is captured as is.
export CAMERA_CAPTURE_MODES="{
  \"$FRONT_CAMERA\": [800, 600]
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
    \"height\": 360,
    \"fps\": 30,
    \"fourcc\": \"MJPG\",
    \"warmup_s\": 5
  }
}"

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
        echo "Please run scripts/setup/install_lerobot.sh first."
        exit 1
    fi
    export PATH="$PROJECT_ROOT/.venv/bin:$PATH"
}
