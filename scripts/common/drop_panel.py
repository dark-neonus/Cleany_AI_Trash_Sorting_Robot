"""Trash drop mechanism (ESP32-C3, electronics/drop_firmware) client and control panel section.

DropController keeps the serial connection in a background thread: it polls READ every
POLL_S and sends the button commands. add_drop_section() adds the panel section (door
state, current / drop threshold, servo angles, OPEN / OPEN and HOLD / CLOSE and HOLD / STOP
buttons) to a tkinter window; run_drop_panel() opens a window with only that section.

lerobot_wide_fov.py shows it in the recording panel and in its own window for teleoperation,
rollout and replay (DROP_PANEL=false turns it off). The port is DROP_PORT if set, otherwise
the first USB device with Espressif's vendor ID (the C3's native USB). Opening the port
leaves DTR/RTS as the kernel sets them, so the C3 is not reset.
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
    """'R I=13 MAX=100 S=CLOSED FR=15 ...' -> fields, or None for other lines."""
    if not line.startswith("R "):
        return None
    fields = dict(part.split("=", 1) for part in line[2:].split() if "=" in part)
    try:
        return {
            "current_ma": int(fields.pop("I")),
            "max_ma": None if fields["MAX"] == "-" else int(fields["MAX"]),
            "state": fields.pop("S"),
            "angles": {k: int(v) for k, v in fields.items() if k != "MAX"},
        }
    except (KeyError, ValueError):
        return None


class DropController:
    def __init__(self):
        self.status = DropStatus()
        self._commands: list[str] = []
        self._lock = threading.Lock()
        threading.Thread(target=self._run, name="drop_controller", daemon=True).start()

    def send(self, command: str) -> None:
        with self._lock:
            self._commands.append(command)

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

    def refresh() -> None:
        status = controller.status
        if status.connected and status.current_ma is not None:
            state_label.config(text=status.state, fg=STATE_COLORS.get(status.state, "#000000"))
            limit = f"{status.max_ma / 1000:.3f} A" if status.max_ma is not None else "off"
            current_label.config(text=f"Current: {status.current_ma / 1000:.3f} / {limit}")
            angles = "  ".join(f"{name} {deg}°" for name, deg in status.angles.items())
            detail_label.config(text=f"{angles}\n{status.message}".rstrip())
        else:
            state_label.config(text="Not connected", fg=STATE_COLORS["OFF"])
            current_label.config(text="Current: –")
            detail_label.config(text=status.message or "Connecting…")
        for button in buttons:
            button.config(state=tk.NORMAL if status.connected else tk.DISABLED)
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
    add_drop_section(root, controller)
    root.mainloop()


def start_drop_panel(title: str = "Cleany trash drop") -> DropController:
    """Start the controller and its window in a background thread."""
    controller = DropController()

    def run() -> None:
        try:
            run_drop_panel(controller, title)
        except tk.TclError as error:  # no display
            print(f"Drop panel unavailable ({error}).")

    threading.Thread(target=run, name="drop_panel", daemon=True).start()
    return controller


if __name__ == "__main__":
    # Standalone: python scripts/common/drop_panel.py
    run_drop_panel(DropController())
