"""Looking at the poses on the arm (scripts/common/pose_show.py), on a simulated arm."""

from pathlib import Path

import pytest
import yaml
from box_logic import GRIPPER, JOINT_KEYS, max_joint_distance
from box_states import Stop
from pose_catalog import NAMES
from pose_show import EDGES, LAG_DEG, MoveError, Mover, StartError, estimate, go, nearest, route, slideshow, walk
from test_pose_catalog import CAPTURED

MOTION = yaml.safe_load((Path(__file__).parents[1] / "config" / "box_pipeline.yaml").read_text())["motion"]


class Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += max(s, 0.0)


class Arm:
    """Follows every command at once and remembers where it went (the pose names it passed)."""

    def __init__(self, start):
        self.joints, self.sent = dict(start), []

    def observe(self):
        return dict(self.joints)

    def send(self, action):
        assert max_joint_distance(self.joints, action, include_gripper=True) < 12, "a jump"
        self.joints = dict(action)
        self.sent.append(dict(action))


def mover(start="home", **kw):
    arm, clock, said = Arm(CAPTURED[start]), Clock(), []
    m = Mover(arm, CAPTURED, MOTION, clock, say=said.append, **kw)
    m.locate()
    m.arm_log, m.said, m.clock_ = arm, said, clock
    return m


def passed(m):
    """The poses the arm moved to, in order (from the log of moves)."""
    return [line.split()[1] for line in m.said if line.startswith("  ->")]


def test_routes_follow_the_moves_the_pipeline_makes():
    assert route("home", "hover") == ["home", "hover"]
    assert route("metal_bin", "plastic_bin") == ["metal_bin", "transit", "plastic_bin"]  # not through the walls
    assert route("plastic_bin", "home") == ["plastic_bin", "home"]  # RELEASE then HOME
    assert route("tray_low", "metal_bin") == ["tray_low", "hover", "transit", "metal_bin"]
    assert route("hover", "hover") == ["hover"]
    assert {n for e in EDGES for n in e} <= set(NAMES)
    with pytest.raises(KeyError):
        route("home", "nowhere")


def test_walkthrough_visits_every_pose_in_order_with_a_pause_and_ends_at_home():
    m = mover()
    t0 = m.clock_.t
    names = ["home", "hover", "transit", "metal_bin", "plastic_bin", "tray_low"]
    walk(m, names, delay=1.0)
    m.home()
    # metal -> plastic goes through transit, tray_low is reached from hover, home from the bin... via the tree
    assert passed(m) == ["hover", "transit", "metal_bin", "transit", "plastic_bin", "transit", "hover", "tray_low",
                         "hover", "home"]
    assert m.clock_.t - t0 >= 6 * 1.0  # the pause at each of the six poses
    assert sum("(on the way)" in line for line in m.said) >= 2


def test_every_move_is_gentle_and_the_gripper_follows_the_policy():
    m = mover(gripper="closed")
    walk(m, ["hover", "transit", "metal_bin"], delay=0)
    grips = {round(s[GRIPPER], 1) for s in m.arm_log.sent[-5:]}
    assert grips == {round(CAPTURED["home"][GRIPPER], 1)}  # closed everywhere
    steps = m.arm_log.sent
    assert max(max_joint_distance(a, b, include_gripper=True) for a, b in zip(steps, steps[1:], strict=False)) < 4
    m2 = mover(gripper="open")
    walk(m2, ["hover"], delay=0)
    assert m2.arm_log.sent[-1][GRIPPER] == MOTION["gripper_open"]


def test_slideshow_waits_for_enter_and_understands_back_and_quit():
    m = mover()
    answers = iter(["", "", "b", "", "q"])
    asked = []
    slideshow(m, ["hover", "transit", "metal_bin"], lambda p: asked.append(p) or next(answers))
    assert passed(m) == ["hover", "transit", "metal_bin", "transit", "metal_bin"]
    assert len(asked) == 5 and m.at == "metal_bin"
    done = mover()
    slideshow(done, ["hover", "transit"], lambda p: "")  # Enter all the way ends after the last pose
    assert done.at == "transit"


def test_go_holds_a_pose_and_takes_another_name():
    m = mover()
    answers = iter(["metal_bin", "bogus", "home", ""])
    go(m, "hover", lambda p: next(answers))
    assert passed(m) == ["hover", "transit", "metal_bin", "home"] and m.at == "home"
    assert any("not a captured pose" in line for line in m.said)


def test_the_arm_must_start_at_a_known_pose():
    far = {**CAPTURED["home"], "shoulder_pan.pos": 70.0, "elbow_flex.pos": 20.0}
    arm = Arm(far)
    m = Mover(arm, CAPTURED, MOTION, Clock(), say=lambda *_: None)
    with pytest.raises(StartError, match="not at a captured pose.*--from-anywhere"):
        m.locate()
    m.locate(from_anywhere=True)
    assert m.at == nearest(far, CAPTURED)[0]
    with pytest.raises(StartError, match="no poses"):
        Mover(Arm(far), {}, MOTION, Clock()).locate()


def test_the_emergency_stop_ends_a_move_at_once():
    pressed = {"on": False}
    m = mover(paused=lambda: pressed["on"])
    original = m.arm.send

    def send(action):
        original(action)
        if len(m.arm_log.sent) == 5:
            pressed["on"] = True
    m.arm.send = send
    with pytest.raises(Stop, match="emergency"):
        m.visit("hover")
    assert len(m.arm_log.sent) == 5 and m.at is None  # unknown where it is: the next route starts from scratch


def test_estimate_counts_the_way_home_too():
    m = mover()
    short = estimate(m, ["hover"])
    assert short > 2 * MOTION["min_move_s"] and estimate(m, ["hover", "metal_bin"]) > short
    assert set(JOINT_KEYS) <= set(m.here())


class SlowArm(Arm):
    """Moves at most `rate` degrees per command towards it, like a follower that is slower than the plan;
    `the `stuck` joint never moves."""

    def __init__(self, start, rate=1.5, stuck=None):
        super().__init__(start)
        self.rate, self.stuck, self.ahead = rate, stuck, []

    def send(self, action):
        self.ahead.append(max(abs(action[k] - self.joints[k]) for k in JOINT_KEYS))
        for k in JOINT_KEYS:
            if self.stuck and k == self.stuck[0]:
                continue
            self.joints[k] += max(-self.rate, min(self.rate, action[k] - self.joints[k]))
        self.sent.append(dict(self.joints))


def test_the_goal_sent_to_the_arm_changes_smoothly_even_when_the_arm_lags():
    """Stop-and-go commands shake the arm: the step between consecutive goals must change gently."""
    class Recording(SlowArm):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.goals = []

        def send(self, action):
            self.goals.append(action["elbow_flex.pos"])
            super().send(action)

    arm = Recording(CAPTURED["home"], rate=1.2)
    m, _ = slow_mover(arm)
    m.locate()
    m.visit("hover")
    steps = [b - a for a, b in zip(arm.goals, arm.goals[1:], strict=False)]
    jerk = max(abs(b - a) for a, b in zip(steps, steps[1:], strict=False))
    assert jerk < 1.0, f"the goal speeds up or stops by {jerk:.2f} degrees per tick in one tick"
    middle = steps[len(steps) // 5: -len(steps) // 5]
    assert min(abs(d) for d in middle) > 0.05  # it never stands still on the way


def slow_mover(arm):
    said = []
    return Mover(arm, CAPTURED, MOTION, Clock(), say=said.append), said


def test_a_slow_arm_is_never_commanded_far_ahead_and_the_move_ends_on_the_pose():
    arm = SlowArm(CAPTURED["home"], rate=1.2)  # about 36 deg/s: slower than the plan's peak
    m, said = slow_mover(arm)
    m.locate()
    m.visit("hover")
    assert max(arm.ahead) <= LAG_DEG + 3.5  # never far enough ahead for the follower's 10 degree clamp
    assert max_joint_distance(arm.joints, CAPTURED["hover"]) <= 2.5 and m.at == "hover"
    assert m.errors["hover"] <= 2.5 and not any("short" in line for line in said)


def test_an_arm_that_does_not_follow_stops_the_move():
    arm = SlowArm(CAPTURED["home"], stuck=("elbow_flex.pos", 0))
    m, _ = slow_mover(arm)
    m.locate()
    with pytest.raises(MoveError, match="is .* degrees behind the command"):
        m.visit("hover")
    assert m.at is None


def test_an_arm_that_stops_short_is_reported():
    class Sagging(Arm):
        def send(self, action):  # the shoulder sags under its load: it ends 5.5 degrees short of the pose
            super().send({**action, "shoulder_lift.pos": min(action["shoulder_lift.pos"], CAPTURED["hover"]["shoulder_lift.pos"] - 5.5)})
    arm = Sagging(CAPTURED["home"])
    m, said = slow_mover(arm)
    m.locate()
    m.visit("hover")
    assert m.errors["hover"] == pytest.approx(5.5, abs=0.3) and any("5.5 degrees short" in line for line in said)
