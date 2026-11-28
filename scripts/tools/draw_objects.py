"""Draw the object library's boxes on the photos they were cut from: train green, test red.

Usage:
    python scripts/tools/draw_objects.py [--library objects] [--out assets]

Every object in objects/<split>/<id>/item.yaml whose `source` is a photo (`photo`, `boxes`) is drawn
on that photo, labelled with its id; the result is <out>/<photo name>_split.jpg. Objects added from
the recorder's panel have no photo box and are left out.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "common"))
from item_registry import Registry  # noqa: E402

COLORS = {"train": (46, 204, 64), "test": (230, 40, 40)}


def draw(photo: Path, items, out: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.open(photo).convert("RGB")
    canvas = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 13)
    except OSError:
        font = ImageFont.load_default()
    labels = []
    for item in items:
        color = COLORS[item.split]
        for i, box in enumerate(item.source["boxes"]):
            canvas.rectangle(box, outline=color, width=3 if i == 0 else 2)
            if i == 0:
                labels.append((box, item, color))
    for box, item, color in labels:  # labels on top of every box
        text = item.id + (f" x{item.copies}" if item.copies > 1 else "")
        x, y = box[0] + 2, box[1] + 2
        w = canvas.textlength(text, font=font)
        canvas.rectangle([x - 1, y - 1, x + w + 2, y + 15], fill=color)
        canvas.text((x, y), text, fill=(255, 255, 255), font=font)
    legend = "green: train   red: test (held out)"
    canvas.rectangle([0, image.height - 22, canvas.textlength(legend, font=font) + 12, image.height], fill=(0, 0, 0))
    canvas.text((6, image.height - 19), legend, fill=(255, 255, 255), font=font)
    path = out / f"{photo.stem}_split.jpg"
    image.save(path, quality=90)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--library", type=Path, default=PROJECT_ROOT / "objects")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "assets")
    args = parser.parse_args()
    reg = Registry.load(args.library)
    by_photo = defaultdict(list)
    for item in reg.items.values():
        if item.source.get("photo") and item.source.get("boxes"):
            by_photo[item.source["photo"]].append(item)
    if not by_photo:
        sys.exit(f"No object in {args.library} has a photo box")
    args.out.mkdir(parents=True, exist_ok=True)
    for photo, items in sorted(by_photo.items()):
        path = draw(PROJECT_ROOT / photo, items, args.out)
        test = sum(it.split == "test" for it in items)
        print(f"{path.relative_to(PROJECT_ROOT) if path.is_relative_to(PROJECT_ROOT) else path}: "
              f"{len(items)} objects ({len(items) - test} train, {test} test)")


if __name__ == "__main__":
    main()
