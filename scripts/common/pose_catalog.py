"""The named arm poses of the box: what each one is, where it is in the workspace, and how to check
a captured one. One table (POSES) that the capture tool, the workspace figure, the loader and the
docs all read, so a name or an explanation is changed in one place.

Poses are joint values in config/poses.yaml (degrees, gripper 0-100), captured by hand with
scripts/tools/capture_poses.sh. Pure Python plus arm_kinematics (numpy): no arm, no lerobot.

Order = the order of one cycle, which is also the order the capture tool asks for them.
"""

from __future__ import annotations

from dataclasses import dataclass

from arm_kinematics import forward, tool_pitch_deg
from box_logic import GRIPPER, JOINT_KEYS, RENAMED_POSES, RETIRED_POSES, max_joint_distance
from workspace_layout import hand_is_over

NEEDED_FOR = {
    "pipeline": "the box pipeline and the pick recorder (run_box_pipeline.sh, record_pick.sh)",
    "scripted": "the scripted grasp test (run_box_pipeline.sh --grasp scripted)",
}


@dataclass(frozen=True)
class PoseSpec:
    name: str
    title: str  # one line, for lists
    where: str  # where the fingertips are, in workspace words
    how: str  # how to put the arm there, what to watch
    gripper: str  # what to do with the gripper (the value is only used for home)
    used: str  # who moves the arm here and when
    needed_for: tuple[str, ...]
    colour: str  # in the figure

    @property
    def optional(self) -> bool:
        return "pipeline" not in self.needed_for


POSES: tuple[PoseSpec, ...] = (
    PoseSpec(
        "home", "Rest: folded over the base",
        "Folded up over the base, as low and compact as the arm goes, clear of the drop doors.",
        "Fold the arm all the way back, wrist tucked in. Leave the gripper CLOSED: this pose's gripper "
        "value is the one the pipeline uses at rest.",
        "closed (the value is used)",
        "Every cycle starts and ends here. The drop doors only open with the arm here.",
        ("pipeline",), "#475569"),
    PoseSpec(
        "hover", "Above the tray, camera looking down",
        "Over the middle of the tray, gripper pointing down, high enough that the wrist camera sees "
        "the whole tray.",
        "Check the wrist camera picture (the tool saves one): all four tray corners must be in it, and "
        "the gripper itself must not block the view. The pick model starts its grasp from here, so "
        "every recorded episode starts at this pose.",
        "any (the pipeline opens it)",
        "HOVER: the arm goes here after an item is found; the pick model takes over from here.",
        ("pipeline",), "#7c3aed"),
    PoseSpec(
        "transit", "High above the tray, between the two bins",
        "High above the middle of the tray, level with the gap between the bins, higher than every wall "
        "and rim.",
        "Lift the arm clear of everything with the gripper level, above the middle of the tray. An item "
        "held in the gripper must not be able to catch any edge on the way to a bin, and if it is let go "
        "here it must fall onto the tray.",
        "any (set by the program)",
        "CARRY: every carried item passes here on its way to a bin. The pick recorder lets go of the item "
        "here, so it falls back onto the tray.",
        ("pipeline",), "#2563eb"),
    PoseSpec(
        "metal_bin", "Over the metal bin (left)",
        "Above the middle of the metal bin, on the arm's LEFT, fingertips above the rim so the item "
        "falls in.",
        "Swing the arm left over the bin. The item must drop into the bin, not onto its rim.",
        "any (opened over the bin by the program)",
        "CARRY then RELEASE for metal items.",
        ("pipeline",), "#0d9488"),
    PoseSpec(
        "plastic_bin", "Over the plastic bin (right)",
        "Above the middle of the plastic bin, on the arm's RIGHT, fingertips above the rim so the "
        "item falls in.",
        "Swing the arm right over the bin, at the same height and reach as the metal bin pose.",
        "any (opened over the bin by the program)",
        "CARRY then RELEASE for plastic items.",
        ("pipeline",), "#16a34a"),
    PoseSpec(
        "tray_low", "OPTIONAL: low on the tray, where an item lies",
        "Straight down from hover, fingertips at the height of an item lying on the tray floor, "
        "gripper pointing down.",
        "Lower the arm until the fingertips are just above the tray floor, over the middle of the tray. "
        "Stop short of touching it: the servos would strain.",
        "any (set by the program)",
        "Only the scripted grasp test (a fake grasp, to try the pipeline on the arm before a pick model "
        "exists): it goes here and closes the gripper. Not needed for the pipeline or for recording.",
        ("scripted",), "#c026d3"),
)
BY_NAME = {p.name: p for p in POSES}
NAMES = tuple(p.name for p in POSES)


def needed(feature: str) -> tuple[str, ...]:
    return tuple(p.name for p in POSES if feature in p.needed_for)


# --- old files -------------------------------------------------------------------------------------

def migrate(poses: dict) -> tuple[dict, list[str]]:
    """poses.yaml content with old names -> new names, and what was done.
    centre -> transit, grasp -> tray_low; tray_release is dropped (it described the same place as
    tray_low). A pose already under its new name is never overwritten."""
    out, notes = {}, []
    for name, pose in poses.items():
        if name in RETIRED_POSES:
            notes.append(f"dropped '{name}': {RETIRED_POSES[name]}")
            continue
        new = RENAMED_POSES.get(name, name)
        if new != name:
            notes.append(f"renamed '{name}' -> '{new}'")
            if new in poses:
                notes.append(f"kept the existing '{new}', dropped the old '{name}'")
                continue
        out[new] = pose
    ordered = {n: out[n] for n in NAMES if n in out}
    ordered.update({n: p for n, p in out.items() if n not in ordered})  # unknown poses are kept
    return ordered, notes


# --- checks of a captured pose -----------------------------------------------------------------------

@dataclass(frozen=True)
class Finding:
    level: str  # "error": surely wrong; "warn": probably wrong
    text: str


def check(name: str, poses: dict) -> list[Finding]:
    """What looks wrong about poses[name] given the others captured so far. Only objective checks
    (kinematics, left/right, heights): a clean result does not prove the pose is good, you still
    check it with your eyes and the figure."""
    pose, found = poses[name], []
    tcp = forward(pose)["tcp"]
    for other, op in poses.items():
        if other != name and other in BY_NAME and max_joint_distance(pose, op) < 6:
            found.append(Finding("error", f"almost the same joints as '{other}' (within 6 degrees): "
                                          f"did the arm move between the two?"))
    if name == "home" and pose[GRIPPER] > 10:
        found.append(Finding("warn", f"the gripper is open ({pose[GRIPPER]:.0f}); the pipeline leaves it "
                                     f"like this at rest. Close it and capture again"))
    if name in ("hover", "tray_low") and tool_pitch_deg(pose) < 45:
        found.append(Finding("warn", f"the gripper points only {tool_pitch_deg(pose):.0f} degrees down: "
                                     f"{'the wrist camera will not see the tray' if name == 'hover' else 'it cannot grab from above'}"))
    over = hand_is_over(name, float(tcp[0]), float(tcp[1]))
    if over is not None and not over:
        area = f"{name.split('_')[0]} bin" if name.endswith("_bin") else "tray"
        why = " (the pick recorder lets the item go here: it must fall onto the tray)" if name == "transit" else ""
        found.append(Finding("warn", f"the fingertips ({tcp[0]:.0f} cm ahead, {tcp[1]:+.0f} cm sideways) do not look "
                                     f"like they are over the {area}{why} (layout is approximate, see the figure)"))
    if name in ("metal_bin", "plastic_bin"):
        left = name == "metal_bin"
        if (tcp[1] < 3) if left else (tcp[1] > -3):
            found.append(Finding("error", f"the fingertips are {abs(tcp[1]):.0f} cm to the "
                                          f"{'right' if tcp[1] < 0 else 'left'} of the arm: the "
                                          f"{name.split('_')[0]} bin is on the {'left' if left else 'right'}"))
    low, high = poses.get("tray_low"), poses.get("hover")
    if name in ("hover", "tray_low") and low and high:
        gap = forward(high)["tcp"][2] - forward(low)["tcp"][2]
        if gap < 8:
            found.append(Finding("error", f"hover is only {gap:.0f} cm above tray_low: it must be clearly higher"))
    if name == "transit":
        bins = [forward(poses[b])["tcp"][2] for b in ("metal_bin", "plastic_bin") if b in poses]
        if bins and tcp[2] < min(bins) - 3:
            found.append(Finding("warn", f"{min(bins) - tcp[2]:.0f} cm lower than the bin poses: an item may "
                                         f"catch a rim on the way there"))
    return found


def status(poses: dict) -> dict[str, list[Finding] | None]:
    """name -> findings, or None when the pose is missing."""
    return {n: (check(n, poses) if n in poses else None) for n in NAMES}


def missing_for(feature: str, poses: dict) -> list[str]:
    return [n for n in needed(feature) if n not in poses]


def joint_summary(pose: dict) -> str:
    return "  ".join(f"{k.split('.')[0].replace('_', ' ')} {pose[k]:6.1f}" for k in JOINT_KEYS)
