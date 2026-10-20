"""Add more labeled frames per episode: the frames before the arm reaches the item.

Usage:
    python extra_frames.py [--frames yolo/frames] [--out yolo/frames_extra] [--per-episode 4]

Until the arm touches it, the item lies where it was in the episode's first frame, so the
first frame's label (yolo/frames/labels/<dataset>_ep<NNN>_first.txt) is valid for those
frames too. They add views with the arm in different poses. A frame is taken every second
from 1 s on, and the episode stops as soon as the image inside the item's box changes
(mean grayscale difference > --max-diff), i.e. the arm got there or the item moved.

Output: <out>/images/<dataset>_ep<NNN>_t<sec>.jpg and <out>/labels/<same>.txt.
prepare_dataset.py adds them to train (never to val).
"""

import argparse
import json
import re
import shutil
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from lerobot.datasets.video_utils import decode_video_frames

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CAMERA_KEY = "observation.images.front"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--frames", default="yolo/frames")
    parser.add_argument("--out", default="yolo/frames_extra")
    parser.add_argument("--per-episode", type=int, default=4)
    parser.add_argument("--max-diff", type=float, default=6.0)
    args = parser.parse_args()

    frames = PROJECT_ROOT / args.frames
    out = PROJECT_ROOT / args.out
    if out.exists():
        shutil.rmtree(out)
    (out / "images").mkdir(parents=True)
    (out / "labels").mkdir()

    labels = {lab.name.removesuffix("_first.txt"): lab for lab in (frames / "labels").glob("*_first.txt")}
    total = 0
    for dataset in sorted({re.sub(r"_ep\d+$", "", key) for key in labels}):
        root = PROJECT_ROOT / "data" / dataset
        info = json.loads((root / "meta/info.json").read_text())
        episodes = pd.concat(pd.read_parquet(f) for f in sorted((root / "meta/episodes").glob("*/*.parquet")))
        prefix = f"videos/{CAMERA_KEY}"
        for _, ep in episodes.iterrows():
            key = f"{dataset}_ep{int(ep['episode_index']):03d}"
            if key not in labels:
                continue
            label_text = labels[key].read_text()
            video = root / info["video_path"].format(
                video_key=CAMERA_KEY,
                chunk_index=int(ep[f"{prefix}/chunk_index"]),
                file_index=int(ep[f"{prefix}/file_index"]),
            )
            start = float(ep[f"{prefix}/from_timestamp"])
            seconds = [0.5 * k for k in range(1, 13)]  # check every 0.5 s up to 6 s
            decoded = decode_video_frames(video, [start] + [start + s for s in seconds],
                                          tolerance_s=0.02, backend="pyav", return_uint8=True)
            images = decoded.permute(0, 2, 3, 1).numpy()
            height, width = images.shape[1:3]
            gray = [cv2.cvtColor(im, cv2.COLOR_RGB2GRAY).astype(np.float32) for im in images]

            # Union of the item boxes in the label, padded a little
            x0, y0, x1, y1 = width, height, 0, 0
            for line in label_text.splitlines():
                _, cx, cy, w, h = map(float, line.split())
                x0, y0 = min(x0, (cx - w / 2) * width), min(y0, (cy - h / 2) * height)
                x1, y1 = max(x1, (cx + w / 2) * width), max(y1, (cy + h / 2) * height)
            ya, yb = max(0, int(y0) - 8), min(height, int(y1) + 8)
            xa, xb = max(0, int(x0) - 8), min(width, int(x1) + 8)

            kept = 0
            for second, image, g in zip(seconds, images[1:], gray[1:]):
                if np.abs(g[ya:yb, xa:xb] - gray[0][ya:yb, xa:xb]).mean() > args.max_diff:
                    break
                if second % 1 == 0 and kept < args.per_episode:
                    stem = f"{key}_t{second:.1f}"
                    cv2.imwrite(str(out / "images" / f"{stem}.jpg"), cv2.cvtColor(image, cv2.COLOR_RGB2BGR),
                                [cv2.IMWRITE_JPEG_QUALITY, 95])
                    (out / "labels" / f"{stem}.txt").write_text(label_text)
                    kept += 1
            total += kept
    print(f"{total} extra frames -> {out}")


if __name__ == "__main__":
    main()
