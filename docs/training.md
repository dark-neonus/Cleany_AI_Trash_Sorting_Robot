# Training and sharing models

Part of the [Cleany README](../README.md).

## Training

```bash
scripts/train/train_act.sh plastic --steps=2000   # smoke test
scripts/train/train_act.sh plastic                # full run (100k steps)
```

Checkpoints go to `outputs/train/act_<model>_<timestamp>/checkpoints/`, every 5000 steps
(`SAVE_FREQ=2500` to save more often; each checkpoint is ~0.6 GB).

**To stop early, type `exit` and press Enter** in the training terminal: the step in progress
finishes, a checkpoint of exactly that step is saved (e.g. `checkpoints/054321`) and training
ends. Ctrl+C instead stops immediately and loses everything since the last checkpoint.

Every run starts from scratch in a new folder. To **continue** a stopped or finished run from
its last checkpoint (same folder, same settings, step counter continues):

```bash
scripts/train/train_act.sh plastic --resume                    # latest act_plastic_* run
scripts/train/train_act.sh plastic --resume outputs/train/act_plastic_20261020_1400
STEPS=150000 scripts/train/train_act.sh plastic --resume       # train longer than planned
```

**Image augmentation is on by default**, so the models learn the item's position and shape
rather than its colour (YOLO already decides the material). Each training frame gets 3 random
changes out of: brightness and contrast (±25%), saturation (0.5–1.5×), hue (±0.15, which really
changes object colours), sharpness, and grayscale (about 11% of frames). LeRobot's random image
shift/rotation is left out, because ACT needs exact pixel positions and our cameras are fixed.
The recorded dataset is not changed. The settings are in
[scripts/config/augmentation.json](../scripts/config/augmentation.json); to see each one on a
recorded episode (written to `outputs/augmentation_preview/`):

```bash
scripts/tools/preview_augmentation.sh plastic 49
```

To check that augmentation helps, train a second model without it and compare both on the real
robot with objects in colours that are not in the dataset:

```bash
AUGMENT=false JOB_NAME=act_plastic_noaug scripts/train/train_act.sh plastic
```

## Sharing trained models

Upload a checkpoint to a private model repo on the Hugging Face Hub, e.g. to run it on the
other laptop. Repos are named `cleany-ai/<setup>_act_<model>_<YYYYmmdd_HHMM>`, for example
`cleany-ai/setupv2_act_plastic_20261020_1432`:

- `<setup>` (`SETUP_NAME` in [scripts/config/datasets.sh](../scripts/config/datasets.sh), now
  `setupv2`): a model only works with the box, cameras, lighting and arm calibration it was
  trained with. Change it whenever the physical setup changes.
- the timestamp is when the checkpoint's last training step finished.

```bash
scripts/train/upload_model.sh plastic --dry-run                # show what would be uploaded
scripts/train/upload_model.sh plastic                          # last checkpoint of the latest run
scripts/train/upload_model.sh plastic outputs/train/act_plastic_20261020_1400 --checkpoint 50000
```

Only the model itself is uploaded (`pretrained_model/` plus a model card with the dataset,
step and settings), not the optimizer state, so an uploaded model can be run but not resumed.
Uploading the same checkpoint twice is refused. All uploaded models:
https://huggingface.co/cleany-ai (filter by `setupv2`).

Download one on another machine (or pass the repo id directly as `--policy.path`):

```bash
.venv/bin/hf download cleany-ai/setupv2_act_plastic_20261020_1432 --local-dir outputs/models/setupv2_act_plastic_20261020_1432
```
