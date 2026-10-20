"""Extract front-camera frames from LeRobot datasets for YOLO labeling, with pre-labels.

Usage:
    python extract_frames.py [--datasets cleany_plastic cleany_metal] [--out yolo/frames]
                             [--model models/yolo/yolo_kaggle_best.pt] [--conf 0.25] [--device cpu]

Takes the first and the last frame of every episode (the pile before and after one item
was moved, so every episode gives two different layouts) and pre-labels them with the
current YOLO model, so labeling only means fixing classes and adding missed items.

Output (<out>/):
    images/<dataset>_ep<NNN>_<first|last>.jpg
    labels/<same name>.txt          YOLO pre-labels: "<class> cx cy w h", normalized
    classes.txt                     0 metal, 1 plastic
    label_studio_tasks.json         import into Label Studio (pre-labels as predictions)
    label_studio_config.xml         labeling interface for the Label Studio project

Label Studio reads the images from disk through local file serving, with the repo as the
document root (LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT=<repo>).
"""

import argparse
import json
from pathlib import Path

import cv2
import pandas as pd

from lerobot.datasets.video_utils import decode_video_frames

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CAMERA_KEY = "observation.images.front"
CLASSES = ["metal", "plastic"]  # class ids used everywhere: 0 metal, 1 plastic

LABEL_CONFIG = """<View>
  <Image name="image" value="$image" zoomControl="true"/>
  <RectangleLabels name="label" toName="image">
    <Label value="metal" background="#1f6feb"/>
    <Label value="plastic" background="#2ea043"/>
  </RectangleLabels>
</View>
"""


def episode_frames(dataset_root: Path):
    """Yields (episode_index, position, timestamp, video_path) for the first and last frame."""
    info = json.loads((dataset_root / "meta/info.json").read_text())
    fps = info["fps"]
    episodes = pd.concat(
        pd.read_parquet(f) for f in sorted((dataset_root / "meta/episodes").glob("*/*.parquet"))
    ).sort_values("episode_index")
    prefix = f"videos/{CAMERA_KEY}"
    for _, ep in episodes.iterrows():
        video = dataset_root / info["video_path"].format(
            video_key=CAMERA_KEY,
            chunk_index=int(ep[f"{prefix}/chunk_index"]),
            file_index=int(ep[f"{prefix}/file_index"]),
        )
        start = float(ep[f"{prefix}/from_timestamp"])
        end = float(ep[f"{prefix}/to_timestamp"]) - 1 / fps
        yield int(ep["episode_index"]), "first", start, video
        yield int(ep["episode_index"]), "last", end, video


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--datasets", nargs="+", default=["cleany_plastic", "cleany_metal"],
                        help="dataset folder names under data/")
    parser.add_argument("--out", default="yolo/frames")
    parser.add_argument("--model", default="models/yolo/yolo_kaggle_best.pt",
                        help="model for pre-labels; 'none' extracts frames only")
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--device", default="cpu", help="cpu keeps the GPU free for training")
    parser.add_argument("--max-area", type=float, default=0.25,
                        help="drop pre-label boxes covering more of the frame than this (the Kaggle "
                             "model often boxes the whole table)")
    args = parser.parse_args()

    out = PROJECT_ROOT / args.out
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "labels").mkdir(parents=True, exist_ok=True)
    (out / "classes.txt").write_text("\n".join(CLASSES) + "\n")
    (out / "label_studio_config.xml").write_text(LABEL_CONFIG)

    model = None
    if args.model != "none":
        from ultralytics import YOLO
        model = YOLO(str(PROJECT_ROOT / args.model))
        # Map the model's class names onto ours by name (the Kaggle model also has an unused "other")
        class_map = {i: CLASSES.index(n) for i, n in model.names.items() if n in CLASSES}

    tasks = []
    total_boxes = 0
    for name in args.datasets:
        dataset_root = PROJECT_ROOT / "data" / name
        for episode, position, timestamp, video in episode_frames(dataset_root):
            frame = decode_video_frames(video, [timestamp], tolerance_s=0.02, backend="pyav", return_uint8=True)
            image = cv2.cvtColor(frame[0].permute(1, 2, 0).numpy(), cv2.COLOR_RGB2BGR)
            stem = f"{name}_ep{episode:03d}_{position}"
            image_path = out / "images" / f"{stem}.jpg"
            cv2.imwrite(str(image_path), image, [cv2.IMWRITE_JPEG_QUALITY, 95])

            boxes = []  # (class_id, cx, cy, w, h, score), normalized
            if model is not None:
                # agnostic NMS: one box per item even when the model is unsure about its class
                result = model.predict(image, conf=args.conf, device=args.device, agnostic_nms=True, verbose=False)[0]
                for cls, xywhn, score in zip(result.boxes.cls.tolist(), result.boxes.xywhn.tolist(),
                                             result.boxes.conf.tolist()):
                    if int(cls) in class_map and xywhn[2] * xywhn[3] <= args.max_area:
                        boxes.append((class_map[int(cls)], *xywhn, score))
            total_boxes += len(boxes)
            (out / "labels" / f"{stem}.txt").write_text(
                "".join(f"{c} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n" for c, cx, cy, w, h, _ in boxes)
            )

            height, width = image.shape[:2]
            tasks.append({
                "data": {
                    "image": f"/data/local-files/?d={image_path.relative_to(PROJECT_ROOT)}",
                    "dataset": name, "episode": episode, "position": position,
                },
                "predictions": [{
                    "model_version": Path(args.model).stem,
                    "result": [{
                        "type": "rectanglelabels", "from_name": "label", "to_name": "image",
                        "original_width": width, "original_height": height,
                        "score": score,
                        "value": {
                            "x": (cx - w / 2) * 100, "y": (cy - h / 2) * 100,
                            "width": w * 100, "height": h * 100,
                            "rectanglelabels": [CLASSES[c]],
                        },
                    } for c, cx, cy, w, h, score in boxes],
                }],
            })
            print(f"{stem}: {len(boxes)} boxes")

    (out / "label_studio_tasks.json").write_text(json.dumps(tasks, indent=1))
    print(f"\n{len(tasks)} frames, {total_boxes} pre-label boxes -> {out}")


if __name__ == "__main__":
    main()
