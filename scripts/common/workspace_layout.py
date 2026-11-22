"""Where the parts of the v3 box are, in the arm's frame (cm): the tray, the two bins, the trash
entry, the walls. APPROXIMATE: scaled from assets/setup_v3_workspace_labeled.png, not measured.

How the numbers were made: the metal-bin and plastic-bin poses were captured by hand, so their
fingertip positions (arm_kinematics.forward) are exact. Together with the arm base they give three
points that match photo pixels to floor positions (an affine fit; the photo is a perspective
shot, so it is only good to a few cm). The fit puts the drop-down tray at x 11-38 cm, y -11..7.5 cm,
and the `hover` and `tray_low` poses, which were NOT used in the fit, land inside it: a check that
the fit is sound. The annotated boxes in the photo include walls and perspective, so the rectangles
below are shrunk to the openings.

Frame: origin on the arm base, x forward, y to the left, z up (arm_kinematics.py). z = 0 is taken as
the table the arm stands on; the tray floor is lower (tray_low reaches about -6 cm).

Replace the rectangles with measurements when there are any: everything that draws or checks the
workspace reads them from here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    x0: float  # forward
    x1: float
    y0: float  # y0 < y1; positive y is the arm's left
    y1: float

    def contains(self, x: float, y: float, margin: float = 0.0) -> bool:
        return bool(self.x0 - margin <= x <= self.x1 + margin and self.y0 - margin <= y <= self.y1 + margin)

    @property
    def centre(self) -> tuple[float, float]:
        return (self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2


# Inner walls of the box (the aluminium frame is about 60 cm wide)
BOX = Rect(-12, 52, -33, 32)
# The drop-down tray where the chute lets the items land (the white plate, in a cut-out of the table)
TRAY = Rect(12, 38, -8, 4)
BINS = {"metal": Rect(12.5, 36.5, 10, 27), "plastic": Rect(12.5, 36.5, -27.3, -10.3)}
# The trash entry: a chute in the back wall, above the far end of the tray
ENTRY = Rect(44, 52, -9, 9)
# The arm's base plate, centred on the shoulder_pan axis (3.9 cm in front of the frame's origin)
BASE = Rect(-1.1, 8.9, -5, 5)
TABLE_Z = 0.0


def hand_is_over(pose_name: str, x: float, y: float, margin: float = 4.0) -> bool | None:
    """Are the fingertips of the named pose above where they should be? None: no such area."""
    if pose_name in ("hover", "tray_low", "transit"):  # the recorder lets go of the item at transit
        return TRAY.contains(x, y, margin)
    if pose_name.endswith("_bin") and pose_name.split("_")[0] in BINS:
        return BINS[pose_name.split("_")[0]].contains(x, y, margin)
    return None
