"""Write a small markdown report of the data collected: what a model trained now is trained on.

Usage (no robot needed):
    scripts/tools/data_report.sh                     # docs/reports/data_<date>.md
    scripts/tools/data_report.sh --name act-pilot    # docs/reports/act-pilot.md
    scripts/tools/data_report.sh --name act-pilot --force   # overwrite (hand-written notes are lost)

Reads the object library (objects/), data/pick/items/records.jsonl and the dataset's meta/info.json.
The report is a snapshot to commit next to a model: records per object (N/target), totals per class,
and empty places for the model's name and its results on the held-out objects, to fill in by hand.
An existing report is not overwritten without --force.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "common"))
from box_logic import load_yaml  # noqa: E402
from item_registry import CLASSES, Registry, RegistryError, read_records  # noqa: E402


def table(header: list[str], rows: list[list]) -> list[str]:
    return ["| " + " | ".join(header) + " |", "|" + " --- |" * len(header),
            *("| " + " | ".join(str(v).replace("|", "/") for v in row) + " |" for row in rows)]


def report(reg: Registry, records: list[dict], dataset: dict, title: str, made: str, commit: str) -> str:
    """The report as markdown. dataset: {"repo_id", "episodes", "frames"}."""
    counts = reg.item_counts(records)
    train = sorted(reg.train_items(), key=lambda it: (CLASSES.index(it.cls), it.id))
    done = [it for it in train if counts[it.id] >= it.target]
    recorded = [it for it in train if counts[it.id]]
    episodes = [r for r in records if r.get("kind") == "episode"]
    unassigned = [r for r in records if reg.resolve_record(r) is None]

    lines = [f"# {title}", "",
             f"Data snapshot of {made}, code at `{commit}`.", "",
             f"- Dataset `{dataset['repo_id']}`: **{dataset['episodes']} episodes**, {dataset['frames']} frames",
             f"- Pictures without an episode (Save other): {len(records) - len(episodes)}",
             f"- Training objects: {len(recorded)} of {len(train)} recorded, {len(done)} complete"]
    if len(episodes) != dataset["episodes"]:
        lines.append(f"- **Mismatch:** records.jsonl has {len(episodes)} episodes, the dataset {dataset['episodes']}")

    lines += ["", "## Model", "", "Fill in after training:", "",
              *table(["Model", "Trained on", "Date", "Notes"], [["", "", "", ""]]),
              "", "## Per class", ""]
    rows = []
    for cls in CLASSES:
        items = [it for it in train if it.cls == cls]
        mine = [r for r in records if r.get("material") == cls]
        rows.append([cls, sum(r.get("kind") == "episode" for r in mine), sum(r.get("kind") != "episode" for r in mine),
                     f"{sum(bool(counts[it.id]) for it in items)}/{len(items)}"])
    lines += table(["Class", "Episodes", "Saved only", "Objects recorded"], rows)

    lines += ["", "## Records per object", ""]
    if recorded:
        rows = []
        for it in recorded:
            numbers = [r["episode"] for r in records
                       if r.get("kind") == "episode" and "episode" in r and reg.resolve_record(r) is it]
            rows.append([it.label(), f"`{it.id}`", it.cls, f"{counts[it.id]}/{it.target}",
                         ", ".join(str(n) for n in sorted(numbers)) or "-"])
        lines += table(["Object", "Id", "Class", "Records", "Episodes"], rows)
    else:
        lines.append("Nothing recorded yet.")
    if unassigned:
        numbers = sorted(r["episode"] for r in unassigned if "episode" in r)
        lines += ["", f"Not assigned to an object: {len(unassigned)} records"
                  + (f" (episodes {', '.join(map(str, numbers))})" if numbers else "") + "."]
    missing = [f"`{it.id}`" for it in train if not counts[it.id]]
    if missing:
        lines += ["", f"Not recorded yet ({len(missing)}): " + ", ".join(missing)]

    test = sorted((it for it in reg.items.values() if it.split == "test"), key=lambda it: (CLASSES.index(it.cls), it.id))
    lines += ["", "## Real-world test (held-out objects)", "",
              "Never recorded. Per object: tries, then how many were classified right, grasped and put in the right bin.",
              ""]
    lines += table(["Object", "Id", "Class", "Tries", "Classified", "Grasped", "Right bin"],
                   [[it.label(), f"`{it.id}`", it.cls, "", "", "", ""] for it in test])
    return "\n".join(lines) + "\n"


def git_commit() -> str:
    done = subprocess.run(["git", "describe", "--always", "--dirty"], cwd=PROJECT_ROOT, capture_output=True, text=True)
    return done.stdout.strip() or "unknown"


def main():
    recording = load_yaml(PROJECT_ROOT / "config" / "pick_recording.yaml")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", help="file name and title (default: data_<date>)")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "docs" / "reports")
    parser.add_argument("--force", action="store_true", help="overwrite an existing report")
    args = parser.parse_args()

    items = recording.get("items") or {}
    try:
        reg = Registry.load(PROJECT_ROOT / items.get("registry", "objects"),
                            PROJECT_ROOT / items.get("labels", "config/item_labels.yaml"))
    except RegistryError as error:
        sys.exit(f"Error: {error}")
    records = read_records(PROJECT_ROOT / recording["outputs"]["records"])
    if not records:
        sys.exit("Error: no records yet (scripts/dataset/record_pick.sh, or sync.sh pull pick)")
    info_path = PROJECT_ROOT / recording["dataset"]["root"] / "meta" / "info.json"
    info = json.loads(info_path.read_text()) if info_path.exists() else {}
    dataset = {"repo_id": recording["dataset"]["repo_id"], "episodes": info.get("total_episodes", 0),
               "frames": info.get("total_frames", 0)}

    now = datetime.now()
    name = args.name or f"data_{now:%Y_%m_%d}"
    path = args.out / f"{name}.md"
    if path.exists() and not args.force:
        sys.exit(f"Error: {path} exists (it may hold hand-written results). Give another --name, or --force")
    args.out.mkdir(parents=True, exist_ok=True)
    path.write_text(report(reg, records, dataset, name, f"{now:%Y-%m-%d %H:%M}", git_commit()))
    print(f"Wrote {path.relative_to(PROJECT_ROOT) if path.is_relative_to(PROJECT_ROOT) else path}")


if __name__ == "__main__":
    main()
