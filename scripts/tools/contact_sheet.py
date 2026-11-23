"""Contact sheets of a pick recording session: every record's gallery crop with its number, so the
agent (Claude) can recognise the items and write config/items.yaml and config/item_labels.yaml
(docs/collection-plan.md).

Usage (through scripts/tools/contact_sheet.sh):
    contact_sheet.sh                       # the latest session
    contact_sheet.sh --session 20261123    # a session (its stamp, or a prefix such as the day)
    contact_sheet.sh --session all --unlabelled   # everything not labelled yet
    contact_sheet.sh --items               # one tile per registered item (to match new crops against)

Writes data/pick/sheets/<name>_<page>.jpg (48 tiles per page) and <name>.yaml: the records in
tile order (number, time, class, typed name, episode, current item) to fill item_labels.yaml from.
Records from before sessions were stored are grouped by day.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "common"))
from box_logic import load_yaml  # noqa: E402
from item_registry import Registry, crop_files, read_records  # noqa: E402

TILE, CAPTION, COLUMNS, PER_PAGE = 200, 34, 8, 48
COLORS = {"metal": "#90a4ae", "plastic": "#4fc3f7", "generic": "#ffb74d", "other": "#a1887f"}


def session_of(record: dict) -> str:
    return str(record.get("session") or str(record["time"])[:8])


def pick_session(records: list[dict], wanted: str) -> list[dict]:
    if wanted == "all":
        return records
    if wanted == "latest":
        if not records:
            return []
        wanted = max(session_of(r) for r in records)
    return [r for r in records if session_of(r).startswith(wanted) or str(r["time"]).startswith(wanted)]


def find_image(record: dict, crops: Path, yolo: Path) -> Path | None:
    crop = crops / record["material"] / f"{record['item']}_{record['time']}.jpg"
    if crop.exists():
        return crop
    frame = yolo / "images" / f"pick_{record['time']}.jpg"
    return frame if frame.exists() else None


def sheet(tiles: list[tuple[Path | None, str, str, str]]):
    """tiles: (image or None, line 1, line 2, class). One PIL image, COLUMNS wide."""
    from PIL import Image, ImageDraw, ImageOps

    rows = (len(tiles) + COLUMNS - 1) // COLUMNS
    page = Image.new("RGB", (COLUMNS * TILE, rows * (TILE + CAPTION)), "#202020")
    draw = ImageDraw.Draw(page)
    for i, (path, line1, line2, cls) in enumerate(tiles):
        x, y = (i % COLUMNS) * TILE, (i // COLUMNS) * (TILE + CAPTION)
        if path is not None:
            with Image.open(path) as im:
                page.paste(ImageOps.pad(im.convert("RGB"), (TILE - 4, TILE - 4), color="#202020"), (x + 2, y + 2))
        else:
            draw.text((x + 60, y + 90), "no image", fill="#888888")
        draw.rectangle([x, y + TILE, x + TILE - 1, y + TILE + CAPTION - 1], fill=COLORS.get(cls, "#cccccc"))
        draw.text((x + 4, y + TILE + 3), line1[:34], fill="black")
        draw.text((x + 4, y + TILE + 18), line2[:34], fill="black")
    return page


def record_tiles(records: list[dict], reg: Registry, crops: Path, yolo: Path):
    tiles, index = [], []
    for n, r in enumerate(records, 1):
        item = reg.resolve(str(r["time"]), r.get("item", ""))
        ep = f" ep{r['episode']}" if "episode" in r else ""
        tiles.append((find_image(r, crops, yolo), f"#{n} {r['material']}{ep}",
                      f"{r.get('item', '')} -> {item.id if item else '?'}", r["material"]))
        index.append({"n": n, "time": str(r["time"]), "material": r["material"], "typed": r.get("item", ""),
                      "episode": r.get("episode"), "item": item.id if item else None})
    return tiles, index


def item_tiles(records: list[dict], reg: Registry, crops: Path, yolo: Path):
    """One tile per registered item: its first record's image (or any crop named after it)."""
    first = {}
    for r in records:
        item = reg.resolve(str(r["time"]), r.get("item", ""))
        if item is not None and item.id not in first:
            first[item.id] = find_image(r, crops, yolo)
    for path, _, name, time in crop_files(crops):
        item = reg.resolve(time, name)
        if item is not None and first.get(item.id) is None:
            first[item.id] = path
    tiles, index = [], []
    for item in reg.items.values():
        tiles.append((first.get(item.id), f"{item.id} {item.split}", item.label(), item.cls))
        index.append({"item": item.id, "class": item.cls, "split": item.split, "design": item.design})
    return tiles, index


def write(tiles, index, out: Path, name: str) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    pages = []
    for p in range(0, max(len(tiles), 1), PER_PAGE):
        path = out / f"{name}_{p // PER_PAGE + 1}.jpg"
        sheet(tiles[p:p + PER_PAGE]).save(path, quality=88)
        pages.append(path)
    (out / f"{name}.yaml").write_text(yaml.safe_dump(index, sort_keys=False, allow_unicode=True))
    return pages


def main():
    recording = load_yaml(PROJECT_ROOT / "config" / "pick_recording.yaml")
    outputs, items = recording["outputs"], recording.get("items") or {}
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", default="latest", help="latest (default), all, or a session stamp / day prefix")
    parser.add_argument("--unlabelled", action="store_true", help="only records not resolved to an item yet")
    parser.add_argument("--items", action="store_true", help="one tile per registered item instead")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "data" / "pick" / "sheets")
    args = parser.parse_args()

    reg = Registry.load(PROJECT_ROOT / items.get("registry", "config/items.yaml"),
                        PROJECT_ROOT / items.get("labels", "config/item_labels.yaml"))
    crops, yolo = PROJECT_ROOT / outputs["crops"], PROJECT_ROOT / outputs["yolo_frames"]
    records = read_records(PROJECT_ROOT / outputs["records"])
    if args.items:
        tiles, index = item_tiles(records, reg, crops, yolo)
        name = "items"
    else:
        records = pick_session(records, args.session)
        if args.unlabelled:
            records = [r for r in records if reg.resolve(str(r["time"]), r.get("item", "")) is None]
        if not records:
            sys.exit(f"No records for --session {args.session}{' not labelled yet' if args.unlabelled else ''}")
        tiles, index = record_tiles(records, reg, crops, yolo)
        name = ("session_" + (session_of(records[0]) if args.session == "latest" else args.session)
                + ("_unlabelled" if args.unlabelled else ""))
    pages = write(tiles, index, args.out, name)
    print(f"{len(tiles)} tiles: " + ", ".join(str(p.relative_to(PROJECT_ROOT)) if p.is_relative_to(PROJECT_ROOT)
                                               else str(p) for p in pages))
    print(f"Index: {args.out / (name + '.yaml')}")


if __name__ == "__main__":
    main()
