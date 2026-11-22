"""Capture the named arm poses of the box (config/poses.yaml), with a live picture of the arm.

Usage (through scripts/tools/capture_poses.sh, which fills in the ports and the calibration):
    capture_poses.sh                  # the panel; the follower follows the leader (no sagging arm)
    capture_poses.sh --hand           # torque off: you move the follower itself by hand
    capture_poses.sh tray_low         # start on one pose
    capture_poses.sh --list           # what is captured, what looks wrong, what is still needed (no arm)
    capture_poses.sh --migrate        # old pose names (centre, grasp) -> new ones (no arm)
    capture_poses.sh --demo           # try the panel with a moving fake arm (no arm)

The panel lists the poses in the order of a cycle. For the selected one it says where the arm has to
be and how to check it, and draws the arm live from above and from the side over the box, with the
poses captured so far marked. "Right now" tells while you move whether the fingertips are over the
tray or the bin and whether the gripper points down. Press Enter (or Capture) when the arm is in
place and still: the mean of the last 0.4 s is stored in config/poses.yaml at once, checked against
the other poses, and the panel moves on to the next missing one. Nothing is lost if you stop.

What each pose is: scripts/common/pose_catalog.py. How they all look: assets/poses_workspace.svg
(scripts/tools/draw_poses.py). The gripper value only matters for `home` (leave it closed).
Keys: Enter / Space capture, Left / Right (or Up / Down) select, W wrist camera photo.
"""

import argparse
import collections
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "common"))
import pose_capture  # noqa: E402
from arm_kinematics import forward  # noqa: E402
from box_logic import JOINT_KEYS  # noqa: E402
from pose_catalog import BY_NAME, NAMES, NEEDED_FOR, POSES, check, joint_summary, missing_for  # noqa: E402
from pose_view import (  # noqa: E402
    PlanView,
    SideView,
    TkCanvas,
    draw_arm,
    draw_plan_workspace,
    draw_side_workspace,
    tcp_text,
)

SAMPLE_HZ = 30
SYNC_DEG = 10  # leader mode: the follower stays put until the leader is this close to it
HAND_COLOUR, LEADER_COLOUR = "#6a1b9a", "#1565c0"


# --- where the arm's joints come from -----------------------------------------------------------------

class ArmIO:
    """What the panel needs: recent samples [(time, joints)] of the follower, a status line."""

    mode = "demo"

    def __init__(self):
        self._samples = collections.deque(maxlen=SAMPLE_HZ * 3)
        self.message = ""
        self.stop = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._loop, name="arm_io", daemon=True)
        self.thread.start()

    def samples(self) -> list:
        return list(self._samples)

    def latest(self) -> dict | None:
        return self._samples[-1][1] if self._samples else None

    def push(self, joints: dict):
        self._samples.append((time.monotonic(), joints))

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=2)

    def _loop(self):
        raise NotImplementedError


class DemoArm(ArmIO):
    """--demo: an arm that glides through poses by itself, to try the panel without hardware."""

    mode = "demo"

    def __init__(self, poses: dict):
        super().__init__()
        self.stops = [poses[n] for n in ("home", "hover", "tray_low", "transit", "metal_bin", "transit", "plastic_bin")
                      if n in poses] or [dict.fromkeys(JOINT_KEYS, 0.0)]
        self.message = "DEMO: a fake arm moves by itself. Nothing is connected."

    def _loop(self):
        t0 = time.monotonic()
        while not self.stop.is_set():
            phase = ((time.monotonic() - t0) / 3.0) % len(self.stops)
            i, f = int(phase), phase - int(phase)
            f = f * f * (3 - 2 * f) if f < 0.7 else 1.0  # glide, then rest
            a, b = self.stops[i], self.stops[(i + 1) % len(self.stops)]
            self.push({k: a[k] + (b[k] - a[k]) * f for k in JOINT_KEYS})
            time.sleep(1 / SAMPLE_HZ)


class RealArm(ArmIO):
    """The follower (and the leader, in leader mode). Opening the ports does not move anything:
    in leader mode the follower only starts following once the leader is close to its pose."""

    def __init__(self, robot_port: str, calibration_dir: Path, leader_port: str | None, max_step: float):
        super().__init__()
        from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

        import lerobot_wide_fov  # noqa: F401  (follower speed limits and soft torque start, as everywhere)

        self.leader = None
        self.mode = "leader" if leader_port else "hand"
        if leader_port:
            import arm_estop
            import clamp_log

            clamp_log.install()  # the follower limits fast leader moves: no warning per command
            arm_estop.install()  # the red button releases the follower's torque
            from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig

            self.leader = SO101Leader(SO101LeaderConfig(port=leader_port, id="leader_arm",
                                                        calibration_dir=Path(calibration_dir)))
            self.leader.connect()
        self.follower = SO101Follower(SO101FollowerConfig(port=robot_port, id="follower_arm",
                                                          calibration_dir=Path(calibration_dir),
                                                          max_relative_target=max_step))
        self.follower.connect()
        self.synced = False

    def release_torque(self):
        """Hand mode: the arm goes limp (it sags: the caller has told the user to hold it)."""
        self.follower.bus.disable_torque()

    def _read(self) -> dict:
        return {f"{m}.pos": v for m, v in self.follower.bus.sync_read("Present_Position").items()}

    def _loop(self):
        period = 1 / SAMPLE_HZ
        while not self.stop.is_set():
            began = time.monotonic()
            try:
                measured = self._read()
                if self.leader is not None:
                    action = self.leader.get_action()
                    gap = max(JOINT_KEYS, key=lambda k: abs(action[k] - measured[k]))
                    if not self.synced and abs(action[gap] - measured[gap]) < SYNC_DEG:
                        self.synced = True
                    if self.synced:
                        self.follower.send_action(action)
                        self.message = "The follower follows the leader: move the LEADER to the pose."
                    else:
                        self.message = (f"Put the LEADER in the same pose as the follower first ({gap.split('.')[0]} "
                                        f"is {action[gap] - measured[gap]:+.0f}° off): the follower stays put until then.")
                else:
                    self.message = "Torque is OFF: move the arm by hand to the pose."
                self.push(measured)
            except Exception as error:  # noqa: BLE001  (a missed servo reply: skip this reading)
                self.message = f"Arm read failed: {error.__class__.__name__}"
            time.sleep(max(0.0, period - (time.monotonic() - began)))

    def close(self):
        super().close()
        for arm in (self.follower, self.leader):
            if arm is not None and getattr(arm, "is_connected", True):
                try:
                    arm.disconnect()
                except Exception as error:  # noqa: BLE001
                    print(f"  disconnect: {error}")


# --- wrist camera photo ----------------------------------------------------------------------------------

def wrist_photo(device: str) -> Path | None:
    import cv2

    out = PROJECT_ROOT / "outputs" / "poses" / "hover_wrist.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    camera = cv2.VideoCapture(device)
    ok, frame = False, None
    for _ in range(10):  # let the exposure settle
        ok, frame = camera.read()
    camera.release()
    if not ok:
        return None
    cv2.imwrite(str(out), frame)
    return out


# --- the panel ----------------------------------------------------------------------------------------------

class Panel:
    PLAN_SCALE, SIDE_SCALE = 5.0, 5.0

    def __init__(self, root: tk.Tk, session: pose_capture.CaptureSession, io: ArmIO, first: str, wrist: str | None):
        self.root, self.session, self.io, self.wrist = root, session, io, wrist
        self.selected = first
        self.photo = None
        root.title("Cleany pose capture")
        root.resizable(False, False)
        if io.mode == "leader":
            from estop import add_estop_button

            add_estop_button(root)
        colour = {"leader": LEADER_COLOUR, "hand": HAND_COLOUR, "demo": "#546e7a"}[io.mode]
        self.mode_label = tk.Label(root, font=("Sans", 11, "bold"), fg="#ffffff", bg=colour, anchor="w", padx=10, pady=4)
        self.mode_label.pack(fill="x")

        body = tk.Frame(root)
        body.pack(padx=12, pady=8)
        left = tk.Frame(body)
        left.grid(row=0, column=0, sticky="n", padx=(0, 14))
        tk.Label(left, text="Poses, in the order of a cycle", font=("Sans", 10, "bold"), fg="#555555").pack(anchor="w")
        self.rows = {}
        for number, spec in enumerate(POSES, 1):
            row = tk.Label(left, anchor="w", justify="left", font=("Sans", 11), padx=6, pady=3, width=46, cursor="hand2")
            row.pack(fill="x", pady=1)
            row.bind("<Button-1>", lambda _e, n=spec.name: self.select(n))
            self.rows[spec.name] = (row, number)
        self.needs_label = tk.Label(left, anchor="w", justify="left", font=("Sans", 9), fg="#555555", wraplength=330)
        self.needs_label.pack(anchor="w", pady=(10, 0))
        self.photo_label = tk.Label(left)
        self.photo_label.pack(anchor="w", pady=(10, 0))

        right = tk.Frame(body)
        right.grid(row=0, column=1, sticky="n")
        self.title = tk.Label(right, font=("Sans", 16, "bold"), anchor="w")
        self.title.pack(anchor="w")
        self.info = tk.Label(right, font=("Sans", 10), justify="left", anchor="w", wraplength=680)
        self.info.pack(anchor="w", pady=(2, 6))
        self.saved = tk.Label(right, font=("Sans", 10, "bold"), justify="left", anchor="w", wraplength=680)
        self.saved.pack(anchor="w")

        views = tk.Frame(right)
        views.pack(anchor="w", pady=4)
        ps, ss = self.PLAN_SCALE, self.SIDE_SCALE
        self.plan_canvas = tk.Canvas(views, width=72 * ps + 4, height=70 * ps + 4, bg="#f8fafc", highlightthickness=0)
        self.plan_canvas.grid(row=0, column=0)
        self.side_canvas = tk.Canvas(views, width=54 * ss + 4, height=44 * ss + 4, bg="#f8fafc", highlightthickness=0)
        self.side_canvas.grid(row=0, column=1, sticky="n", padx=(10, 0))
        self.plan = PlanView(2 + 36 * ps, 2 + 56 * ps, ps)
        self.side = SideView(2 + 12 * ss, 2 + 32 * ss, ss)
        self.live_label = tk.Label(right, font=("Sans", 10), justify="left", anchor="w", wraplength=680)
        self.live_label.pack(anchor="w")
        self.now_label = tk.Label(right, font=("Sans", 11, "bold"), justify="left", anchor="w", wraplength=680)
        self.now_label.pack(anchor="w", pady=(4, 0))

        buttons = tk.Frame(right)
        buttons.pack(anchor="w", pady=8)
        tk.Button(buttons, text="Capture  [Enter]", width=18, font=("Sans", 11, "bold"), command=self.capture).pack(side="left", padx=2)
        tk.Button(buttons, text="◀", width=3, command=lambda: self.step(-1)).pack(side="left", padx=2)
        tk.Button(buttons, text="▶", width=3, command=lambda: self.step(1)).pack(side="left", padx=2)
        if wrist:
            tk.Button(buttons, text="Wrist photo  [W]", width=14, command=self.take_photo).pack(side="left", padx=2)
        tk.Button(buttons, text="Done", width=8, command=self.done).pack(side="left", padx=(20, 2))
        self.message = tk.Label(right, font=("Sans", 10), anchor="w", justify="left", wraplength=680)
        self.message.pack(anchor="w")

        root.bind("<Return>", lambda _e: self.capture())
        root.bind("<space>", lambda _e: self.capture())
        root.bind("<Left>", lambda _e: self.step(-1))
        root.bind("<Up>", lambda _e: self.step(-1))
        root.bind("<Right>", lambda _e: self.step(1))
        root.bind("<Down>", lambda _e: self.step(1))
        root.bind("<w>", lambda _e: self.take_photo())
        root.protocol("WM_DELETE_WINDOW", self.done)
        root.focus_set()
        self.select(first)
        self.refresh()

    # -- actions -------------------------------------------------------------------------------------

    def say(self, text: str, colour: str = "#222222"):
        self.message.config(text=text, fg=colour)

    def select(self, name: str):
        self.selected = name
        spec = BY_NAME[name]
        number = NAMES.index(name) + 1
        self.title.config(text=f"{number}  {spec.name}  -  {spec.title}")
        self.info.config(text=f"WHERE   {spec.where}\nHOW      {spec.how}\nGRIPPER  {spec.gripper}\nUSED      {spec.used}")
        self.update_list()

    def step(self, delta: int):
        self.select(NAMES[(NAMES.index(self.selected) + delta) % len(NAMES)])

    def capture(self):
        pose, why = pose_capture.steady_pose(self.io.samples(), time.monotonic())
        if pose is None:
            self.say(why, "#b71c1c")
            return
        name = self.selected
        found = self.session.capture(name, pose)
        text = f"Saved {name}: " + joint_summary(pose)
        self.say(text + ("" if not found else "\nCheck it: see the warnings above."), "#2e7d32" if not found else "#e65100")
        if name == "hover" and self.wrist:
            self.take_photo()
        nxt = self.session.next_missing(after=name)
        if nxt and not found:
            self.select(nxt)
        else:
            self.select(name)

    def take_photo(self):
        if not self.wrist:
            return
        path = wrist_photo(self.wrist)
        if path is None:
            self.say("The wrist camera gave no picture.", "#b71c1c")
            return
        from PIL import Image, ImageTk

        image = Image.open(path)
        image.thumbnail((290, 170))
        self.photo = ImageTk.PhotoImage(image)
        self.photo_label.config(image=self.photo, text="Wrist camera at hover: all four tray\ncorners must be visible", compound="top",
                                font=("Sans", 9), justify="left")
        self.say(f"Wrist camera photo saved: {path.relative_to(PROJECT_ROOT)}", "#2e7d32")

    def done(self):
        if self.io.mode == "leader":
            if not messagebox.askokcancel("Finish", "Put the LEADER in its rest pose now (the follower follows it), then "
                                                    "press OK: both arms go limp."):
                return
        elif self.io.mode == "hand":
            if not messagebox.askokcancel("Finish", "Hold the arm in its rest pose, then press OK: its torque stays off."):
                return
        self.root.quit()

    # -- drawing ---------------------------------------------------------------------------------------

    def update_list(self):
        status = self.session.poses
        for name, (row, number) in self.rows.items():
            found = self.session.findings(name) if name in status else None
            mark, colour = ("✗", "#9e9e9e") if name not in status else (("⚠", "#e65100") if found else ("✓", "#2e7d32"))
            row.config(text=f"{mark}  {number}  {name}\n       {BY_NAME[name].title}", fg=colour,
                       bg="#e3f2fd" if name == self.selected else self.root.cget("bg"))
        needs = []
        for feature, what in NEEDED_FOR.items():
            missing = missing_for(feature, self.session.poses)
            needs.append((("ready: " if not missing else f"needs {', '.join(missing)}: ")) + what)
        self.needs_label.config(text="\n".join(needs))
        found = self.session.findings(self.selected)
        self.saved.config(text="\n".join(("✗ " if f.level == "error" else "⚠ ") + f.text for f in found),
                          fg="#b71c1c" if any(f.level == "error" for f in found) else "#e65100")

    def refresh(self):
        live = self.io.latest()
        self.mode_label.config(text=self.io.message or "Connecting…")
        self.draw(live)
        self.root.after(60, self.refresh)

    def draw(self, live: dict | None):
        plan_c, side_c = TkCanvas(self.plan_canvas), TkCanvas(self.side_canvas)
        self.plan_canvas.delete("all")
        self.side_canvas.delete("all")
        draw_plan_workspace(plan_c, self.plan)
        draw_side_workspace(side_c, self.side, self.session.poses, live)
        for name, pose in self.session.poses.items():  # captured poses: a ring at the fingertips
            spec = BY_NAME.get(name)
            if spec is None:
                continue
            tip = forward(pose)["tcp"]
            fill = "#ffffff" if name == self.selected else spec.colour
            for view, canvas in ((self.plan, plan_c), (self.side, side_c)):
                x, y = view.point(tip, pose)  # the side view puts it in the pose's own arm plane
                canvas.oval(x, y, 5, fill=fill, outline=spec.colour, width=2)
        stored = self.session.poses.get(self.selected)
        if stored:  # the stored version of the selected pose, pale, under the live arm
            draw_arm(plan_c, self.plan, stored, color="#b6c2d0", fingers="#fde3a0", width=4)
            draw_arm(side_c, self.side, stored, color="#b6c2d0", fingers="#fde3a0", width=4)
        if live is None:
            self.live_label.config(text="No arm readings yet.")
            self.now_label.config(text="")
            return
        draw_arm(plan_c, self.plan, live, width=5)
        draw_arm(side_c, self.side, live, width=5)
        self.live_label.config(text=joint_summary(live) + "\n" + tcp_text(live))
        now = check(self.selected, {**self.session.poses, self.selected: live})
        self.now_label.config(text="Right now: " + ("looks right for this pose" if not now else "\n".join(
            ("✗ " if f.level == "error" else "⚠ ") + f.text for f in now)), fg="#2e7d32" if not now else "#e65100")


# --- main ----------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("names", nargs="*", help="start on this pose (the panel always lists all of them)")
    parser.add_argument("--robot-port")
    parser.add_argument("--leader-port", help="follower follows this leader (default when given); see --hand")
    parser.add_argument("--hand", action="store_true", help="torque off, move the follower by hand")
    parser.add_argument("--calibration-dir")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "config" / "poses.yaml")
    parser.add_argument("--wrist", help="wrist camera device: a photo at hover")
    parser.add_argument("--max-step", type=float, default=10)
    parser.add_argument("--list", action="store_true", help="show what is captured and exit (no arm)")
    parser.add_argument("--migrate", action="store_true", help="rename old poses in the file and exit (no arm)")
    parser.add_argument("--demo", action="store_true", help="a fake moving arm (no arm)")
    args = parser.parse_args()

    session = pose_capture.CaptureSession(args.output)
    if args.migrate or args.list:
        for note in session.notes:
            print(f"  {note}")
        if args.migrate:
            if session.notes:
                session.save()
                print(f"Wrote {args.output} (the old file is kept as {args.output.name}.bak)")
            else:
                print("Nothing to migrate: the names are already the new ones.")
        print(pose_capture.report(session.poses))
        return
    unknown = [n for n in args.names if n not in NAMES]
    if unknown:
        sys.exit(f"Unknown pose {', '.join(unknown)}. The poses are: {', '.join(NAMES)}")
    first = args.names[0] if args.names else (session.next_missing() or NAMES[0])

    if args.demo:
        io = DemoArm(session.poses)
    else:
        if not (args.robot_port and args.calibration_dir):
            sys.exit("--robot-port and --calibration-dir are needed (scripts/tools/capture_poses.sh fills them in)")
        leader_port = None if args.hand else args.leader_port
        io = RealArm(args.robot_port, args.calibration_dir, leader_port, args.max_step)
    root = tk.Tk()
    if isinstance(io, RealArm) and io.mode == "hand":
        messagebox.showinfo("Torque off", "The arm's torque goes off now and the arm will sag: hold it, then press OK.")
        io.release_torque()
    io.start()
    Panel(root, session, io, first, args.wrist)
    try:
        root.mainloop()
    finally:
        io.close()
        root.destroy()
    print(pose_capture.report(session.poses))
    print(f"\nSaved in {args.output}. See them: python scripts/tools/draw_poses.py --png")


if __name__ == "__main__":
    main()

