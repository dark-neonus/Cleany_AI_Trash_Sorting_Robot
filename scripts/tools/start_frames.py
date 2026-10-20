"""Grid of the first front (ambient) camera frame of every episode in a dataset.

Usage:
    python start_frames.py <repo_id> <dataset_root> <output_image> [--columns N] [--camera KEY]

One look shows where the items started in all episodes, so missing start positions (and
episodes that started wrongly) are easy to spot. Each tile is labelled with its episode index,
the number to use with scripts/dataset/view.sh or the episode deletion command.
"""

import argparse
from pathlib import Path

import cv2
import numpy as np

from lerobot.datasets.lerobot_dataset import LeRobotDataset

TILE_WIDTH = 240


def to_tile(image, label: str) -> np.ndarray:
    """CHW float RGB in [0, 1] -> labelled HWC uint8 BGR tile."""
    array = (image.clamp(0, 1).permute(1, 2, 0).numpy()[:, :, ::-1] * 255).astype(np.uint8)
    height = round(array.shape[0] * TILE_WIDTH / array.shape[1])
    tile = cv2.resize(array, (TILE_WIDTH, height), interpolation=cv2.INTER_AREA)
    cv2.rectangle(tile, (0, 0), (8 + 11 * len(label), 22), (0, 0, 0), -1)
    cv2.putText(tile, label, (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return cv2.copyMakeBorder(tile, 2, 2, 2, 2, cv2.BORDER_CONSTANT, value=(255, 255, 255))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repo_id")
    parser.add_argument("root")
    parser.add_argument("output", type=Path)
    parser.add_argument("--columns", type=int, default=10)
    parser.add_argument("--camera", default="observation.images.front")
    args = parser.parse_args()

    dataset = LeRobotDataset(args.repo_id, root=args.root)
    episodes = dataset.meta.episodes
    tiles = []
    for episode in episodes:
        frame = dataset[int(episode["dataset_from_index"])]
        tiles.append(to_tile(frame[args.camera], f"ep {episode['episode_index']}"))

    # Pad the last row with blank tiles so the grid is rectangular
    blank = np.full_like(tiles[0], 255)
    tiles += [blank] * (-len(tiles) % args.columns)
    rows = [np.hstack(tiles[i:i + args.columns]) for i in range(0, len(tiles), args.columns)]
    grid = np.vstack(rows)

    title = f"{Path(args.root).name}: first {args.camera.split('.')[-1]} frame of {len(episodes)} episodes"
    header = np.full((36, grid.shape[1], 3), 255, np.uint8)
    cv2.putText(header, title, (8, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2, cv2.LINE_AA)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.output), np.vstack([header, grid]))
    print(f"Saved {args.output} ({len(episodes)} episodes)")


if __name__ == "__main__":
    main()
