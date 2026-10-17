"""Sync a local LeRobot dataset with a private Hugging Face Hub dataset repo.

Usage:
    python dataset_sync.py <push|pull|status> <repo_id> <local_root> [--force]

The Hub repo is the shared copy. Episode counts are compared before every transfer so
an older copy never overwrites a newer one; --force skips that check.

push    Upload the local dataset. Files deleted locally (e.g. by delete_last_episode.sh)
        are deleted on the Hub too, and the repo gets the LeRobot version tag that
        LeRobotDataset needs to load it from the Hub.
pull    Download the Hub dataset. An existing local copy is moved to <root>.before_pull.
status  Print local and Hub episode counts.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download, snapshot_download
from huggingface_hub.errors import EntryNotFoundError, RepositoryNotFoundError, RevisionNotFoundError

from lerobot.datasets.dataset_metadata import CODEBASE_VERSION, LeRobotDatasetMetadata
from lerobot.datasets.utils import create_lerobot_dataset_card

INFO_PATH = "meta/info.json"


def local_episodes(root: Path) -> int | None:
    info = root / INFO_PATH
    return json.loads(info.read_text())["total_episodes"] if info.exists() else None


def hub_episodes(repo_id: str) -> int | None:
    try:
        # No force_download: it wraps these errors in a ValueError. The cache is revalidated anyway.
        path = hf_hub_download(repo_id, INFO_PATH, repo_type="dataset")
    except (RepositoryNotFoundError, EntryNotFoundError, RevisionNotFoundError):
        return None
    return json.loads(Path(path).read_text())["total_episodes"]


def push(repo_id: str, root: Path, force: bool) -> None:
    local, hub = local_episodes(root), hub_episodes(repo_id)
    if local is None:
        sys.exit(f"Error: no dataset at {root}")
    if hub is not None and hub > local and not force:
        sys.exit(
            f"Error: the Hub has {hub} episodes, local has {local}. Pull first, or pass --force "
            "if you deleted episodes on purpose."
        )

    api = HfApi()
    api.create_repo(repo_id, repo_type="dataset", private=True, exist_ok=True)
    api.upload_folder(
        repo_id=repo_id,
        repo_type="dataset",
        folder_path=root,
        ignore_patterns=["images/**"],
        delete_patterns=["data/**", "meta/**", "videos/**"],
        commit_message=f"Sync {local} episodes",
    )

    info = LeRobotDatasetMetadata(repo_id, root=root).info
    create_lerobot_dataset_card(dataset_info=info, license="apache-2.0", repo_id=repo_id).push_to_hub(
        repo_id=repo_id, repo_type="dataset"
    )
    try:
        api.delete_tag(repo_id, tag=CODEBASE_VERSION, repo_type="dataset")
    except RevisionNotFoundError:
        pass
    api.create_tag(repo_id, tag=CODEBASE_VERSION, repo_type="dataset")
    print(f"Pushed {local} episodes to https://huggingface.co/datasets/{repo_id}")


def pull(repo_id: str, root: Path, force: bool) -> None:
    local, hub = local_episodes(root), hub_episodes(repo_id)
    if hub is None:
        sys.exit(f"Error: {repo_id} not found on the Hub (or you have no access)")
    if local is not None and local > hub and not force:
        sys.exit(f"Error: local has {local} episodes, the Hub has {hub}. Push first, or pass --force to discard them.")

    if root.exists():
        backup = root.with_name(root.name + ".before_pull")
        shutil.rmtree(backup, ignore_errors=True)
        root.rename(backup)
        print(f"Previous local copy kept at {backup}")
    snapshot_download(repo_id, repo_type="dataset", local_dir=root)
    print(f"Pulled {hub} episodes into {root}")


def status(repo_id: str, root: Path) -> None:
    local, hub = local_episodes(root), hub_episodes(repo_id)
    print(f"{repo_id}: local {local if local is not None else '-'}, hub {hub if hub is not None else '-'}")
    if hub is None:
        print("  not on the Hub yet (created on the first push), or no access: check `hf auth whoami`")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["push", "pull", "status"])
    parser.add_argument("repo_id")
    parser.add_argument("root", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.command == "push":
        push(args.repo_id, args.root, args.force)
    elif args.command == "pull":
        pull(args.repo_id, args.root, args.force)
    else:
        status(args.repo_id, args.root)


if __name__ == "__main__":
    main()
