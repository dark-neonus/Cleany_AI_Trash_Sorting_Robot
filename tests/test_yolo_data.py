"""The YOLO train/val split must keep whole episodes on one side, also for the extra frames."""

import subprocess
import sys

import cv2
import numpy as np

from conftest import PROJECT_ROOT
from evaluate import build_eval_sets


def make_frames(root, episodes=10, extra_per_episode=1):
    """Fake labelled frames: first frames in <root>/frames, extra frames in <root>/extra."""
    image = np.zeros((48, 64, 3), np.uint8)
    for folder in ("frames", "extra"):
        for kind in ("images", "labels"):
            (root / folder / kind).mkdir(parents=True)
    for ep in range(episodes):
        stems = [("frames", f"cleany_metal_ep{ep:03d}_first")]
        stems += [("extra", f"cleany_metal_ep{ep:03d}_t{t + 1}.0") for t in range(extra_per_episode)]
        for folder, stem in stems:
            cv2.imwrite(str(root / folder / "images" / f"{stem}.jpg"), image)
            (root / folder / "labels" / f"{stem}.txt").write_text("0 0.5 0.5 0.2 0.2\n")


def run_prepare(root):
    subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts/yolo/prepare_dataset.py"),
                    "--frames", str(root / "frames"), "--extra", str(root / "extra"), "--out", str(root / "out")],
                   check=True, capture_output=True)
    return ({p.stem for p in (root / "out/labels/train").glob("*.txt")},
            {p.stem for p in (root / "out/labels/val").glob("*.txt")})


def test_every_fifth_episode_is_validation(tmp_path):
    make_frames(tmp_path, episodes=10)
    _, val = run_prepare(tmp_path)
    assert val == {"cleany_metal_ep004_first", "cleany_metal_ep009_first"}


def test_no_episode_is_in_both_train_and_val(tmp_path):
    make_frames(tmp_path, episodes=10, extra_per_episode=2)
    train, val = run_prepare(tmp_path)
    episodes = lambda stems: {s.split("_ep")[1][:3] for s in stems}  # noqa: E731
    assert not episodes(train) & episodes(val)
    assert len(train) == 8 * 3  # 8 training episodes x (first frame + 2 extra frames)


def test_evaluation_uses_the_same_validation_episodes(tmp_path):
    make_frames(tmp_path, episodes=10)
    test_dir = tmp_path / "frames" / "test"
    for kind in ("images", "labels"):
        (test_dir / kind).mkdir(parents=True)
    cv2.imwrite(str(test_dir / "images" / "photo.jpg"), np.zeros((48, 64, 3), np.uint8))
    (test_dir / "labels" / "photo.txt").write_text("1 0.5 0.5 0.2 0.2\n")

    val_yaml, test_yaml = build_eval_sets(tmp_path / "frames", tmp_path / "eval")
    _, prepare_val = run_prepare(tmp_path)
    evaluate_val = {p.stem for p in (val_yaml.parent / "val" / "labels").glob("*.txt")}
    assert evaluate_val == prepare_val
    assert [p.name for p in (test_yaml.parent / "test" / "images").iterdir()] == ["photo.jpg"]
