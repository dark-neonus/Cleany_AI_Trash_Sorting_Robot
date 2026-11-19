#!/usr/bin/env bash
set -e

# Build the DINO gallery (models/dino/gallery.npz) for the box pipeline's classifier and print a
# held-out evaluation. No robot needed. See scripts/tools/build_gallery.py.
#
# Usage: scripts/tools/build_gallery.sh [--yolo-dataset DIR] [--crops DIR]
#   scripts/tools/build_gallery.sh                                 # the labelled YOLO frames (old setup)
#   scripts/tools/build_gallery.sh --crops data/box_crops          # <class>/<item>_<n>.jpg from the box
#   scripts/tools/build_gallery.sh --yolo-dataset yolo/dataset_cleany --crops data/box_crops

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/scripts/config/hardware.sh"
require_venv

if [ $# -eq 0 ]; then set -- --yolo-dataset "$PROJECT_ROOT/yolo/dataset_cleany"; fi
python "$SCRIPT_DIR/build_gallery.py" "$@"
