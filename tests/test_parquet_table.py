import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "common"))
from parquet_table import load  # noqa: E402


def test_vectors_become_named_columns_and_stats_columns_are_dropped(tmp_path):
    (tmp_path / "meta").mkdir()
    (tmp_path / "meta" / "info.json").write_text(json.dumps({"features": {"action": {"names": ["a", "b"]}}}))
    (tmp_path / "data").mkdir()
    frame = pd.DataFrame({"action": [[0.12345678, 1.0], [2.0, 3.0]], "item.embedding": [[0.0] * 384] * 2,
                          "tasks": [["Pick"], ["Pick"]], "stats/action/min": [[0.0], [0.0]], "index": [0, 1]})
    frame.to_parquet(tmp_path / "data" / "file.parquet")
    table = load(tmp_path / "data" / "file.parquet")
    assert list(table.columns) == ["action.a", "action.b", "item.embedding", "tasks", "index"]
    assert table["action.a"][0] == 0.1235 and table["item.embedding"][0] == "[384 values]"
    assert table["tasks"][0] == "Pick"
