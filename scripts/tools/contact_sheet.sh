#!/usr/bin/env bash
set -e

# See scripts/tools/contact_sheet.py (docs/collection-plan.md). No robot needed.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/scripts/config/hardware.sh"
require_venv

python "$SCRIPT_DIR/contact_sheet.py" "$@"
