"""The panel's object library, without a window (scripts/run/pick_library.py)."""

from item_registry import Item, Registry
from pick_library import count_text, library_items, summary


def reg():
    return Registry({i.id: i for i in (
        Item("p-water", "plastic", "water", kind="bottle"), Item("c-green", "plastic", "cap", kind="cap"),
        Item("m-hell", "metal", "hell", kind="can"), Item("m-peach", "metal", "peach", "test"),
        Item("o-tube", "other", "tube", kind="paper"))})


def test_tiles_are_training_objects_in_a_stable_order_and_filter_by_type():
    assert [it.id for it in library_items(reg())] == ["m-hell", "p-water", "c-green", "o-tube"]  # no test object
    assert [it.id for it in library_items(reg(), "Plastic")] == ["p-water"]
    assert [it.id for it in library_items(reg(), "Caps")] == ["c-green"]


def test_counts_read_n_of_target():
    item = Item("m-hell", "metal", "hell")
    assert count_text(item, {}) == ("0/3", "#757575")
    assert count_text(item, {"m-hell": 2})[0] == "2/3" and count_text(item, {"m-hell": 3})[0] == "3/3 ✓"
    assert summary(reg(), {"m-hell": 5, "p-water": 1}) == "4 objects · 1 done · 4/12 records"
