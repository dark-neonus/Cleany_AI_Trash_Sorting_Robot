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
  * The leader's gripper servo can be a 12 V model: on the leader's 5 V it cannot drive the handle
    (measured 2026-11-23: it stalls with almost no current, then reports Overload and Input voltage
    errors; the other five servos are 7.4 V models). With drive_gripper=False the script never
    commands or enables the gripper: it stays free in the person's hand, as in plain teleoperation.
  * A person who grabs the handle while the leader holds a pose squeezes the trigger against the
    held gripper goal, which overloads the servo too (that was the Overload at the start of every
    recording). While the leader is held by script its gripper therefore pushes with only
    `gripper_torque` percent of its force, and an Overload flag seen when the torque goes off, which is
    that same hand, is only noted in `notes`, not shown as a warning.
"""

from __future__ import annotations

from comm_retry import retry
from motor_state import JOINTS

GRIPPER = "gripper"
GRIPPER_MARGIN = 3.0  # percent of the gripper range kept clear of each end stop
FULL_TORQUE = 1000  # Torque_Limit register: 0-1000


def inside_range(value: float, margin: float = GRIPPER_MARGIN) -> float:
    return min(100.0 - margin, max(margin, float(value)))


class Leader:
    """teleop: lerobot's SO101Leader (its .bus and get_action()). Torque on holds it where it is first."""

    def __init__(self, teleop, gripper_torque: float = 40, drive_gripper: bool = True):
        """gripper_torque: percent of its force the gripper holds with while the leader is held by script.
        drive_gripper: False leaves the gripper alone (torque off, no goals), see above."""
        self.teleop, self.bus = teleop, teleop.bus
        self.drive_gripper = drive_gripper
        self.torque = False
        self.gripper_limit = round(FULL_TORQUE * min(max(gripper_torque, 5), 100) / 100)
        self.warnings: list[str] = []  # servo error flags worth showing (an overload that is not a hand)
        self.notes: list[str] = []  # expected ones: an overload when the torque goes off

    def read(self) -> dict:
        return retry(self.teleop.get_action)

    def command(self, degrees: dict):
        goal = {j: degrees[f"{j}.pos"] for j in JOINTS if self.drive_gripper or j != GRIPPER}
        if self.drive_gripper:
            goal[GRIPPER] = inside_range(goal[GRIPPER])
        retry(self.bus.sync_write, "Goal_Position", goal)

    def _write(self, name: str, motor: str, value: int):
        """One register write; a servo's error flag in the reply is noted, not raised."""
        try:
            retry(self.bus.write, name, motor, value)
        except RuntimeError as error:  # the servo answered with an error flag (ConnectionError is not one)
            text = f"leader {motor}: {name} {value}: {str(error).strip()}"
            hand = name == "Torque_Enable" and value == 0 and "Overload" in text  # a person fought the hold
            seen = self.notes if hand else self.warnings
            if text not in seen:
                seen.append(text)

    def set_torque(self, on: bool):
        if on and not self.torque:
            present = dict(retry(self.bus.sync_read, "Present_Position"))
            if self.drive_gripper:
                present[GRIPPER] = inside_range(present[GRIPPER])
            else:
                present.pop(GRIPPER, None)
            retry(self.bus.sync_write, "Goal_Position", present)
            for motor in present:
                self._write("Torque_Enable", motor, 1)
                self._write("Lock", motor, 1)
            if self.drive_gripper:
                self._write("Torque_Limit", GRIPPER, self.gripper_limit)  # a hand on the trigger moves it, not overloads it
        elif not on and self.torque:
            for motor in self.bus.motors:
                self._write("Torque_Enable", motor, 0)
                self._write("Lock", motor, 0)
            if self.drive_gripper:
                self._write("Torque_Limit", GRIPPER, FULL_TORQUE)
        self.torque = on
