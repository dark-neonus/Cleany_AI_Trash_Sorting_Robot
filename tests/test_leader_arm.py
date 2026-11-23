"""The leader arm driver (scripts/common/leader_arm.py) on a fake servo bus."""

import pytest
from leader_arm import GRIPPER_MARGIN, Leader
from motor_state import JOINTS


class Bus:
    """Records writes; a servo can answer with an error flag (lerobot raises RuntimeError for it)."""

    def __init__(self, flagged=None):
        self.motors = dict.fromkeys(JOINTS)
        self.flagged, self.writes, self.goals = flagged or {}, [], []

    def write(self, name, motor, value):
        self.writes.append((name, motor, value))  # the servo carried it out either way
        if (name, motor) in self.flagged:
            raise RuntimeError(f"Failed to write {name!r} on id_=6 with '{value}' after 1 tries. {self.flagged[(name, motor)]}")

    def sync_write(self, name, values):
        self.goals.append(dict(values))

    def sync_read(self, name):
        return {**dict.fromkeys(JOINTS, 0.0), "gripper": 50.0}


class Teleop:
    def __init__(self, bus):
        self.bus = bus

    def get_action(self):
        return {}


def degrees(gripper):
    return {f"{j}.pos": 0.0 for j in JOINTS} | {"gripper.pos": gripper}


def test_an_overload_flag_while_switching_torque_off_is_noted_not_fatal_nor_shown():
    bus = Bus({("Torque_Enable", "gripper"): "[RxPacketError] Overload error!"})
    leader = Leader(Teleop(bus))
    leader.torque = True
    leader.set_torque(False)  # used to raise and end the session
    assert not leader.torque
    assert ("Lock", "gripper", 0) in bus.writes  # carried on to the next register and the other servos
    assert [w[1] for w in bus.writes if w[0] == "Torque_Enable"] == list(JOINTS)
    assert leader.warnings == [] and len(leader.notes) == 1  # a hand on the trigger: expected, not a warning
    assert "Overload" in leader.notes[0] and "gripper" in leader.notes[0]
    leader.torque = True
    leader.set_torque(False)
    assert len(leader.notes) == 1  # the same flag is not repeated


def test_other_servo_flags_are_shown():
    bus = Bus({("Torque_Enable", "elbow_flex"): "[RxPacketError] Overload error!"})
    leader = Leader(Teleop(bus))
    leader.set_torque(True)  # an overload while switching ON is not a hand
    assert len(leader.warnings) == 1 and "elbow_flex" in leader.warnings[0]


def test_the_leader_gripper_holds_gently_under_script_and_fully_again_when_released():
    bus = Bus()
    leader = Leader(Teleop(bus), gripper_torque=40)
    leader.set_torque(True)
    assert ("Torque_Limit", "gripper", 400) in bus.writes
    assert bus.writes.index(("Torque_Limit", "gripper", 400)) > bus.writes.index(("Torque_Enable", "gripper", 1))
    leader.set_torque(False)
    assert bus.writes[-1] == ("Torque_Limit", "gripper", 1000)
    assert Leader(Teleop(bus), gripper_torque=500).gripper_limit == 1000 and Leader(Teleop(bus), 0).gripper_limit == 50


def test_a_lost_connection_still_raises():
    bus = Bus()
    bus.write = lambda *a: (_ for _ in ()).throw(ConnectionError("no status packet"))
    leader = Leader(Teleop(bus))
    leader.torque = True
    with pytest.raises(ConnectionError):
        leader.set_torque(False)


def test_the_gripper_goal_stays_off_the_end_stops():
    bus = Bus()
    leader = Leader(Teleop(bus))
    for asked, got in ((0, GRIPPER_MARGIN), (100, 100 - GRIPPER_MARGIN), (60, 60)):
        leader.command(degrees(asked))
        assert bus.goals[-1]["gripper"] == pytest.approx(got)
    leader.set_torque(True)  # holds where it is: a gripper resting on its stop is eased off it
    assert bus.goals[-1]["gripper"] == 50.0
    bus2 = Bus()
    bus2.sync_read = lambda name: {**dict.fromkeys(JOINTS, 0.0), "gripper": 0.0}
    Leader(Teleop(bus2)).set_torque(True)
    assert bus2.goals[-1]["gripper"] == GRIPPER_MARGIN and bus2.writes[0] == ("Torque_Enable", "shoulder_pan", 1)
