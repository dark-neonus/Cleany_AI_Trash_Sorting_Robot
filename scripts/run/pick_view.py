"""Drawing of the pick recorder panel's camera views (scripts/run/pick_panel.py), without Tk.

A view is the camera image at the size asked for, with a badge (camera, fps, resolution), a frame
that is red while recording, a REC counter, and, on the front camera, the boxes of the session
(YOLO blue, tray change orange, target green; the tray region grey). Boxes are in 640x480
coordinates whatever size the camera frame has.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

GREEN, AMBER, RED, GREY = "#00c853", "#ffab00", "#ff1744", "#888888"
GOOD_FPS = 24  # below this the badge turns amber

_font_cache: dict[int, ImageFont.FreeTypeFont] = {}


def font(size: int):
    if size not in _font_cache:
        _font_cache[size] = ImageFont.load_default(size=size)
    return _font_cache[size]


def badge_text(name: str, state: str, fps: float, size) -> tuple[str, str]:
    """('FRONT  30.0 fps  640x480', colour) or ('FRONT  NO SIGNAL', red)."""
    if state != "live":
        return f"{name.upper()}  NO SIGNAL", RED
    return f"{name.upper()}  {fps:4.1f} fps  {size[0]}x{size[1]}", GREEN if fps >= GOOD_FPS else AMBER


def render(frame, size: tuple[int, int], badge: tuple[str, str], boxes=(), recording: float | None = None) -> Image.Image:
    """frame: RGB array; size: (w, h) of the view; boxes: [(box, colour, line width)] in 640x480;
    recording: seconds into the episode, or None."""
    image = Image.fromarray(frame).resize(size, Image.BILINEAR)
    draw = ImageDraw.Draw(image)
    sx, sy = size[0] / 640, size[1] / 480
    for box, color, width in boxes:
        if box is not None:
            draw.rectangle([box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy], outline=color, width=width)
    text, color = badge
    f = font(14)
    left, top, right, bottom = draw.textbbox((8, 6), text, font=f)
    draw.rectangle([left - 5, top - 3, right + 5, bottom + 3], fill="#000000cc" if image.mode == "RGBA" else "#101010")
    draw.text((8, 6), text, fill=color, font=f)
    if recording is not None:
        label = f"REC  {recording:4.1f} s"
        w = draw.textlength(label, font=f)
        draw.rectangle([size[0] - w - 36, 4, size[0] - 6, 28], fill="#101010")
        draw.ellipse([size[0] - w - 30, 10, size[0] - w - 18, 22], fill=RED)
        draw.text((size[0] - w - 12, 6), label, fill="#ffffff", font=f)
        draw.rectangle([0, 0, size[0] - 1, size[1] - 1], outline=RED, width=3)
    return image
