# models/

Trained weights are **not** committed: they live on the Hugging Face Hub, and everything in
`models/` except this file is git-ignored (a local copy may sit here, it is never pushed).

## Why not commit the model file?

An ACT checkpoint is 200 MB; every retrained version would stay in git history forever. The
Hub versions each model by commit, shows a model card, and LeRobot and Ultralytics load from
it directly.

## The current models

| Name in `config/default.yaml` | Hub repo | What it is |
|---|---|---|
| `act_plastic` | [`cleany-ai/setupv2_act_plastic_20261020_1926`](https://huggingface.co/cleany-ai/setupv2_act_plastic_20261020_1926) | ACT policy: puts a plastic item into the right bin |
| `act_metal` | [`cleany-ai/setupv2_act_metal_20261021_1855`](https://huggingface.co/cleany-ai/setupv2_act_metal_20261021_1855) | ACT policy: puts a metal item into the left bin |
| `yolo` | [`cleany-ai/setupv2_yolo_20261020_2008`](https://huggingface.co/cleany-ai/setupv2_yolo_20261020_2008) | YOLO26n metal/plastic detector for the front camera |
| `yolo_base` | [`cleany-ai/yolo_kaggle_garbage_20261016_2356`](https://huggingface.co/cleany-ai/yolo_kaggle_garbage_20261016_2356) | Kaggle-only YOLO, the starting point for YOLO training |

All are public. Names are `<setup>_<model>_<YYYYmmdd_HHMM>`: a model only works with the
physical setup it was trained on, and the timestamp is when its training finished.

## How the code loads it

`config/default.yaml` names the model per role. `scripts/common/models.py <name>` returns a
repo id (ACT: LeRobot downloads `--policy.path=<repo id>` itself) or downloads a single file
(YOLO `best.pt`) into the Hugging Face cache and returns its path:

```bash
python scripts/common/models.py yolo          # -> ~/.cache/huggingface/hub/.../best.pt
```

Override a model for one run with the env vars of the script (`PLASTIC_MODEL`, `METAL_MODEL`,
`YOLO_MODEL` for `scripts/run/run_pipeline.sh`, `BASE` for `scripts/yolo/train.sh`), or change
it for everyone in `config/default.yaml`.

## How to publish a model

- **ACT**: `scripts/train/upload_model.sh <plastic|metal>` uploads the last checkpoint's
  `pretrained_model/` with a model card (details in [docs/training.md](../docs/training.md));
  then make the repo public on its Hub page.
- **YOLO**: upload `outputs/yolo/<job>/weights/best.pt` as `best.pt` to a new repo
  `cleany-ai/<setup>_yolo_<YYYYmmdd_HHMM>` with a model card (data, epochs, validation and
  test-photo numbers from `scripts/yolo/evaluate.py`).

Then point the role in `config/default.yaml` at the new repo and update
[results/](../results/README.md).

## Model card checklist (on the Hub)

- Which dataset revision and setup it was trained on
- Training settings (steps or epochs, batch, augmentation)
- How it was evaluated and the numbers (`results/metrics.json`)
- Known limitations (only ~20 items seen, one item at a time, one room)
- Safety: run on the arm only with someone next to it
