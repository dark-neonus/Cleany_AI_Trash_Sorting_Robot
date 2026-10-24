"""Resolve a model name from config/default.yaml to what a script can load.

Usage:
    python models.py <name>        # e.g. yolo, yolo_base, act_plastic

Prints a Hub repo id as is (LeRobot downloads ACT models itself) and downloads a
"<repo id>/<file>" entry, printing the local path of the file in the Hugging Face cache.
A local path (an existing file or folder) is printed unchanged, so config entries may also
point at a checkpoint on disk.
"""

import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG = PROJECT_ROOT / "config" / "default.yaml"


def resolve(spec: str) -> str:
    if (PROJECT_ROOT / spec).exists() or Path(spec).exists():
        return spec
    parts = spec.split("/")
    if len(parts) == 2:  # "<owner>/<repo>": a model repo, loaded by repo id
        return spec
    if len(parts) >= 3:  # "<owner>/<repo>/<file in repo>"
        from huggingface_hub import hf_hub_download

        return hf_hub_download("/".join(parts[:2]), "/".join(parts[2:]))
    raise ValueError(f"Not a local path, a repo id or a '<repo id>/<file>': {spec}")


def model(name: str) -> str:
    models = yaml.safe_load(CONFIG.read_text())["models"]
    if name not in models:
        raise KeyError(f"No model '{name}' in {CONFIG} (have: {', '.join(models)})")
    return resolve(models[name])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(model(sys.argv[1]))
