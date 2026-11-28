"""The data report (scripts/tools/data_report.py)."""

import sys
from pathlib import Path

from item_registry import Item, Registry

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts" / "tools"))
from data_report import report  # noqa: E402

DATASET = {"repo_id": "org/cleany_pick", "episodes": 3, "frames": 500}


def test_the_report_counts_records_per_object_and_leaves_the_results_to_fill_in():
    reg = Registry({i.id: i for i in (
        Item("m-hell", "metal", "hell", name="Hell"), Item("p-water", "plastic", "water", name="Water"),
        Item("o-box", "other", "box", name="Box"), Item("p-mojo", "plastic", "mojo", "test", name="Mojo"))})

    def rec(time, cls, item, kind="episode", episode=None):
        r = {"time": time, "material": cls, "item": item, "item_id": item, "kind": kind}
        return r if episode is None else {**r, "episode": episode}

    records = [rec("T1", "metal", "m-hell", episode=0), rec("T2", "metal", "m-hell", episode=1),
               rec("T3", "other", "o-box", "other"), rec("T4", "plastic", "item", episode=2)]
    text = report(reg, records, DATASET, "act-pilot", "2026-11-28 12:00", "abc1234")
    assert text.startswith("# act-pilot\n") and "**3 episodes**, 500 frames" in text and "Mismatch" not in text
    assert "| Hell | `m-hell` | metal | 2/3 | 0, 1 |" in text and "| Box | `o-box` | other | 1/3 | - |" in text
    assert "Not assigned to an object: 1 records (episodes 2)." in text
    assert "Not recorded yet (1): `p-water`" in text
    assert "| Mojo | `p-mojo` | plastic |  |  |  |  |" in text  # held out: results by hand
    assert "| metal | 2 | 0 | 1/1 |" in text and "| other | 0 | 1 | 1/1 |" in text
    assert "Mismatch" in report(reg, records, {**DATASET, "episodes": 5}, "x", "now", "c")
