"""Recording of a sorting pipeline run, and the showcase video made from it afterwards.

During the run, Recorder stores the raw front and wrist frames (MJPG .avi: cheap to write, so
the control loop is not slowed down) and, per frame, what the pipeline was doing
(frames.jsonl: YOLO detections or which ACT model is running). Writing happens in a background
thread; if the disk cannot keep up, frames are dropped rather than delaying the arm.

render() then makes showcase.mp4 in the same folder:
  - the front camera scaled to 720 px high (960x720, the camera's 4:3 kept),
  - the wrist camera, in sync, in the bottom-right corner at 1/4 of the video width,
  - while YOLO decides: its boxes with class and confidence, and how long the class has held,
  - a label in the top-right corner: "YOLO", "Plastic ACT" or "Metal ACT".

Render again (e.g. after Ctrl+C during rendering, or with other sizes):
    python scripts/run/pipeline_recording.py recordings/pipeline_<timestamp> [--height 720] [--inset 0.25]
"""

import argparse
import json
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

FPS = 30
MJPG_QUALITY = 85
CLASS_COLORS_BGR = {"metal": (255, 140, 60), "plastic": (60, 210, 60)}
MODE_LABELS = {"yolo": "YOLO", "plastic": "Plastic ACT", "metal": "Metal ACT"}


class Recorder:
    """Raw front/wrist frames plus per-frame pipeline state, at most FPS frames per second."""

    def __init__(self, run_dir: Path, info: dict):
        self.dir = run_dir
        run_dir.mkdir(parents=True, exist_ok=True)
        self.info = {"started_at": datetime.now().astimezone().isoformat(timespec="seconds"), **info}
        self.meta = (run_dir / "frames.jsonl").open("w")
        self.writers = {}
        self.counts = {"front": 0, "wrist": 0}
        self.dropped = 0
        self.start = time.monotonic()
        self.last = None
        self.queue = queue.Queue(maxsize=FPS * 4)
        self.thread = threading.Thread(target=self._write_loop, daemon=True)
        self.thread.start()

    def add(self, front: np.ndarray, wrist: np.ndarray | None, mode: str,
            detections: list | None = None, lock: tuple | None = None):
        """Queue one RGB frame pair. mode: 'yolo', 'plastic' or 'metal'. Extra calls within
        1/FPS s are ignored, so callers can call it from loops of any rate."""
        now = time.monotonic()
        if self.last is not None and now - self.last < 0.9 / FPS:
            return
        self.last = now
        item = (now - self.start, front.copy(), None if wrist is None else wrist.copy(), mode, detections, lock)
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            self.dropped += 1

    def _write_loop(self):
        while (item := self.queue.get()) is not None:
            t, front, wrist, mode, detections, lock = item
            record = {"t": round(t, 4), "mode": mode, "front": self._write("front", front),
                      "wrist": None if wrist is None else self._write("wrist", wrist)}
            if detections:
                record["detections"] = detections
            if lock:
                record["lock"] = list(lock)
            self.meta.write(json.dumps(record) + "\n")

    def _write(self, name: str, frame_rgb: np.ndarray) -> int:
        writer = self.writers.get(name)
        if writer is None:
            h, w = frame_rgb.shape[:2]
            writer = cv2.VideoWriter(str(self.dir / f"{name}.avi"), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (w, h))
            writer.set(cv2.VIDEOWRITER_PROP_QUALITY, MJPG_QUALITY)
            self.writers[name] = writer
        writer.write(cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR))
        self.counts[name] += 1
        return self.counts[name] - 1

    def close(self):
        """Write everything still queued and close the files."""
        self.queue.put(None)
        self.thread.join()
        for writer in self.writers.values():
            writer.release()
        self.meta.close()
        self.info.update(ended_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                         seconds=round(time.monotonic() - self.start, 1), frames=self.counts["front"],
                         wrist_frames=self.counts["wrist"], dropped_frames=self.dropped)
        (self.dir / "info.json").write_text(json.dumps(self.info, indent=2) + "\n")


class _SequentialReader:
    """Frame i of a video, for non-decreasing i (the recording is read once, front to back)."""

    def __init__(self, path: Path):
        self.capture = cv2.VideoCapture(str(path))
        self.index, self.frame = -1, None

    def get(self, index: int) -> np.ndarray | None:
        while self.index < index:
            ok, frame = self.capture.read()
            if not ok:
                break
            self.index, self.frame = self.index + 1, frame
        return self.frame


def _text(canvas, text, org, scale, color=(255, 255, 255), background=(0, 0, 0), anchor="left", pad=8):
    """Text on a dark box. org is the box's top-left (anchor=left) or top-right (anchor=right)."""
    thickness = max(1, round(scale * 2))
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
    x, y = org
    if anchor == "right":
        x -= tw + 2 * pad
    x = max(0, min(x, canvas.shape[1] - tw - 2 * pad))
    y = max(0, min(y, canvas.shape[0] - th - base - 2 * pad))
    cv2.rectangle(canvas, (x, y), (x + tw + 2 * pad, y + th + base + 2 * pad), background, -1)
    cv2.putText(canvas, text, (x + pad, y + pad + th), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)
    return y + th + base + 2 * pad


def compose(front, wrist, record: dict, size: tuple[int, int], inset: float, lock_seconds: float | None) -> np.ndarray:
    width, height = size
    scale = height / front.shape[0]
    canvas = cv2.resize(front, (width, height), interpolation=cv2.INTER_LINEAR)

    for det in record.get("detections", []):
        color = CLASS_COLORS_BGR.get(det["class"], (255, 255, 255))
        x0, y0, x1, y1 = (round(v * scale) for v in det["box"])
        cv2.rectangle(canvas, (x0, y0), (x1, y1), color, 3)
        _text(canvas, f"{det['class']} {det['conf']:.2f}", (x0 - 1, y0 - 34), 0.7, (0, 0, 0), color, pad=6)

    if wrist is not None:
        inset_w = round(width * inset)
        inset_h = round(inset_w * wrist.shape[0] / wrist.shape[1])
        margin, border = 16, 2
        x1, y1 = width - margin, height - margin
        x0, y0 = x1 - inset_w, y1 - inset_h
        cv2.rectangle(canvas, (x0 - border, y0 - border), (x1 + border - 1, y1 + border - 1), (255, 255, 255), -1)
        canvas[y0:y1, x0:x1] = cv2.resize(wrist, (inset_w, inset_h), interpolation=cv2.INTER_AREA)

    mode = record["mode"]
    background = (40, 40, 40) if mode == "yolo" else CLASS_COLORS_BGR[mode]
    bottom = _text(canvas, MODE_LABELS.get(mode, mode), (width - 16, 16), 1.1,
                   (255, 255, 255) if mode == "yolo" else (0, 0, 0), background, anchor="right", pad=10)
    if mode == "yolo" and record.get("lock"):
        cls, held = record["lock"]
        progress = f"{cls} {held:.1f}/{lock_seconds:.0f} s" if lock_seconds else f"{cls} {held:.1f} s"
        _text(canvas, progress, (width - 16, bottom + 6), 0.7, anchor="right", pad=6)
    return canvas


def render(run_dir: Path, height: int = 720, inset: float = 0.25) -> Path | None:
    """Make <run_dir>/showcase.mp4 from the raw recording, at a steady FPS."""
    import av

    lines = (run_dir / "frames.jsonl").read_text().splitlines() if (run_dir / "frames.jsonl").exists() else []
    records = [json.loads(line) for line in lines]
    if not records:
        print(f"Nothing recorded in {run_dir}: no video made.")
        return None
    info = json.loads((run_dir / "info.json").read_text()) if (run_dir / "info.json").exists() else {}
    lock_seconds = info.get("lock_seconds")

    front = _SequentialReader(run_dir / "front.avi")
    wrist = _SequentialReader(run_dir / "wrist.avi") if (run_dir / "wrist.avi").exists() else None
    first = front.get(0)
    width = round(first.shape[1] * height / first.shape[0] / 2) * 2  # even, for yuv420p

    output = run_dir / "showcase.mp4"
    container = av.open(str(output), "w")
    stream = container.add_stream("libx264", rate=FPS, options={"crf": "21", "preset": "veryfast"})
    stream.width, stream.height, stream.pix_fmt = width, height, "yuv420p"

    # Frames were recorded at a varying rate; for each output frame take the latest recorded one
    t0, t_end = records[0]["t"], records[-1]["t"]
    total = int((t_end - t0) * FPS) + 1
    j, last_j, canvas = 0, None, None
    print(f"Rendering {output} ({total / FPS:.0f} s of video)...", flush=True)
    for k in range(total):
        t = t0 + k / FPS
        while j + 1 < len(records) and records[j + 1]["t"] <= t:
            j += 1
        if j != last_j:
            record = records[j]
            wrist_frame = wrist.get(record["wrist"]) if wrist is not None and record["wrist"] is not None else None
            canvas = compose(front.get(record["front"]), wrist_frame, record, (width, height), inset, lock_seconds)
            last_j = j
        for packet in stream.encode(av.VideoFrame.from_ndarray(canvas, format="bgr24")):
            container.mux(packet)
        if k and k % (FPS * 60) == 0:
            print(f"  {k / total:.0%}", flush=True)
    for packet in stream.encode():
        container.mux(packet)
    container.close()
    print(f"Saved {output}")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--height", type=int, default=720, help="video height in px (default 720)")
    parser.add_argument("--inset", type=float, default=0.25, help="wrist view width as part of the video width")
    args = parser.parse_args()
    render(args.run_dir, args.height, args.inset)


if __name__ == "__main__":
    main()
