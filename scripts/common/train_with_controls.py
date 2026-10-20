"""Run lerobot-train with a graceful stop: type `exit` + Enter to save the current step and stop.

Usage:
    python train_with_controls.py [lerobot-train args...]

While training runs, typing `exit` (or `stop`) and Enter in the terminal makes training save a
checkpoint right after the step in progress (e.g. checkpoints/054321, not the last 050000) and
then end. The run can be continued later with train_act.sh --resume.

Every checkpoint also gets cleany_info.json next to pretrained_model/, with the step and the
time its last training step finished (used to name uploaded models).

Hooks into lerobot_train without changing lerobot:
  - should_save_checkpoint: also true for the step finished after `exit` was typed
  - update_last_checkpoint: runs right after a checkpoint is written; writes cleany_info.json
    and, after `exit`, stops training by raising StopTraining (caught below)
"""

import json
import logging
import socket
import sys
import threading
from datetime import datetime
from pathlib import Path

from lerobot.scripts import lerobot_train

STOP_COMMANDS = {"exit", "stop"}
INFO_FILE = "cleany_info.json"


class StopTraining(Exception):
    pass


stop_requested = threading.Event()
stop_saved = threading.Event()


def _watch_stdin() -> None:
    for line in sys.stdin:
        if line.strip().lower() in STOP_COMMANDS:
            logging.info("`exit` received: saving a checkpoint after the current step, then stopping...")
            stop_requested.set()
            return


original_should_save = lerobot_train.should_save_checkpoint
original_update_last = lerobot_train.update_last_checkpoint


def should_save_checkpoint(step: int, save_freq: int, total_steps: int) -> bool:
    return stop_requested.is_set() or original_should_save(step, save_freq, total_steps)


def update_last_checkpoint(checkpoint_dir: Path):
    result = original_update_last(checkpoint_dir)
    info = {
        "step": int(Path(checkpoint_dir).name),
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "host": socket.gethostname(),
        "stopped_early": stop_requested.is_set(),
    }
    (Path(checkpoint_dir) / INFO_FILE).write_text(json.dumps(info, indent=2) + "\n")
    if stop_requested.is_set():
        stop_saved.set()
        raise StopTraining(checkpoint_dir)
    return result


lerobot_train.should_save_checkpoint = should_save_checkpoint
lerobot_train.update_last_checkpoint = update_last_checkpoint


if __name__ == "__main__":
    if sys.stdin.isatty():
        threading.Thread(target=_watch_stdin, name="stop_watcher", daemon=True).start()
        print("Type `exit` and press Enter to save the current step and stop training.", flush=True)
    try:
        lerobot_train.main()
    except StopTraining as stopped:
        checkpoint_dir = Path(stopped.args[0])
        print(f"\nTraining stopped at step {int(checkpoint_dir.name)}. Saved: {checkpoint_dir}", flush=True)
        print("Continue later with: scripts/train/train_act.sh <model> --resume", flush=True)
