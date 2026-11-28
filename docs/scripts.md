# Scripts

Part of the [Cleany README](../README.md).

## Scripts

All scripts can be run from any directory; they `cd` to the project root themselves.

| Folder                 | Script                   | What it does                                                  |
| ---------------------- | ------------------------ | ------------------------------------------------------------- |
| `scripts/setup/`       | `install_dependencies.sh` | Install system packages, LeRobot and YOLO (Ultralytics) into `.venv` |
| `scripts/calibration/` | `calibrate_leader.sh`, `calibrate_follower.sh` | Calibrate the arms into `calibration/`  |
| `scripts/teleop/`      | `run_teleop.sh`          | Drive the follower with the leader arm, cameras shown in Rerun |
| `scripts/dataset/`     | `record_pick.sh`         | Record the box pipeline's pick dataset with a panel ([pick-dataset.md](pick-dataset.md)) |
|                        | `view.sh`                | Browse a recorded episode in Rerun (no robot needed)          |
|                        | `replay.sh`              | Replay a recorded episode on the follower arm                 |
|                        | `delete_last_episode.sh` | Drop the last episode (e.g. a failed demo)                    |
|                        | `sync.sh`                | Push/pull datasets to/from the Hub (`pick` = cleany_pick + cleany_pick_items) |
| `scripts/train/`       | `train_act.sh`           | Train ACT on the pick dataset (type `exit` to stop and save); `train_act_dino.sh`: with the DINO encoder |
|                        | `upload_model.sh`        | Upload a trained checkpoint to the Hugging Face Hub           |
| `scripts/run/`         | `run_box_pipeline.sh`    | The box pipeline: DINO classifier, pick model, scripted moves, doors (`--dry-run` without the arm) |
|                        | `pipeline_recording.py`  | Records a pipeline run and makes its showcase video           |
|                        | `pipeline_support.py`    | Event log, Rerun display, pick-model stepping and frame source shared by the runner |
| `scripts/yolo/`        | `extract_frames.py`      | Take the first front-camera frame of every episode, pre-labelled by the current YOLO |
|                        | `label_studio.sh`        | Local Label Studio for checking and fixing YOLO labels        |
|                        | `extra_frames.py`        | More labelled frames per episode: the ones before the arm reaches the item |
|                        | `prepare_dataset.py`     | Build the YOLO train/val dataset from the labelled frames     |
|                        | `train.sh`               | Train the YOLO detector (runs the two scripts above first) |
| `scripts/tools/`       | `capture_poses.sh`       | Capture the arm's named poses with a live panel ([box-pipeline.md](box-pipeline.md#setting-it-up-in-the-box)) |
|                        | `show_poses.sh`          | Move the arm through the poses: walk, slideshow, go to one (`--dry-run` without the arm) |
|                        | `draw_poses.py`          | Draw the poses in the v3 box (`assets/poses_workspace.svg`) |
|                        | `contact_sheet.sh`       | One image per pick session with every record's crop, to check the items ([collection-plan.md](collection-plan.md)) |
|                        | `data_report.sh`         | Markdown snapshot of the data collected (records per object), to commit next to a model: `docs/reports/` |
|                        | `draw_objects.py`        | The object library's boxes on the setup photos, train green / test red ([objects/README.md](../objects/README.md)) |
|                        | `check_split.sh`         | Fail when a held-out test item is in the pick records, crops, YOLO frames or gallery |
|                        | `tune_cameras.sh`        | Lock camera exposure, gain and white balance to the current lighting |
|                        | `preview_augmentation.sh` | Show the training image augmentations on a recorded episode |
| `scripts/config/`      | `hardware.sh`, `datasets.sh` | Ports, cameras, video codec, display, motion limits; model names, tasks, Hub namespace |
|                        | `camera_settings.sh`     | Fixed camera settings written by `tune_cameras.sh`            |
| `scripts/common/`      | `lerobot_wide_fov.py`, `dataset_sync.py` | Helpers used by the scripts above   |
