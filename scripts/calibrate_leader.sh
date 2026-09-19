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

LEADER_PORT="/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B79034180-if00"
CALIB_DIR="$PROJECT_ROOT/calibration"

mkdir -p "$CALIB_DIR"

if [ ! -e "$LEADER_PORT" ]; then
    echo "Error: Leader arm not found at $LEADER_PORT"
    exit 1
fi

echo "=========================================================="
echo "Starting LEADER Arm Calibration (ID: leader_arm)"
echo "Saving results to: $CALIB_DIR/leader_arm.json"
echo "Follow the terminal instructions to set motor limits."
echo "=========================================================="

lerobot-calibrate \
  --teleop.type=so101_leader \
  --teleop.port="$LEADER_PORT" \
  --teleop.id=leader_arm \
  --teleop.calibration_dir="$CALIB_DIR" 