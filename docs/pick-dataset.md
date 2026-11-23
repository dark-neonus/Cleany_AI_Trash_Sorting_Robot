# Pick dataset: what is recorded and what ACT trains on

Part of the [Cleany README](../README.md). The dataset for the box pipeline's pick model
([box-pipeline.md](box-pipeline.md#pick-model-act-with-a-dino-encoder)): hover pose to item lifted,
all materials. Agreed on 2026-11-20. Recorded with `scripts/dataset/record_pick.sh`: see
[How to record](#how-to-record).

## Decision

| | Recorded | Trained on |
| --- | --- | --- |
| Front and wrist camera | yes | yes |
| Joint positions (6), normalised | yes | yes |
| Velocity (6) | yes | no |
| Current (6) | yes | **gripper only** |
| Load (6) | yes | **gripper only** |
| Temperature (6) | yes | no |
| Voltage (6) | yes | no: explains current, which rises with supply voltage at the same load |
| Action: leader joint positions (6), normalised the same way | yes | yes (target) |

Everything is recorded so later runs can try more inputs without recording again. Training on all
of it is not planned.

- **Positions are normalised by each arm's own calibration range**, not given in degrees: body
  joints to [-1, 1], gripper to [0, 1]. This is LeRobot's `use_degrees=False` (-100…100 and
  0…100) divided by 100. The scale is then the same in every dataset (the mean/std that ACT
  computes per dataset is not), and the leader's "gripper closed" maps to the follower's even
  though their raw ranges differ (follower 2018–3514, leader 1568–2892 ticks). `wrist_roll` has no
  limits (0–4095), so its ±1 is a full turn. The box pipeline's poses and grasp-check thresholds
  are in degrees: convert at the boundary, keep the policy normalised.
- **Velocity is not trained on**: at 30 Hz it is almost the difference of consecutive positions,
  coarse at low speed, and it invites the "copycat" failure of imitation learning (the policy
  continues the current motion instead of looking at the images). The ACT paper uses positions only.
- **Gripper current and load are trained on**: they tell the policy it is squeezing something,
  which the cameras often cannot see under the fingers. They exist at inference too. Current and
  load of the other joints mostly reflect gravity, the item's weight, temperature and voltage.

## How to record

### Once, before the first session

1. **Poses**, with the box, cameras and arm in their final place (see
   [box-pipeline.md](box-pipeline.md#setting-it-up-in-the-box)):

   ```bash
   scripts/tools/capture_poses.sh
   ```

   The recorder needs the pipeline's poses: `home`, `hover`, `transit`, `metal_bin` and
   `plastic_bin` (what they are: [box-pipeline.md](box-pipeline.md#setting-it-up-in-the-box)).
   It uses the same poses as the pipeline, so every episode starts where the pipeline will start
   its grasp, and it lets go of the item at `transit`, above the tray.
2. **Tray region**: `trigger.tray_region` in [box_pipeline.yaml](../config/box_pipeline.yaml).
3. **Check the leader holds a pose under torque.** It runs on 5 V (the follower on 12 V). If it
   sags at hover or cannot hold, set `start.leader_hold: false` in
   [pick_recording.yaml](../config/pick_recording.yaml): it then goes limp at hover and you
   start with Space while holding it.

### A session

```bash
scripts/dataset/sync.sh pull pick        # the shared copy (skip for the first session)
scripts/dataset/record_pick.sh           # record; appends to data/cleany_pick
scripts/dataset/sync.sh push pick        # upload
```

The doors open and close once (keep hands out), both arms go home and the empty tray is
photographed. Then, per item:

1. **READY.** Put one item on the tray, name it in the **Item** field, press **Metal** (M),
   **Plastic** (P), **Pick other** (G) or **Other** (O). The name is a short hint (`hell black`);
   once [config/items.yaml](../config/items.yaml) has items, pick one from the list instead: it shows
   each item's episode count, and the panel names the least-recorded item per class. A held-out
   test item, or an item whose registered class is not the button's, is refused.
   **Pick other** is for generic objects (socks, toys, tools): a pick episode like metal and
   plastic, for grasp variety ([collection-plan.md](collection-plan.md#how-much)). The counts line
   shows the episodes against the targets of the current phase (`targets` in
   [pick_recording.yaml](../config/pick_recording.yaml)).
2. **CLASSIFY.** Hands off the tray. The panel shows the tray change (orange), the YOLO boxes
   (blue) and the target (green), and warns when DINO disagrees with your button or YOLO found
   nothing. A labelled YOLO frame and a gallery crop are saved.
   **Other** ends here: the doors drop the item, back to READY.
3. **HOVER, ARMED.** Both arms move to the hover pose by themselves: hands off. Then grab the
   leader and **push it**: the moment it moves 3°, its torque goes off and recording starts
   (or press **Space**). **Esc** cancels: back home, nothing recorded.
4. **RECORDING.** Lower, grasp, lift. It ends by itself once the item is lifted, with the box
   pipeline's own grasp check (fingers blocked by the item and arm back up 8°), or on **Space**,
   or after 20 s. The bar turns orange after 10 s: the pipeline gives the model 10 s to grasp,
   and a model copies the pace of its demos. **Backspace** throws the episode away.
5. **PLACE, HOME.** Let go of the leader: both arms carry the item to `transit`, high above the
   tray, open the gripper for 1 s so the item falls back onto the tray, and go home with the
   gripper closing on the way (as in the pipeline). The item lands near the spot below the
   gripper and may bounce or roll a little, so the next episode needs no hands, but it will not
   land in a fresh place every time: move or turn the item yourself every few episodes (see the
   recommendations). `release.where: bin` in the config carries it to its bin instead.
6. **READY again**, with the episode's length and how it ended. **Backspace** discards it (and
   its YOLO frame and crop) until you press the next Metal / Plastic / Other.

**Stop session** (or closing the window, or Ctrl+C) keeps the last finished episode, discards
one being recorded, and sends both arms home. The red **EMERGENCY STOP** releases both arms;
an episode being recorded is discarded; pressed again, the arms go home and you are back at
READY. Without the doors: `record_pick.sh --door none` (take Other items out by hand).

### The panel

Both cameras are shown live, side by side, from the cameras' own capture buffers, so they keep
running while the session waits for the doors or classifies. Each view has a badge with that
camera's real fps (green from 24, amber below, red NO SIGNAL after a second without a frame) and
its resolution; the front view also shows the session's boxes (tray region grey, YOLO blue, tray
change orange, target green). While recording, both views get a red frame and the episode time,
and a line under them shows the rate the dataset is actually recorded at (red below 90 % of the
30 fps target: frames are being lost). Keys **1 / 2 / 3** switch between both cameras, front only
and wrist only (bigger), **B** toggles the boxes, **S** (or the button) saves a screenshot of both
cameras to `recordings/screenshots/`. Leader servo error flags (overload) appear as the red warning.

**Leader gripper overload.** Grabbing the leader's handle squeezes its trigger against the gripper
goal the leader holds at hover, and the servo reports Overload when the torque is released. The leader's
gripper therefore holds with only `start.leader_gripper_torque` (40 %) of its force under script, and
that Overload flag is only noted in the log (`leader_note`). Any other servo flag shows as the red
warning. **Follower limited commands:** when the follower lags behind the leader (the fingers blocked
by the item at the grasp, or a fast move) lerobot limits the command to `--max-step`; they are counted
and reported once at the end of the session instead of printed for every command.

### What a session writes

| Where | What |
| --- | --- |
| `data/cleany_pick/` | the LeRobot dataset; the material is the episode's task |
| `data/pick_yolo/` | `images/`, `labels/` (YOLO format, classes in `classes.txt`: metal, plastic, other), `frames.jsonl` with every box found; one negative (empty tray) frame per session |
| `data/box_crops/<material>/<item>_<time>.jpg` | DINO gallery crops: `scripts/tools/build_gallery.sh --crops data/box_crops` |
| `data/box_crops/generic/` | Pick other crops: not a gallery class, so `build_gallery.sh` leaves them out |
| `data/pick_records.jsonl` | one line per kept episode or Other item: session, length, how it ended, DINO's opinion |
| `logs/pick/pick_<time>.jsonl` | every event |

**YOLO labels without a good YOLO.** With one item on the tray, the label box is the change from
the empty-tray photo (`label_from: tray_change`), whatever YOLO sees: the old-setup YOLO is only
a cross-check. Record the first sessions with **one item at a time**, retrain YOLO on
`data/pick_yolo` (as a one-class `item` detector is the plan), then several items are fine.

### After a session: label the items

```bash
scripts/tools/contact_sheet.sh     # data/contact_sheets/session_<stamp>_1.jpg + .yaml
scripts/tools/check_split.sh       # fails when a held-out item got into the training data
```

The agent (Claude) looks at the contact sheet, adds new items to
[config/items.yaml](../config/items.yaml) and writes each record's item into
[config/item_labels.yaml](../config/item_labels.yaml), then runs the split check.
`build_gallery.sh` skips held-out crops and groups labelled crops by item.

### Recommendations

The full strategy (items, train/test split, how many episodes, evaluation) is in
[collection-plan.md](collection-plan.md).

- **Balance the materials**: the panel counts metal / plastic / other.
- **Vary**: items, where the item lands, its orientation, a little lighting (as in
  [dataset-collection.md](dataset-collection.md#recommendations)).
- **Short, decisive grasps**: under 10 s. Discard hesitant ones.
- **Put glass, paper and cardboard through Other**: the gallery needs `other` examples
  (see [box-pipeline.md](box-pipeline.md#kaggle-check-of-the-classifier)).

### Not done yet

- **Running a pick model**: the box pipeline's `PolicyGrasper` still feeds a policy degrees and
  the 6-joint state. A model trained on this dataset needs the 8-value normalised state in and
  its actions turned back into degrees with the leader's calibration (`motor_state.Normaliser`).
  Until then `run_policy.sh` and `replay.sh` refuse the pick dataset.

## What the servos report

Feetech STS3215, firmware 3, read on both arms on 2026-11-20 (torque off, arms idle). Every
register is one `sync_read` of about 1 ms per arm; the live block `Present_Position` (address 56)
to `Present_Current` (address 69) is contiguous, so one 15-byte read gets them all.

| Register | Unit | Note |
| --- | --- | --- |
| `Present_Position` | ticks, 4096 per turn (0.088°) | |
| `Present_Velocity` | ticks/s, signed | |
| `Present_Load` | 0.1 % PWM duty, signed, ±1000 | capped by `Torque_Limit` (follower gripper 500) |
| `Present_Current` | about 6.5 mA per unit | follower `Protection_Current` 310, gripper 250 |
| `Present_Voltage` | 0.1 V | follower 12.0 V, leader 5.1 V |
| `Present_Temperature` | °C | 23–33 at rest |
| `Moving`, `Status` | flags; `Status` holds error bits | |

### Current and load are not the same thing

- **Current is measured**: a sense resistor in the motor's power path. Torque is roughly
  proportional to it, so it is the force really produced, friction included. Noisy, and it shifts
  with temperature and supply voltage.
- **Load is commanded, not measured**: the PWM duty the servo's controller drives the motor with,
  set from the position error (goal − measured) times the P gain (`P_Coefficient` 16 on the
  follower). It means "how hard the servo is trying".
- At a stall (fingers blocked on an item) the two rise together. While moving, back-EMF makes
  them differ: high load, modest current. Load is clean but mostly repeats the position error;
  current is the independent physical signal. That is why the gripper gets both.

## Still to check on the arm

- `Present_Velocity` with torque off (leader moved by hand): does it update?
- Current and load on the follower with torque on, gripper closing on an item: the real range,
  to fix their scale (proposed: load / 1000, current / `Protection_Current`).
  Enabling torque moves the follower to its stored `Goal_Position`: check it is near the present
  position first.
