"""Render the training image augmentations on frames of one recorded episode.

Usage:
    python preview_augmentation.py <repo_id> <dataset_root> <episode> <output_dir>

Reads the same transforms as training (scripts/config/augmentation.json). For every camera it
writes one image: rows are the original frame, each augmentation at the low and high end of its
range, grayscale, and two random combinations exactly as training samples them; columns are
frames from the start, middle and end of the episode.
"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np
import torch

from lerobot.configs.default import DatasetConfig
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.transforms.transforms import ImageTransformConfig, ImageTransforms, make_transform_from_config

AUGMENTATION_CONFIG = Path(__file__).resolve().parents[1] / "config" / "augmentation.json"
TILE_WIDTH = 320
LABEL_WIDTH = 190


def variants(tfs: dict) -> list[tuple[str, object]]:
    """(label, transform) pairs: each transform pinned to both ends of its range, plus random combos."""
    rows: list[tuple[str, object]] = [("original", None)]
    for name, spec in tfs.items():
        ranges = {k: v for k, v in spec["kwargs"].items() if isinstance(v, list) and len(v) == 2}
        if not ranges:  # no parameter range, e.g. grayscale
            rows.append((name, make_transform_from_config(ImageTransformConfig(**spec))))
            continue
        for end, label in ((0, "low"), (1, "high")):
            kwargs = {k: (v[end], v[end]) for k, v in ranges.items()}
            pinned = ImageTransformConfig(weight=spec["weight"], type=spec["type"], kwargs={**spec["kwargs"], **kwargs})
            value = ", ".join(f"{v[end]:g}" for v in ranges.values())
            rows.append((f"{name} {label} ({value})", make_transform_from_config(pinned)))
    random_cfg = DatasetConfig(repo_id="x").image_transforms
    random_cfg.enable = True
    random_cfg.tfs = {name: ImageTransformConfig(**spec) for name, spec in tfs.items()}
    combined = ImageTransforms(random_cfg)
    rows += [("random (training) 1", combined), ("random (training) 2", combined)]
    return rows


def to_tile(image: torch.Tensor) -> np.ndarray:
    """CHW float RGB in [0, 1] -> HWC uint8 BGR, resized to TILE_WIDTH."""
    array = (image.clamp(0, 1).permute(1, 2, 0).numpy()[:, :, ::-1] * 255).astype(np.uint8)
    height = round(array.shape[0] * TILE_WIDTH / array.shape[1])
    return cv2.resize(array, (TILE_WIDTH, height), interpolation=cv2.INTER_AREA)


def label_cell(text: str, height: int) -> np.ndarray:
    cell = np.full((height, LABEL_WIDTH, 3), 255, np.uint8)
    cv2.putText(cell, text, (8, height // 2 + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    return cell


def column_header(text: str) -> np.ndarray:
    cell = np.full((28, TILE_WIDTH, 3), 255, np.uint8)
    cv2.putText(cell, text, (8, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    return cell


def main() -> None:
    repo_id, root, episode, output_dir = sys.argv[1], sys.argv[2], int(sys.argv[3]), Path(sys.argv[4])
    output_dir.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(0)

    dataset = LeRobotDataset(repo_id, root=root, episodes=[episode])
    frame_indices = [round(len(dataset) * f) for f in (0.1, 0.5, 0.9)]
    frames = [dataset[i] for i in frame_indices]
    rows = variants(json.loads(AUGMENTATION_CONFIG.read_text()))
    model = Path(root).name.removeprefix("cleany_")

    for camera in dataset.meta.camera_keys:
        originals = [frame[camera] for frame in frames]
        tile_height = to_tile(originals[0]).shape[0]
        header = [label_cell(f"{model} episode {episode}", 28)] + [
            column_header(f"frame {frame['frame_index'].item()} / {len(dataset)}") for frame in frames
        ]
        grid = [np.hstack(header)]
        for label, transform in rows:
            tiles = [to_tile(image if transform is None else transform(image)) for image in originals]
            grid.append(np.hstack([label_cell(label, tile_height)] + tiles))
        name = camera.removeprefix("observation.images.")
        path = output_dir / f"{model}_episode{episode}_{name}.jpg"
        cv2.imwrite(str(path), np.vstack(grid))
        print(f"Saved {path}")


if __name__ == "__main__":
    main()
