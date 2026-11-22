"""Build the DINO gallery of the box pipeline's classifier and check it on held-out items.

Usage (through scripts/tools/build_gallery.sh):
    python build_gallery.py [--yolo-dataset DIR] [--crops DIR] [--output models/dino/gallery.npz]

Sources (any mix):
  --yolo-dataset DIR  a YOLO dataset (images/<split>, labels/<split>, dataset.yaml): every
                      labelled box is cropped. Group: the episode in the file name
                      (cleany_metal_ep003_t1.0.jpg -> metal_ep003).
  --crops DIR         DIR/<class>/<item>_<n>.jpg crops, class metal, plastic or other. Group: the
                      part of the file name before the last "_", so name the files by item
                      (cola_can_01.jpg, cola_can_02.jpg, ...) to evaluate on unseen items.
                      Crops of held-out test items (config/items.yaml, item_labels.yaml) are
                      skipped (docs/collection-plan.md); a labelled crop is grouped by its item id.
                      DIR/generic/ (Pick other objects) is not a gallery class and is left out.

Evaluation: every group is held out in turn and its crops are classified against the rest, at
several max_distance values. With --yolo-dataset only, the same cans appear in several
episodes, so the numbers are optimistic (docs/pipeline-proposal.md); use --crops with item
names and `other` items from the box for real numbers.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "common"))
from box_logic import crop_box, load_yaml  # noqa: E402
from dino_classifier import Embedder, Gallery, decide  # noqa: E402
from item_registry import Registry  # noqa: E402

CLASSES = ("metal", "plastic", "other")


def yolo_crops(root: Path, pad: float):
    names = yaml.safe_load((root / "dataset.yaml").read_text())["names"]
    for label in sorted(root.glob("labels/*/*.txt")):
        image_path = next(root.glob(f"images/{label.parent.name}/{label.stem}.*"), None)
        if image_path is None:
            continue
        image = cv2.cvtColor(cv2.imread(str(image_path)), cv2.COLOR_BGR2RGB)
        h, w = image.shape[:2]
        image = cv2.resize(image, (640, 480)) if (w, h) != (640, 480) else image
        parts = label.stem.split("_")  # cleany_metal_ep000_t1.0
        group = "_".join(parts[1:3]) if len(parts) >= 3 else label.stem
        for line in label.read_text().split("\n"):
            if not line.strip():
                continue
            cls, cx, cy, bw, bh = line.split()[:5]
            cx, cy, bw, bh = float(cx) * 640, float(cy) * 480, float(bw) * 640, float(bh) * 480
            crop = crop_box(image, [cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], pad)
            if crop is not None and names[int(cls)] in CLASSES:
                yield crop, names[int(cls)], group


def folder_crops(root: Path, registry: Registry | None = None, skipped: list | None = None):
    registry = registry or Registry()
    for cls in CLASSES:
        for path in sorted((root / cls).glob("*")):
            if path.suffix.lower() in (".jpg", ".jpeg", ".png"):
                group, _, time = path.stem.rpartition("_")
                group = group or path.stem
                item = registry.resolve(time, group) or registry.held_out(group)
                if item is not None and item.split == "test":
                    if skipped is not None:
                        skipped.append(path)
                    continue
                if item is not None:
                    group = item.id
                yield cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB), cls, f"{cls}/{group}"


def evaluate(gallery: Gallery, k: int, margin: float, distances=(0.2, 0.25, 0.3, 0.35, 0.4, 0.5)):
    groups = np.unique(gallery.groups)
    print(f"\nHeld-out evaluation: each of {len(groups)} groups against the others (k={k}, min_margin={margin})")
    print(f"{'max_distance':>12}  {'correct':>8}  {'wrong bin':>9}  {'-> other':>8}  {'other kept out':>14}")
    for max_distance in distances:
        counts = Counter()
        for group in groups:
            held = gallery.groups == group
            rest = gallery.subset(~held)
            for emb, truth in zip(gallery.embeddings[held], gallery.labels[held]):
                got = decide(emb, rest, k, max_distance, margin).cls
                if truth == "other":
                    counts["other_total"] += 1
                    counts["other_ok"] += got == "other"
                else:
                    counts["sortable"] += 1
                    counts["correct"] += got == truth
                    counts["wrong"] += got not in (truth, "other")
                    counts["rejected"] += got == "other"
        n = max(counts["sortable"], 1)
        other = (f"{counts['other_ok']}/{counts['other_total']}" if counts["other_total"] else "no examples")
        print(f"{max_distance:>12.2f}  {counts['correct'] / n:>8.1%}  {counts['wrong'] / n:>9.1%}  "
              f"{counts['rejected'] / n:>8.1%}  {other:>14}")
    print("Pick the largest max_distance with an acceptable wrong-bin rate and set it in config/box_pipeline.yaml.")


def main():
    config = load_yaml(PROJECT_ROOT / "config" / "box_pipeline.yaml")["classifier"]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yolo-dataset", type=Path)
    parser.add_argument("--crops", type=Path)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / config["gallery"])
    parser.add_argument("--device", default=None)
    parser.add_argument("--items", type=Path, default=PROJECT_ROOT / "config" / "items.yaml",
                        help="item registry: held-out test items are skipped")
    parser.add_argument("--labels", type=Path, default=PROJECT_ROOT / "config" / "item_labels.yaml")
    args = parser.parse_args()
    if not args.yolo_dataset and not args.crops:
        sys.exit("Give --yolo-dataset and/or --crops")

    import torch

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    samples = []
    if args.yolo_dataset:
        samples += list(yolo_crops(args.yolo_dataset, config.get("crop_pad", 0.15)))
    if args.crops:
        skipped = []
        samples += list(folder_crops(args.crops, Registry.load(args.items, args.labels), skipped))
        if skipped:
            print(f"Skipped {len(skipped)} crops of held-out test items")
    if not samples:
        sys.exit("No crops found")
    crops, labels, groups = zip(*samples)
    print(f"{len(crops)} crops: " + ", ".join(f"{c} {n}" for c, n in sorted(Counter(labels).items())))

    embedder = Embedder(config["backbone"], config.get("fallback_backbone"), device)
    print(f"Backbone: {embedder.backbone}")
    gallery = Gallery(embedder(list(crops)), np.array(labels), np.array(groups), embedder.backbone)
    gallery.save(args.output)
    print(f"Saved {args.output}")
    evaluate(gallery, config.get("k", 5), config["min_margin"])


if __name__ == "__main__":
    main()
