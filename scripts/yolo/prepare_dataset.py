"""Build the YOLO training dataset from the labeled frames of extract_frames.py.

Usage:
    python prepare_dataset.py [--frames yolo/frames] [--out yolo/dataset_cleany] [--val-every 5]

Takes every frame that has a label file in <frames>/labels (the first frames of the episodes,
one item each) and splits them into train/val. Every --val-every-th episode of each dataset
goes to val, so both classes and every recording session show up in val. Extra frames from
extra_frames.py are added to train, except those of val episodes.

Output (<out>/, rebuilt from scratch on every run):
    images/{train,val}/*.jpg, labels/{train,val}/*.txt
    dataset.yaml    for scripts/yolo/train.sh (classes: 0 metal, 1 plastic)
"""

import argparse
import re
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLASSES = ["metal", "plastic"]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--frames", default="yolo/frames")
    parser.add_argument("--out", default="yolo/dataset_cleany")
    parser.add_argument("--val-every", type=int, default=5)
    parser.add_argument("--extra", default="yolo/frames_extra", help="frames from extra_frames.py, if any")
    args = parser.parse_args()

    frames = PROJECT_ROOT / args.frames
    out = PROJECT_ROOT / args.out
    if out.exists():
        shutil.rmtree(out)

    counts = {"train": [0, 0], "val": [0, 0]}
    for label in sorted((frames / "labels").glob("*.txt")):
        image = frames / "images" / f"{label.stem}.jpg"
        episode = int(re.search(r"_ep(\d+)_", label.name).group(1))
        split = "val" if episode % args.val_every == args.val_every - 1 else "train"
        for kind, src in (("images", image), ("labels", label)):
            (out / kind / split).mkdir(parents=True, exist_ok=True)
            shutil.copy(src, out / kind / split / src.name)
        for line in label.read_text().splitlines():
            counts[split][int(line.split()[0])] += 1

    # Extra frames of the same episodes (extra_frames.py): train only, and only from train
    # episodes, so val never shows an episode the model was trained on
    extra = PROJECT_ROOT / args.extra
    for label in sorted((extra / "labels").glob("*.txt")) if extra.exists() else []:
        episode = int(re.search(r"_ep(\d+)_", label.name).group(1))
        if episode % args.val_every == args.val_every - 1:
            continue
        shutil.copy(label, out / "labels" / "train" / label.name)
        shutil.copy(extra / "images" / f"{label.stem}.jpg", out / "images" / "train" / f"{label.stem}.jpg")
        for line in label.read_text().splitlines():
            counts["train"][int(line.split()[0])] += 1

    (out / "dataset.yaml").write_text(
        f"path: {out}\ntrain: images/train\nval: images/val\n"
        + "names:\n" + "".join(f"  {i}: {name}\n" for i, name in enumerate(CLASSES))
    )
    for split, (metal, plastic) in counts.items():
        print(f"{split}: {metal} metal, {plastic} plastic boxes")
    print(f"-> {out / 'dataset.yaml'}")


if __name__ == "__main__":
    main()
