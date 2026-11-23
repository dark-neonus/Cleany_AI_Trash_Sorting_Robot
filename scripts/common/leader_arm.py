"""The leader arm as the pick recorder drives it: held at a pose, moved by script, or limp in the hand
(scripts/dataset/record_pick.py, tests/test_leader_arm.py).

Two things learned on the arm (2026-11-23):
  * A servo that reports an error flag in its reply to a write (Overload: it was pushed past its
    load limit, for instance a gripper held against its end stop) makes lerobot raise a RuntimeError
    even though the servo carried the write out. Switching torque off must not end the session
    because of that: the flags are collected in `warnings` and shown, only a lost connection raises.
  * The gripper must not be commanded to the very ends of its range: its calibrated minimum and
    maximum are the mechanical stops, and holding a goal against a stop overloads the servo. The
    gripper goal is kept GRIPPER_MARGIN percent inside.
"""

from __future__ import annotations

from motor_state import JOINTS

GRIPPER = "gripper"
GRIPPER_MARGIN = 3.0  # percent of the gripper range kept clear of each end stop


def inside_range(value: float, margin: float = GRIPPER_MARGIN) -> float:
    return min(100.0 - margin, max(margin, float(value)))


class Leader:
    """teleop: lerobot's SO101Leader (its .bus and get_action()). Torque on holds it where it is first."""

    def __init__(self, teleop):
        self.teleop, self.bus = teleop, teleop.bus
        self.torque = False
        self.warnings: list[str] = []  # servo error flags seen while switching torque (overload, ...)

    def read(self) -> dict:
        return self.teleop.get_action()

    def command(self, degrees: dict):
        goal = {j: degrees[f"{j}.pos"] for j in JOINTS}
        goal[GRIPPER] = inside_range(goal[GRIPPER])
        self.bus.sync_write("Goal_Position", goal)

    def _write(self, name: str, motor: str, value: int):
        """One register write; a servo's error flag in the reply is noted, not raised."""
        try:
            self.bus.write(name, motor, value)
        except RuntimeError as error:  # the servo answered with an error flag (ConnectionError is not one)
            text = f"leader {motor}: {name} {value}: {str(error).strip()}"
            if text not in self.warnings:
                self.warnings.append(text)

    def set_torque(self, on: bool):
        if on and not self.torque:
            present = dict(self.bus.sync_read("Present_Position"))
            present[GRIPPER] = inside_range(present[GRIPPER]) if GRIPPER in present else None
            self.bus.sync_write("Goal_Position", {m: v for m, v in present.items() if v is not None})
            for motor in self.bus.motors:
                self._write("Torque_Enable", motor, 1)
                self._write("Lock", motor, 1)
        elif not on and self.torque:
            for motor in self.bus.motors:
                self._write("Torque_Enable", motor, 0)
                self._write("Lock", motor, 0)
        self.torque = on
