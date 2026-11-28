"""Control panel of the pick recorder (scripts/dataset/record_pick.py): what the session is doing,
both cameras live, and the buttons, each with a key.

    M / P          Metal / Plastic: classify the item on the tray, then a pick episode (READY)
    G              Pick other: neither metal nor plastic, with a pick episode (class `other`)
    O              Save other: class `other`, picture only (YOLO / gallery), the doors drop it
    E              Retake empty tray: the photo items are compared with (tray empty, hands out)
    N              Add new object: the object on the tray joins the library (type and name beside it)
    Space          start the episode (ARMED), end it (RECORDING)
    Backspace      discard the last record (READY), or the episode being recorded
    Esc            cancel: back home without recording (ARMED)
    1 / 2 / 3      view: both cameras / front only / wrist only (bigger)
    B              boxes on the front view on / off
    S              screenshot of both cameras (recordings/screenshots/)

The views come from the cameras' own capture buffers (camera_feed.py), not from the session loop,
so they stay live while the session waits for the doors or classifies. Each view has a badge with
the camera's real fps (green from 24, amber below, red NO SIGNAL after a second without a frame),
the front view the boxes of the session, and while recording both get a red frame and the episode
time; under them is the rate the dataset is actually recorded at.

On the right is the object library (pick_library.py): every training object of objects/train with
its picture and N/3 records. Choosing one (a click) is required before a record: the record, its
YOLO frame and crop carry its id. Keys work while the panel has focus and the new object's name
field does not (Enter leaves the field). The panel only reads the session's Status and puts
commands in its queue; the session runs in its own thread.
"""

from __future__ import annotations

import time
import tkinter as tk

from camera_feed import StatusFeed
from estop import add_estop_button
from item_registry import Registry, progress
from pick_library import LibraryView
from pick_session import Commands, Status
from pick_view import GREEN, GREY, RED, badge_text, render
from screenshot import save_screenshots

PHASE_COLORS = {"READY": "#1565c0", "ARMED": "#6a1b9a", "RECORDING": "#2e7d32", "E-STOP": "#b71c1c",
                "STOPPED": "#546e7a"}
# (front, wrist) view sizes: both side by side, or one of them bigger
VIEWS = {"both": ((512, 384), (512, 288)), "front": ((800, 600), None), "wrist": (None, (800, 450))}
VIEW_KEYS = {"1": "both", "2": "front", "3": "wrist"}
FEED_MS = 15  # how often the views look for a new camera frame (30 fps cameras: every frame is drawn)

# command, label, key shown, phases it is enabled in
BUTTONS = [
    ("metal", "Metal", "M", ("READY",)),
    ("plastic", "Plastic", "P", ("READY",)),
    ("pick_other", "Pick other", "G", ("READY",)),
    ("other", "Save other", "O", ("READY",)),
    ("start", "Start", "Space", ("ARMED",)),
    ("end", "End", "Space", ("RECORDING",)),
    ("cancel", "Cancel", "Esc", ("ARMED",)),
    ("discard", "Discard", "Bksp", ("READY", "RECORDING")),
    ("empty", "Retake empty tray", "E", ("READY",)),
]


def rate_text(status: Status, target_fps: float) -> tuple[str, str]:
    """The line under the views: the dataset's recording rate while recording."""
    if status.phase == "RECORDING" and status.rec_fps:
        ok = status.rec_fps >= 0.9 * target_fps
        return (f"Recording {status.rec_fps:4.1f} fps (target {target_fps:g})"
                + ("" if ok else "  slower than the target: the dataset gets fewer frames"), GREEN if ok else RED)
    return "", GREY


def run_panel(status: Status, commands: Commands, stop, title: str, tray_region, warn_after_s: float,
              is_running, registry: Registry | None = None, feeds: dict | None = None, target_fps: float = 30) -> None:
    """Tk main loop in the calling thread. stop(): ask the session to stop; is_running(): False once
    it has finished, then the window closes. feeds: {"front": Feed, "wrist": Feed} (camera_feed.py);
    without them the views show the frames the session publishes."""
    from PIL import ImageTk

    feeds = {"front": StatusFeed("front", status, "frame"), "wrist": StatusFeed("wrist", status, "wrist"),
             **(feeds or {})}
    root = tk.Tk()
    root.title(title)
    root.resizable(False, False)
    root.protocol("WM_DELETE_WINDOW", stop)  # closing the window stops the session (arms go home)
    add_estop_button(root)
    body = tk.Frame(root)
    body.pack(fill="both", expand=True)
    left = tk.Frame(body)
    left.pack(side="left", anchor="n")

    phase_label = tk.Label(left, font=("Sans", 18, "bold"))
    phase_label.pack(padx=16, pady=(8, 0), anchor="w")
    message_label = tk.Label(left, font=("Sans", 11), justify="left", wraplength=1000)
    message_label.pack(padx=16, anchor="w")
    warning_label = tk.Label(left, font=("Sans", 11, "bold"), fg="#b71c1c", justify="left", wraplength=1000)
    warning_label.pack(padx=16, anchor="w")

    bar = tk.Canvas(left, width=1000, height=18, highlightthickness=0, bg="#dddddd")
    bar.pack(padx=16, pady=(6, 0))

    cameras = tk.Frame(left, bg="#101010")
    cameras.pack(padx=16, pady=6)
    views = {name: tk.Label(cameras, bg="#222222", bd=0) for name in ("front", "wrist")}
    rate_label = tk.Label(left, font=("Sans", 10, "bold"))
    rate_label.pack(padx=16, anchor="w")

    view_var = tk.StringVar(value="both")
    show_boxes = tk.BooleanVar(value=True)
    options = tk.Frame(left)
    options.pack(padx=16, pady=(2, 0), fill="x")
    tk.Label(options, text="View:", font=("Sans", 10)).pack(side="left")
    for key, name in VIEW_KEYS.items():
        tk.Radiobutton(options, text=f"{name} [{key}]", value=name, variable=view_var, font=("Sans", 10),
                       command=lambda: layout()).pack(side="left", padx=4)
    tk.Checkbutton(options, text="boxes [B]", variable=show_boxes, font=("Sans", 10)).pack(side="left", padx=12)
    screenshot_label = tk.Label(options, font=("Sans", 9), fg="#666666", wraplength=520, justify="left")
    screenshot_label.pack(side="right")
    tk.Button(options, text="Screenshot [S]", font=("Sans", 10), command=lambda: screenshot()).pack(side="right", padx=6)

    counts_label = tk.Label(left, font=("Sans", 11))
    counts_label.pack(padx=16, pady=(6, 0), anchor="w")
    suggest_label = tk.Label(left, font=("Sans", 10), fg="#1565c0", justify="left", wraplength=1000)
    suggest_label.pack(padx=16, anchor="w")
    last_label = tk.Label(left, font=("Sans", 10), fg="#444444")
    last_label.pack(padx=16, anchor="w")

    registry = registry or Registry()
    library = LibraryView(body, registry, commands, status, on_add=lambda: commands.put("add_object"),
                          is_ready=lambda: status.phase == "READY")

    grid = tk.Frame(left)
    grid.pack(padx=16, pady=8)
    widgets = {}
    for i, (command, label, key, _) in enumerate(BUTTONS):
        widgets[command] = tk.Button(grid, text=f"{label}  [{key}]", width=18, font=("Sans", 11, "bold"),
                                     command=lambda c=command: commands.put(c))
        widgets[command].grid(row=i // 4, column=i % 4, padx=3, pady=3)
    tk.Button(left, text="Stop session (arms go home)", command=stop).pack(padx=16, pady=(0, 10), fill="x")

    def screenshot():
        screenshot_label.config(text=save_screenshots())

    def key(event):
        if library.typing:
            return
        if event.keysym.lower() == "n":
            library.add()
            return
        if event.keysym in VIEW_KEYS:
            view_var.set(VIEW_KEYS[event.keysym])
            layout()
            return
        if event.keysym.lower() == "b":
            show_boxes.set(not show_boxes.get())
            return
        if event.keysym.lower() == "s":
            screenshot()
            return
        phase = status.phase
        name = {"m": "metal", "p": "plastic", "g": "pick_other", "o": "other", "e": "empty", "BackSpace": "discard",
                "Escape": "cancel"}.get(event.keysym, event.keysym.lower())
        if event.keysym == "space":
            name = "start" if phase == "ARMED" else "end"
        enabled = next((b[3] for b in BUTTONS if b[0] == name), ())
        if phase in enabled:
            commands.put(name)

    root.bind("<Key>", key)
    root.focus_set()
    photo = {}  # the images shown: Tk drops an image nobody refers to
    sizes = {}

    def layout():
        front, wrist = VIEWS[view_var.get()]
        sizes.update(front=front, wrist=wrist)
        for column, name in enumerate(("front", "wrist")):
            if sizes[name] is None:
                views[name].grid_remove()
            else:
                views[name].grid(row=0, column=column, padx=2, pady=2, sticky="n")
        for name in feeds:  # redraw at the new size even before the next frame
            feeds[name].redraw = True

    def boxes():
        if not show_boxes.get():
            return []
        return [(tray_region, GREY, 1), *((b, "#42a5f5", 2) for b in status.yolo_boxes),
                (status.change_box, "#ffa726", 2), (status.target_box, "#00e676", 3)]

    def draw(name: str, now: float):
        feed, size = feeds[name], sizes[name]
        if size is None or feed.frame is None:
            return
        state, fps = feed.state(now)
        recording = status.elapsed if status.phase == "RECORDING" else None
        image = render(feed.frame, size, badge_text(name, state, fps, feed.size),
                       boxes() if name == "front" else (), recording, rotate180=name == "front")
        photo[name] = ImageTk.PhotoImage(image)
        views[name].config(image=photo[name], width=size[0], height=size[1])

    def tick_feeds():
        if not is_running():
            return
        now = time.perf_counter()
        for name, feed in feeds.items():
            fresh = feed.poll()
            if fresh or feed.redraw or (feed.frame is not None and feed.state(now)[0] != "live"):
                feed.redraw = False
                draw(name, now)
        root.after(FEED_MS, tick_feeds)

    def refresh():
        if not is_running():
            root.destroy()
            return
        s = status
        phase_label.config(text=("● " if s.phase == "RECORDING" else "") + s.phase,
                           fg=PHASE_COLORS.get(s.phase, "#37474f"))
        message_label.config(text=s.message)
        warning_label.config(text=s.warning)
        counts_label.config(text=f"Kept: {progress(s.counts, s.targets, s.target_phase)}   (this session {s.session})")
        suggest_label.config(text=("Least recorded: " + " · ".join(f"{c} {v}" for c, v in s.suggest.items()))
                             if s.suggest and s.phase == "READY" else "")
        last_label.config(text=(f"Last: {s.last}" if s.last else "") +
                          (f"   ·   Discard drops the last {s.pending}" if s.pending else ""))
        text, color = rate_text(s, target_fps)
        rate_label.config(text=text, fg=color if color != GREY else "#444444")
        bar.delete("all")
        if s.phase == "RECORDING" and s.timeout:
            color = "#2e7d32" if s.elapsed < warn_after_s else "#ef6c00"
            bar.create_rectangle(0, 0, 1000 * min(1.0, s.elapsed / s.timeout), 18, fill=color, width=0)
            bar.create_text(500, 9, text=f"{s.elapsed:4.1f} s / {s.timeout:g} s")
        library.refresh()
        for command, _, _, phases in BUTTONS:
            enabled = s.phase in phases and (command != "discard" or s.phase == "RECORDING" or bool(s.pending))
            widgets[command].config(state=tk.NORMAL if enabled else tk.DISABLED)
        root.after(100, refresh)

    layout()
    tick_feeds()
    refresh()
    root.mainloop()
