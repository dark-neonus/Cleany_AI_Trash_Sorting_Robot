"""The pick recorder's LeRobot dataset: opening it, recording episodes into it, and keeping it readable.

Why every episode is checkpointed (2026-11-23): lerobot writes the footers of the dataset's parquet
files (the data and the episode metadata) only when the dataset is finalized, at the end of the
session. A session that ends any other way (the process aborted at exit, was killed, lost power)
left `meta/episodes` missing and the data file without a footer: the dataset could not be opened, and
the next start fell through to a Hugging Face lookup and crashed. save() now finalizes the dataset and
opens it again after every episode (about 0.4 s, in the idle READY state), so whatever happens
later at most the episode being recorded is lost. open_dataset() also sets a dataset that cannot be
read aside (renamed, never deleted) and starts a new one.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import numpy as np
from motor_state import Normaliser, dataset_features, training_state


class DatasetError(RuntimeError):
    pass


def dataset_problem(root: Path) -> str | None:
    """Why the dataset folder cannot be appended to, or None when it is fine (or does not exist)."""
    import pyarrow.parquet as pq

    root = Path(root)
    if not root.exists() or not any(root.iterdir()):
        return None
    info = root / "meta" / "info.json"
    if not info.exists():
        return "no meta/info.json (an incomplete dataset)"
    if json.loads(info.read_text()).get("total_episodes", 0) and not list(root.glob("meta/episodes/*/*.parquet")):
        return "its episode metadata was never written: the session ended before the dataset was finalized"
    for path in [*sorted(root.glob("data/*/*.parquet")), *sorted(root.glob("meta/episodes/*/*.parquet"))]:
        try:
            pq.ParquetFile(path)
        except Exception as error:  # noqa: BLE001
            return f"{path.relative_to(root)} cannot be read ({type(error).__name__}): it was never finalized"
    return None


def open_dataset(cfg: dict, root: Path, cameras: dict[str, tuple[int, int]], embedding_dim: int, say=print,
                 codec: str | None = None):
    """Create or resume the dataset. cameras: name -> (height, width). A dataset with a different set
    of features raises DatasetError; one that cannot be read is renamed away first."""
    from lerobot.configs.video import RGBEncoderConfig
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    root = Path(root)
    features = dataset_features(cameras, embedding_dim)
    encoder = RGBEncoderConfig(vcodec=codec or os.environ.get("VIDEO_CODEC", "h264_nvenc"),
                               crf=int(os.environ.get("VIDEO_QUALITY", "23")),
                               extra_options=json.loads(os.environ.get("VIDEO_EXTRA_OPTIONS", '{"bf": 0}')))
    common = dict(rgb_encoder=encoder, streaming_encoding=True, encoder_threads=2)
    problem = dataset_problem(root)
    if problem is not None:
        moved = root.with_name(f"{root.name}.unusable_{datetime.now():%Y%m%d_%H%M%S}")
        root.rename(moved)
        say(f"The dataset {root} cannot be used: {problem}.\nMoved it to {moved} (nothing was deleted) "
            f"and starting a new one.")
    if (root / "meta" / "info.json").exists():
        dataset = LeRobotDataset.resume(cfg["repo_id"], root=root, **common)
        mismatch = {k for k in features if k not in dataset.features or
                    tuple(dataset.features[k]["shape"]) != tuple(features[k]["shape"])}
        if mismatch:
            raise DatasetError(f"{root} has different features ({sorted(mismatch)}): move it away or change dataset.root")
        say(f"Appending to {root} ({dataset.meta.total_episodes} episodes)")
    else:
        dataset = LeRobotDataset.create(cfg["repo_id"], cfg["fps"], features, root=root, robot_type="so101_follower",
                                        use_videos=True, **common)
        say(f"New dataset at {root}")
    return dataset


class DatasetRecorder:
    """Episodes of the LeRobot dataset; an episode stays in the buffer until save() or cancel().

    reopen(): opens the dataset again (open_dataset with the session's arguments); save() uses it to
    checkpoint after every episode, see the module docstring."""

    def __init__(self, dataset, follower_norm: Normaliser, leader_norm: Normaliser, protection_current: float,
                 cameras: list[str], reopen=None):
        self.dataset, self.fn, self.ln, self.protection = dataset, follower_norm, leader_norm, protection_current
        self.cameras, self.reopen = cameras, reopen
        self.task, self.item = None, None

    def begin(self, task: str, item: dict):
        if self.dataset.has_pending_frames():
            self.dataset.clear_episode_buffer()
        dim = self.dataset.features["item.embedding"]["shape"][0]
        embedding = item["embedding"] if item["embedding"] is not None else np.zeros(dim, np.float32)
        self.task = task
        self.item = {"item.embedding": np.asarray(embedding, np.float32),
                     "item.box": np.asarray(item["box"], np.float32)}

    def add(self, obs: dict, action: dict, extras: dict):
        positions = self.fn.positions(obs)
        frame = {"observation.state": training_state(positions, extras, self.protection),
                 "action": self.ln.positions(action),
                 **{f"observation.images.{c}": obs[c] for c in self.cameras},
                 **{f"motors.{k}": v for k, v in extras.items()},
                 **self.item, "task": self.task}
        self.dataset.add_frame(frame)

    def cancel(self):
        if self.dataset.has_pending_frames():
            self.dataset.clear_episode_buffer()

    def save(self) -> int:
        """Save the episode and make the dataset readable on disk (footers written), returns its index."""
        self.dataset.save_episode()
        index = self.dataset.meta.total_episodes - 1
        if self.reopen is not None:
            self.dataset.finalize()
            self.dataset = self.reopen()
        return index

    def close(self):
        self.dataset.finalize()
