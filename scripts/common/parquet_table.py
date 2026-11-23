"""A parquet file as a flat table for viewing: vector columns become one column per element.

LeRobot's data files store observation.state, action and motors.* as lists; its meta/episodes files carry
177 stats columns. Names for the elements come from the dataset's meta/info.json when the file sits in
one (any folder above it), else they are numbered. Lists longer than MAX_EXPAND stay one cell, "[384 values]".
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

MAX_EXPAND = 16


def find_features(path: Path) -> dict:
    for folder in path.resolve().parents:
        info = folder / "meta" / "info.json"
        if info.exists():
            return json.loads(info.read_text()).get("features", {})
    return {}


def flatten(frame: pd.DataFrame, features: dict, details: bool = False) -> pd.DataFrame:
    """details: keep the stats/ and videos/ columns of meta/episodes."""
    columns: dict[str, object] = {}
    for name in frame.columns:
        if not details and name.startswith(("stats/", "videos/")):
            continue
        first = next((v for v in frame[name] if v is not None), None)
        if isinstance(first, (list, tuple, np.ndarray)) and name != "tasks":
            size = len(first)
            if size > MAX_EXPAND:
                columns[name] = [f"[{len(v)} values]" if v is not None else None for v in frame[name]]
                continue
            labels = (features.get(name) or {}).get("names") or [str(i) for i in range(size)]
            values = np.stack([np.asarray(v, dtype=float) for v in frame[name]])
            short = name.removeprefix("observation.")
            for i, label in enumerate(labels):
                columns[f"{short}.{label}"] = values[:, i].round(4)
        elif isinstance(first, (list, tuple, np.ndarray)):
            columns[name] = ["; ".join(map(str, v)) for v in frame[name]]
        else:
            columns[name] = frame[name].round(4) if frame[name].dtype.kind == "f" else frame[name]
    table = pd.DataFrame(columns)
    lead = [c for c in ("episode_index", "frame_index", "timestamp") if c in table]
    return table[lead + [c for c in table.columns if c not in lead]]


def load(path: Path, details: bool = False) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    if not isinstance(frame.index, pd.RangeIndex):  # meta/tasks.parquet: the task text is the index
        frame = frame.reset_index()
    return flatten(frame, find_features(path), details)
