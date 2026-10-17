# Cleany_AI_Trash_Sorting_Robot

## Purpose

Sorting trash using lerobot so101 robot arm inside custom made box in which trash is dropped.

If robot detect metal it thrown it in the left hole, if plastic detected it is thrownin the right hole. If neither, signal is given to esp32 conntroller to open floor of trash receiving area and remaining(other) trash is being dropped into mixed bin.

## Model Pipeline

```mermaid
flowchart TD
    A[Idle: YOLO on every front-camera frame] --> B{Same class, confidence ≥ threshold,<br/>N frames in a row?}
    B -->|No| A
    B -->|Yes: lock the class| C{Locked class}

    C -->|Plastic| D[Plastic ACT]
    C -->|Metal| E[Metal ACT]
    C -->|Other| F[ESP32: open trash dropping mechanism]

    D --> G[Wait a few seconds & return to beginning state<br/>Arm start position, trash dropping mechanism closed]
    E --> G
    F --> G

    G --> A
```

- **YOLO decides once, at the start.** While the arm is idle, YOLO runs on every frame of
  the front camera. Single frames are unreliable while the item is still falling or
  bouncing, so the class is locked only when the same class wins with confidence above a
  threshold for N consecutive frames. Nothing detected means keep waiting.
- **YOLO is not consulted while an ACT runs.** The arm hides the item during the grasp, so
  the class could flip, and switching policies mid-grasp is worse than finishing.
- **ACT models get no YOLO output.** Each material has its own ACT model, so the class is
  already chosen by picking the model. Each ACT finds the item from the camera images alone.
- **The YOLO model needs an `other` class**, so "an item that is neither plastic nor metal"
  can be told apart from "the box is empty". YOLO weights are not in the repo yet; the
  pipeline runner and YOLO scripts will be added with them.

## Scripts

All scripts can be run from any directory; they `cd` to the project root themselves.

| Folder                 | Script                   | What it does                                                  |
| ---------------------- | ------------------------ | ------------------------------------------------------------- |
| `scripts/setup/`       | `install_lerobot.sh`     | Install system packages and LeRobot into `.venv`              |
| `scripts/calibration/` | `calibrate_leader.sh`, `calibrate_follower.sh` | Calibrate the arms into `calibration/`  |
| `scripts/teleop/`      | `run_teleop.sh`          | Drive the follower with the leader arm, cameras shown in Rerun |
| `scripts/dataset/`     | `record.sh`              | Record teleoperated episodes for one ACT model                |
|                        | `view.sh`                | Browse a recorded episode in Rerun (no robot needed)          |
|                        | `replay.sh`              | Replay a recorded episode on the follower arm                 |
|                        | `delete_last_episode.sh` | Drop the last episode (e.g. a failed demo)                    |
|                        | `sync.sh`                | Push/pull datasets to/from the Hugging Face Hub               |
| `scripts/train/`       | `train_act.sh`           | Train the ACT model of one material                           |
| `scripts/config/`      | `hardware.sh`, `datasets.sh` | Ports, cameras, motion limits; model names, tasks, Hub namespace |
| `scripts/common/`      | `lerobot_wide_fov.py`, `dataset_sync.py` | Helpers used by the scripts above   |

## Recording datasets for the ACT models

There is one dataset per ACT model, selected by the model name `plastic` or `metal`:

| Model     | Local folder           | Hub repo                     | Task text                                  |
| --------- | ---------------------- | ---------------------------- | ------------------------------------------ |
| `plastic` | `data/cleany_plastic/` | `cleany-ai/cleany_plastic`   | Put the plastic item into the right hole   |
| `metal`   | `data/cleany_metal/`   | `cleany-ai/cleany_metal`     | Put the metal item into the left hole      |

Model names, task texts and the Hub namespace live in
[scripts/config/datasets.sh](scripts/config/datasets.sh). `data/` is never committed to git.

### Workflow

```bash
scripts/dataset/sync.sh pull plastic        # 1. get the latest shared copy (skip if the Hub repo is still empty)
scripts/dataset/record.sh plastic 10        # 2. record 10 episodes (appends if the dataset exists)
scripts/dataset/view.sh plastic 9           # 3. check the last one
scripts/dataset/delete_last_episode.sh plastic   #    ...and drop it if it went wrong
scripts/dataset/sync.sh push plastic        # 4. upload
```

`record.sh --push plastic 10` does steps 2 and 4 in one go.

While recording, the follower copies the leader arm and both cameras show in Rerun.
Each episode lasts `EPISODE_TIME_S` (30 s), followed by `RESET_TIME_S` (10 s) to put a new
item into the box. Keys: **→** ends the episode early, **←** re-records it, **Esc** stops.
If asked about calibration, press ENTER to use the files in `calibration/`.

Tips for good ACT data:

- Start every episode from the same arm start position, the one the pipeline returns to.
- Vary the item and where it lands; keep lighting and camera positions fixed.
- Aim for 50+ episodes per model before the first serious training run.

Replay an episode on the real arm, at half speed:

```bash
scripts/dataset/replay.sh --speed 0.5 --episode 3 plastic
```

### Training

```bash
scripts/train/train_act.sh plastic --steps=2000   # smoke test
scripts/train/train_act.sh plastic                # full run (100k steps)
```

Checkpoints go to `outputs/train/act_<model>_<timestamp>/checkpoints/`.

## Storing datasets in the cloud

### Recommended: private Hugging Face Hub dataset repos

| Option                      | Fit for LeRobot data | Versioning           | Cost / limits          |
| --------------------------- | -------------------- | -------------------- | ---------------------- |
| **Hugging Face Hub**        | Native: training and the dataset viewer load it directly by repo id | Every push is a commit; roll back to any revision | Free private storage up to a quota per account/org |
| Google Drive (via `rclone`) | Plain files only     | None, files are overwritten | Free 15 GB per account |
| S3 / Cloudflare R2          | Plain files only     | Optional bucket versioning | Pay per GB          |
| DVC on top of git           | Plain files only     | Full, tied to git commits | Needs a storage backend anyway |

The Hub is the format LeRobot already uses, so nothing has to be converted: the same repo
can be pulled on any machine (for example a bigger GPU for training) or opened in the
online LeRobot dataset visualizer. Each `push` is a git commit, so a bad upload can be
undone. A LeRobot dataset is a few hundred files (parquet tables + MP4 videos), which suits
the Hub's git/Xet storage much better than Drive.

### One-time setup

1. Create a Hugging Face organization (default name `cleany-ai`; set another in
   `scripts/config/datasets.sh` or via `HF_NAMESPACE=...`) and add the team members.
2. Create an access token with **write** permission at
   https://huggingface.co/settings/tokens and log in on every machine:

   ```bash
   .venv/bin/hf auth login
   ```

Repos are created on the first push, always **private**.

### Sync commands

```bash
scripts/dataset/sync.sh status              # episode counts, local vs Hub, for every model
scripts/dataset/sync.sh push plastic        # upload local → Hub
scripts/dataset/sync.sh pull all            # download Hub → local, every model
```

- `push` uploads the local dataset and makes the Hub copy match it exactly, including
  episodes deleted locally. It refuses if the Hub has more episodes than the local copy.
- `pull` replaces the local copy with the Hub one, keeping the old one in
  `data/cleany_<model>.before_pull/`. It refuses if the local copy has more episodes.
- Add `--force` to skip the episode-count check, e.g. to push after deleting episodes:
  `scripts/dataset/sync.sh push plastic --force`.

### Team rules

- **Pull before you record, push right after.** The Hub copy is the shared truth.
- **One person records a given model at a time.** LeRobot datasets cannot be merged by
  syncing; two people appending to the same dataset in parallel would overwrite each
  other's episodes. To record the same model on two machines in parallel, the second
  machine pushes to a personal namespace instead
  (`HF_NAMESPACE=<your-user> scripts/dataset/sync.sh push plastic`), and the two datasets
  are merged afterwards with `lerobot-edit-dataset --operation.type=merge`.
- Trained checkpoints are not synced yet. Upload good ones to Hub **model** repos
  (`hf upload --private cleany-ai/act_plastic outputs/train/<job>/checkpoints/last/pretrained_model`).
