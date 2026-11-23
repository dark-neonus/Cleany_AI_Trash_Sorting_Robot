"""Camera feeds and the drawing of the panel's views (scripts/common/camera_feed.py, scripts/run/pick_view.py)."""

import threading
from types import SimpleNamespace

import numpy as np
import pytest
from camera_feed import STALLED_S, CameraFeed, FeedStats, StatusFeed
from pick_view import AMBER, GREEN, RED, badge_text, render


def test_fps_is_measured_from_the_frame_times_and_decays_when_frames_stop():
    stats = FeedStats()
    assert stats.fps(0.0) == 0.0 and stats.age(0.0) is None
    for i in range(31):
        stats.add(i / 30)
    assert stats.fps(1.0) == pytest.approx(30.0, abs=0.1) and stats.age(1.0) == pytest.approx(0.0)
    assert stats.fps(1.6) < 20 and stats.fps(3.0) == 0.0  # the window slides on: a stalled camera reads 0
    slow = FeedStats()
    for i in range(10):
        slow.add(i / 12)
    assert slow.fps(9 / 12) == pytest.approx(12.0, abs=0.2)


class FakeCamera:
    def __init__(self):
        self.frame_lock, self.latest_frame, self.latest_timestamp = threading.Lock(), None, None

    def capture(self, stamp, value=0):
        with self.frame_lock:
            self.latest_frame, self.latest_timestamp = np.full((48, 64, 3), value, np.uint8), stamp


def test_a_camera_feed_takes_each_new_frame_once_without_consuming_the_buffer():
    camera = FakeCamera()
    feed = CameraFeed("front", camera)
    assert not feed.poll() and feed.state(0.0) == ("no signal", 0.0) and feed.size is None
    camera.capture(1.0)
    assert feed.poll() and not feed.poll() and feed.size == (64, 48)  # one frame, polled twice
    assert camera.latest_frame is not None  # still there for the session's own reads
    for i in range(1, 31):
        camera.capture(1.0 + i / 30)
        feed.poll()
    state, fps = feed.state(2.0)
    assert state == "live" and fps == pytest.approx(30, abs=1)
    assert feed.state(2.0 + STALLED_S + 0.5)[0] == "no signal"


def test_status_feed_shows_the_frames_of_the_session():
    status = SimpleNamespace(frame=None, wrist=None)
    feed = StatusFeed("wrist", status, "wrist")
    assert not feed.poll()
    status.wrist = np.zeros((36, 64, 3), np.uint8)
    assert feed.poll() and not feed.poll() and feed.size == (64, 36)


def test_badge_colours_follow_the_fps():
    assert badge_text("front", "live", 30.0, (640, 480)) == ("FRONT  30.0 fps  640x480", GREEN)
    assert badge_text("wrist", "live", 12.0, (640, 360))[1] == AMBER
    assert badge_text("wrist", "no signal", 0, None) == ("WRIST  NO SIGNAL", RED)


def test_a_view_has_the_asked_size_badge_boxes_and_a_recording_frame():
    frame = np.full((480, 640, 3), 100, np.uint8)
    plain = render(frame, (512, 384), ("FRONT  30.0 fps", GREEN))
    assert plain.size == (512, 384)
    boxed = render(frame, (512, 384), ("FRONT  30.0 fps", GREEN), [([100, 100, 300, 300], "#00e676", 3), (None, RED, 1)])
    assert boxed.getpixel((80 + 1, 160)) == (0, 230, 118)  # the left edge of the box: 100 * 512/640 = 80
    assert plain.getpixel((80 + 1, 160)) == (100, 100, 100)
    recording = render(frame, (512, 384), ("FRONT  30.0 fps", GREEN), recording=3.2)
    assert recording.getpixel((0, 200)) == (255, 23, 68)  # the red frame
    wrist = render(np.zeros((360, 640, 3), np.uint8), (512, 288), ("WRIST", GREEN))
    assert wrist.size == (512, 288)
