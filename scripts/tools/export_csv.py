"""Flatten a LeRobot dataset's parquet files into plain CSV tables, for VS Code (Rainbow CSV, Data Wrangler).

Parquet viewers show the vector columns (observation.state, action, motors.*) as one cell of nested
lists, and the 177 stats columns of meta/episodes make the table unreadable. Here every vector becomes one
column per element, named from meta/info.json (state.shoulder_pan.pos, motors.current.gripper, ...).

Usage (through scripts/tools/export_csv.sh):
    export_csv.py [--root data/pick/episodes] [--out data/pick/export] [--embedding]

Writes <out>/frames.csv (every frame, episode_index first), <out>/episodes.csv (one row per episode:
length, task, files) and <out>/tasks.csv. The 384 item.embedding columns are left out unless --embedding.
"""

import argparse
import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def flatten(frames: pd.DataFrame, features: dict, embedding: bool) -> pd.DataFrame:
    columns = {"episode_index": frames["episode_index"], "frame_index": frames["frame_index"],
               "timestamp": frames["timestamp"].round(4), "task_index": frames["task_index"]}
    for name, feature in features.items():
        if (feature["dtype"] == "video" or name in columns or name == "index" or name not in frames
                or name == "item.embedding" and not embedding):
            continue
        values = np.stack(frames[name].values).reshape(len(frames), -1)
        names = feature.get("names") or [str(i) for i in range(values.shape[1])]
        short = name.removeprefix("observation.")
        for i, label in enumerate(names):
            columns[f"{short}.{label}"] = values[:, i].round(4)
    return pd.DataFrame(columns)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT / "data" / "pick" / "episodes")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "data" / "pick" / "export")
    parser.add_argument("--embedding", action="store_true")
    args = parser.parse_args()

    features = json.loads((args.root / "meta" / "info.json").read_text())["features"]
    frames = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(str(args.root / "data/chunk-*/file-*.parquet")))])
    frames = frames.sort_values("index").reset_index(drop=True)
    args.out.mkdir(parents=True, exist_ok=True)
    table = flatten(frames, features, args.embedding)
    table.to_csv(args.out / "frames.csv", index=False)

    episodes = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(str(args.root / "meta/episodes/chunk-*/file-*.parquet")))])
    keep = [c for c in episodes.columns if not c.startswith("stats/") and not c.startswith("videos/")]
    episodes = episodes[keep].copy()
    episodes["tasks"] = episodes["tasks"].map(lambda t: "; ".join(t))
    episodes["seconds"] = (episodes["length"] / json.loads((args.root / "meta" / "info.json").read_text())["fps"]).round(2)
    episodes.to_csv(args.out / "episodes.csv", index=False)
    pd.read_parquet(args.root / "meta" / "tasks.parquet").reset_index().to_csv(args.out / "tasks.csv", index=False)
    print(f"{len(table)} frames, {len(table.columns)} columns, {len(episodes)} episodes -> {args.out}")


if __name__ == "__main__":
    main()
