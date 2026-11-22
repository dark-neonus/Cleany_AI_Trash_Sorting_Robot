"""Move the follower arm between the named poses (config/poses.yaml) to look at them.

Usage (through scripts/tools/show_poses.sh, which fills in the port and the calibration):
    show_poses.sh walk [pose ...]        # every pose in order, 1 s at each (--delay), home at the end
    show_poses.sh slideshow [pose ...]   # one pose at a time: Enter next, b back, q quit
    show_poses.sh go <pose>              # one pose; then Enter to finish, or type another pose name
    add --dry-run to any of them to see the route and the timing without the arm.

Without pose names, walk and slideshow use every captured pose in the order of a cycle: home,
hover, transit, metal_bin, plastic_bin (and tray_low when captured).

The arm moves by itself. It moves the way the pipeline does: minimum-jerk moves (60 deg/s mean,
--speed), only along routes the pipeline itself takes (the bins are reached through transit), and it
must start at a captured pose, normally home. If the arm cannot follow, the plan slows down smoothly
instead of letting the arm fall behind. Keep hands and cables out of the box. The red EMERGENCY STOP
window ends everything (the arm then goes limp where it is). Ctrl+C, or the end, sends the arm home
first (--no-home: it goes limp where it is instead).
The gripper stays closed (--gripper closed), or open, or takes each pose's own value (pose).
"""

import argparse
import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "common"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "run"))
from box_logic import REQUIRED_POSES, load_poses, load_yaml  # noqa: E402
from box_states import Clock, Stop  # noqa: E402
from pose_catalog import NAMES  # noqa: E402
from pose_show import MoveError, Mover, StartError, estimate, go, slideshow, walk  # noqa: E402


class SimClock(Clock):
    """--dry-run: time passes without waiting."""

    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += max(seconds, 0.0)


class SimArm:
    def __init__(self, joints):
        self.joints = dict(joints)

    def observe(self):
        return dict(self.joints)

    def send(self, action):
        self.joints = dict(action)


def ask(prompt: str) -> str:
    """input() with the prompt on stdout: Python writes input() prompts to stderr, which the launcher
    pipes through a line-buffered filter, so a prompt without a newline would not show up."""
    print(prompt, end="", flush=True)
    return input()


class RobotArm:
    def __init__(self, robot):
        self.robot = robot

    def observe(self):
        return self.robot.get_observation()

    def send(self, action):
        self.robot.send_action(action)  # through arm_estop's guard


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=("walk", "slideshow", "go"))
    parser.add_argument("names", nargs="*", help="poses (go: exactly one)")
    parser.add_argument("--delay", type=float, default=1.0, help="walk: seconds at each pose (default 1)")
    parser.add_argument("--loop", action="store_true", help="walk: again and again until Ctrl+C")
    parser.add_argument("--speed", type=float, default=60, help="mean joint speed of the moves in deg/s (default 60; "
                                                                "the arm slows the plan down smoothly if it cannot follow)")
    parser.add_argument("--gripper", choices=("closed", "open", "pose"), default="closed")
    parser.add_argument("--no-home", action="store_true", help="do not go home at the end: the arm goes limp where it is")
    parser.add_argument("--from-anywhere", action="store_true", help="start even if the arm is at no captured pose")
    parser.add_argument("--yes", action="store_true", help="do not ask before the first move")
    parser.add_argument("--dry-run", action="store_true", help="no arm: show the route and the timing")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config" / "box_pipeline.yaml")
    parser.add_argument("--robot-port")
    parser.add_argument("--calibration-dir")
    parser.add_argument("--max-step", type=float, default=10)
    args = parser.parse_args()

    config = load_yaml(args.config)
    try:
        poses = load_poses(PROJECT_ROOT / config["poses"], REQUIRED_POSES)
    except (FileNotFoundError, KeyError) as error:
        sys.exit(f"Error: {error}")
    names = args.names or [n for n in NAMES if n in poses]
    bad = [n for n in names if n not in poses]
    if bad:
        sys.exit(f"Error: no captured pose {', '.join(bad)}. Captured: {', '.join(n for n in NAMES if n in poses)}")
    if args.mode == "go" and len(names) != 1:
        sys.exit("Error: go takes exactly one pose, e.g. show_poses.sh go hover")

    stop = threading.Event()
    robot, clamps = None, None
    if args.dry_run:
        arm, clock, paused = SimArm(poses["home"]), SimClock(), (lambda: False)
    else:
        if not (args.robot_port and args.calibration_dir):
            sys.exit("Error: --robot-port and --calibration-dir are needed (scripts/tools/show_poses.sh fills them in)")
        import arm_estop
        import clamp_log
        import estop

        import lerobot_wide_fov  # noqa: F401  (follower speed limits and soft torque start, as everywhere)

        clamps = clamp_log.install()  # counted, not printed a hundred times
        arm_estop.install()
        estop.start_estop_window()
        from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

        robot = SO101Follower(SO101FollowerConfig(port=args.robot_port, id="follower_arm",
                                                  calibration_dir=Path(args.calibration_dir),
                                                  max_relative_target=args.max_step))
        robot.connect()
        arm, clock, paused = RobotArm(robot), Clock(), estop.is_active

    mover = Mover(arm, poses, config["motion"], clock, args.gripper, print, paused, stop.is_set, args.speed,
                  lag_deg=0.8 * args.max_step)  # keep the command inside the follower's --max-step limit
    emergency, moving = False, False  # moving: this run may have moved the arm
    try:
        mover.locate(args.from_anywhere)
        seconds = estimate(mover, names)
        pauses = f" + {len(names)} pauses of {args.delay:g} s" if args.mode == "walk" else ""
        print(f"\n{args.mode}: {', '.join(names)}")
        print(f"The arm is at {mover.at}. About {seconds:.0f} s of motion{pauses} at {mover.speed:g} deg/s, "
              f"gripper {args.gripper}, then back home{' (not with --no-home)' if args.no_home else ''}.")
        if not args.dry_run and not args.yes:
            print("Keep hands and cables out of the box. The red EMERGENCY STOP window ends everything.")
            ask("Press Enter to start (Ctrl+C cancels) > ")
        moving = True
        if args.mode == "walk":
            walk(mover, names, args.delay, args.loop)
        elif args.mode == "slideshow":
            slideshow(mover, names, ask)
        else:
            go(mover, names[0], ask)
    except StartError as error:
        print(f"\n{error}")
        sys.exit(1)
    except Stop as error:
        emergency = "emergency" in str(error)
        print(f"\nStopped: {error}.")
    except MoveError as error:
        emergency = True  # the arm does not respond to commands: do not send it anywhere else
        print(f"\n{error}")
    except (KeyboardInterrupt, EOFError):
        print("\nInterrupted.")
    finally:
        if moving and not emergency and not args.no_home:
            try:
                mover.should_stop, mover.paused = (lambda: False), (lambda: False)
                if mover.at is None:
                    mover.locate(True)  # interrupted in the middle of a move: the route starts at the nearest pose
                print("Going home.")
                mover.home()
            except Exception as error:  # noqa: BLE001
                print(f"Could not go home: {error}")
        if robot is not None and robot.is_connected:
            robot.disconnect()  # torque off: the arm rests where it is (home)
        if moving and args.no_home and not emergency and not args.dry_run:
            print("--no-home: the arm is limp where it stopped.")
        if mover.errors:
            worst = ", ".join(f"{n} {e:.1f}" for n, e in mover.errors.items())
            print(f"\nHow close the arm got to each pose (degrees, worst joint): {worst}")
        if clamps is not None and clamps.count:
            print(f"{clamps.count} commands were limited by --max-step {args.max_step:g}: the arm could not follow "
                  f"that fast, so the moves took longer than planned.")


if __name__ == "__main__":
    main()
