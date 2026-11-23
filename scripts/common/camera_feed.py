"""Live camera frames for the control panels, with the real frame rate of each camera.

The pick recorder's session thread reads the cameras through the robot, only as fast as its own
loop runs and not at all while it waits (the doors, a classification). A panel that shows those
frames freezes and its fps says nothing about the camera. lerobot's OpenCVCamera keeps its newest
frame in a buffer filled by a capture thread of its own; CameraFeed peeks at that buffer, without
consuming a frame, so the panel shows what the camera delivers whatever the session is doing and
measures the camera's real fps from the capture time stamps.
"""

from __future__ import annotations

import time
from collections import deque

WINDOW_S = 1.0  # fps is measured over this much time
STALLED_S = 1.0  # no new frame for this long: no signal


class FeedStats:
    """Frames per second over the last WINDOW_S seconds, from the time stamps of the frames."""

    def __init__(self, window: float = WINDOW_S):
        self.window, self.times = window, deque()

    def add(self, t: float):
        self.times.append(t)
        while self.times and self.times[0] < t - self.window:
            self.times.popleft()

    def fps(self, now: float) -> float:
        times = [t for t in self.times if t >= now - self.window]
        if len(times) < 2 or times[-1] <= times[0]:
            return 0.0
        rate = (len(times) - 1) / (times[-1] - times[0])
        if now - times[-1] > 2 / rate:  # frames have stopped coming: count the silence too
            rate = (len(times) - 1) / (now - times[0])
        return rate

    def age(self, now: float) -> float | None:
        """Seconds since the last frame, None before the first."""
        return None if not self.times else now - self.times[-1]


class Feed:
    """One camera's frames: poll() says whether there is a new one; frame, stats, size follow."""

    def __init__(self, name: str):
        self.name, self.stats, self.frame, self.last = name, FeedStats(), None, None
        self.redraw = False  # the panel sets it to draw again at once (a new view size)

    @property
    def size(self) -> tuple[int, int] | None:
        return None if self.frame is None else (self.frame.shape[1], self.frame.shape[0])

    def state(self, now: float) -> tuple[str, float]:
        """('live' | 'no signal', fps)."""
        age = self.stats.age(now)
        if self.frame is None or age is None or age > STALLED_S:
            return "no signal", 0.0
        return "live", self.stats.fps(now)

    def accept(self, frame, stamp: float) -> bool:
        if frame is None or stamp is None or stamp == self.last:
            return False
        self.frame, self.last = frame, stamp
        self.stats.add(stamp)
        return True


class CameraFeed(Feed):
    """The newest frame of a lerobot OpenCVCamera, from its capture thread's buffer (RGB)."""

    def __init__(self, name: str, camera):
        super().__init__(name)
        self.camera = camera

    def poll(self) -> bool:
        with self.camera.frame_lock:
            frame, stamp = self.camera.latest_frame, self.camera.latest_timestamp
        return self.accept(frame, stamp)  # the capture time, from time.perf_counter()


class StatusFeed(Feed):
    """Frames the session published in its Status (no cameras of the panel's own: tests, fallbacks)."""

    def __init__(self, name: str, status, attribute: str):
        super().__init__(name)
        self.status, self.attribute = status, attribute

    def poll(self) -> bool:
        frame = getattr(self.status, self.attribute, None)
        return frame is not None and frame is not self.frame and self.accept(frame, time.perf_counter())
