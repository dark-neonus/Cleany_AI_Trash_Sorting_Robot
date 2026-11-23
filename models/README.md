# models/

Trained weights are **not** committed: they live on the Hugging Face Hub, and everything in
`models/` except this file is git-ignored (a local copy may sit here, it is never pushed).

## Why not commit the model file?

An ACT checkpoint is 200+ MB; every retrained version would stay in git history forever. The
Hub versions each model by commit, shows a model card, and LeRobot and Ultralytics load from
it directly.

## The models

| Name in `config/default.yaml` | Hub repo | What it is |
|---|---|---|
| `yolo` | [`cleany-ai/setupv2_yolo_20261020_2008`](https://huggingface.co/cleany-ai/setupv2_yolo_20261020_2008) | YOLO26n detector for the front camera: the box pipeline uses its boxes only. Trained on the old setup's frames, to be retrained on `data/pick/items/yolo` |
| `yolo_base` | [`cleany-ai/yolo_kaggle_garbage_20261016_2356`](https://huggingface.co/cleany-ai/yolo_kaggle_garbage_20261016_2356) | Kaggle-only YOLO, the starting point for YOLO training |
| pick model | (not trained yet) | `act_dino`, trained on `cleany-ai/cleany_pick`; passed as `GRASP_MODEL` |

Names are `<setup>_<model>_<YYYYmmdd_HHMM>`: a model only works with the physical setup it was
trained on (`setupv3` is the current box), and the timestamp is when its training finished.
The models of the old open-table setup (`setupv2_act_plastic_*`, `setupv2_act_metal_*`) stay on the Hub
but nothing in this repository uses them any more.

## How the code loads it

`config/default.yaml` names the model per role. `scripts/common/models.py <name>` returns a
repo id (ACT: LeRobot downloads `--policy.path=<repo id>` itself) or downloads a single file
(YOLO `best.pt`) into the Hugging Face cache and returns its path:

```bash
python scripts/common/models.py yolo          # -> ~/.cache/huggingface/hub/.../best.pt
```

Override a model for one run with the env vars of the script (`YOLO_MODEL`, `GRASP_MODEL` for
`scripts/run/run_box_pipeline.sh`, `BASE` for `scripts/yolo/train.sh`), or change it for everyone in
`config/default.yaml`.

## How to publish a model

- **ACT / act_dino**: `scripts/train/upload_model.sh pick` uploads the last checkpoint's
  `pretrained_model/` with a model card (details in [docs/training.md](../docs/training.md));
  then make the repo public on its Hub page.
- **YOLO**: upload `outputs/yolo/<job>/weights/best.pt` as `best.pt` to a new repo
  `cleany-ai/<setup>_yolo_<YYYYmmdd_HHMM>` with a model card (data, epochs, validation numbers).

Then point the role in `config/default.yaml` at the new repo.

## Model card checklist (on the Hub)

- Which dataset revision and setup it was trained on
- Training settings (steps or epochs, batch, augmentation)
- How it was evaluated and the numbers
- Known limitations
- Safety: run on the arm only with someone next to it
