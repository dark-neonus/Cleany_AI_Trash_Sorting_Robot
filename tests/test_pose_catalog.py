"""The named poses (scripts/common/pose_catalog.py): table, migration of old files, checks."""

import pytest
import yaml
from box_logic import GRIPPER, JOINT_KEYS, REQUIRED_POSES, load_poses
from pose_catalog import BY_NAME, NAMES, POSES, check, migrate, missing_for, needed, status


def pose(pan, lift, elbow, wflex, roll=-84.8, gripper=2.5):
    return dict(zip(JOINT_KEYS, (pan, lift, elbow, wflex, roll, gripper), strict=True))


# Captured by hand on the v3 box (config/poses.yaml of 2026-11-22)
CAPTURED = {
    "home": pose(2.86, -104.4, 98.24, 76.75, -84.62),
    "hover": pose(2.68, -22.99, 7.87, 91.87),
    "transit": pose(-0.13, -82.95, 70.02, 23.65),
    "metal_bin": pose(-40.13, -30.37, 32.4, 23.65),
    "plastic_bin": pose(44.35, -30.29, 32.13, 23.65),
    "tray_low": pose(-3.38, 13.23, 53.41, 23.47, gripper=53.28),
}


def test_table_is_complete_and_matches_what_the_code_requires():
    assert len(set(NAMES)) == len(NAMES) == len(POSES)
    assert needed("pipeline") == REQUIRED_POSES
    assert needed("scripted") == ("tray_low",) and BY_NAME["tray_low"].optional and not BY_NAME["transit"].optional
    for spec in POSES:
        assert spec.title and spec.where and spec.how and spec.gripper and spec.used and spec.needed_for


def test_real_captures_pass_every_check():
    assert all(f == [] for f in status(CAPTURED).values())
    assert missing_for("scripted", CAPTURED) == []
    assert missing_for("pipeline", {"home": CAPTURED["home"]}) == ["hover", "transit", "metal_bin", "plastic_bin"]


def test_old_files_are_migrated_and_nothing_captured_is_lost():
    old = {"home": CAPTURED["home"], "hover": CAPTURED["hover"], "centre": CAPTURED["transit"],
           "grasp": CAPTURED["tray_low"], "tray_release": pose(-0.57, -104.92, 98.68, 23.65, gripper=99),
           "metal_bin": CAPTURED["metal_bin"], "plastic_bin": CAPTURED["plastic_bin"], "extra": CAPTURED["home"]}
    new, notes = migrate(old)
    assert list(new) == ["home", "hover", "transit", "metal_bin", "plastic_bin", "tray_low", "extra"]
    assert new["transit"] == CAPTURED["transit"] and new["tray_low"] == CAPTURED["tray_low"]
    assert any("tray_release" in n and "dropped" in n for n in notes)
    # idempotent, and a pose already under the new name wins over the old one
    assert migrate(new)[0] == new and migrate(new)[1] == []
    again, notes = migrate({**old, "tray_low": CAPTURED["hover"]})
    assert again["tray_low"] == CAPTURED["hover"] and any("kept the existing" in n for n in notes)


def test_loader_tells_how_to_fix_an_old_file(tmp_path):
    path = tmp_path / "poses.yaml"
    path.write_text(yaml.safe_dump({"poses": {"home": CAPTURED["home"], "hover": CAPTURED["hover"],
                                              "centre": CAPTURED["transit"], "metal_bin": CAPTURED["metal_bin"],
                                              "plastic_bin": CAPTURED["plastic_bin"]}}))
    with pytest.raises(KeyError, match=r"transit.*centre -> transit.*--migrate"):
        load_poses(path)


def test_checks_catch_the_mistakes_that_were_made():
    # the two bins swapped
    swapped = {**CAPTURED, "metal_bin": CAPTURED["plastic_bin"], "plastic_bin": CAPTURED["metal_bin"]}
    assert "on the left" in check("metal_bin", swapped)[-1].text and check("metal_bin", swapped)[-1].level == "error"
    assert check("plastic_bin", swapped)[-1].level == "error"
    assert [f.level for f in check("metal_bin", swapped)] == ["warn", "error"]
    assert "over the metal bin" in check("metal_bin", swapped)[0].text
    # a hover swung 60 degrees to the right: not over the tray any more
    off = {**CAPTURED, "hover": pose(60, -22.99, 7.87, 91.87)}
    assert [f.level for f in check("hover", off)] == ["warn"] and "over the tray" in check("hover", off)[0].text
    # arm not moved between two poses
    same = {**CAPTURED, "transit": {**CAPTURED["home"]}}
    assert any("almost the same joints as 'home'" in f.text for f in check("transit", same))
    # a gripper left open at home; the gripper value of other poses does not matter
    assert any("gripper is open" in f.text for f in check("home", {**CAPTURED, "home": {**CAPTURED["home"], GRIPPER: 60}}))
    assert not any("gripper" in f.text for f in check("tray_low", CAPTURED))
    # hover must be well above tray_low, and its gripper must point down
    flat = {**CAPTURED, "hover": pose(2.7, -40, 40, 10)}
    texts = " ".join(f.text for f in check("hover", flat))
    assert "wrist camera will not see" in texts
    barely_above = {**CAPTURED, "hover": pose(-3.4, 6, 53.4, 23.5)}  # 7 degrees of shoulder lift above tray_low
    assert any("must be clearly higher" in f.text for f in check("hover", barely_above))
    # a transit pose lower than the bins
    low = {**CAPTURED, "transit": pose(0, -50, 60, 30)}
    assert any("catch a rim" in f.text for f in check("transit", low))


def test_names_are_looked_up_by_spec():
    assert BY_NAME["home"].gripper.startswith("closed")
