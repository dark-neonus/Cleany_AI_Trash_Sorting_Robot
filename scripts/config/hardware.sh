#!/usr/bin/env bash
# Shared hardware config. Source it from scripts after PROJECT_ROOT is set:
#   source "$PROJECT_ROOT/scripts/config/hardware.sh"

FOLLOWER_PORT="/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B79031690-if00"
LEADER_PORT="/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B79034180-if00"
FRONT_CAMERA="/dev/v4l/by-id/usb-046d_0825_A0006B50-video-index0"
WRIST_CAMERA="/dev/v4l/by-id/usb-Alpha_Imaging_Tech._Corp._SEMIC_Camera-video-index0"
CALIB_DIR="$PROJECT_ROOT/calibration"

# 640x480 is a center crop on the front camera. Capture it in its full-FOV 800x600 mode
# instead and let lerobot_wide_fov.py downscale frames to 640x480 (same 4:3 view).
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

# Rerun display. DISPLAY_DATA=false turns the viewer off entirely (the recorded data is not
# affected). DISPLAY_COMPRESSED=true JPEG-compresses images before they go to the viewer
# (~50 KB instead of ~900 KB per frame); off by default because on our setup the viewer froze
# and showed no camera images with it on. LeRobot reuses a Rerun viewer already running on
# port 9876 instead of starting a new one, so close stale viewers (pkill -x rerun) if the
# viewer shows no new data.
DISPLAY_DATA="${DISPLAY_DATA:-true}"
DISPLAY_COMPRESSED="${DISPLAY_COMPRESSED:-false}"
DISPLAY_ARGS=(--display_data="$DISPLAY_DATA" --display_compressed_images="$DISPLAY_COMPRESSED")

# Video codec for recorded datasets. LeRobot defaults to libsvtav1, a CPU encoder costing
# ~100 ms of CPU per frame: two cameras at 30 fps saturate a weak CPU and the cameras lag.
# h264_nvenc encodes on the NVIDIA GPU for ~3 ms of CPU per frame. Keep one codec for the
# whole team: episodes from both laptops end up in the same video files.
# VIDEO_QUALITY is the constant quantizer (lower = better quality, bigger files).
# bf=0 (no B-frames): LeRobot puts a keyframe every 2 frames (g=2, fast seeking in training),
# which NVENC rejects with its default B-frames; no B-frames also means lower latency.
VIDEO_CODEC="${VIDEO_CODEC:-h264_nvenc}"
VIDEO_QUALITY="${VIDEO_QUALITY:-23}"
VIDEO_EXTRA_OPTIONS='{"bf": 0}'
VIDEO_ENCODER_ARGS=(
    --dataset.rgb_encoder.vcodec="$VIDEO_CODEC"
    --dataset.rgb_encoder.crf="$VIDEO_QUALITY"
    --dataset.rgb_encoder.extra_options="$VIDEO_EXTRA_OPTIONS"
)

# LeRobot only checks that FFmpeg knows the encoder, not that the GPU can run it, so encode a
# few test frames with exactly the options recording will use. Stops instead of silently
# switching codecs (see VIDEO_CODEC above).
require_video_encoder() {
    if ! python - "$VIDEO_CODEC" "$VIDEO_QUALITY" "$VIDEO_EXTRA_OPTIONS" <<'EOF'
import io, json, sys
import av, numpy as np
from lerobot.configs.video import RGBEncoderConfig
codec, quality, extra = sys.argv[1], int(sys.argv[2]), json.loads(sys.argv[3])
options = RGBEncoderConfig(vcodec=codec, crf=quality, extra_options=extra).get_codec_options(as_strings=True)
out = av.open(io.BytesIO(), "w", format="mp4")
stream = out.add_stream(codec, 30, options=options)
stream.width, stream.height, stream.pix_fmt = 640, 480, "yuv420p"
for _ in range(5):
    for packet in stream.encode(av.VideoFrame.from_ndarray(np.zeros((480, 640, 3), np.uint8), "rgb24")):
        out.mux(packet)
for packet in stream.encode():
    out.mux(packet)
out.close()
EOF
    then
        echo "Error: video encoder $VIDEO_CODEC does not work on this machine (see the error above)."
        echo "For NVENC, check the NVIDIA driver with nvidia-smi. Only change VIDEO_CODEC together with"
        echo "the whole team: mixing codecs in one dataset can corrupt its video files."
        exit 1
    fi
}

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

# Camera driver settings. They live in the camera and reset when it is replugged, so scripts
# apply them before opening the cameras (both cameras):
#   exposure_dynamic_framerate=0  otherwise they drop fps in dim light to expose longer
#                                 (the front C270 fell to ~12 fps at 800x600)
#   power_line_frequency=1        50 Hz mains (Ukraine), avoids flicker bands under room lights
# plus the fixed exposure/gain/white balance from camera_settings.sh (written by
# scripts/tools/tune_cameras.sh). Without that file the cameras run in auto mode.
configure_cameras() {
    if ! command -v v4l2-ctl &> /dev/null; then
        echo "Warning: v4l2-ctl not found (sudo apt install v4l-utils); the front camera may run below 30 fps"
        return
    fi
    local FRONT_CAMERA_CONTROLS="auto_exposure=3,white_balance_automatic=1,brightness=128"
    local WRIST_CAMERA_CONTROLS="auto_exposure=3,white_balance_automatic=1,brightness=128"
    if [ -f "$PROJECT_ROOT/scripts/config/camera_settings.sh" ]; then
        source "$PROJECT_ROOT/scripts/config/camera_settings.sh"
    fi
    local device controls
    for device in FRONT WRIST; do
        controls="${device}_CAMERA_CONTROLS"
        device="${device}_CAMERA"
        v4l2-ctl -d "${!device}" -c exposure_dynamic_framerate=0,power_line_frequency=1
        # Modes first: the manual values are rejected while the matching auto mode is on.
        v4l2-ctl -d "${!device}" -c "$(echo "${!controls}" | tr ',' '\n' | grep -E '^(auto_exposure|white_balance_automatic)=' | paste -sd,)"
        v4l2-ctl -d "${!device}" -c "${!controls}"
    done
}

# The C270 MJPG stream makes libjpeg print "Corrupt JPEG data: N extraneous bytes before
# marker" for nearly every frame. The frames decode fine, so drop those lines.
# Usage: some_command 2> >(filter_jpeg_warnings)
filter_jpeg_warnings() {
    grep --line-buffered -v "^Corrupt JPEG data" >&2
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
        echo "Please run scripts/setup/install_dependencies.sh first."
        exit 1
    fi
    export PATH="$PROJECT_ROOT/.venv/bin:$PATH"
}
