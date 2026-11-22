"""Draw the arm's named poses in the box: a top view and a side view of the arm, over the
approximate layout of workspace_layout.py.

One description of each picture, two renderers: SvgCanvas (the figure in assets/, scripts/tools/
draw_poses.py) and TkCanvas (the live view of the capture tool). Canvas methods take pixels; the
views turn arm coordinates (cm) into pixels.

  plan view  seen from above: the arm's base at the bottom, the trash entry at the top, the
             arm's left (the metal bin) on the left, like the photo of the box
  side view  the arm's own vertical plane: distance from the shoulder_pan axis along the way the
             arm points, against height. Honest about reach and height whatever the pan angle.
"""

from __future__ import annotations

import math
import textwrap
from dataclasses import dataclass

import workspace_layout as layout
from arm_kinematics import SKELETON, forward, reach_cm, tool_pitch_deg
from pose_catalog import BY_NAME, NAMES, POSES

INK, SUB, BODY, LINE = "#0f172a", "#64748b", "#334155", "#e2e8f0"
FLOOR, WALL, TRAY_FILL, BIN_FILL = "#f1f5f9", "#94a3b8", "#ffffff", "#cbd5e1"
ARM, FINGERS = "#334155", "#f59e0b"


# --- canvases --------------------------------------------------------------------------------------

class SvgCanvas:
    def __init__(self, width: int, height: int):
        self.width, self.height, self.parts = width, height, []

    @staticmethod
    def _esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    @staticmethod
    def _dash(dash) -> str:
        return f' stroke-dasharray="{dash[0]} {dash[1]}"' if dash else ""

    def rect(self, x0, y0, x1, y1, fill=None, outline=None, width=1, dash=None, radius=0):
        self.parts.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{x1 - x0:.1f}" height="{y1 - y0:.1f}" rx="{radius}" '
                          f'fill="{fill or "none"}" stroke="{outline or "none"}" stroke-width="{width}"{self._dash(dash)}/>')

    def line(self, points, color, width=1, dash=None, arrow=False):
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        marker = ' marker-end="url(#arrow)"' if arrow else ""
        self.parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{width}" '
                          f'stroke-linecap="round" stroke-linejoin="round"{self._dash(dash)}{marker}/>')

    def oval(self, cx, cy, r, fill=None, outline=None, width=1):
        self.parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{fill or "none"}" '
                          f'stroke="{outline or "none"}" stroke-width="{width}"/>')

    def polygon(self, points, fill=None, outline=None, width=1):
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        self.parts.append(f'<polygon points="{pts}" fill="{fill or "none"}" stroke="{outline or "none"}" '
                          f'stroke-width="{width}" stroke-linejoin="round"/>')

    def text(self, x, y, s, size=13, color=BODY, anchor="start", weight=400):
        self.parts.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{color}" font-weight="{weight}" '
                          f'text-anchor="{anchor}">{self._esc(s)}</text>')

    def svg(self, title: str, desc: str) -> str:
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.width} {self.height}" '
                f'width="{self.width}" height="{self.height}" '
                f"font-family=\"Arial, 'Liberation Sans', 'Helvetica Neue', Helvetica, sans-serif\">\n"
                f"<title>{self._esc(title)}</title>\n<desc>{self._esc(desc)}</desc>\n"
                '<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" '
                'orient="auto"><path d="M0 0 L10 5 L0 10 Z" fill="#64748b"/></marker></defs>\n'
                f'<rect width="{self.width}" height="{self.height}" fill="#f8fafc"/>\n')
        return head + "\n".join(self.parts) + "\n</svg>\n"


class TkCanvas:
    """The same calls on a tkinter Canvas (cleared by the caller before each frame)."""

    ANCHOR = {"start": "w", "middle": "center", "end": "e"}

    def __init__(self, canvas):
        self.c = canvas

    @staticmethod
    def _dash(dash):
        return tuple(int(d) for d in dash) if dash else None

    def rect(self, x0, y0, x1, y1, fill=None, outline=None, width=1, dash=None, radius=0):
        self.c.create_rectangle(x0, y0, x1, y1, fill=fill or "", outline=outline or "", width=width, dash=self._dash(dash))

    def line(self, points, color, width=1, dash=None, arrow=False):
        flat = [v for p in points for v in p]
        self.c.create_line(*flat, fill=color, width=width, capstyle="round", joinstyle="round", dash=self._dash(dash),
                           arrow="last" if arrow else None)

    def oval(self, cx, cy, r, fill=None, outline=None, width=1):
        self.c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fill or "", outline=outline or "", width=width)

    def polygon(self, points, fill=None, outline=None, width=1):
        self.c.create_polygon(*[v for p in points for v in p], fill=fill or "", outline=outline or "", width=width)

    def text(self, x, y, s, size=13, color=BODY, anchor="start", weight=400):
        self.c.create_text(x, y - size * 0.35, text=s, anchor=self.ANCHOR[anchor], fill=color,
                           font=("Sans", -size, "bold" if weight >= 600 else "normal"))


# --- views -----------------------------------------------------------------------------------------

@dataclass(frozen=True)
class PlanView:
    """From above. (x forward, y left) in cm -> pixels; ox, oy: where the base origin is drawn."""
    ox: float
    oy: float
    scale: float
    x_range: tuple[float, float] = (-14, 56)
    y_range: tuple[float, float] = (-36, 36)

    def px(self, x: float, y: float) -> tuple[float, float]:
        return self.ox - y * self.scale, self.oy - x * self.scale

    def point(self, p, joints=None) -> tuple[float, float]:
        return self.px(p[0], p[1])

    @property
    def box(self) -> tuple[float, float, float, float]:
        (x0, x1), (y0, y1) = self.x_range, self.y_range
        return (*self.px(x1, y1), *self.px(x0, y0))


@dataclass(frozen=True)
class SideView:
    """The arm's vertical plane. (r along the arm's direction from the pan axis, z up) in cm."""
    ox: float  # pixel of r = 0 (the pan axis)
    oy: float  # pixel of z = 0 (the table)
    scale: float
    r_range: tuple[float, float] = (-12, 42)
    z_range: tuple[float, float] = (-12, 32)

    def px(self, r: float, z: float) -> tuple[float, float]:
        return self.ox + r * self.scale, self.oy - z * self.scale

    def point(self, p, joints) -> tuple[float, float]:
        pan = forward(joints)["shoulder_pan"]
        theta = math.radians(joints["shoulder_pan.pos"])
        r = (p[0] - pan[0]) * math.cos(theta) - (p[1] - pan[1]) * math.sin(theta)
        return self.px(r, p[2])

    @property
    def box(self) -> tuple[float, float, float, float]:
        (r0, r1), (z0, z1) = self.r_range, self.z_range
        return (*self.px(r0, z1), *self.px(r1, z0))


def _frame(c, view, title: str | None = None):
    x0, y0, x1, y1 = view.box
    c.rect(x0, y0, x1, y1, fill="#ffffff", outline=LINE, width=1.5, radius=8)
    if title:
        c.text(x0 + 8, y0 + 16, title, 12, SUB, weight=700)


def _scale_bar(c, view, label="10 cm"):
    x0, y0, x1, y1 = view.box
    c.line([(x1 - 12 - 10 * view.scale, y1 - 12), (x1 - 12, y1 - 12)], SUB, 2)
    c.text(x1 - 12 - 5 * view.scale, y1 - 17, label, 11, SUB, "middle")


# --- the workspace -----------------------------------------------------------------------------------

def draw_plan_workspace(c, v: PlanView, labels: bool = True):
    _frame(c, v, "TOP VIEW" if labels else None)
    for y in range(-30, 31, 10):  # 10 cm grid
        c.line([v.px(v.x_range[0], y), v.px(v.x_range[1], y)], "#f1f5f9", 1)
    for x in range(-10, 51, 10):
        c.line([v.px(x, v.y_range[0]), v.px(x, v.y_range[1])], "#f1f5f9", 1)
    b = layout.BOX
    (ax, ay), (bx, by) = v.px(b.x1, b.y1), v.px(b.x0, b.y0)
    c.rect(ax, ay, bx, by, fill=FLOOR, outline=WALL, width=1.5, dash=(7, 5))
    for name, r in layout.BINS.items():
        (ax, ay), (bx, by) = v.px(r.x1, r.y1), v.px(r.x0, r.y0)
        c.rect(ax, ay, bx, by, fill=BIN_FILL, outline="#64748b", width=1.5, radius=4)
        if labels:
            c.text((ax + bx) / 2, ay + 18, f"{name} bin", 12, SUB, "middle", 700)
    t = layout.TRAY
    (ax, ay), (bx, by) = v.px(t.x1, t.y1), v.px(t.x0, t.y0)
    c.rect(ax, ay, bx, by, fill=TRAY_FILL, outline="#64748b", width=1.5, radius=4)
    if labels:
        c.text((ax + bx) / 2, ay + 18, "tray", 12, SUB, "middle", 700)
    e = layout.ENTRY
    (ax, ay), (bx, by) = v.px(e.x1, e.y1), v.px(e.x0, e.y0)
    c.rect(ax, ay, bx, by, fill="#fef3c7", outline="#d97706", width=1.5, dash=(5, 4), radius=3)
    if labels:
        c.text((ax + bx) / 2, (ay + by) / 2 + 4, "trash entry", 11, "#92400e", "middle", 700)
    s = layout.BASE
    (ax, ay), (bx, by) = v.px(s.x1, s.y1), v.px(s.x0, s.y0)
    c.rect(ax, ay, bx, by, fill="#e2e8f0", outline="#64748b", width=1.5, radius=4)
    if labels:
        c.text((ax + bx) / 2, by + 15, "arm base", 11, SUB, "middle")
    _scale_bar(c, v)


def _ray_interval(rect, joints: dict, step: float = 0.25):
    """Where (distance r from the pan axis) the arm's vertical plane crosses rect, or None."""
    pan = forward(joints)["shoulder_pan"]
    theta = math.radians(joints["shoulder_pan.pos"])
    inside = [i * step for i in range(-80, 280)
              if rect.contains(pan[0] + i * step * math.cos(theta), pan[1] - i * step * math.sin(theta))]
    return (min(inside), max(inside)) if inside else None


def draw_side_workspace(c, v: SideView, poses: dict, joints: dict | None = None, labels: bool = True):
    """The table in the arm's plane, with the recess of the tray (shallow) and the bins (deep) where
    the plane crosses them. joints: the arm's pose (its pan decides what the plane crosses)."""
    _frame(c, v, "SIDE VIEW (the arm's plane)" if labels else None)
    joints = joints or {**dict.fromkeys(("shoulder_lift.pos", "elbow_flex.pos", "wrist_flex.pos", "wrist_roll.pos"), 0.0),
                        "shoulder_pan.pos": 0.0}
    r0, r1 = v.r_range
    z0 = v.z_range[0]
    for z in range(-10, 31, 10):
        c.line([v.px(r0, z), v.px(r1, z)], "#f1f5f9", 1)
    floor_z = -7.0
    if "tray_low" in poses:
        floor_z = forward(poses["tray_low"])["tcp"][2] - 1.0
    notches = []
    for name, rect, depth in [("tray", layout.TRAY, floor_z)] + [(f"{n} bin", r, z0) for n, r in layout.BINS.items()]:
        span = _ray_interval(rect, joints)
        if span:
            notches.append((span[0], span[1], depth, name))
    notches.sort()
    outline = [v.px(r0, z0), v.px(r0, 0)]
    for a, b, depth, _ in notches:
        outline += [v.px(a, 0), v.px(a, depth), v.px(b, depth), v.px(b, 0)]
    outline += [v.px(r1, 0), v.px(r1, z0)]
    c.polygon(outline, fill="#e2e8f0", outline="#64748b", width=1.5)
    if labels:
        for a, b, depth, name in notches:
            mid = v.px((a + b) / 2, -3.5)
            c.text(mid[0], mid[1], name, 11, SUB, "middle", 700)
    s = layout.BASE
    (ax, ay), (bx, by) = v.px(s.x0 - 3.9, 6.2), v.px(s.x1 - 3.9, 0)
    c.rect(ax, ay, bx, by, fill="#cbd5e1", outline="#64748b", width=1.5)
    _scale_bar(c, v)


# --- the arm ---------------------------------------------------------------------------------------

def draw_arm(c, view, joints: dict, color: str = ARM, fingers: str = FINGERS, width: float = 5, marker: str | None = None):
    """The arm's skeleton: links, joint dots, the gripper as a different colour, a ring at the
    fingertips (marker: its fill)."""
    pts = forward(joints)
    px = [view.point(pts[name], joints) for name in SKELETON]
    c.line(px[:-1], color, width)
    c.line(px[-2:], fingers, width)
    for p in px[1:-1]:
        c.oval(p[0], p[1], width * 0.7, fill="#ffffff", outline=color, width=max(1.5, width * 0.35))
    tip = px[-1]
    c.oval(tip[0], tip[1], width * 1.15, fill=marker or fingers, outline="#ffffff", width=1.5)


def badge(c, x, y, n: int, colour: str, r: float = 11):
    c.oval(x, y, r, fill=colour, outline="#ffffff", width=2)
    c.text(x, y + r * 0.38, str(n), r * 1.15, "#ffffff", "middle", 700)


def tcp_text(joints: dict) -> str:
    t = forward(joints)["tcp"]
    return f"{t[0]:.0f} cm ahead  ·  {t[1]:+.0f} cm sideways  ·  {t[2]:+.0f} cm up  ·  gripper {tool_pitch_deg(joints):.0f}° down"


# --- the figure -------------------------------------------------------------------------------------

ROUTE = (("home", "hover"), ("hover", "transit"), ("transit", "metal_bin"), ("transit", "plastic_bin"))
# where a pose's name goes next to its marker: (dx, dy, anchor)
PLAN_LABEL = {"home": (18, 4, "start"), "hover": (18, 4, "start"), "tray_low": (-18, 4, "end"),
              "transit": (0, -17, "middle"), "metal_bin": (0, 28, "middle"), "plastic_bin": (0, 28, "middle")}
SIDE_LABEL = {"home": (-16, 4, "end"), "hover": (-16, 4, "end"), "tray_low": (0, 28, "middle"),
              "transit": (-16, 4, "end"), "metal_bin": None, "plastic_bin": (-10, -20, "middle")}
SIDE_TEXT = {"plastic_bin": "metal_bin · plastic_bin"}  # both bins share one dot in the side view
SIDE_NUDGE = {"metal_bin": -10, "plastic_bin": 10}  # both bins are at the same reach and height

CARD_W, CARD_H, SC = 580, 500, 4.0  # card size and cm -> px in the small views


def _pose_card(c, x: float, y: float, spec, joints: dict | None, number: int):
    c.rect(x, y, x + CARD_W, y + CARD_H, fill="#ffffff", outline=LINE, width=2, radius=18)
    badge(c, x + 30, y + 32, number, spec.colour, 15)
    c.text(x + 54, y + 38, spec.name, 22, INK, weight=700)
    c.text(x + 54 + len(spec.name) * 13.5 + 12, y + 38, spec.title, 14, SUB)
    for i, line in enumerate(textwrap.wrap(spec.where, 70)[:3]):
        c.text(x + 22, y + 68 + 17 * i, line, 12.5, BODY)
    top = y + 124
    plan = PlanView(x + 22 + 36 * SC, top + 56 * SC, SC)
    side = SideView(x + 22 + 72 * SC + 22 + 12 * SC, top + 32 * SC, SC)
    draw_plan_workspace(c, plan, labels=False)
    draw_side_workspace(c, side, poses_for_floor(spec, joints), joints, labels=False)
    c.text(side.box[0], side.box[3] + 22, "Who moves the arm here", 12, SUB, weight=700)
    for i, line in enumerate(textwrap.wrap(spec.used, 40)[:5]):
        c.text(side.box[0], side.box[3] + 41 + 16 * i, line, 12, BODY)
    if joints is None:
        c.text(x + CARD_W / 2, top + 130, "not captured yet", 20, "#b91c1c", "middle", 700)
        return
    draw_arm(c, plan, joints, width=4.5, marker=spec.colour)
    draw_arm(c, side, joints, width=4.5, marker=spec.colour)
    c.text(x + 22, y + CARD_H - 42, tcp_text(joints), 12.5, INK, weight=700)
    c.text(x + 22, y + CARD_H - 20, "pan {:.0f}  lift {:.0f}  elbow {:.0f}  wrist flex {:.0f}  roll {:.0f}  gripper {:.0f}".format(
        *(joints[f"{j}.pos"] for j in ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"))),
        12, SUB)


def poses_for_floor(spec, joints):
    return {"tray_low": joints} if spec.name == "tray_low" and joints else {}


def figure_svg(poses: dict) -> str:
    """The overview (all fingertip positions and the route of a cycle) and one card per pose."""
    W, H = 1840, 1850
    c = SvgCanvas(W, H)
    c.text(40, 58, "Cleany v3 box: the named arm poses", 34, INK, weight=700)
    c.text(40, 90, "Where each pose from config/poses.yaml puts the arm. The arm is exact (forward kinematics of the "
                   "SO-101); the tray and bins are approximate, scaled from the v3 photo.", 16, SUB)

    c.rect(30, 112, W - 30, 725, fill="#ffffff", outline=LINE, width=2, radius=20)
    S = 8
    plan = PlanView(48 + 36 * S, 130 + 56 * S, S)
    draw_plan_workspace(c, plan)
    side = SideView(48 + 72 * S + 40 + 12 * S, 130 + 32 * S, S)
    draw_side_workspace(c, side, poses)
    tips = {n: forward(poses[n])["tcp"] for n in NAMES if n in poses}
    # the carry to a bin, seen from above
    for a, b in (("transit", "metal_bin"), ("transit", "plastic_bin")):
        if a in tips and b in tips:
            _arrow(c, plan.point(tips[a]), plan.point(tips[b]))
    # the whole route, seen from the side (the poses separate by height there)
    side_px = {n: (side.point(tips[n], poses[n])[0] + SIDE_NUDGE.get(n, 0), side.point(tips[n], poses[n])[1]) for n in tips}
    for a, b in ROUTE:
        if a in side_px and b in side_px:
            _arrow(c, side_px[a], side_px[b])
    for i, spec in enumerate(POSES, 1):
        if spec.name not in tips:
            continue
        px, py = plan.point(tips[spec.name])
        badge(c, px, py, i, spec.colour)
        dx, dy, anchor = PLAN_LABEL[spec.name]
        c.text(px + dx, py + dy, spec.name, 12.5, INK, anchor, 700)
        sx, sy = side_px[spec.name]
        badge(c, sx, sy, i, spec.colour)
        if SIDE_LABEL[spec.name]:
            dx, dy, anchor = SIDE_LABEL[spec.name]
            c.text(sx + dx, sy + dy, SIDE_TEXT.get(spec.name, spec.name), 12.5, INK, anchor, 700)

    nx = side.box[0]
    c.text(nx, side.box[3] + 30, "How to read it", 15, INK, weight=700)
    for k, line in enumerate(("Dots: between the fingertips. Dashed arrows: the route of one cycle: home, hover (the pick",
                              "model lowers, grasps, lifts), transit, a bin, home. The arm is exact; the tray and bins",
                              "approximate. Side view: the arm's plane at pan 0 (the two bins share one dot position).")):
        c.text(nx, side.box[3] + 54 + 19 * k, line, 12.5, SUB)

    lx = side.box[2] + 36
    c.text(lx, 156, "Fingertip positions", 20, INK, weight=700)
    c.text(lx, 178, "cm, from the arm base; z = 0 is the table", 13, SUB)
    for i, spec in enumerate(POSES, 1):
        y = 218 + (i - 1) * 56
        badge(c, lx + 12, y, i, spec.colour)
        c.text(lx + 34, y + 2, spec.name, 15, INK, weight=700)
        if spec.name in tips:
            t = tips[spec.name]
            c.text(lx + 34, y + 21, f"{t[0]:.0f} ahead, {t[1]:+.0f} sideways, {t[2]:+.0f} up", 12.5, SUB)
        else:
            c.text(lx + 34, y + 21, "not captured", 12.5, "#b91c1c")

    for i, spec in enumerate(POSES):
        col, row = i % 3, i // 3
        _pose_card(c, 30 + col * (CARD_W + 25), 755 + row * (CARD_H + 24), spec, poses.get(spec.name), i + 1)
    return c.svg("Cleany v3 box: the named arm poses",
                 "Top and side views of the SO-101 at each named pose of the box pipeline, over an approximate "
                 "layout of the tray and bins.")


def _arrow(c, a, b):
    d = math.hypot(b[0] - a[0], b[1] - a[1]) or 1
    ux, uy = (b[0] - a[0]) / d, (b[1] - a[1]) / d
    if d > 36:
        c.line([(a[0] + ux * 15, a[1] + uy * 15), (b[0] - ux * 17, b[1] - uy * 17)], "#64748b", 2, (6, 4), arrow=True)


__all__ = ["BY_NAME", "PlanView", "SideView", "SvgCanvas", "TkCanvas", "draw_arm", "draw_plan_workspace",
           "draw_side_workspace", "figure_svg", "reach_cm", "tcp_text"]
