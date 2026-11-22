"""Draw the named arm poses in the v3 box: assets/poses_workspace.svg (and .png).

Usage:
    python scripts/tools/draw_poses.py                     # config/poses.yaml -> assets/poses_workspace.svg
    python scripts/tools/draw_poses.py --png               # also the PNG (needs cairosvg)
    uv run --no-project --with cairosvg python scripts/tools/draw_poses.py --png

No arm needed: it only reads config/poses.yaml. The arm is drawn exactly (forward kinematics,
arm_kinematics.py); the tray and the bins are approximate (workspace_layout.py). Run it again after
capturing poses to see them. Old pose names (centre, grasp) are read as their new names.
"""

import argparse
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "common"))
from pose_catalog import migrate  # noqa: E402
from pose_view import figure_svg  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--poses", type=Path, default=PROJECT_ROOT / "config" / "poses.yaml")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "assets" / "poses_workspace.svg")
    parser.add_argument("--png", action="store_true", help="also write the PNG next to it (2x, needs cairosvg)")
    args = parser.parse_args()

    poses = (yaml.safe_load(args.poses.read_text()) or {}).get("poses", {}) if args.poses.exists() else {}
    poses, notes = migrate(poses)
    for note in notes:
        print(f"  {note}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(figure_svg(poses))
    print(f"Wrote {args.out} ({len(poses)} poses)")
    if args.png:
        try:
            import cairosvg
        except ImportError:
            sys.exit("--png needs cairosvg: uv run --no-project --with cairosvg python scripts/tools/draw_poses.py --png")
        png = args.out.with_suffix(".png")
        cairosvg.svg2png(url=str(args.out), write_to=str(png), scale=2)
        print(f"Wrote {png}")


if __name__ == "__main__":
    main()
