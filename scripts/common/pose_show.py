"""Move the arm between the named poses to look at them: a walkthrough, a slideshow, one pose.
The logic of scripts/tools/show_poses.py, without arm or window (tests/test_pose_show.py).

Safety, the same as the pipeline's own moves:
  * every move is a minimum-jerk move (paced_move.py), from where the arm really is, so nothing
    jumps, and slowed down smoothly when the arm cannot follow;
  * the arm only moves between poses along EDGES, the moves the pipeline itself makes, so a walk
    from one bin to the other goes through `transit` instead of swinging through the walls;
  * it starts only from a pose it knows (the arm within START_DEG of one), because the route
    begins there;
  * the emergency stop ends everything at once.
"""

from __future__ import annotations

from box_logic import GRIPPER, approach_waypoint, max_joint_distance, move_duration
from box_states import Clock, Stop
from paced_move import LAG_DEG, SHORT_DEG, MoveError, run  # noqa: F401  (MoveError: re-exported)
from pose_catalog import BY_NAME, NAMES
from pose_view import tcp_text

# Which poses the arm moves between directly (who makes the move in the pipeline)
EDGES = (
    ("home", "hover"),  # HOVER after an item was found; GRASP failed: back to HOVER
    ("hover", "transit"),  # CARRY after the lift
    ("transit", "metal_bin"),  # CARRY
    ("transit", "plastic_bin"),
    ("home", "transit"),  # the pick recorder lets go at transit, then HOME
    ("metal_bin", "home"),  # RELEASE, then HOME
    ("plastic_bin", "home"),
    ("hover", "tray_low"),  # the scripted grasp
)
START_DEG = 12  # the arm counts as "at" a pose when every joint is this close (gripper excluded)


class StartError(RuntimeError):
    pass


# When two routes are equally short, the one through the poses earlier in this list wins: up and
# over through `transit` rather than folding through `home`
PREFER = ("transit", "hover", "home", "tray_low", "metal_bin", "plastic_bin")


def neighbours(name: str) -> list[str]:
    near = [b if a == name else a for a, b in EDGES if name in (a, b)]
    return sorted(near, key=PREFER.index)


def route(start: str, goal: str) -> list[str]:
    """The poses to pass through from start to goal (both included), fewest moves first; at equal
    length see PREFER. Every move on it is one the pipeline makes. KeyError when there is no way."""
    paths, seen = [[start]], {start}
    while paths:
        path = paths.pop(0)
        if path[-1] == goal:
            return path
        for n in neighbours(path[-1]):
            if n not in seen:
                seen.add(n)
                paths.append([*path, n])
    raise KeyError(f"no route from {start} to {goal}")


def nearest(joints: dict, poses: dict) -> tuple[str | None, float]:
    """The captured pose closest to the arm's joints, and how far (degrees, gripper excluded)."""
    return min(((n, max_joint_distance(joints, p)) for n, p in poses.items() if n in BY_NAME),
               key=lambda x: x[1], default=(None, float("inf")))


class Mover:
    """Moves a real or simulated arm: arm.observe() -> joints, arm.send(joints)."""

    def __init__(self, arm, poses: dict, motion: dict, clock: Clock | None = None, gripper: str = "closed",
                 say=print, paused=lambda: False, should_stop=lambda: False, speed: float | None = None,
                 lag_deg: float = LAG_DEG):
        self.arm, self.poses, self.motion = arm, poses, motion
        self.clock, self.say, self.paused, self.should_stop = clock or Clock(), say, paused, should_stop
        self.gripper = gripper
        self.speed = speed or motion["speed_deg_s"]
        self.lag_deg = lag_deg
        self.at: str | None = None  # the pose the arm is at, once known
        self.errors: dict[str, float] = {}  # pose -> degrees the arm stopped short (worst joint)

    def here(self) -> dict:
        return {k: v for k, v in self.arm.observe().items() if k.endswith(".pos")}

    def target(self, name: str) -> dict:
        grip = {"closed": self.poses["home"][GRIPPER], "open": self.motion["gripper_open"],
                "pose": self.poses[name][GRIPPER]}[self.gripper]
        return {**self.poses[name], GRIPPER: grip}

    def seconds(self, start: dict, name: str) -> float:
        return move_duration(start, self.target(name), self.speed, self.motion["min_move_s"], self.motion.get("ramp_s"))

    def check(self):
        if self.paused():
            raise Stop("emergency stop")
        if self.should_stop():
            raise Stop("stopped")

    def move(self, name: str):
        """Minimum-jerk move from where the arm is to the pose, paced by the arm (paced_move.py): the plan
        slows down smoothly as the arm lags. Returns when the arm has settled on the pose."""
        self.at = None
        m = self.motion
        target = self.target(name)
        waypoint = approach_waypoint(self.here(), target, self.poses, m.get("approach"))
        result = None
        for leg in ([waypoint] if waypoint else []) + [target]:
            result = run(self.here(), leg, speed=self.speed, min_s=m["min_move_s"], fps=m["fps"],
                         observe=self.here, send=self.arm.send, clock=self.clock, lag_deg=self.lag_deg,
                         check=self.check, include_gripper=True, ramp_s=m.get("ramp_s"))
        self.errors[name] = max(self.errors.get(name, 0.0), result.error)
        if result.error > SHORT_DEG:
            self.say(f"  ! {name}: the arm stopped {result.error:.1f} degrees short ({result.joint}): "
                     f"blocked, or too much load")
        self.at = name

    def locate(self, from_anywhere: bool = False):
        """Find out which pose the arm is at. Refuses when it is at none of them, unless told."""
        name, distance = nearest(self.here(), self.poses)
        if name is None:
            raise StartError("no poses captured: run scripts/tools/capture_poses.sh")
        if distance > START_DEG and not from_anywhere:
            raise StartError(f"The arm is not at a captured pose (closest: {name}, {distance:.0f} degrees away). "
                             f"The route starts from a known pose: put the arm at `home` first (for example with "
                             f"scripts/teleop/run_teleop.sh), or use --from-anywhere to start the route from {name}: "
                             f"the first move then goes straight from where the arm is.")
        self.at = name

    def visit(self, name: str):
        """Go to a pose along the route; the poses on the way are only passed through."""
        path = route(self.at, name) if self.at else [name]
        for hop in path[1:] if self.at else path:
            via = "" if hop == name else "  (on the way)"
            self.say(f"  -> {hop}{via}  {self.seconds(self.here(), hop):.1f} s")
            self.move(hop)

    def home(self):
        if self.at != "home":
            self.visit("home")


def describe(name: str, index: int, total: int, poses: dict) -> str:
    spec = BY_NAME[name]
    return (f"[{index}/{total}] {name} - {spec.title}\n        {spec.where}\n        fingertips: "
            f"{tcp_text(poses[name])}")


def estimate(mover: Mover, names: list[str]) -> float:
    """Seconds of motion for visiting the poses in order from where the arm is, home at the end."""
    t, here, at = 0.0, mover.here(), mover.at
    for name in [*names, "home"]:
        for hop in (route(at, name)[1:] if at else [name]):
            t += mover.seconds(here, hop)
            here, at = mover.target(hop), hop
    return t


def walk(mover: Mover, names: list[str], delay: float, loop: bool = False):
    """Visit the poses in order, waiting `delay` seconds at each, then (once, or until stopped) again."""
    while True:
        for i, name in enumerate(names, 1):
            mover.say(describe(name, i, len(names), mover.poses))
            mover.visit(name)
            end = mover.clock.now() + delay
            while mover.clock.now() < end:
                mover.check()
                mover.clock.sleep(0.05)
        if not loop:
            return


def slideshow(mover: Mover, names: list[str], ask):
    """One pose at a time. ask(prompt) -> the user's answer: Enter next, b back, q quit."""
    i = 0
    while 0 <= i < len(names):
        name = names[i]
        mover.say(describe(name, i + 1, len(names), mover.poses))
        mover.visit(name)
        answer = ask("   Enter: next   b: back   q: quit  > ").strip().lower()
        if answer in ("q", "quit", "exit"):
            return
        i = max(0, i - 1) if answer in ("b", "back") else i + 1


def go(mover: Mover, name: str, ask):
    """Move to one pose and hold it. Then: Enter ends (the caller sends the arm home), or type
    another pose name to go there."""
    while True:
        mover.say(describe(name, NAMES.index(name) + 1, len(NAMES), mover.poses))
        mover.visit(name)
        answer = ask(f"   The arm holds {name}. Enter: finish   or a pose name ({', '.join(NAMES)}) > ").strip().lower()
        if not answer:
            return
        if answer not in mover.poses:
            mover.say(f"   '{answer}' is not a captured pose.")
            continue
        name = answer
