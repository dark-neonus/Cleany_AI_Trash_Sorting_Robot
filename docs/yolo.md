# YOLO detector

Part of the [Cleany README](../README.md).

## YOLO detector

YOLO finds the items on the table in the front-camera image and says `metal` (class 0) or
`plastic` (class 1); the pipeline uses it to pick which ACT to run.

| | |
| --- | --- |
| Weights | Hub: [`cleany-ai/setupv2_yolo_20261020_2008`](https://huggingface.co/cleany-ai/setupv2_yolo_20261020_2008) (`best.pt`, 5 MB), `yolo` in [config/default.yaml](../config/default.yaml) |
| Data | the first frame of each `cleany_plastic` (60) and `cleany_metal` (40) episode, one item per frame, plus 60 frames of the same episodes before the arm reaches the item; every 5th episode is held out for validation |
| Validation (20 frames) | mAP50 0.995, mAP50-95 0.87 |
| Unseen photo (8 items, another camera) | all 8 found with the right class at confidence 0.25 |
| Limits | It has seen ~20 different items. New cans and bottles, especially crumpled transparent ones, may be missed or mixed up: record episodes with new items and retrain. |

### Use it

```python
from ultralytics import YOLO
from huggingface_hub import hf_hub_download

model = YOLO(hf_hub_download("cleany-ai/setupv2_yolo_20261020_2008", "best.pt"))
result = model.predict("frame.jpg", conf=0.25)[0]
for cls, conf, box in zip(result.boxes.cls, result.boxes.conf, result.boxes.xyxy):
    print(model.names[int(cls)], float(conf), box.tolist())
```

Run Python from `.venv` with `export YOLO_AUTOINSTALL=false` (`train.sh` sets it): otherwise
Ultralytics may install an OpenCV that breaks LeRobot's. `python scripts/common/models.py yolo`
prints the local path of the weights (downloading them on first use).

To measure a model: `python scripts/yolo/evaluate.py` (validation frames + the unseen test
photo, see [results/](../results/README.md); `make reproduce` runs it from a fresh download).

### Retrain it

The labelled frames live in `yolo/frames/` (not in git) and are shared as the private Hub
dataset [`cleany-ai/cleany_yolo_frames`](https://huggingface.co/datasets/cleany-ai/cleany_yolo_frames)
(images, YOLO labels, `boxes_first.json`, Label Studio tasks). On a machine without them, get
them first (needs `hf auth login` with a team account):

```bash
.venv/bin/hf download cleany-ai/cleany_yolo_frames --repo-type dataset --local-dir yolo/frames
```

The episode videos are needed too (`extra_frames.py` reads them):
`scripts/dataset/sync.sh pull all`. After adding or fixing labels, upload the frames again:
`.venv/bin/hf upload cleany-ai/cleany_yolo_frames yolo/frames . --repo-type dataset --exclude "*_last*"`.

```bash
scripts/yolo/train.sh                          # ~7 min on the RTX 2050; result in outputs/yolo/<job>/weights/best.pt
scripts/yolo/train.sh epochs=5                 # smoke test
```

`train.sh` fine-tunes the Kaggle-only YOLO (`yolo_base` in [config/default.yaml](../config/default.yaml)) for 150 epochs with strong colour
augmentation (hue ±0.1, saturation, brightness), so that the material and not the label colour
decides the class. Tried and found worse on the unseen photo: adding the Kaggle photos to the
training set, and the bigger `yolo26s` model (see [results/experiments.md](../results/experiments.md)).
To make a better model the default: compare it with `python scripts/yolo/evaluate.py --models
current=yolo new=outputs/yolo/<job>/weights/best.pt`, upload its `best.pt` to a new Hub repo
`cleany-ai/<setup>_yolo_<YYYYmmdd_HHMM>`, and point `yolo` in `config/default.yaml` at it.

**Adding newly recorded episodes:**

1. `.venv/bin/python scripts/yolo/extract_frames.py` takes the first frame of every episode
   that has no label yet, boxes the item with the current model and sets the class from the
   dataset name (`cleany_metal` → `metal`). Frames that already have labels are not touched.
2. Check the new boxes: `scripts/yolo/label_studio.sh`, open http://localhost:8080 (login
   and password are printed; the account is local) and import
   `yolo/frames/label_studio_new_tasks.json` with **Import**. Fix wrong or missing boxes;
   copy the corrected ones back into `yolo/frames/labels/<frame>.txt`
   (`<class> <cx> <cy> <w> <h>`, normalized to 0–1).
3. `scripts/yolo/train.sh`.
