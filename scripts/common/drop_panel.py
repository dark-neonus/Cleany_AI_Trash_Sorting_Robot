"""Trash drop mechanism (ESP32-C3, electronics/drop_firmware) client and control panel section.

DropController keeps the serial connection in a background thread: it polls READ every
POLL_S and sends the button commands. add_drop_section() adds the panel section (door
state, current / drop threshold, overload flag, servo angles, OPEN / OPEN and HOLD /
CLOSE and HOLD / STOP / RESET OVERLOAD buttons) to a tkinter window; run_drop_panel()
opens a window with only that section.

Overload: the firmware opens the doors, sets its overload flag and refuses motion until
RESET_OVERLOAD. DropController.overload_seen is set when a READ reports the flag and stays
set until the RESET OVERLOAD button was pressed and the board confirmed it, so a board
reboot alone never releases it. arm_overload_guard.py stops the follower while it is set.

lerobot_wide_fov.py shows the panel in the recording panel and in its own window for
teleoperation, rollout and replay (DROP_PANEL=false turns the panel and the arm guard off).
The port is DROP_PORT if set, otherwise the first USB device with Espressif's vendor ID
(the C3's native USB). Opening the port may reset the C3 (its startup test then moves the
doors).
"""

import os
import threading
import time
import tkinter as tk
from dataclasses import dataclass, field

import serial
from serial.tools import list_ports

ESPRESSIF_VID = 0x303A
POLL_S = 0.1
RECONNECT_S = 2.0

STATE_COLORS = {"CLOSED": "#2e7d32", "OPEN": "#ef6c00", "OPENING": "#1565c0", "CLOSING": "#1565c0",
                "STOPPED": "#b71c1c", "PARTIAL": "#b71c1c", "OFF": "#546e7a"}


@dataclass
class DropStatus:
    connected: bool = False
    port: str | None = None
    current_ma: int | None = None
    max_ma: int | None = None  # None: overload detection is off
    state: str = "?"
    overload: bool = False  # the board's flag
    sensor_ok: bool = True  # False: current sensor fault, overload detection off
    calibrating: bool = False  # a ZERO cycle runs (the doors open and close by themselves)
    angles: dict[str, int] = field(default_factory=dict)
    message: str = ""


def find_port() -> str | None:
    if os.environ.get("DROP_PORT"):
        return os.environ["DROP_PORT"]
    for port in list_ports.comports():
        if port.vid == ESPRESSIF_VID:
            return port.device
    return None


def parse_read(line: str) -> dict | None:
    """'R I=13 MAX=100 OVL=0 SENS=1 CAL=0 ZERO=1514 S=CLOSED FR=15 ...' -> fields, or None."""
    if not line.startswith("R "):
        return None
    fields = dict(part.split("=", 1) for part in line[2:].split() if "=" in part)
    try:
        return {
            "current_ma": int(fields.pop("I")),
            "max_ma": None if fields["MAX"] == "-" else int(fields["MAX"]),
            "state": fields.pop("S"),
            "overload": fields["OVL"] == "1",
            "sensor_ok": fields.get("SENS", "1") == "1",
            "calibrating": fields.get("CAL", "0") == "1",
            "angles": {k: int(v) for k, v in fields.items() if k not in ("MAX", "OVL", "SENS", "CAL", "ZERO")},
        }
    except (KeyError, ValueError):
        return None


class DropController:
    def __init__(self):
        self.status = DropStatus()
        self.overload_seen = False  # see the module docstring
        self._reset_pressed = False
        self._commands: list[str] = []
        self._lock = threading.Lock()
        threading.Thread(target=self._run, name="drop_controller", daemon=True).start()

    def send(self, command: str) -> None:
        with self._lock:
            self._commands.append(command)

    def calibrate_zero(self) -> None:
        """Ask the board for a ZERO cycle (it opens and closes the doors, then re-zeroes the sensor)."""
        self.send("ZERO")

    def reset_overload(self) -> None:
        """RESET OVERLOAD button: the board closes the doors; the arm is released once it confirms."""
        self._reset_pressed = True
        self.send("RESET_OVERLOAD")

    def _run(self) -> None:
        while True:
            port = find_port()
            if port is None:
                self.status = DropStatus(message="ESP32 not found")
                time.sleep(RECONNECT_S)
                continue
            try:
                with serial.Serial(port, 115200, timeout=0.2) as ser:
                    self.status = DropStatus(connected=True, port=port)
                    self._poll(ser)
            except (serial.SerialException, OSError) as error:
                self.status = DropStatus(port=port, message=f"disconnected ({error.__class__.__name__})")
                time.sleep(RECONNECT_S)

    def _poll(self, ser: serial.Serial) -> None:
        ser.reset_input_buffer()
        while True:
            with self._lock:
                commands, self._commands = self._commands, []
            for command in commands + ["READ"]:
                ser.write(f"{command}\n".encode())
            deadline = time.monotonic() + 0.5
            pending = len(commands) + 1  # one reply line per command
            while pending and time.monotonic() < deadline:
                line = ser.readline().decode(errors="replace").strip()
                if not line:
                    continue
                if line.startswith(("R ", "OK ", "ERR ")):
                    pending -= 1
                read = parse_read(line)
                if read:
                    self.status = DropStatus(connected=True, port=ser.port, **read,
                                             message=self.status.message)
                    if read["overload"]:
                        self.overload_seen = True
                elif line == "OK ZERO":
                    # The board drops its overload flag for a ZERO cycle: the baseline it was judged
                    # against is being re-measured. Only the connect hook and the button send it.
                    self.overload_seen = False
                    self.status.message = ""
                elif line in ("OK RESET_OVERLOAD", "ERR not overloaded") and self._reset_pressed:
                    # The board is closing the doors (or was not overloaded): release the arm.
                    self._reset_pressed = False
                    self.overload_seen = False
                    self.status.message = ""
                elif line.startswith("ERR "):
                    self.status.message = line[4:]
                elif line.startswith("OK "):
                    self.status.message = ""
            time.sleep(POLL_S)


def add_drop_section(parent: tk.Misc, controller: DropController) -> tk.Frame:
    """Pack a 'Trash drop' section into parent and keep it refreshed."""
    frame = tk.LabelFrame(parent, text="Trash drop", font=("Sans", 10, "bold"), padx=8, pady=6)
    frame.pack(padx=16, pady=(0, 12), fill="x")

    state_label = tk.Label(frame, font=("Sans", 16, "bold"))
    state_label.grid(row=0, column=0, columnspan=2, sticky="w")
    overload_label = tk.Label(frame, font=("Sans", 10, "bold"), fg="#b71c1c", justify="left")
    overload_label.grid(row=6, column=0, columnspan=2, sticky="w")
    current_label = tk.Label(frame, font=("Sans", 12))
    current_label.grid(row=1, column=0, columnspan=2, sticky="w")
    detail_label = tk.Label(frame, font=("Sans", 9), fg="#666666", justify="left")
    detail_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 6))

    buttons = [
        tk.Button(frame, text="OPEN (2 s)", width=18, font=("Sans", 11, "bold"),
                  command=lambda: controller.send("OPEN")),
        tk.Button(frame, text="STOP", width=18, font=("Sans", 11, "bold"), fg="#b71c1c",
                  command=lambda: controller.send("STOP")),
        tk.Button(frame, text="OPEN and HOLD", width=18, command=lambda: controller.send("OPEN_HOLD")),
        tk.Button(frame, text="CLOSE and HOLD", width=18, command=lambda: controller.send("CLOSE")),
    ]
    for i, button in enumerate(buttons):
        button.grid(row=3 + i // 2, column=i % 2, padx=4, pady=4)
    reset_button = tk.Button(frame, text="RESET OVERLOAD", width=38, font=("Sans", 11, "bold"),
                             command=controller.reset_overload)
    reset_button.grid(row=5, column=0, columnspan=2, padx=4, pady=4)
    zero_button = tk.Button(frame, text="CALIBRATE CURRENT ZERO", width=38, command=controller.calibrate_zero)
    zero_button.grid(row=7, column=0, columnspan=2, padx=4, pady=4)

    def refresh() -> None:
        status = controller.status
        if status.connected and status.current_ma is not None:
            state_label.config(text=status.state, fg=STATE_COLORS.get(status.state, "#000000"))
            limit = f"{status.max_ma / 1000:.3f} A" if status.max_ma is not None else "off"
            if status.calibrating:
                current_label.config(text="Calibrating the current zero…", fg="#1565c0")
            elif status.sensor_ok:
                current_label.config(text=f"Current: {status.current_ma / 1000:.3f} / {limit}", fg="#000000")
            else:
                current_label.config(text="Current sensor FAULT: overload detection off", fg="#b71c1c")
            angles = "  ".join(f"{name} {deg}°" for name, deg in status.angles.items())
            detail_label.config(text=f"{angles}\n{status.message}".rstrip())
        else:
            state_label.config(text="Not connected", fg=STATE_COLORS["OFF"])
            current_label.config(text="Current: –")
            detail_label.config(text=status.message or "Connecting…")
        overloaded = controller.overload_seen
        if overloaded:
            state_label.config(text="OVERLOAD", fg=STATE_COLORS["STOPPED"])
            overload_label.config(text="Doors opened, arm stopped.\nMove the arm to its start pose "
                                       "by hand, then press RESET OVERLOAD.")
        else:
            overload_label.config(text="")
        idle = status.connected and not overloaded and not status.calibrating
        for button in buttons:  # the board refuses these while overloaded; STOP always works
            button.config(state=tk.NORMAL if idle else tk.DISABLED)
        buttons[1].config(state=tk.NORMAL if status.connected and not overloaded else tk.DISABLED)
        zero_button.config(state=tk.NORMAL if idle else tk.DISABLED)
        reset_button.config(state=tk.NORMAL if status.connected and overloaded else tk.DISABLED)
        frame.after(100, refresh)

    refresh()
    return frame


def run_drop_panel(controller: DropController, title: str = "Cleany trash drop") -> None:
    """Window with only the drop section; call from its own thread (it runs a Tk mainloop)."""
    root = tk.Tk()
    root.title(title)
    root.attributes("-topmost", True)
    root.resizable(False, False)
    root.protocol("WM_DELETE_WINDOW", root.iconify)  # closing it must not stop the robot
    tk.Frame(root, height=8).pack()
    from screenshot import add_screenshot_button  # lazy: only the camera runs have frames
    add_screenshot_button(root)
    add_drop_section(root, controller)
    root.mainloop()


_controller: DropController | None = None


def get_controller() -> DropController:
    """The one controller of this process (the panels and the arm guard share it)."""
    global _controller
    if _controller is None:
        _controller = DropController()
    return _controller


def start_drop_panel(title: str = "Cleany trash drop") -> DropController:
    """Start the controller and its window in a background thread."""
    controller = get_controller()

    def run() -> None:
        try:
            run_drop_panel(controller, title)
        except tk.TclError as error:  # no display
            print(f"Drop panel unavailable ({error}).")

    threading.Thread(target=run, name="drop_panel", daemon=True).start()
    return controller


if __name__ == "__main__":
    # Standalone: python scripts/common/drop_panel.py
    run_drop_panel(get_controller())
