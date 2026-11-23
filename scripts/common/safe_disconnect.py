"""Disconnect an arm even when a servo reports a status flag on the way out.

lerobot's disconnect switches the torque off first, then disconnects the cameras. A servo that is
overloaded (a gripper squeezing a glass bottle) answers its Torque_Enable write with an Overload
flag, lerobot raises, and the camera threads are left running: the process then aborts on exit
("FATAL: exception not rethrown", a core dump). The flag only reports the state: the write itself went
through. So each step is done on its own and a flag is reported, not raised.
"""

from __future__ import annotations


def release(device, say=lambda text: None) -> None:
    """Torque off on every servo, cameras and port closed; whatever fails is said, none stops the rest."""
    try:
        if not device.is_connected:
            return
    except Exception:  # noqa: BLE001
        pass
    try:
        device.disconnect()
        return
    except Exception as error:  # noqa: BLE001
        say(f"disconnect failed ({error.__class__.__name__}: {error}); releasing the parts one by one")
    bus = getattr(device, "bus", None)
    if bus is not None:
        for motor in list(bus.motors):
            try:
                bus.write("Torque_Enable", motor, 0, num_retry=2)
            except Exception as error:  # noqa: BLE001  (a status flag: the write still went through)
                say(f"{motor}: torque off answered with {error.__class__.__name__}")
    for name, camera in (getattr(device, "cameras", None) or {}).items():
        try:
            camera.disconnect()
        except Exception as error:  # noqa: BLE001
            say(f"camera {name}: {error.__class__.__name__}: {error}")
    if bus is not None:
        try:
            bus.disconnect(False)
        except Exception as error:  # noqa: BLE001
            say(f"port: {error.__class__.__name__}: {error}")
