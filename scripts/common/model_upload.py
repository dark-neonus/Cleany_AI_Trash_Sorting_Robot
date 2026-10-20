"""Upload one trained checkpoint to a private Hugging Face model repo.

Usage:
    python model_upload.py <checkpoint_dir> <repo_prefix> [--dry-run]

The repo is named <repo_prefix>_<YYYYmmdd_HHMM>, the time the checkpoint's last training step
finished (from cleany_info.json written by train_with_controls.py; for older checkpoints the
time model.safetensors was written). It gets the checkpoint's pretrained_model/ folder, which is
everything needed to run the policy (--policy.path=<repo>), plus a short model card. Optimizer
state is not uploaded.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from huggingface_hub import HfApi

INFO_FILE = "cleany_info.json"


def checkpoint_info(checkpoint_dir: Path) -> dict:
    info_path = checkpoint_dir / INFO_FILE
    if info_path.exists():
        info = json.loads(info_path.read_text())
        info["finished_at"] = datetime.fromisoformat(info["finished_at"])
        return info
    weights = checkpoint_dir / "pretrained_model" / "model.safetensors"
    return {"step": int(checkpoint_dir.name), "finished_at": datetime.fromtimestamp(weights.stat().st_mtime).astimezone()}


def model_card(repo_id: str, info: dict, train_config: dict, run_name: str) -> str:
    dataset = train_config.get("dataset", {})
    augment = dataset.get("image_transforms", {}).get("enable", False)
    return f"""---
library_name: lerobot
tags: [lerobot, act, robotics, cleany]
---
# {repo_id.split("/")[-1]}

ACT policy for the Cleany trash sorting robot (SO-101 arm).

| | |
| --- | --- |
| Setup | `{repo_id.split("/")[-1].split("_act_")[0]}`: only valid for this physical setup |
| Dataset | `{dataset.get("repo_id")}` |
| Training step | {info["step"]} of {train_config.get("steps")} |
| Last training step finished | {info["finished_at"].isoformat(timespec="minutes")} |
| Image augmentation | {"on" if augment else "off"} |
| Batch size | {train_config.get("batch_size")} |
| Training run | `{run_name}` |

Run it with `--policy.path={repo_id}`.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("checkpoint_dir", type=Path)
    parser.add_argument("repo_prefix", help="e.g. cleany-ai/setupv2_act_plastic")
    parser.add_argument("--dry-run", action="store_true", help="print what would be uploaded, upload nothing")
    args = parser.parse_args()

    checkpoint_dir = args.checkpoint_dir.resolve()
    model_dir = checkpoint_dir / "pretrained_model"
    if not (model_dir / "model.safetensors").exists():
        sys.exit(f"Error: no model in {model_dir}")

    info = checkpoint_info(checkpoint_dir)
    repo_id = f"{args.repo_prefix}_{info['finished_at']:%Y%m%d_%H%M}"
    train_config = json.loads((model_dir / "train_config.json").read_text())
    run_name = checkpoint_dir.parent.parent.name
    card = model_card(repo_id, info, train_config, run_name)

    print(f"Checkpoint: {checkpoint_dir} (step {info['step']}, finished {info['finished_at']:%Y-%m-%d %H:%M})")
    print(f"Repo:       https://huggingface.co/{repo_id} (private)")
    print(f"Files:      {', '.join(sorted(p.name for p in model_dir.iterdir()))}, README.md")

    api = HfApi()
    # Names have minute resolution: never silently replace a model uploaded under the same name.
    if api.repo_exists(repo_id, repo_type="model"):
        sys.exit(f"Error: {repo_id} already exists on the Hub (same checkpoint uploaded before, or another "
                 "checkpoint finished in the same minute). Nothing uploaded.")
    if args.dry_run:
        print("Dry run: nothing uploaded.")
        return

    api.create_repo(repo_id, repo_type="model", private=True)
    api.upload_folder(repo_id=repo_id, repo_type="model", folder_path=model_dir,
                      commit_message=f"Upload {run_name} step {info['step']}")
    api.upload_file(repo_id=repo_id, repo_type="model", path_or_fileobj=card.encode(), path_in_repo="README.md",
                    commit_message="Add model card")
    print(f"Uploaded. Use it with: --policy.path={repo_id}")


if __name__ == "__main__":
    main()
