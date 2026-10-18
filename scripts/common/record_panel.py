"""Control panel window for lerobot-record: phase, countdown and Start/End/Discard/Stop buttons.

Installed by lerobot_wide_fov.py for the `record` command (disable with RECORD_PANEL=false to
get plain lerobot behaviour). It wraps lerobot_record functions without changing lerobot:
  - init_keyboard_listener: to share its `events` flags with the panel. The buttons set the
    same flags as the Right/Left/Esc keys, so both behave identically and the keys still work.
  - record_loop: called with a dataset for an episode and without one for the reset. The panel
    makes every episode wait for Start: before each episode the arm stays teleoperated but
    nothing is recorded (READY), and the reset after an episode has no time limit either.
  - log_say: the "Recording episode N" announcement is held back until Start is pressed.

Flow per episode: READY/RESET (wait, not recorded) -> Start -> RECORDING (countdown) -> RESET.
LeRobot saves an episode only after the reset that follows it, so Discard during the reset
drops the episode that was just recorded. After the last episode there is no reset.
"""

import re
import sys
import threading
import time
import tkinter as tk

from lerobot.utils.keyboard_input import apply_recording_control

COLORS = {"ready": "#1565c0", "episode": "#2e7d32", "reset": "#ef6c00", "saving": "#546e7a", "waiting": "#546e7a"}
WAIT_PHASES = ("ready", "reset")
ACTIVE_PHASES = ("ready", "episode", "reset")


class PanelState:
    """Shared between the recording thread (writes) and the panel thread (reads)."""

    def __init__(self, total_episodes: int | None):
        self.total_episodes = total_episodes
        self.events: dict | None = None
        self.phase = "waiting"
        self.phase_start = time.perf_counter()
        self.phase_duration: float | None = None
        self.first_episode_index: int | None = None
        self.episode = 0  # number of the current/next episode within this session
        self.start_requested = False  # the last wait ended with Start, not Discard/Stop

    def set_phase(self, phase: str, duration: float | None = None) -> None:
        self.phase_duration = duration
        self.phase_start = time.perf_counter()
        self.phase = phase


def _num_episodes_from_argv() -> int | None:
    for arg in sys.argv:
        match = re.fullmatch(r"--dataset\.num_episodes=(\d+)", arg)
        if match:
            return int(match.group(1))
    return None


def _run_panel(state: PanelState, title: str) -> None:
    root = tk.Tk()
    root.title(title)
    root.attributes("-topmost", True)
    root.resizable(False, False)
    root.protocol("WM_DELETE_WINDOW", root.iconify)  # closing the panel must not stop recording

    phase_label = tk.Label(root, font=("Sans", 16, "bold"))
    phase_label.pack(padx=16, pady=(12, 0), anchor="w")
    info_label = tk.Label(root, font=("Sans", 11), justify="left")
    info_label.pack(padx=16, anchor="w")
    bar = tk.Canvas(root, width=380, height=22, highlightthickness=0, bg="#dddddd")
    bar.pack(padx=16, pady=8)
    time_label = tk.Label(root, font=("Sans", 22, "bold"))
    time_label.pack(padx=16)
    note_label = tk.Label(root, font=("Sans", 10), fg="#b71c1c")
    note_label.pack(padx=16)

    buttons = tk.Frame(root)
    buttons.pack(padx=16, pady=12)

    def press(control: str, phases: tuple[str, ...]) -> None:
        if state.events is not None and state.phase in phases:
            apply_recording_control(control, state.events)

    start_button = tk.Button(buttons, text="Start episode  ▶", width=18, font=("Sans", 11, "bold"),
                             command=lambda: press("right", WAIT_PHASES))
    end_button = tk.Button(buttons, text="End episode  ■", width=18, command=lambda: press("right", ("episode",)))
    discard_button = tk.Button(buttons, width=18, command=lambda: press("left", ("episode", "reset")))
    stop_button = tk.Button(buttons, text="Stop session", width=18, command=lambda: press("esc", ACTIVE_PHASES))
    start_button.grid(row=0, column=0, padx=4, pady=4)
    end_button.grid(row=0, column=1, padx=4, pady=4)
    discard_button.grid(row=1, column=0, padx=4, pady=4)
    stop_button.grid(row=1, column=1, padx=4, pady=4)
    tk.Label(root, text="Keys in the terminal: → start / end, ← discard, Esc stop",
             font=("Sans", 9), fg="#666666").pack(padx=16, pady=(0, 10))

    def refresh() -> None:
        phase, duration = state.phase, state.phase_duration
        elapsed = time.perf_counter() - state.phase_start
        events = state.events or {}
        total = f" / {state.total_episodes}" if state.total_episodes else ""

        if phase == "ready":
            phase_label.config(text="READY (not recorded)", fg=COLORS[phase])
            info_label.config(text=f"Arm to the start position, item in the start zone.\n"
                                   f"Next: episode {state.episode}{total}")
        elif phase == "episode":
            phase_label.config(text="● RECORDING", fg=COLORS[phase])
            info_label.config(text=f"Episode {state.episode}{total}\nGrasp, drop into the bin, back to start.")
        elif phase == "reset":
            phase_label.config(text="RESET (not recorded)", fg=COLORS[phase])
            info_label.config(text=f"Episode {state.episode} is kept unless you discard it.\n"
                                   f"Prepare the next item, then Start episode {state.episode + 1}{total}.")
        elif phase == "saving":
            phase_label.config(text="Saving…", fg=COLORS[phase])
            info_label.config(text="\n")
        else:
            phase_label.config(text="Connecting…", fg=COLORS["waiting"])
            info_label.config(text="Waiting for the robot and cameras\n")

        bar.delete("all")
        if phase == "episode" and duration:
            bar.create_rectangle(0, 0, 380 * min(1.0, elapsed / duration), 22, fill=COLORS[phase], width=0)
            time_label.config(text=f"{max(0.0, duration - elapsed):4.1f} s left")
        elif phase in WAIT_PHASES:
            time_label.config(text=f"waiting {elapsed:4.0f} s")
        else:
            time_label.config(text="")

        if events.get("stop_recording"):
            note_label.config(text="Stopping the session…")
        elif events.get("rerecord_episode"):
            note_label.config(text="This episode will be discarded")
        else:
            note_label.config(text="")

        discard_button.config(text="Discard last episode  ↺" if phase == "reset" else "Discard episode  ↺")
        ready = state.events is not None
        discard_phases = () if events.get("rerecord_episode") else ("episode", "reset")
        for button, phases in ((start_button, WAIT_PHASES), (end_button, ("episode",)),
                               (discard_button, discard_phases), (stop_button, ACTIVE_PHASES)):
            button.config(state=tk.NORMAL if ready and phase in phases else tk.DISABLED)
        root.after(100, refresh)

    refresh()
    root.mainloop()


def install(record_module, title: str = "Cleany recorder") -> None:
    """Wrap lerobot_record's keyboard listener, record loop and announcements, then open the panel."""
    state = PanelState(_num_episodes_from_argv())

    original_init_listener = record_module.init_keyboard_listener
    original_record_loop = record_module.record_loop
    original_log_say = record_module.log_say
    pending_say: list[tuple] = []

    def init_keyboard_listener():
        listener, events = original_init_listener()
        state.events = events
        return listener, events

    def log_say(text, *args, **kwargs):
        if str(text).startswith("Recording episode"):
            pending_say[:] = [(text, args, kwargs)]  # announced when the episode really starts
            return None
        if str(text).startswith("Re-record") and (state.events or {}).get("stop_recording"):
            return None  # Stop pressed while waiting: nothing is re-recorded

        return original_log_say(text, *args, **kwargs)

    def wait_for_start(kwargs: dict) -> None:
        """Teleoperate without recording until Start (Right arrow), Discard or Stop ends the wait."""
        events = kwargs["events"]
        already_discarding = events["rerecord_episode"]  # Discard was pressed during the episode
        original_record_loop(**{**kwargs, "dataset": None, "control_time_s": float("inf")})
        discarded_now = events["rerecord_episode"] and not already_discarding
        state.start_requested = not (discarded_now or events["stop_recording"])

    def record_loop(**kwargs):
        events, dataset = kwargs["events"], kwargs.get("dataset")
        try:
            if dataset is None:  # lerobot's reset after an episode: wait for Start instead of a timer
                state.set_phase("reset")
                wait_for_start(kwargs)
                return None

            if state.first_episode_index is None:
                state.first_episode_index = dataset.num_episodes
            state.episode = dataset.num_episodes - state.first_episode_index + 1
            if not state.start_requested:  # first episode, or the previous one was discarded
                state.set_phase("ready")
                wait_for_start(kwargs)
            if events["stop_recording"]:
                # Nothing recorded yet: mark it discarded so lerobot clears the empty buffer
                # instead of saving an empty episode, then its loop ends on stop_recording.
                events["rerecord_episode"] = True
                return None
            if events["rerecord_episode"]:  # Discard pressed while waiting: nothing to discard
                events["rerecord_episode"] = False
                events["exit_early"] = False
            state.start_requested = False
            for text, args, kw in pending_say:
                original_log_say(text, *args, **kw)
            pending_say.clear()
            state.set_phase("episode", kwargs.get("control_time_s"))
            return original_record_loop(**kwargs)
        finally:
            state.set_phase("saving")

    record_module.init_keyboard_listener = init_keyboard_listener
    record_module.record_loop = record_loop
    record_module.log_say = log_say

    def run() -> None:
        try:
            _run_panel(state, title)
        except tk.TclError as error:  # no display: keep recording with the keys only
            print(f"Recording panel unavailable ({error}); use the keyboard controls.")

    threading.Thread(target=run, name="record_panel", daemon=True).start()
