"""Sync the pick dataset's item side with its private Hugging Face repo (<namespace>/cleany_pick_items).

The pick dataset is two repos (docs/pick-dataset.md):
  cleany_pick          the LeRobot episodes (scripts/common/dataset_sync.py)
  cleany_pick_items    what says which item is in which episode, and the vision data:
      README.md          this layout
      records.jsonl      one line per kept episode or Other item (session, episode, material, boxes, DINO)
      registry/          objects/ (the object library: train/<id>/ with pictures, test/<id>/item.yaml without)
                         and item_labels.yaml: the objects, their split and each old record's object
      crops/<class>/     gallery crops (DINO)
      yolo/              images/, labels/, classes.txt, frames.jsonl (YOLO training frames)

Usage:
    python items_sync.py <push|pull|status|init> <repo_id> <local_root> [--registry FILE ...] [--force]

push    Copies the --registry files into <local_root>/registry/, then uploads the folder (files deleted
        locally are deleted on the Hub). Refused when the Hub has more records, unless --force.
pull    Downloads into <local_root> (an existing copy is moved to <root>.before_pull); the registry
        files are left in <local_root>/registry/ for you to copy into config/ if you want them.
status  Record counts, local vs Hub.
init    Creates the private repo with its README when it does not exist.
"""

import argparse
import shutil
import sys
from pathlib import Path

README = """---
license: apache-2.0
task_categories:
- robotics
- object-detection
---

# Cleany pick: items, records and vision data

Companion of `{namespace}/cleany_pick` (the LeRobot episodes). Recorded with `scripts/dataset/record_pick.sh`
of the Cleany trash-sorting robot (SO-101 arms, front and wrist camera).

| Path | What |
| --- | --- |
| `records.jsonl` | one line per kept episode or Other item: `session`, `episode` (index in cleany_pick), `material` (metal, plastic, other), `item` as typed, boxes, DINO's opinion |
| `registry/objects/` | the object library: `train/<id>/item.yaml` + pictures, `test/<id>/item.yaml` (held out: never recorded, no pictures here) |
| `registry/item_labels.yaml` | record `time` -> item id, for records made before the library (newer records carry `item_id`) |
| `crops/<class>/` | item crops for the DINO gallery (metal, plastic, other) |
| `yolo/` | front frames with YOLO labels (`images/`, `labels/`, `classes.txt`, `frames.jsonl`) |

The train/test split is by item design: no held-out design appears in any file here.
"""


def count_records(path: Path) -> int | None:
    return sum(1 for line in path.read_text().splitlines() if line.strip()) if path.exists() else None


def stage(root: Path, registry: list[Path]) -> None:
    """Copy the registry (the object library folder and label files) next to the data they describe.
    Held-out objects go as item.yaml only: no picture of a test object is uploaded."""
    target = root / "registry"
    target.mkdir(parents=True, exist_ok=True)
    for file in registry:
        if file.is_dir():
            shutil.rmtree(target / file.name, ignore_errors=True)
            shutil.copytree(file, target / file.name,
                            ignore=lambda d, names: [n for n in names if Path(d).parent.name == "test"
                                                     and n.endswith((".jpg", ".png"))])
        elif file.exists():
            shutil.copy2(file, target / file.name)


def hub_records(repo_id: str) -> int | None:
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import EntryNotFoundError, RepositoryNotFoundError, RevisionNotFoundError

    try:
        return count_records(Path(hf_hub_download(repo_id, "records.jsonl", repo_type="dataset")))
    except (RepositoryNotFoundError, EntryNotFoundError, RevisionNotFoundError):
        return None


def init(repo_id: str) -> None:
    from huggingface_hub import HfApi

    api = HfApi()
    api.create_repo(repo_id, repo_type="dataset", private=True, exist_ok=True)
    api.upload_file(path_or_fileobj=README.format(namespace=repo_id.split("/")[0]).encode(), path_in_repo="README.md",
                    repo_id=repo_id, repo_type="dataset", commit_message="Describe the layout")
    print(f"https://huggingface.co/datasets/{repo_id} (private)")


def push(repo_id: str, root: Path, registry: list[Path], force: bool) -> None:
    from huggingface_hub import HfApi

    local, hub = count_records(root / "records.jsonl"), hub_records(repo_id)
    if local is None:
        sys.exit(f"Error: no records at {root}")
    if hub is not None and hub > local and not force:
        sys.exit(f"Error: the Hub has {hub} records, local has {local}. Pull first, or pass --force.")
    stage(root, registry)
    init(repo_id)
    HfApi().upload_folder(repo_id=repo_id, repo_type="dataset", folder_path=root, ignore_patterns=["README.md"],
                          delete_patterns=["records.jsonl", "registry/**", "crops/**", "yolo/**"],
                          commit_message=f"Sync {local} records")
    print(f"Pushed {local} records to https://huggingface.co/datasets/{repo_id}")


def pull(repo_id: str, root: Path, force: bool) -> None:
    from huggingface_hub import snapshot_download

    local, hub = count_records(root / "records.jsonl"), hub_records(repo_id)
    if hub is None:
        sys.exit(f"Error: {repo_id} not found on the Hub (or you have no access)")
    if local is not None and local > hub and not force:
        sys.exit(f"Error: local has {local} records, the Hub has {hub}. Push first, or pass --force to discard them.")
    if root.exists():
        backup = root.with_name(root.name + ".before_pull")
        shutil.rmtree(backup, ignore_errors=True)
        root.rename(backup)
        print(f"Previous local copy kept at {backup}")
    snapshot_download(repo_id, repo_type="dataset", local_dir=root)
    print(f"Pulled {hub} records into {root}")


def status(repo_id: str, root: Path) -> None:
    local, hub = count_records(root / "records.jsonl"), hub_records(repo_id)
    print(f"{repo_id}: local {local if local is not None else '-'} records, hub {hub if hub is not None else '-'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["push", "pull", "status", "init"])
    parser.add_argument("repo_id")
    parser.add_argument("root", type=Path)
    parser.add_argument("--registry", type=Path, action="append", default=[])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.command == "push":
        push(args.repo_id, args.root, args.registry, args.force)
    elif args.command == "pull":
        pull(args.repo_id, args.root, args.force)
    elif args.command == "init":
        init(args.repo_id)
    else:
        status(args.repo_id, args.root)


if __name__ == "__main__":
    main()
