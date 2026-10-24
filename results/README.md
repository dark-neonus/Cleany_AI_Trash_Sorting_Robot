# results/

Small, committed outputs that the README and slides quote. Do not edit the numbers by hand:
regenerate them.

| File | Made by |
|---|---|
| `metrics.json` | `python scripts/yolo/evaluate.py` (or `make reproduce`): YOLO metrics on the validation frames and the unseen test photo, plus the versions, OS and git commit they were produced with |
| `figures/yolo_confusion_matrix.png` | same run: confusion matrix of the selected YOLO on the validation frames |
| `figures/yolo_test_photo.jpg` | same run: detections of the old (Kaggle) and the current YOLO on the test photo |
| `experiments.md` | by hand: every model we trained, including the rejected ones, and why |

Not here yet: the success rate of the ACT models and of the whole pipeline on the arm (see
`experiments.md`). A demo video belongs in `results/demo/` (see [docs/recording-a-demo.md](../docs/recording-a-demo.md)).
