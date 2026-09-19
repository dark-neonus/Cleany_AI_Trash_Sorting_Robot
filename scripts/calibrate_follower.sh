#!/usr/bin/env bash
set -e

# Always resolve to the project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Ensure virtual environment exists
if [ ! -f ".venv/bin/lerobot-calibrate" ]; then
    echo "Error: .venv not found or lerobot is not installed."
    echo "Please check your setup in .venv."
    exit 1
fi

export PATH="$PROJECT_ROOT/.venv/bin:$PATH"

FOLLOWER_PORT="/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B79031690-if00"
CALIB_DIR="$PROJECT_ROOT/calibration"

mkdir -p "$CALIB_DIR"

if [ ! -e "$FOLLOWER_PORT" ]; then
    echo "Error: Follower arm not found at $FOLLOWER_PORT"
    exit 1
fi

echo "=========================================================="
echo "Starting FOLLOWER Arm Calibration (ID: follower_arm)"
echo "Saving results to: $CALIB_DIR/follower_arm.json"
echo "Follow the terminal instructions to set motor limits."
echo "=========================================================="

lerobot-calibrate \
  --robot.type=so101_follower \
  --robot.port="$FOLLOWER_PORT" \
  --robot.id=follower_arm \
  --robot.calibration_dir="$CALIB_DIR"