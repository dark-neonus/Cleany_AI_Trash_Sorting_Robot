#!/usr/bin/env bash
set -e

# Always resolve to the project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Ensure virtual environment exists
if [ ! -f ".venv/bin/lerobot-teleoperate" ]; then
    echo "Error: Virtual environment not found or lerobot is not installed in .venv"
    echo "Please run your install script first."
    exit 1
fi

# Add virtual environment binaries to PATH for this script execution
export PATH="$PROJECT_ROOT/.venv/bin:$PATH"

# Swapped ports:
FOLLOWER_PORT="/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B79031690-if00"
LEADER_PORT="/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B79034180-if00"
CALIB_DIR="$PROJECT_ROOT/calibration"

# Validate ports exist
if [ ! -e "$FOLLOWER_PORT" ]; then
    echo "Error: Follower arm not found at $FOLLOWER_PORT"
    exit 1
fi

if [ ! -e "$LEADER_PORT" ]; then
    echo "Error: Leader arm not found at $LEADER_PORT"
    exit 1
fi

echo "Starting teleoperation (auto-accepting calibration)..."

# Pipe empty newlines into standard input to auto-confirm calibration
yes '' | lerobot-teleoperate \
  --robot.type=so101_follower \
  --robot.port="$FOLLOWER_PORT" \
  --robot.id=follower_arm \
  --robot.calibration_dir="$CALIB_DIR" \
  --robot.cameras='{
    "front": {
      "type": "opencv",
      "index_or_path": "/dev/video0",
      "width": 640,
      "height": 480,
      "fps": 30,
      "fourcc": "MJPG",
      "warmup_s": 3
    },
    "wrist": {
      "type": "opencv",
      "index_or_path": "/dev/video2",
      "width": 640,
      "height": 480,
      "fps": 15,
      "fourcc": "MJPG",
      "warmup_s": 5
    }
  }' \
  --teleop.type=so101_leader \
  --teleop.port="$LEADER_PORT" \
  --teleop.id=leader_arm \
  --teleop.calibration_dir="$CALIB_DIR" \
  --display_data=true