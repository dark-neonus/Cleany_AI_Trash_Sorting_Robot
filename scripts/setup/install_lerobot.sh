#!/usr/bin/env bash
set -e

echo "=== 1. Installing Linux System Libraries & Video Headers ==="
sudo apt-get update
sudo apt-get install -y \
    git curl cmake pkg-config build-essential \
    ffmpeg libevdev-dev \
    libavformat-dev libavcodec-dev libavdevice-dev libavutil-dev \
    libswscale-dev libswresample-dev libavfilter-dev

echo "=== 2. Configuring Serial Hardware Access & USB Latency ==="
# Grant current user access to serial ports (Dynamixel, Feetech, U2D2, etc.)
sudo usermod -aG dialout "$USER"

# Set USB serial latency timer to 1ms for low-jitter robot control
if [ ! -f /etc/udev/rules.d/99-lerobot-latency.rules ]; then
    echo "Adding udev rule for 1ms USB serial latency..."
    echo 'ACTION=="add", SUBSYSTEM=="tty", KERNEL=="ttyUSB*", ATTR{device/latency_timer}="1"' | sudo tee /etc/udev/rules.d/99-lerobot-latency.rules
    sudo udevadm control --reload-rules
    sudo udevadm trigger
fi

echo "=== 3. Ensuring 'uv' is Available in PATH ==="
# Check common directories where uv might have been installed
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"

# `command -v` is not enough: a version-manager shim (mise, asdf) can exist without a uv version set.
if ! uv --version &> /dev/null; then
    echo "Installing uv package manager..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    hash -r
fi

echo "Using uv at: $(command -v uv) ($(uv --version))"

echo "=== 4. Creating Virtual Environment (Python 3.12) ==="
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"
# Keep uv's standalone Python out of sandboxed data dirs (e.g. snap VS Code terminals set
# XDG_DATA_HOME to ~/snap/code/<revision>/, which disappears on update and breaks .venv).
export UV_PYTHON_INSTALL_DIR="$HOME/.local/share/uv/python"
uv venv --clear --python 3.12 .venv
source .venv/bin/activate

echo "=== 5. Installing PyTorch with CUDA ==="
uv pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

echo "=== 6. Installing LeRobot with Core Scripts, Hardware & Training Extras ==="
uv pip install "lerobot[core_scripts,training,feetech,dynamixel,intelrealsense,diffusion]"

echo "=== 7. Verifying Installation ==="
lerobot-info

echo "================================================================="
echo "Installation complete!"
echo ""
echo "NEXT STEPS:"
echo "1. If this is your first time adding yourself to dialout:"
echo "   newgrp dialout"
echo ""
echo "2. Activate your environment in Fish shell:"
echo "   source .venv/bin/activate.fish"
echo "================================================================="