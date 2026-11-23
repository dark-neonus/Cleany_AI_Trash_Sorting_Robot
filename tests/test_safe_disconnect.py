import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "common"))
from safe_disconnect import release  # noqa: E402


class Bus:
    motors = {"a": 1, "gripper": 6}

    def __init__(self):
        self.writes, self.closed = [], False

    def write(self, register, motor, value, num_retry=0):
        self.writes.append(motor)
        if motor == "gripper":
            raise RuntimeError("[RxPacketError] Overload error!")

    def disconnect(self, torque=True):
        self.closed = True


class Camera:
    disconnected = False

    def disconnect(self):
        self.disconnected = True


class Arm:
    is_connected = True

    def __init__(self, fail):
        self.bus, self.cameras, self.fail = Bus(), {"front": Camera()}, fail

    def disconnect(self):
        if self.fail:
            raise RuntimeError("Failed to write 'Torque_Enable' on id_=6: Overload error!")


def test_a_flagged_servo_does_not_keep_the_cameras_running():
    arm, said = Arm(fail=True), []
    release(arm, said.append)
    assert arm.bus.writes == ["a", "gripper"]  # every servo was told, the flagged one too
    assert arm.cameras["front"].disconnected and arm.bus.closed
    assert any("Overload" in line for line in said)


def test_a_clean_disconnect_is_left_to_the_arm():
    arm = Arm(fail=False)
    release(arm)
    assert arm.bus.writes == [] and not arm.bus.closed
