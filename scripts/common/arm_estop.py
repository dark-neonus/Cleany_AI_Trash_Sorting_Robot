"""Stops the SO-101 follower while the emergency stop (estop.py, red panel button) is pressed.

Installed by lerobot_wide_fov.py in every mode. Every lerobot command (teleoperate, record,
rollout, replay) and sort_pipeline.py send their actions through SOFollower.send_action, so that
is what gets wrapped. Per follower, a state machine driven by estop.is_active():

  RUN        normal.
  RELEASING  the button was pressed: actions are no longer sent, the servos keep their last goal
             while Torque_Limit ramps down over ESTOP_TORQUE_RAMP_S (default 1), so the arm
             sags instead of dropping. Then torque is disabled and the original Torque_Limit
             written back.
  OFF        torque is off and actions are dropped; teleoperation keeps reading the leader, but
             the follower does not follow. Move the arm to a safe pose by hand, then press the
             button again.
  RESUMING   the button was released: goal := present position, torque on, then the commanded
             action is blended in from the present position over ESTOP_RESUME_S (default 2), so
             the arm does not jump to wherever the leader is.

send_action returns the requested action while released (callers such as lerobot-record
expect a full action); nothing was sent to the motors then. The stop takes effect on the next
send_action call, so a loop that is blocked elsewhere (e.g. inference) acts on it afterwards.
"""

import os
import time
from dataclasses import dataclass, field

import estop

from lerobot.robots.so_follower.so_follower import SOFollower

TORQUE_RAMP_S = float(os.environ.get("ESTOP_TORQUE_RAMP_S", "1"))
RESUME_S = float(os.environ.get("ESTOP_RESUME_S", "2"))

_original_send_action = SOFollower.send_action
_original_disconnect = SOFollower.disconnect


@dataclass
class _Guard:
    state: str = "RUN"
    t0: float = 0.0
    limits: dict[str, int] = field(default_factory=dict)  # Torque_Limit before the ramp
    start: dict[str, float] = field(default_factory=dict)  # present positions when resuming
    error_shown: bool = False


def _guard(robot) -> _Guard:
    if not hasattr(robot, "_estop_guard"):
        robot._estop_guard = _Guard()
    return robot._estop_guard


def _begin_release(robot, g: _Guard) -> None:
    g.limits = {motor: robot.bus.read("Torque_Limit", motor) for motor in robot.bus.motors}
    g.t0 = time.monotonic()
    g.state = "RELEASING"
    print(f"[estop] emergency stop: arm stopped, releasing torque over {TORQUE_RAMP_S:g} s")


def _step_release(robot, g: _Guard) -> None:
    fraction = (time.monotonic() - g.t0) / TORQUE_RAMP_S
    if fraction < 1:
        robot.bus.sync_write("Torque_Limit", {m: round(limit * (1 - fraction)) for m, limit in g.limits.items()})
        return
    robot.bus.disable_torque()
    robot.bus.sync_write("Torque_Limit", g.limits)  # back to normal for the next enable
    g.state = "OFF"
    print("[estop] arm torque off. Move it to a safe pose by hand, then press the button again.")


def _begin_resume(robot, g: _Guard) -> None:
    present = robot.bus.sync_read("Present_Position")
    # Torque is off: write the present position as the goal first, so enabling torque holds
    # the arm where the human put it instead of pulling it back to the pre-stop goal.
    robot.bus.sync_write("Goal_Position", present)
    robot.bus.enable_torque()
    g.start = {f"{motor}.pos": value for motor, value in present.items()}
    g.t0 = time.monotonic()
    g.state = "RESUMING"
    print(f"[estop] resumed: arm re-engaged, following again over {RESUME_S:g} s")


def _send_action(self, action):
    g = _guard(self)
    try:
        if estop.is_active() and g.state in ("RUN", "RESUMING"):
            _begin_release(self, g)
        elif not estop.is_active() and g.state == "OFF":
            _begin_resume(self, g)
        if g.state == "RELEASING":
            _step_release(self, g)
        g.error_shown = False
    except Exception as error:  # a bus error must not end the session; retry on the next call
        if not g.error_shown:
            print(f"[estop] arm guard error ({error.__class__.__name__}: {error}); retrying")
            g.error_shown = True

    if g.state in ("RELEASING", "OFF"):
        return action
    if g.state == "RESUMING":
        alpha = min(1.0, (time.monotonic() - g.t0) / RESUME_S)
        eased = alpha * alpha * (3 - 2 * alpha)
        action = {k: g.start[k] + (v - g.start[k]) * eased if k in g.start else v for k, v in action.items()}
        if alpha >= 1:
            g.state = "RUN"
    return _original_send_action(self, action)


def _disconnect(self, *args, **kwargs):
    g = getattr(self, "_estop_guard", None)
    if g is not None and g.state == "RELEASING":  # leave no reduced Torque_Limit in the servos
        try:
            self.bus.sync_write("Torque_Limit", g.limits)
        except Exception:
            pass
    return _original_disconnect(self, *args, **kwargs)


def install() -> None:
    SOFollower.send_action = _send_action
    SOFollower.disconnect = _disconnect
