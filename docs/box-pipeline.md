# Box pipeline

Part of the [Cleany README](../README.md). This is the final pipeline from the
[midterm](slides/midterm/midterm.tex) ("New pipeline") as worked out in
[pipeline-proposal.md](pipeline-proposal.md). The old two-ACT pipeline
([pipeline.md](pipeline.md)) stays as plan B.

Math does what is predictable and models do what is not. The models only do two things: say
what an item is, and grasp it. Everything else is minimum-jerk moves between named poses, the
ESP32 doors, and a state machine.

```mermaid
flowchart TD
    W[WAIT: background difference<br/>against the empty tray] -->|something changed| S{SETTLE<br/>still for 0.5 s?}
    S -->|timeout 8 s| D
    S -->|yes| C[CLASSIFY: YOLO boxes,<br/>DINO material per item]
    C -->|metal or plastic item| H[HOVER]
    C -->|only other / unknown| D[DROP: doors open and close]
    C -->|tray empty| W
    H --> G[GRASP: pick model or scripted]
    G -->|check holds| M[CARRY: transit, then the bin]
    G -->|timeout, tries left| H
    G -->|3 tries| B
    M -->|slipped| B
    M --> R[RELEASE] --> B[HOME] --> S
    D --> S
```

## What is implemented

| Part | Where | State |
| --- | --- | --- |
| State machine, door sequencing, emergency stop handling | [box_states.py](../scripts/run/box_states.py) | Done, tested with a simulated arm, camera and door |
| Background trigger, settle gate, grasp check, moves, target choice | [box_logic.py](../scripts/common/box_logic.py) | Done, unit-tested |
| DINO classifier (metal / plastic / other) | [dino_classifier.py](../scripts/common/dino_classifier.py) | Done; thresholds **uncalibrated** |
| Runner (arm, cameras, ESP32, Rerun, showcase video) | [box_pipeline.py](../scripts/run/box_pipeline.py), [run_box_pipeline.sh](../scripts/run/run_box_pipeline.sh) | Dry run checked on recorded videos; **not yet run on the arm** |
| Pose capture | [capture_poses.sh](../scripts/tools/capture_poses.sh), [pose_catalog.py](../scripts/common/pose_catalog.py) | Done; poses captured on 2026-11-22 (check them with `capture_poses.sh --list`) |
| Gallery build and held-out evaluation | [build_gallery.sh](../scripts/tools/build_gallery.sh) | Done; only old-setup crops so far |
| Pick model (hover to lifted) | `grasp.model` in [box_pipeline.yaml](../config/box_pipeline.yaml) | **Not trained**: needs the hover-start dataset recorded in the box |
| ACT with a frozen DINO encoder (`act_dino`) | [lerobot_policy_act_dino](../scripts/policies/lerobot_policy_act_dino/), [train_act_dino.sh](../scripts/train/train_act_dino.sh) | Done, tested; trains and runs on the old datasets, **no trained model yet** |

Not in it yet (later steps of the proposal): the target image as a third camera, several
items with distractor demos, the one-class YOLO, and the target item's DINO embedding as
`observation.environment_state` (ACT already takes it; the recording tool has to write it).

## Setting it up in the box

1. **Poses.** With the arm, cameras and box in their final place:

   ```bash
   scripts/tools/capture_poses.sh          # a panel; the follower follows the leader arm
   scripts/tools/capture_poses.sh --hand   # or: torque off, move the follower by hand
   scripts/tools/capture_poses.sh --list   # what is captured, what looks wrong (no arm needed)
   ```

   The panel lists the poses in the order of a cycle, says for the selected one where the arm has
   to be and how to check it, and draws the arm live from above and from the side over the box,
   with the poses captured so far marked. "Right now" tells while you move whether the fingertips
   are over the tray or the bin and whether the gripper points down. Press Enter when the arm
   is in place and still: the pose is stored at once, checked against the others (a bin on the
   wrong side, two poses that are the same, a hover that is not above the tray), and the panel
   moves on. `hover` also saves `outputs/poses/hover_wrist.jpg`: all four tray corners must be
   visible in it. The pipeline refuses to move the arm while a pose is missing.

   | Pose | Where the fingertips are | Used for |
   | --- | --- | --- |
   | `home` | folded over the base, gripper **closed** | start and end of every cycle; the doors only open here |
   | `hover` | over the middle of the tray, gripper down, wrist camera sees the whole tray | the pick model starts its grasp here |
   | `transit` | high above the middle of the tray, higher than every wall | every carry passes here; the pick recorder lets go of the item here |
   | `metal_bin` | above the metal bin (left) | the item is released here |
   | `plastic_bin` | above the plastic bin (right) | the item is released here |
   | `tray_low` | *optional:* just above the tray floor | only the scripted grasp test below |

   ![The poses in the v3 box](../assets/poses_workspace.png)

   The figure is made from `config/poses.yaml` by `python scripts/tools/draw_poses.py --png`
   (run it again after capturing). The arm is exact (forward kinematics of the SO-101, from
   [arm_kinematics.py](../scripts/common/arm_kinematics.py)); the tray and bins are approximate,
   scaled from the v3 photo (measurements go in [workspace_layout.py](../scripts/common/workspace_layout.py)).
   A `poses.yaml` with the old names (`centre`, `grasp`, `tray_release`) is read as the new ones;
   `capture_poses.sh --migrate` rewrites it and keeps the old file as `poses.yaml.bak`.
   **Looking at the poses on the arm.** [show_poses.sh](../scripts/tools/show_poses.sh) moves the
   follower between them, the way the pipeline does (minimum-jerk moves at 60 deg/s that slow down
   smoothly if the arm cannot follow, only along routes the pipeline takes, the bins through
   `transit`; the arm must start at a captured pose, normally home; the red stop window ends
   everything; Ctrl+C or the end sends it home). It waits for the arm to settle on each pose and
   prints how close it got:

   ```bash
   scripts/tools/show_poses.sh walk                 # every pose in order, 1 s at each (--delay), then home
   scripts/tools/show_poses.sh slideshow            # Enter: next pose, b: back, q: quit
   scripts/tools/show_poses.sh go hover             # one pose, held; type another name or Enter to finish
   scripts/tools/show_poses.sh walk --dry-run       # no arm: the route and the timing
   ```

   Walking through them is also the first real test of the moves the pipeline makes, in
   particular each bin straight to `home`. Run it with the box empty and a hand near the stop.
   **How fast the arm can be moved by a script.** Measured on the follower (2026-11-22): with
   lerobot's `--max-step 10` limit it tracks only about 48 deg/s, while a plan of 45 deg/s
   *mean* peaks at about 85 deg/s, so the commanded goal runs ahead (after a second the elbow
   was 33 deg behind) and lerobot prints a "had to be clamped" warning per command. Two things
   to know:

   - **Do not hold the command until the arm catches up.** A goal that stops and starts makes
     the arm shake. [pose_show.py](../scripts/common/pose_show.py) instead slows the whole plan
     down *continuously* as the arm lags, so the goal never stops, and waits for the arm to settle
     on each pose. It runs smoothly at `--speed 60 --max-velocity 120 --max-step 20`. If it
     shakes again, lower `--acceleration` (try 20) or `--speed`.
   - **The pipeline and the pick recorder use it too**
     ([paced_move.py](../scripts/common/paced_move.py), called from `BoxPipeline.move_to`): a move
     slows down smoothly while the arm lags the plan and ends when the arm has settled, so the
     next state never starts while the arm is still on its way. The scripted grasp is paced the
     same way. The limit is 80 % of `--max-step`. The pipeline keeps its slower defaults
     (`--max-step 10`, velocity limit 90): try `--max-step 20 --max-velocity 120` as the viewer
     does if it should move faster. The pick model's own actions are not paced (the model decides).

2. **Tray region.** Set `trigger.tray_region` in [box_pipeline.yaml](../config/box_pipeline.yaml)
   to the tray in the 640×480 front image, so the bins and walls are not watched.
3. **Gallery.** Take front-camera crops of the items in the box, as
   `data/pick/items/crops/<metal|plastic|other>/<item>_<n>.jpg` (several per item, items named so the
   evaluation can hold out whole items), then:

   ```bash
   scripts/tools/build_gallery.sh --crops data/pick/items/crops
   ```

   It prints, per `max_distance`, how many held-out crops land in the right bin, the wrong bin,
   or `other`. Set `classifier.max_distance` (and `min_margin`) from that table.
4. **DINOv3.** The default backbone is gated on the Hub. Accept its licence at
   [facebook/dinov3-vits16-pretrain-lvd1689m](https://huggingface.co/facebook/dinov3-vits16-pretrain-lvd1689m)
   and run `hf auth login`. Until then DINOv2 with registers (same size) is used, with a warning.
   Rebuild the gallery after switching: a gallery only works with the backbone it was built with.

## Running

```bash
# No arm: simulated arm and door, the front camera or a recorded video
scripts/run/run_box_pipeline.sh --recording false --dry-run --display
scripts/run/run_box_pipeline.sh --recording false --dry-run --source data/cleany_metal/videos/observation.images.front/chunk-000/file-000.mp4

# On the arm with a scripted grasp (the optional `tray_low` pose): tests everything but the model
scripts/run/run_box_pipeline.sh --recording true --display

# On the arm with the pick model
GRASP_MODEL=cleany-ai/<pick model> scripts/run/run_box_pipeline.sh --recording true --grasp policy --display
```

The tray must be empty at start: the empty-tray reference is taken once the doors report
`CLOSED` and the arm is home. Opening the ESP32's port can reset it, which runs one door cycle
first. Stop with `exit` + Enter or Ctrl+C: the arm goes home first. The red emergency stop
button releases the torque; pressed again, the arm stays where it was put, then goes home and
the pipeline continues. Without the drop mechanism use `--door none`: items that cannot be
sorted then wait until you take them out.

Every event goes to `logs/pipeline/box_<timestamp>.jsonl`: triggers, every item with its class,
DINO distances and the reason (`unlike anything known`, `metal vs plastic too close`), grasp
results, slips, drops. With `--recording true`, `showcase.mp4` shows the state top right.

## How it decides

- **Trigger.** Share of tray pixels that differ from the empty reference (after a 4×4 blur)
  above `occupied_fraction`, or any YOLO box. Independent of what the item is.
- **Classify.** YOLO only gives boxes (any class, conf ≥ 0.25). Boxes from `classify_frames`
  settled frames are grouped by overlap; each item's crops are embedded and averaged, then
  compared with the gallery: mean distance to the k nearest crops per class. Metal or plastic
  only when it is the closest class, nearer than `max_distance`, and clearly nearer than the
  other (`min_margin`); otherwise `other`. A wrong bin is worse than the mixed bin.
  `classifier.type: yolo` uses YOLO's own class instead (plan B).
- **Target.** The sortable item with the most free space around it; items overlapping another
  box, or that failed 3 times, are left to the doors.
- **Grasp check.** Both for 0.3 s: the measured gripper stays over 4° above the commanded one
  (fingers blocked by the item), and the lift joint has come back 8° from its lowest point of
  the attempt (lifted). Timeout 10 s: the gripper opens over the tray and it counts as a try.
- **Carry.** The gripper is commanded 3° past where it closed on the item, not fully closed, so
  the servo does not stall. Closing 6° further means the item slipped: home, re-detect.
- **Moves.** Minimum-jerk profile, duration from the largest joint distance at
  `speed_deg_s` (mean), at least `min_move_s`.
- **Stale reference.** If the tray still looks occupied after 2 drops in a row, the reference is
  retaken (the doors just emptied the tray), so a light change cannot make it drop forever.

## Pick model: ACT with a DINO encoder

`act_dino` is ACT with the ResNet-18 replaced by a frozen DINO ViT, by default the same DINOv3
ViT-S/16 as the classifier. ACT turns each camera image into a feature map and feeds every cell
to its transformer as one token; DINO's patch tokens, put back on their grid, are such a map. So
only the backbone and the 1×1 projection change ([modeling_act_dino.py](../scripts/policies/lerobot_policy_act_dino/modeling_act_dino.py)).

- **Frozen**: no gradients, always in eval mode. Only ACT's layers train (40 M parameters, as with
  ResNet). The encoder's weights are saved in the checkpoint (about 240 MB in all).
- **Images resized to 240×320**: a 15×20 patch grid, 300 tokens per camera, as many as ResNet-18 on
  480×640. `--policy.dino_height/width` changes it.
- **Defaults for the short hover-to-lifted episodes**: `chunk_size` 45, temporal ensembling 0.01.
- **Backbone fallback**: if DINOv3 cannot be downloaded, DINOv2 with registers is used and written
  into the saved config, so the model never runs on a different encoder than it was trained with.
- **Normalisation**: ImageNet mean/std, LeRobot's default (`dataset.use_imagenet_stats`).
- Our scripts import the plugin themselves (training, `run_policy.sh`, the box pipeline); plain
  `lerobot-*` commands do not know `act_dino`.

```bash
scripts/train/train_act_dino.sh metal --steps=2000          # smoke test
scripts/train/train_act_dino.sh metal                       # 50k steps
scripts/train/train_act_dino.sh metal --resume              # continue; `exit` + Enter stops
POLICY=act_dino scripts/train/upload_model.sh metal
```

Measured on the RTX 2050 (2026-11-15, old `cleany_metal` dataset, 2 cameras):

| | ACT ResNet-18 | ACT DINOv3 |
| --- | --- | --- |
| Training, batch 8 | | 0.8 s per step, 2.5 GB GPU memory |
| One forward pass (both cameras) | 42 ms | 39 ms (DINO 12 ms per camera) |

Neither fits 33 ms, so with temporal ensembling (a forward pass every control step) the pick runs
at about 25 Hz instead of 30, slightly slower than the demonstrations. If that matters on the arm,
set `"temporal_ensemble_coeff": null` and `"n_action_steps": 10` in the model's `config.json`:
these only change inference, not the trained weights.

The dataset names are still per material (`metal`, `plastic`); the hover-start pick dataset for
all materials does not exist yet. What it will record and train on: [pick-dataset.md](pick-dataset.md).

## Old-setup check of the classifier

`scripts/tools/build_gallery.sh` on the 160 labelled frames of the old setup (each episode held
out in turn):

| max_distance | DINOv3 ViT-S/16: correct / wrong bin / other | DINOv2 ViT-S + registers: correct / wrong bin / other |
| --- | --- | --- |
| 0.30 | 82.5 % / 0.0 % / 17.5 % | 76.9 % / 0.0 % / 23.1 % |
| 0.35 | 93.8 % / 0.6 % / 5.6 % | 87.5 % / 0.0 % / 12.5 % |
| 0.40 | 95.0 % / 0.6 % / 4.4 % | 94.4 % / 0.0 % / 5.6 % |
| 0.50 | 97.5 % / 1.2 % / 1.2 % | 96.9 % / 1.2 % / 1.9 % |

These numbers are **optimistic**: the same cans appear in several episodes, and there are no
`other` items. They only show that the classifier works; the thresholds have to come from crops
taken in the box.

## Kaggle check of the classifier

[`scripts/tools/eval_classifier.py`](../scripts/tools/eval_classifier.py) on the Kaggle
[Garbage Classification](https://www.kaggle.com/datasets/mostafaabla/garbage-classification)
dataset (12 classes; all 769 metal and 865 plastic photos, 150 of each of the other 10 classes as
unknown items), DINOv3 ViT-S/16, `k=5`, `min_margin=0.03`. Run on 2026-11-14.

**1. Our gallery (160 old-setup crops) against Kaggle photos.** Nothing transfers: at
`max_distance` 0.35 every metal and plastic photo goes to `other`; at 0.6, 29 % reach the right
bin and 4 % the wrong one. Unknown items do stay out (100 % up to 0.4). A gallery only works for
the camera and scene it was taken with, so the box gallery must come from the box camera.

**2. In-domain: a gallery of half the Kaggle metal and plastic photos, tested on the other
half and all unknown classes** (every photo is a different item, so this is the real
open-set test):

| max_distance | Right bin | Wrong bin | Sortable sent to other | Unknown kept out | Worst unknown classes |
| --- | --- | --- | --- | --- | --- |
| 0.40 | 76.5 % | 0.7 % | 22.8 % | 95.2 % | white glass 79 %, green glass 81 % |
| 0.50 | 91.6 % | 0.9 % | 7.6 % | 84.3 % | white glass 48 %, green glass 51 %, brown glass 62 % |
| 0.60 | 95.7 % | 1.0 % | 3.3 % | 65.4 % | green glass 20 %, white glass 25 % |

**3. Same, plus 20 photos of each unknown class in the gallery as `other`:**

| max_distance | Right bin | Wrong bin | Sortable sent to other | Unknown kept out | Worst unknown classes |
| --- | --- | --- | --- | --- | --- |
| 0.40 | 76.1 % | 0.7 % | 23.1 % | 98.9 % | white glass 92 % |
| 0.50 | 91.2 % | 0.9 % | 8.0 % | 95.2 % | white glass 78 %, green glass 90 % |
| 0.60 | 95.2 % | 1.0 % | 3.8 % | 92.7 % | white glass 75 %, paper 86 % |

What this means for the box:

- **Metal against plastic is easy for DINOv3**: about 1 % wrong bin at every threshold.
- **Glass is the unknown that looks most like a known class** (clear bottles look like plastic
  ones). With no `other` examples, a threshold that sorts 90 % of recyclables lets half the
  glass into a bin.
- **A few `other` examples fix most of it**: 20 per kind cuts the unknowns that get into a
  bin from 16 % to 5 % at 0.5 (from 35 % to 7 % at 0.6), without costing recyclables. Put glass bottles, paper and cardboard into
  `data/pick/items/crops/other/` when building the box gallery.
- **The threshold is a trade-off to choose on box crops**: around 0.5 on these photos, but the
  scale depends on the camera, so measure it again on the box gallery.

Reproduce (the dataset is about 240 MB):

```bash
uv run --no-project --with kagglehub python -c "import kagglehub; print(kagglehub.dataset_download('mostafaabla/garbage-classification'))"
python scripts/tools/eval_classifier.py --test <that path>/garbage_classification                      # 1
python scripts/tools/eval_classifier.py --test <that path>/garbage_classification --in-domain          # 2
python scripts/tools/eval_classifier.py --test <that path>/garbage_classification --in-domain --other-examples 20   # 3
```
