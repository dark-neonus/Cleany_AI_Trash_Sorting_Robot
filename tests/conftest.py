"""Make the scripts importable as modules: they are scripts, not an installed package."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for folder in ("scripts/common", "scripts/run", "scripts/yolo"):
    sys.path.insert(0, str(PROJECT_ROOT / folder))
