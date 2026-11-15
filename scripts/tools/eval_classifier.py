"""Check the box pipeline's DINO classifier on a folder of labelled photos, e.g. the Kaggle
Garbage Classification dataset (mostafaabla/garbage-classification, 12 classes).

Usage:
    python eval_classifier.py --test DIR [--gallery models/dino/gallery.npz] [--in-domain]

DIR/<class>/*.jpg: `metal` and `plastic` must go to their bin, every other folder (paper, glass,
clothes, ...) is an item the classifier has never seen and must come out as `other`. Each photo
is one item, so the whole image is the crop.

  default      the stored gallery (our frames) against the test photos: does it transfer to
               other photos, and does it keep unknown items out of the bins?
  --in-domain  a gallery from half of the test set's metal and plastic photos (seeded split)
               against the other half plus all other classes: open-set rejection without the
               camera/domain gap, with every photo a different item.
  --other-examples N  with --in-domain: also put N photos of every unknown class into the
               gallery as `other` (as a box gallery with some known non-recyclables would be);
               those photos are left out of the test.

Prints, per max_distance: sortable photos in the right bin / wrong bin / sent to other, and per
unknown class the share kept out of the bins.
"""

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "common"))
from box_logic import load_yaml  # noqa: E402
from dino_classifier import Embedder, Gallery, decide  # noqa: E402

SORTABLE = ("metal", "plastic")


def load_images(root: Path, per_class: int, rng) -> tuple[list, list]:
    images, labels = [], []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        files = sorted(f for f in folder.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png"))
        if folder.name not in SORTABLE and len(files) > per_class:
            files = list(rng.choice(files, per_class, replace=False))
        for f in files:
            image = cv2.imread(str(f))
            if image is not None:
                images.append(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
                labels.append(folder.name)
    return images, labels


def report(embeddings, labels, gallery: Gallery, k: int, margin: float, distances):
    labels = np.array(labels)
    unknown = sorted(set(labels) - set(SORTABLE))
    print(f"\n{'max_dist':>8}  {'right bin':>9}  {'wrong bin':>9}  {'-> other':>8}  {'unknown kept out':>16}  "
          + "  ".join(f"{u[:11]:>11}" for u in unknown))
    for max_distance in distances:
        got = np.array([decide(e, gallery, k, max_distance, margin).cls for e in embeddings])
        s = np.isin(labels, SORTABLE)
        right = np.mean(got[s] == labels[s])
        wrong = np.mean(np.isin(got[s], SORTABLE) & (got[s] != labels[s]))
        rejected = np.mean(got[s] == "other")
        kept = np.mean(got[~s] == "other") if (~s).any() else float("nan")
        per = "  ".join(f"{np.mean(got[labels == u] == 'other'):>11.0%}" for u in unknown)
        print(f"{max_distance:>8.2f}  {right:>9.1%}  {wrong:>9.1%}  {rejected:>8.1%}  {kept:>16.1%}  {per}")


def main():
    config = load_yaml(PROJECT_ROOT / "config" / "box_pipeline.yaml")["classifier"]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--test", type=Path, required=True)
    parser.add_argument("--gallery", type=Path, default=PROJECT_ROOT / config["gallery"])
    parser.add_argument("--in-domain", action="store_true")
    parser.add_argument("--other-examples", type=int, default=0)
    parser.add_argument("--per-class", type=int, default=150, help="photos per unknown class (all metal/plastic)")
    parser.add_argument("--distances", type=float, nargs="+", default=[0.2, 0.25, 0.3, 0.35, 0.4, 0.5])
    parser.add_argument("--device", default=None)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    import torch

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    rng = np.random.default_rng(args.seed)
    images, labels = load_images(args.test, args.per_class, rng)
    counts = {c: labels.count(c) for c in sorted(set(labels))}
    print(f"{len(images)} photos: " + ", ".join(f"{c} {n}" for c, n in counts.items()))

    embedder = Embedder(config["backbone"], config.get("fallback_backbone"), device)
    print(f"Backbone: {embedder.backbone}")
    embeddings = embedder(images)
    labels = np.array(labels)

    if args.in_domain:
        sortable = np.flatnonzero(np.isin(labels, SORTABLE))
        in_gallery = np.zeros(len(labels), bool)
        in_gallery[rng.choice(sortable, len(sortable) // 2, replace=False)] = True
        for cls in set(labels) - set(SORTABLE):
            if args.other_examples:
                in_gallery[rng.choice(np.flatnonzero(labels == cls), args.other_examples, replace=False)] = True
        names = np.where(np.isin(labels, SORTABLE), labels, "other")
        gallery = Gallery(embeddings[in_gallery], names[in_gallery], labels[in_gallery], embedder.backbone)
        embeddings, labels = embeddings[~in_gallery], labels[~in_gallery]
        print(f"In-domain: gallery of {in_gallery.sum()} photos ({args.other_examples} per unknown class as other), "
              f"{len(labels)} test photos")
    else:
        gallery = Gallery.load(args.gallery)
        if gallery.backbone != embedder.backbone:
            sys.exit(f"Gallery built with {gallery.backbone}, loaded {embedder.backbone}: rebuild it")
        print(f"Gallery: {args.gallery} ({len(gallery.labels)} crops)")
    report(embeddings, labels, gallery, config.get("k", 5), config["min_margin"], args.distances)


if __name__ == "__main__":
    main()
