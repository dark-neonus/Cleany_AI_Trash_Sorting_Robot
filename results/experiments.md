# Experiment log

## YOLO: which material is on the table

**Data.** The first front-camera frame of each of the 100 episodes (60 plastic, 40 metal at
the time), one item each, boxed by hand and tightened with SAM 2.1, every box checked by eye.
Validation: every 5th episode (20 frames, 8 metal / 12 plastic). Because the same cans and
bottles appear in training and validation episodes, validation is easy (mAP50 saturates at
0.995), so every model was also scored on an **unseen test photo**: 8 items (4 cans, bottle
handle, cap, toy, crumpled bottle) taken with a phone on another table. Numbers below: mAP50-95
on validation and on the test photo, and the test photo at confidence 0.25 (what the pipeline
sees). Reproduce the first and the selected row with `python scripts/yolo/evaluate.py`.

| Run | Change | Val mAP50-95 | Test mAP50-95 | Test photo at conf 0.25 |
|---|---|---|---|---|
| Baseline: Kaggle-only YOLO26n | trained on Kaggle *Garbage Classification* photos only | 0.002 | 0.188 | 0 of 8 found |
| A | fine-tune the Kaggle model on our 80 training frames, 150 epochs, strong hue/saturation/brightness augmentation | 0.861 | 0.729 | 7 of 8 right; crumpled bottle called `metal` |
| **B — selected** | A + up to 4 more frames per training episode, taken before the arm reaches the item (same box, arm in view) | **0.870** | 0.721 | **8 of 8 right**, no extra boxes |
| C — rejected | B + the 1 307 Kaggle photos in training (60 epochs) | 0.869 | 0.653 | 2 plastic items missed |
| D — rejected | B with the bigger YOLO26s, from COCO weights | 0.858 | 0.655 | 2 extra wrong `metal` boxes |

**Decision: B.** Its box accuracy equals A's within noise (one test photo, 8 boxes), but it is
the only run that gets every item right at the pipeline's working threshold. The frames with
the arm in view are what helped; the Kaggle photos (studio shots, side views) pulled the model
away from our camera, and the bigger model overfits ~140 images.

**Caveat.** The test set is one photo. It shows the model transfers to a new camera and
table, not how often it is right on new items; the next step is labelling frames with items
that are in no training episode.

## ACT: moving the item

One ACT policy per material, LeRobot 0.6.1 defaults (chunk 100, ResNet-18 backbone), both
cameras, batch 8, 100 000 steps, image augmentation on (brightness, contrast, saturation, hue
±0.15, sharpness, 11 % grayscale; no shifts or rotations, since the cameras are fixed). About
18 h each on an RTX 2050 (4 GB).

| Model | Dataset | Epochs | Result |
|---|---|---|---|
| `setupv2_act_plastic_20261020_1926` | `cleany_plastic`, 60 episodes | ~22 | **9/10** into the right bin on the arm |
| `setupv2_act_metal_20261021_1855` | `cleany_metal`, 80 episodes | ~19 | **8/10** into the right bin on the arm |

Earlier, before the current setup: a SmolVLA policy (20 000 steps) trained on 31 episodes of
a single can on an empty table did move the can on the arm, but that dataset did not match the
sorting task and the model was dropped.

On-arm test: the current pipeline, one item in the start zone, 10 trials per model; success =
the item ends in the right bin. 10 trials gives a wide error bar (8/10 is anything from ~50 % to
~95 % at 95 % confidence), so the next runs use 20+ trials and items that are in no episode.

**Next (new pipeline, being finalised):** one "pick" model trained on all 140 episodes cut at the
grasp, scripted placing into the bin, grasp check from the gripper servo; ACT vs Diffusion Policy
as the pick model, YOLO vs YOLO + DINOv3 crop features for the material.
