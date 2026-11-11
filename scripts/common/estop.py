"""Emergency stop of the SO-101 follower: the shared flag and the red panel button.

The flag is set by the red button (add_estop_button) and read by arm_estop.py, which releases
the arm's torque while it is set. The button is in every panel (record panel, drop panel) and
in a window of its own (start_estop_window) for runs that have no panel, so it exists in every
mode. This module needs no lerobot and no serial port.
"""

import threading
import tkinter as tk

_active = threading.Event()


def is_active() -> bool:
    return _active.is_set()


def trigger() -> None:
    _active.set()


def release() -> None:
    _active.clear()


def add_estop_button(parent: tk.Misc) -> tk.Frame:
    """Pack the red button at the current end of parent. Press: arm torque off. Press again: resume."""
    frame = tk.Frame(parent)
    frame.pack(padx=16, pady=(12, 8), fill="x")
    button = tk.Button(frame, font=("Sans", 14, "bold"), height=2, activeforeground="#ffffff")
    button.pack(fill="x")
    hint = tk.Label(frame, font=("Sans", 9), justify="left", fg="#b71c1c")
    hint.pack(anchor="w")

    def press() -> None:
        release() if is_active() else trigger()

    button.config(command=press)

    def refresh() -> None:
        if is_active():
            button.config(text="ARM TORQUE OFF  -  press to RESUME", bg="#ef6c00", fg="#ffffff",
                          activebackground="#ff8f00")
            hint.config(text="Move the arm to a safe pose by hand, then press to re-engage it.")
        else:
            button.config(text="EMERGENCY STOP  (arm torque off)", bg="#c62828", fg="#ffffff",
                          activebackground="#e53935")
            hint.config(text="")
        frame.after(100, refresh)

    refresh()
    return frame


def run_estop_window(title: str = "Cleany emergency stop") -> None:
    """A window with only the button; call from its own thread (it runs a Tk mainloop)."""
    root = tk.Tk()
    root.title(title)
    root.attributes("-topmost", True)
    root.resizable(False, False)
    root.protocol("WM_DELETE_WINDOW", root.iconify)  # closing it must not disable the button for good
    add_estop_button(root).config(padx=0)
    root.mainloop()


def start_estop_window(title: str = "Cleany emergency stop") -> None:
    def run() -> None:
        try:
            run_estop_window(title)
        except tk.TclError as error:  # no display
            print(f"E-stop window unavailable ({error}).")

    threading.Thread(target=run, name="estop_window", daemon=True).start()
