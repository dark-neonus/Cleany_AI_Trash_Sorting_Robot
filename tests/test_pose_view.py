"""Drawing the poses (scripts/common/pose_view.py): the figure is well formed and oriented like the box."""

import xml.etree.ElementTree as ET

import pytest
import workspace_layout as layout
from pose_catalog import NAMES
from pose_view import PlanView, SideView, SvgCanvas, _ray_interval, figure_svg, tcp_text
from test_pose_catalog import CAPTURED


def test_figure_is_valid_svg_with_every_pose():
    svg = figure_svg(CAPTURED)
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")
    for name in NAMES:
        assert name in svg
    assert "nan" not in svg.lower() and "not captured" not in svg


def test_figure_still_draws_with_poses_missing():
    svg = figure_svg({"home": CAPTURED["home"]})
    ET.fromstring(svg)
    assert svg.count("not captured") == len(NAMES) - 1 + (len(NAMES) - 1)  # overview list + one card each


def test_plan_view_has_the_metal_bin_on_the_left_and_the_entry_at_the_top():
    plan = PlanView(0, 0, 10)
    assert plan.px(20, 18)[0] < plan.px(20, -18)[0]  # +y (the arm's left) is the left of the picture
    assert plan.px(45, 0)[1] < plan.px(10, 0)[1]  # forward is up


def test_side_view_measures_reach_in_the_arms_own_plane():
    from arm_kinematics import forward, reach_cm
    side = SideView(0, 0, 10)
    for name in ("metal_bin", "plastic_bin"):  # swung 40 degrees either way, same reach in the plane
        tcp = forward(CAPTURED[name])["tcp"]
        assert side.point(tcp, CAPTURED[name])[0] / 10 == pytest.approx(reach_cm(CAPTURED[name]), abs=0.5)


def test_arm_plane_crosses_the_tray_at_pan_zero_and_a_bin_when_swung():
    straight = _ray_interval(layout.TRAY, CAPTURED["hover"])
    assert straight and 6 < straight[0] < 10 and 30 < straight[1] < 36
    assert _ray_interval(layout.BINS["metal"], CAPTURED["hover"]) is None
    assert _ray_interval(layout.BINS["metal"], CAPTURED["metal_bin"])


def test_canvas_escapes_text_and_reports_the_fingertips():
    c = SvgCanvas(10, 10)
    c.text(0, 0, "a < b & c")
    assert "a &lt; b &amp; c" in c.svg("t", "d")
    assert "cm ahead" in tcp_text(CAPTURED["hover"]) and "76° down" in tcp_text(CAPTURED["hover"])
