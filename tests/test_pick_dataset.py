"""The pick dataset stays readable however a session ends (scripts/common/pick_dataset.py), on a tiny
real LeRobot dataset."""

import shutil
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("lerobot")
from pick_dataset import DatasetError, DatasetRecorder, dataset_problem, open_dataset  # noqa: E402

from lerobot.datasets.lerobot_dataset import LeRobotDataset  # noqa: E402

CFG = {"repo_id": "cleany-ai/cleany_pick_test", "fps": 30}
CAMERAS = {"front": (48, 64), "wrist": (36, 64)}
DIM = 8


def opener(root, cameras=CAMERAS):
    return lambda: open_dataset(CFG, root, cameras, DIM, say=lambda _: None, codec="h264")


def frame(rng):
    return {"observation.state": rng.random(8, dtype=np.float32), "action": rng.random(6, dtype=np.float32),
            "observation.images.front": rng.integers(0, 255, (48, 64, 3), dtype=np.uint8),
            "observation.images.wrist": rng.integers(0, 255, (36, 64, 3), dtype=np.uint8),
            **{f"motors.{k}": rng.random(6, dtype=np.float32) for k in ("velocity", "load", "current", "temperature", "voltage")},
            "item.embedding": rng.random(DIM, dtype=np.float32), "item.box": rng.random(4, dtype=np.float32),
            "task": "Pick up the metal item"}


def record(dataset, n, rng):
    for _ in range(n):
        dataset.add_frame(frame(rng))


@pytest.fixture
def rng():
    return np.random.default_rng(0)


def test_every_saved_episode_is_readable_even_if_the_session_never_ends(tmp_path, rng):
    root = tmp_path / "pick"
    try:
        recorder = DatasetRecorder(opener(root)(), None, None, 0.0, list(CAMERAS), reopen=opener(root))
    except Exception as error:  # noqa: BLE001
        pytest.skip(f"no video encoder here: {error}")
    for expected in (1, 2):
        record(recorder.dataset, 10 + expected, rng)
        assert recorder.save() == expected - 1
        # a second process looking at the folder now, the session being still alive (or crashed): readable
        assert dataset_problem(root) is None
        reader = LeRobotDataset(CFG["repo_id"], root=root)
        assert reader.meta.total_episodes == expected and reader.num_frames == sum(11 + i for i in range(expected))
    record(recorder.dataset, 5, rng)  # a third episode that is never saved: lost, nothing else
    assert LeRobotDataset(CFG["repo_id"], root=root).meta.total_episodes == 2


def test_without_the_checkpoint_the_dataset_is_unreadable_until_finalized(tmp_path, rng):
    """What happened on the arm: the session ended without finalize()."""
    root = tmp_path / "pick"
    try:
        dataset = opener(root)()
    except Exception as error:  # noqa: BLE001
        pytest.skip(f"no video encoder here: {error}")
    record(dataset, 10, rng)
    dataset.save_episode()
    snapshot = tmp_path / "crashed"
    shutil.copytree(root, snapshot)  # the folder as a killed process leaves it
    assert "never written" in dataset_problem(snapshot) or "never finalized" in dataset_problem(snapshot)
    dataset.finalize()
    assert dataset_problem(root) is None


def test_an_unusable_dataset_is_set_aside_not_deleted_and_a_new_one_started(tmp_path, rng):
    root = tmp_path / "pick"
    try:
        dataset = opener(root)()
    except Exception as error:  # noqa: BLE001
        pytest.skip(f"no video encoder here: {error}")
    record(dataset, 10, rng)
    dataset.save_episode()  # not finalized, and the process is gone: simulate by copying the folder over
    broken = tmp_path / "broken" / "pick"
    shutil.copytree(root, broken)
    dataset.finalize()
    said = []
    fresh = open_dataset(CFG, broken, CAMERAS, DIM, say=said.append, codec="h264")
    assert fresh.meta.total_episodes == 0
    moved = list(broken.parent.glob("pick.unusable_*"))
    assert len(moved) == 1 and (moved[0] / "videos").exists()  # the old data is still there
    assert "Moved it to" in said[0] and "episode metadata" in said[0] or "finalized" in said[0]


def test_a_dataset_with_other_features_is_refused(tmp_path):
    root = tmp_path / "pick"
    try:
        opener(root)().finalize()
    except Exception as error:  # noqa: BLE001
        pytest.skip(f"no video encoder here: {error}")
    with pytest.raises(DatasetError, match="different features"):
        open_dataset(CFG, root, CAMERAS, DIM + 1, say=lambda _: None, codec="h264")  # another embedding size
    assert dataset_problem(Path(tmp_path / "nothing")) is None
