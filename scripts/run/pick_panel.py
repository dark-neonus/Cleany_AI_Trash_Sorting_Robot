"""Control panel of the pick recorder (scripts/dataset/record_pick.py): what the session is doing,
the front camera with the boxes it found, and the buttons, each with a key.

    M / P / O      Metal / Plastic / Other: classify the item on the tray (READY)
    Space          start the episode (ARMED), end it (RECORDING)
    Backspace      discard the last record (READY), or the episode being recorded
    Esc            cancel: back home without recording (ARMED)

Keys work while the panel has focus and the item name field does not (Enter leaves the field).
The panel only reads the session's Status and puts commands in its queue; the session runs in
its own thread.
"""

from __future__ import annotations

import tkinter as tk

import numpy as np
from estop import add_estop_button
from pick_session import Commands, Status
from screenshot import add_screenshot_button

PHASE_COLORS = {"READY": "#1565c0", "ARMED": "#6a1b9a", "RECORDING": "#2e7d32", "E-STOP": "#b71c1c",
                "STOPPED": "#546e7a"}
PREVIEW = (400, 300)  # the 640x480 front image at 5/8
SCALE = PREVIEW[0] / 640

# command, label, key shown, phases it is enabled in
BUTTONS = [
    ("metal", "Metal", "M", ("READY",)),
    ("plastic", "Plastic", "P", ("READY",)),
    ("other", "Other", "O", ("READY",)),
    ("start", "Start", "Space", ("ARMED",)),
    ("end", "End", "Space", ("RECORDING",)),
    ("cancel", "Cancel", "Esc", ("ARMED",)),
    ("discard", "Discard", "Bksp", ("READY", "RECORDING")),
]


def run_panel(status: Status, commands: Commands, stop, title: str, tray_region, warn_after_s: float,
              is_running) -> None:
    """Tk main loop in the calling thread. stop(): ask the session to stop; is_running(): False once
    it has finished, then the window closes."""
    from PIL import Image, ImageDraw, ImageTk

    root = tk.Tk()
    root.title(title)
    root.resizable(False, False)
    root.protocol("WM_DELETE_WINDOW", stop)  # closing the window stops the session (arms go home)
    add_estop_button(root)

    phase_label = tk.Label(root, font=("Sans", 18, "bold"))
    phase_label.pack(padx=16, pady=(8, 0), anchor="w")
    message_label = tk.Label(root, font=("Sans", 11), justify="left", wraplength=420)
    message_label.pack(padx=16, anchor="w")
    warning_label = tk.Label(root, font=("Sans", 11, "bold"), fg="#b71c1c", justify="left", wraplength=420)
    warning_label.pack(padx=16, anchor="w")

    bar = tk.Canvas(root, width=PREVIEW[0], height=18, highlightthickness=0, bg="#dddddd")
    bar.pack(padx=16, pady=(6, 0))
    preview = tk.Label(root, bg="#222222", width=PREVIEW[0], height=PREVIEW[1])
    preview.pack(padx=16, pady=6)
    counts_label = tk.Label(root, font=("Sans", 11))
    counts_label.pack(padx=16, anchor="w")
    last_label = tk.Label(root, font=("Sans", 10), fg="#444444")
    last_label.pack(padx=16, anchor="w")

    name_row = tk.Frame(root)
    name_row.pack(padx=16, pady=(8, 0), fill="x")
    tk.Label(name_row, text="Item name:", font=("Sans", 11)).pack(side="left")
    item_var = tk.StringVar(value=commands.item)
    entry = tk.Entry(name_row, textvariable=item_var, font=("Sans", 11), width=24)
    entry.pack(side="left", padx=6)
    tk.Label(name_row, text="(same name for the same item)", font=("Sans", 9), fg="#666666").pack(side="left")
    item_var.trace_add("write", lambda *_: setattr(commands, "item", item_var.get()))
    entry.bind("<Return>", lambda _: root.focus_set())
    entry.bind("<Escape>", lambda _: root.focus_set())

    grid = tk.Frame(root)
    grid.pack(padx=16, pady=8)
    widgets = {}
    for i, (command, label, key, _) in enumerate(BUTTONS):
        widgets[command] = tk.Button(grid, text=f"{label}  [{key}]", width=13, font=("Sans", 11, "bold"),
                                     command=lambda c=command: commands.put(c))
        widgets[command].grid(row=i // 3, column=i % 3, padx=3, pady=3)
    tk.Button(root, text="Stop session (arms go home)", command=stop).pack(padx=16, pady=(0, 6), fill="x")
    add_screenshot_button(root)

    def key(event):
        if root.focus_get() is entry:
            return
        phase = status.phase
        name = {"m": "metal", "p": "plastic", "o": "other", "BackSpace": "discard", "Escape": "cancel"}.get(
            event.keysym, event.keysym.lower())
        if event.keysym == "space":
            name = "start" if phase == "ARMED" else "end"
        enabled = next((b[3] for b in BUTTONS if b[0] == name), ())
        if phase in enabled:
            commands.put(name)

    root.bind("<Key>", key)
    root.focus_set()
    photo = {}

    def draw(frame: np.ndarray):
        image = Image.fromarray(frame).resize(PREVIEW)
        d = ImageDraw.Draw(image)

        def rect(box, color, width=2):
            if box is not None:
                d.rectangle([v * SCALE for v in box], outline=color, width=width)
        rect(tray_region, "#888888", 1)
        for box in status.yolo_boxes:
            rect(box, "#42a5f5")
        rect(status.change_box, "#ffa726")
        rect(status.target_box, "#00e676", 3)
        photo["image"] = ImageTk.PhotoImage(image)
        preview.config(image=photo["image"], width=PREVIEW[0], height=PREVIEW[1])

    def refresh():
        if not is_running():
            root.destroy()
            return
        s = status
        phase_label.config(text=("● " if s.phase == "RECORDING" else "") + s.phase,
                           fg=PHASE_COLORS.get(s.phase, "#37474f"))
        message_label.config(text=s.message)
        warning_label.config(text=s.warning)
        c = s.counts
        counts_label.config(text=f"Kept: metal {c['metal']} · plastic {c['plastic']} · other {c['other']}"
                                 f"   (this session {s.session})")
        last_label.config(text=(f"Last: {s.last}" if s.last else "") +
                          (f"   ·   Discard drops the last {s.pending}" if s.pending else ""))
        bar.delete("all")
        if s.phase == "RECORDING" and s.timeout:
            color = "#2e7d32" if s.elapsed < warn_after_s else "#ef6c00"
            bar.create_rectangle(0, 0, PREVIEW[0] * min(1.0, s.elapsed / s.timeout), 18, fill=color, width=0)
            bar.create_text(PREVIEW[0] / 2, 9, text=f"{s.elapsed:4.1f} s / {s.timeout:g} s")
        if s.frame is not None:
            draw(s.frame)
        for command, _, _, phases in BUTTONS:
            enabled = s.phase in phases and (command != "discard" or s.phase == "RECORDING" or bool(s.pending))
            widgets[command].config(state=tk.NORMAL if enabled else tk.DISABLED)
        root.after(100, refresh)

    refresh()
    root.mainloop()
