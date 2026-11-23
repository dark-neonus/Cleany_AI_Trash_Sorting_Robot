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
  * A person who grabs the handle while the leader holds a pose squeezes the trigger against the
    held gripper goal, which overloads the servo too (that was the Overload at the start of every
    recording). While the leader is held by script its gripper therefore pushes with only
    `gripper_torque` percent of its force, and an Overload flag seen when the torque goes off, which is
    that same hand, is only noted in `notes`, not shown as a warning.
"""

from __future__ import annotations

from motor_state import JOINTS

GRIPPER = "gripper"
GRIPPER_MARGIN = 3.0  # percent of the gripper range kept clear of each end stop
FULL_TORQUE = 1000  # Torque_Limit register: 0-1000


def inside_range(value: float, margin: float = GRIPPER_MARGIN) -> float:
    return min(100.0 - margin, max(margin, float(value)))


class Leader:
    """teleop: lerobot's SO101Leader (its .bus and get_action()). Torque on holds it where it is first."""

    def __init__(self, teleop, gripper_torque: float = 40):
        """gripper_torque: percent of its force the gripper holds with while the leader is held by script."""
        self.teleop, self.bus = teleop, teleop.bus
        self.torque = False
        self.gripper_limit = round(FULL_TORQUE * min(max(gripper_torque, 5), 100) / 100)
        self.warnings: list[str] = []  # servo error flags worth showing (an overload that is not a hand)
        self.notes: list[str] = []  # expected ones: an overload when the torque goes off

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
            hand = name == "Torque_Enable" and value == 0 and "Overload" in text  # a person fought the hold
            seen = self.notes if hand else self.warnings
            if text not in seen:
                seen.append(text)

    def set_torque(self, on: bool):
        if on and not self.torque:
            present = dict(self.bus.sync_read("Present_Position"))
            present[GRIPPER] = inside_range(present[GRIPPER]) if GRIPPER in present else None
            self.bus.sync_write("Goal_Position", {m: v for m, v in present.items() if v is not None})
            for motor in self.bus.motors:
                self._write("Torque_Enable", motor, 1)
                self._write("Lock", motor, 1)
            self._write("Torque_Limit", GRIPPER, self.gripper_limit)  # a hand on the trigger moves it, not overloads it
        elif not on and self.torque:
            for motor in self.bus.motors:
                self._write("Torque_Enable", motor, 0)
                self._write("Lock", motor, 0)
            self._write("Torque_Limit", GRIPPER, FULL_TORQUE)
        self.torque = on
