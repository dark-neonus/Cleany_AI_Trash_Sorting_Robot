#!/usr/bin/env bash
set -e

# Flatten the pick dataset's parquet files into CSV tables you can read in VS Code (see export_csv.py).
#   scripts/tools/export_csv.sh [--root DIR] [--out DIR] [--embedding]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"
source "$PROJECT_ROOT/scripts/config/hardware.sh"
require_venv
python "$SCRIPT_DIR/export_csv.py" "$@"
