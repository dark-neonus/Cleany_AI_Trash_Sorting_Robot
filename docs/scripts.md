# Scripts

Part of the [Cleany README](../README.md).

## Scripts

All scripts can be run from any directory; they `cd` to the project root themselves.

| Folder                 | Script                   | What it does                                                  |
| ---------------------- | ------------------------ | ------------------------------------------------------------- |
| `scripts/setup/`       | `install_dependencies.sh` | Install system packages, LeRobot and YOLO (Ultralytics) into `.venv` |
| `scripts/calibration/` | `calibrate_leader.sh`, `calibrate_follower.sh` | Calibrate the arms into `calibration/`  |
| `scripts/teleop/`      | `run_teleop.sh`          | Drive the follower with the leader arm, cameras shown in Rerun |
| `scripts/dataset/`     | `record.sh`              | Record teleoperated episodes for one ACT model                |
|                        | `view.sh`                | Browse a recorded episode in Rerun (no robot needed)          |
|                        | `replay.sh`              | Replay a recorded episode on the follower arm                 |
|                        | `delete_last_episode.sh` | Drop the last episode (e.g. a failed demo)                    |
|                        | `sync.sh`                | Push/pull datasets to/from the Hugging Face Hub               |
| `scripts/train/`       | `train_act.sh`           | Train the ACT model of one material (type `exit` to stop and save) |
|                        | `upload_model.sh`        | Upload a trained checkpoint to the Hugging Face Hub           |
| `scripts/run/`         | `run_policy.sh`          | Run a trained ACT model (Hub repo or local folder) on the follower arm |
|                        | `run_pipeline.sh`        | Sorting pipeline: YOLO picks the material, its ACT moves the item (`--dry-run` without the arm) |
|                        | `pipeline_recording.py`  | Records a pipeline run and makes its showcase video           |
|                        | `sort_pipeline.py`       | The pipeline's state machine, started by `run_pipeline.sh`    |
| `scripts/yolo/`        | `extract_frames.py`      | Take the first front-camera frame of every episode, pre-labelled by the current YOLO |
|                        | `label_studio.sh`        | Local Label Studio for checking and fixing YOLO labels        |
|                        | `extra_frames.py`        | More labelled frames per episode: the ones before the arm reaches the item |
|                        | `prepare_dataset.py`     | Build the YOLO train/val dataset from the labelled frames     |
|                        | `train.sh`               | Train the metal/plastic YOLO (runs the two scripts above first) |
| `scripts/tools/`       | `tune_cameras.sh`        | Lock camera exposure, gain and white balance to the current lighting |
|                        | `preview_augmentation.sh` | Show the training image augmentations on a recorded episode |
|                        | `start_frames.sh`        | One image with the first top-camera frame of every episode    |
| `scripts/config/`      | `hardware.sh`, `datasets.sh` | Ports, cameras, video codec, display, motion limits; model names, tasks, Hub namespace |
|                        | `camera_settings.sh`     | Fixed camera settings written by `tune_cameras.sh`            |
| `scripts/common/`      | `lerobot_wide_fov.py`, `dataset_sync.py` | Helpers used by the scripts above   |
