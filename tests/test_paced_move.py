"""The paced move (scripts/common/paced_move.py) on simulated arms."""

import math

import pytest
from box_logic import GRIPPER, JOINT_KEYS
from box_states import Stop
from paced_move import ARRIVE_DEG, ARRIVE_S, LAG_DEG, MoveError, pacing, run, worst_joint

HOME = dict.fromkeys(JOINT_KEYS, 0.0)
TARGET = {**HOME, "shoulder_lift.pos": 60.0, "elbow_flex.pos": -40.0, GRIPPER: 0.0}
KW = {"speed": 45, "min_s": 0.8, "fps": 30}


class Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += max(s, 0.0)


class Arm:
    """Follows at most `rate` degrees per command per joint; joints in `stuck` never move."""

    def __init__(self, rate=1e9, stuck=(), short=None):
        self.joints, self.rate, self.stuck, self.short = dict(HOME), rate, stuck, short
        self.commands = []

    def send(self, command):
        self.commands.append(dict(command))
        for k in JOINT_KEYS:
            if k in self.stuck:
                continue
            goal = command[k] if not self.short or k != self.short[0] else command[k] - math.copysign(self.short[1], command[k])
            self.joints[k] += max(-self.rate, min(self.rate, goal - self.joints[k]))

    def observe(self):
        return dict(self.joints)


def go(arm, clock=None, **kw):
    clock = clock or Clock()
    return run(dict(HOME), TARGET, observe=arm.observe, send=arm.send, clock=clock, **KW, **kw), clock


def test_pacing_is_full_speed_until_half_the_limit_then_falls_to_zero():
    assert pacing(0) == pacing(LAG_DEG / 2) == 1.0
    assert pacing(LAG_DEG * 0.75) == pytest.approx(0.5)
    assert pacing(LAG_DEG) == pacing(LAG_DEG * 3) == 0.0
    assert pacing(5, lag_deg=20) == 1.0 and pacing(15, lag_deg=20) == pytest.approx(0.5)


def test_an_arm_that_keeps_up_gets_the_plain_minimum_jerk_move():
    arm = Arm()
    result, clock = go(arm)
    assert not result.aborted and result.error == 0 and arm.joints == TARGET
    assert len(arm.commands) == math.ceil(max(60, 40) / 45 * 30)  # the plan's duration at 45 deg/s: no slowing


def test_a_slow_arm_slows_the_plan_instead_of_being_commanded_far_ahead():
    arm = Arm(rate=1.0)  # 30 deg/s
    result, clock = go(arm)
    ahead = [max(abs(c[k] - j[k]) for k in JOINT_KEYS) for c, j in zip(arm.commands, [HOME, *arm.commands], strict=False)]
    assert max(abs(arm.joints[k] - TARGET[k]) for k in JOINT_KEYS if k != GRIPPER) <= ARRIVE_DEG
    assert len(arm.commands) > math.ceil(60 / 45 * 30) * 1.3  # it took longer than the plan
    # the goal never ran further ahead than the lag limit plus one plan step
    lag = max(max(abs(c[k] - a_[k]) for k in JOINT_KEYS) for c, a_ in zip(arm.commands[1:], arm.commands, strict=False))
    assert lag < 4 and ahead  # steps between consecutive goals stay small


def test_the_gripper_is_left_out_unless_asked():
    target = {**TARGET, GRIPPER: 80.0}
    blocked = Arm(stuck=(GRIPPER,))  # holding an item: it cannot close, or open, any further
    result = run(dict(HOME), target, observe=blocked.observe, send=blocked.send, clock=Clock(), **KW)
    assert not result.aborted and result.error == 0  # the arm joints arrived; the gripper did not matter
    with pytest.raises(MoveError, match="gripper is .* degrees behind"):
        run(dict(HOME), target, observe=blocked.observe, send=blocked.send, clock=Clock(), include_gripper=True, **KW)


def test_an_arm_that_does_not_follow_is_a_move_error_after_a_few_seconds():
    arm = Arm(stuck=("elbow_flex.pos",))
    clock = Clock()
    with pytest.raises(MoveError, match="not following: elbow_flex"):
        go(arm, clock)
    assert 3.0 < clock.t < 8.0


def test_an_arm_that_stops_short_is_reported_once_it_stands_still():
    arm = Arm(short=("shoulder_lift.pos", 4.0))
    result, clock = go(arm)
    assert result.error == pytest.approx(4.0, abs=0.1) and result.joint == "shoulder_lift"
    assert clock.t < ARRIVE_S  # it is not waited for the whole settle time: it stood still, it will not get closer


def test_on_tick_can_abort_and_check_can_stop():
    arm, seen = Arm(), []

    def on_tick(obs):
        seen.append(obs)
        return len(seen) < 10
    result = run(dict(HOME), TARGET, observe=arm.observe, send=arm.send, clock=Clock(), on_tick=on_tick, **KW)
    assert result.aborted and len(arm.commands) == 10

    arm2 = Arm()

    def check():
        if len(arm2.commands) == 5:
            raise Stop("emergency stop")
    with pytest.raises(Stop):
        run(dict(HOME), TARGET, observe=arm2.observe, send=arm2.send, clock=Clock(), check=check, **KW)
    assert len(arm2.commands) == 5


def test_worst_joint_names_the_joint_and_skips_the_gripper_by_default():
    a, b = {**HOME, "wrist_flex.pos": 9.0, GRIPPER: 50.0}, dict(HOME)
    assert worst_joint(a, b) == ("wrist_flex", 9.0)
    assert worst_joint({**HOME, GRIPPER: 50.0}, b, include_gripper=True) == ("gripper", 50.0)


def test_observations_with_camera_frames_are_fine():
    import numpy as np
    arm = Arm(short=("shoulder_lift.pos", 4.0))
    result, _ = go(type("Seen", (), {"send": arm.send, "observe": lambda self: {**arm.observe(), "front": np.zeros((4, 4, 3))}})())
    assert result.error == pytest.approx(4.0, abs=0.1)
