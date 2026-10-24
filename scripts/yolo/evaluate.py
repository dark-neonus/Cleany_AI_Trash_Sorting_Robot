"""Evaluate YOLO models on the held-out frames and the unseen test photo; write results/.

Usage:
    python evaluate.py [--frames yolo/frames] [--models kaggle=yolo_base cleany=yolo]

--frames is a copy of the cleany-ai/cleany_yolo_frames dataset (labelled first frames in
images/ + labels/, the test photo in test/). Validation = every 5th episode's first frame,
the same split prepare_dataset.py uses, so no model saw these frames in training.
A model is a name from config/default.yaml or a .pt path.

Writes results/metrics.json (metrics + environment), results/figures/yolo_confusion_matrix.png
(val, last model) and results/figures/yolo_test_photo.jpg (test-photo detections of each model).
"""

import argparse
import json
import platform
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "common"))
from models import model as configured_model  # noqa: E402

VAL_EVERY = 5


def iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def build_eval_sets(frames: Path, work: Path) -> tuple[Path, Path]:
    """YOLO dataset yamls for the val frames and the test photo."""
    if work.exists():
        shutil.rmtree(work)
    for split, files in (("val", sorted((frames / "labels").glob("*_first.txt"))),
                         ("test", sorted((frames / "test" / "labels").glob("*.txt")))):
        for label in files:
            if split == "val" and int(re.search(r"_ep(\d+)_", label.name).group(1)) % VAL_EVERY != VAL_EVERY - 1:
                continue
            image = label.parent.parent / "images" / f"{label.stem}.jpg"
            (work / split / "images").mkdir(parents=True, exist_ok=True)
            (work / split / "labels").mkdir(parents=True, exist_ok=True)
            shutil.copy(image, work / split / "images" / image.name)
            shutil.copy(label, work / split / "labels" / label.name)
    yamls = []
    for split in ("val", "test"):
        if not (work / split / "images").exists():
            sys.exit(f"No {split} frames found in {frames} (expected labels/*_first.txt and test/labels/)")
        path = work / f"{split}.yaml"
        path.write_text(f"path: {work / split}\ntrain: images\nval: images\nnames:\n  0: metal\n  1: plastic\n")
        yamls.append(path)
    return yamls[0], yamls[1]


def test_photo_counts(model, test_dir: Path, conf: float = 0.25) -> dict:
    """Items found with the right class at conf >= 0.25 (IoU >= 0.5 with a label), and extras."""
    image_path = next((test_dir / "images").glob("*.jpg"))
    image = cv2.imread(str(image_path))
    h, w = image.shape[:2]
    truth = []
    for line in (test_dir / "labels" / f"{image_path.stem}.txt").read_text().splitlines():
        c, cx, cy, bw, bh = map(float, line.split())
        truth.append((int(c), ((cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h)))
    result = model.predict(image, conf=conf, verbose=False)[0]
    preds = [(model.names[int(c)], b) for c, b in zip(result.boxes.cls.tolist(), result.boxes.xyxy.tolist())]
    names = {0: "metal", 1: "plastic"}
    matched = set()
    correct = 0
    for cls, box in truth:
        best = max(range(len(preds)), key=lambda i: iou(box, preds[i][1]), default=None)
        if best is not None and best not in matched and iou(box, preds[best][1]) >= 0.5:
            matched.add(best)
            correct += preds[best][0] == names[cls]
    return {"items": len(truth), "found_right_class": correct, "found_wrong_class": len(matched) - correct,
            "missed": len(truth) - len(matched), "extra_detections": len(preds) - len(matched),
            "plot": result.plot()}


def environment() -> dict:
    import importlib.metadata as md

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT_ROOT,
                            capture_output=True, text=True).stdout.strip()
    return {"python": platform.python_version(), "os": f"{platform.system()} {platform.release()}",
            "git_commit": commit, "date": date.today().isoformat(),
            **{p: md.version(p) for p in ("ultralytics", "torch", "lerobot")}}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--frames", default="yolo/frames")
    parser.add_argument("--models", nargs="+", default=["kaggle=yolo_base", "cleany=yolo"], metavar="NAME=MODEL")
    parser.add_argument("--out", default="results")
    args = parser.parse_args()

    from ultralytics import YOLO

    frames = PROJECT_ROOT / args.frames
    out = PROJECT_ROOT / args.out
    (out / "figures").mkdir(parents=True, exist_ok=True)
    val_yaml, test_yaml = build_eval_sets(frames, PROJECT_ROOT / "yolo" / "eval")

    metrics = {"yolo": {}, "env": environment()}
    plots = []
    for spec in args.models:
        name, source = spec.split("=", 1)
        weights = source if source.endswith(".pt") else configured_model(source)
        model = YOLO(weights)
        entry = {"model": source}
        for split, yaml_path in (("val", val_yaml), ("test_photo", test_yaml)):
            r = model.val(data=str(yaml_path), batch=1, plots=split == "val", verbose=False,
                          project=str(PROJECT_ROOT / "yolo" / "eval" / "runs"), name=f"{name}_{split}", exist_ok=True)
            images = len(list((yaml_path.parent / yaml_path.stem / "images").glob("*.jpg")))
            entry[split] = {"images": images,
                            "mAP50": round(float(r.box.map50), 3), "mAP50_95": round(float(r.box.map), 3),
                            "mAP50_95_metal": round(float(r.box.maps[0]), 3),
                            "mAP50_95_plastic": round(float(r.box.maps[1]), 3)}
            if split == "val":
                matrix = Path(r.save_dir) / "confusion_matrix.png"
        counts = test_photo_counts(model, PROJECT_ROOT / "yolo" / "eval" / "test")
        plots.append((name, counts.pop("plot")))
        entry["test_photo"]["at_conf_0.25"] = counts
        metrics["yolo"][name] = entry
        print(f"{name}: val mAP50-95 {entry['val']['mAP50_95']} | test photo mAP50-95 "
              f"{entry['test_photo']['mAP50_95']}, right class {counts['found_right_class']}/{counts['items']}, "
              f"extra {counts['extra_detections']}")

    if matrix.exists():
        shutil.copy(matrix, out / "figures" / "yolo_confusion_matrix.png")
    tiles = []
    for name, plot in plots:
        tile = cv2.resize(plot, (640, 480))
        cv2.putText(tile, name, (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 255), 3)
        tiles.append(tile)
    cv2.imwrite(str(out / "figures" / "yolo_test_photo.jpg"), np.hstack(tiles), [cv2.IMWRITE_JPEG_QUALITY, 85])
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(f"-> {out / 'metrics.json'}, {out / 'figures'}")


if __name__ == "__main__":
    main()
