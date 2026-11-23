"""A minimum-jerk move that is paced by the arm, used by the pipeline, the pick recorder and the
pose viewer (scripts/run/box_states.py, scripts/common/pose_show.py).

Why: the follower limits every command to --max-step degrees from where it really is, and on the arm
that makes it track only about 48 deg/s, while the plan peaks at about 85 deg/s. A plan played at its
own pace runs ahead (after a second the elbow was 33 degrees behind), lerobot prints a clamp warning
per command, and the next state starts before the arm has arrived.

What: the plan advances by `rate` each tick; rate is 1 while the arm is less than lag_deg/2 behind
the last command and falls smoothly to 0 at lag_deg, so the arm is never commanded far ahead and the
goal never stops and starts. A goal that holds until the arm catches up and then jumps makes the arm
SHAKE: that was tried and failed on the arm. After the last command the move waits for the arm to
settle on the target.

The gripper is left out of the pacing and the settling by default: while it holds an item it is
blocked on purpose, command below measured, and must not slow the arm.
"""

from __future__ import annotations

from dataclasses import dataclass

from box_logic import GRIPPER, interpolate, move_duration, profile

LAG_DEG = 8  # the plan stands still at this lag (keep it below --max-step); half of it: no slowing yet
STALL_S = 3.0  # standing still this long: the arm is not following (blocked? torque off?): stop
ARRIVE_S = 4.0  # after the last command, wait up to this long for the arm to settle on the target
ARRIVE_DEG = 2.5  # settled: every joint this close to the target
IDLE_DEG = 0.3  # an arm that moved less than this in a tick is standing still
IDLE_S = 0.5  # standing still this long after the last command: it will not get closer, stop waiting
SHORT_DEG = 5.0  # further off than this after ARRIVE_S: the arm stopped short
SMOOTH = 0.6  # how much of the previous rate is kept each tick (no chatter)


class MoveError(RuntimeError):
    """The arm does not follow the commands."""


@dataclass
class Result:
    aborted: bool = False  # on_tick returned False
    error: float = 0.0  # degrees the arm stopped short of the target (worst joint)
    joint: str = ""


def worst_joint(a: dict, b: dict, include_gripper: bool = False) -> tuple[str, float]:
    """The joint in which a and b differ most, and by how much (keys of a that b has)."""
    keys = [k for k in a if k in b and (include_gripper or k != GRIPPER)]
    key = max(keys, key=lambda k: abs(a[k] - b[k]))
    return key.removesuffix(".pos"), abs(a[key] - b[key])


def pacing(lag: float, lag_deg: float = LAG_DEG) -> float:
    """How fast the plan may advance, 1 (full speed) to 0 (standing still), for an arm `lag` degrees behind."""
    soft = lag_deg / 2
    return 1.0 if lag <= soft else max(0.0, (lag_deg - lag) / (lag_deg - soft))


def run(start: dict, target: dict, *, speed: float, min_s: float, fps: float, observe, send, clock,
        lag_deg: float = LAG_DEG, check=lambda: None, on_tick=None, include_gripper: bool = False,
        ramp_s: float | None = None) -> Result:
    """Move from start to target (joint dicts: "<joint>.pos" -> degrees), one command per tick.

    observe() -> what the arm reports (a dict with the joint keys; more is fine), called once per tick;
    send(command) sends the joint dict; clock has now() and sleep(); check() may raise to stop (the
    emergency stop); on_tick(obs) runs every tick, also while settling, and returns False to abort
    (a slipped item). Raises MoveError when the arm does not follow for STALL_S."""
    tick = 1 / fps
    total = move_duration(start, target, speed, min_s, ramp_s)
    phase, rate, command, still, obs = 0.0, 1.0, None, 0.0, None
    while phase < 1.0:
        began = clock.now()
        check()
        if command is not None:
            joint, lag = worst_joint(command, obs, include_gripper)
            rate = SMOOTH * rate + (1 - SMOOTH) * pacing(lag, lag_deg)
            still = still + tick if rate < 0.02 else 0.0
            if still > STALL_S:
                raise MoveError(f"The arm is not following: {joint} is {lag:.0f} degrees behind the command "
                                f"after {STALL_S:g} s (blocked? torque off?)")
        phase = min(1.0, phase + rate * tick / total)
        command = interpolate(start, target, profile(phase, total, ramp_s))
        send(command)
        obs = observe()
        if on_tick is not None and on_tick(obs) is False:
            return Result(aborted=True)
        clock.sleep(tick - (clock.now() - began))
    deadline, idle, before = clock.now() + ARRIVE_S, 0.0, {k: obs[k] for k in target}  # observations carry camera frames too
    while True:
        joint, error = worst_joint(target, obs, include_gripper)
        if error <= ARRIVE_DEG or idle >= IDLE_S or clock.now() >= deadline:
            return Result(error=error, joint=joint)
        began = clock.now()
        check()
        send(target)
        obs = observe()
        now = {k: obs[k] for k in target}
        idle = idle + tick if worst_joint(before, now, include_gripper)[1] < IDLE_DEG else 0.0
        before = now
        if on_tick is not None and on_tick(obs) is False:
            return Result(aborted=True)
        clock.sleep(tick - (clock.now() - began))
