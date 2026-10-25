# Running a trained model

Part of the [Cleany README](../README.md).

## Running a trained model

### Available models

| Model | Where | What it is |
| ----- | ----- | ---------- |
| ACT `plastic` | Hub: [`cleany-ai/setupv2_act_plastic_20261020_1926`](https://huggingface.co/cleany-ai/setupv2_act_plastic_20261020_1926) (public) | `setupv2`, trained on `cleany_plastic` (60 episodes), 100k steps, batch 8, colour augmentation |
| ACT `metal` | Hub: [`cleany-ai/setupv2_act_metal_20261021_1855`](https://huggingface.co/cleany-ai/setupv2_act_metal_20261021_1855) (public) | `setupv2`, trained on `cleany_metal` (80 episodes), 100k steps, batch 8, colour augmentation |
| YOLO metal/plastic | Hub: [`cleany-ai/setupv2_yolo_20261020_2008`](https://huggingface.co/cleany-ai/setupv2_yolo_20261020_2008) (public) | `setupv2` front camera, trained on our own frames; see [YOLO detector](yolo.md#yolo-detector) |
| YOLO, old | Hub: [`cleany-ai/yolo_kaggle_garbage_20261016_2356`](https://huggingface.co/cleany-ai/yolo_kaggle_garbage_20261016_2356) (public) | Kaggle photos only, does not work on our camera; kept as the starting point for training |

All models of the team: https://huggingface.co/cleany-ai. The scripts take the current ones from
[config/default.yaml](../config/default.yaml); weights are not stored in git (see [models/](../models/README.md)). Each ACT model only works with
the setup it was trained on (box, camera positions, lighting, arm calibration).

### Get a model from the cloud

A model on the Hub needs no download step: pass its repo id to `run_policy.sh` and it is
downloaded on the first run and cached in `~/.cache/huggingface/`. Public repos need no login;
private ones need `.venv/bin/hf auth login` with a team account (see
[One-time setup](cloud-storage.md#one-time-setup)).

To keep a copy in the project instead (e.g. to work offline):

```bash
.venv/bin/hf download cleany-ai/setupv2_act_plastic_20261020_1926 --local-dir outputs/models/setupv2_act_plastic_20261020_1926
```

The folder holds the weights (`model.safetensors`), the config and the input/output
normalization (`policy_*processor*`); all of them are needed. A model trained on this machine
is used straight from its checkpoint folder,
`outputs/train/<job>/checkpoints/<step>/pretrained_model`.

### Run it on the arm

1. Plug in the follower arm and both cameras (the leader arm is not needed). Check them with
   `pkill -x rerun; scripts/teleop/run_teleop.sh` if in doubt.
2. Put the arm in its start pose and **one item of the model's material** in the start zone.
   The ACT runs on its own, without YOLO, so it always tries to move the item to its bin.
3. Run the model, staying next to the arm (Ctrl+C stops it):

```bash
scripts/run/run_policy.sh --record false plastic cleany-ai/setupv2_act_plastic_20261020_1926   # from the Hub
scripts/run/run_policy.sh --record true plastic outputs/models/setupv2_act_plastic_20261020_1926   # downloaded copy, saved
scripts/run/run_policy.sh --record false plastic outputs/train/act_plastic_20261020_0133/checkpoints/050000/pretrained_model
scripts/run/run_policy.sh --record false --max-velocity 60 --duration 30 plastic cleany-ai/setupv2_act_plastic_20261020_1926   # slower, 30 s
```

The material argument picks the task text and must match the model's material.

**`--record true|false` is required, there is no default:** decide for every run whether to
save it. With `true`, the run (both camera videos, joint states and the model's actions) is
saved as a LeRobot dataset in `recordings/rollout_<material>_<model>_<YYYYmmdd_HHMMSS>/`
(not committed to git). The script prints the folder at the end; review the run with:

```bash
scripts/dataset/view.sh recordings/rollout_plastic_<model>_<timestamp>                # watch both cameras, no robot needed
scripts/dataset/replay.sh --speed 0.5 recordings/rollout_plastic_<model>_<timestamp>  # repeat the motion on the arm
```

Replays use the speed limits the run had. Recordings are never uploaded; long runs are split
into several episodes (`view.sh <dir> 1` shows the second one).

| Option | Default | Effect |
| ------ | ------- | ------ |
| `--record true\|false` | **required** | Save the run's camera videos, joint states and actions to `recordings/` |
| `--duration S` | 60 | Stop after S seconds; `0` runs until Ctrl+C |
| `--max-velocity DEG_S` | 90 | Max joint speed. Use 60 or less for the first runs of a new model |
| `--acceleration N` | 40 | Servo acceleration, 0–254 |
| `--max-step DEG` | 10 | Max joint change per control step |
| `--device cpu` | `cuda` if available | Run on the CPU, e.g. while a training run uses the GPU (4 GB is not enough for both) |

The cameras are shown in Rerun as during teleoperation (`DISPLAY_DATA=false` turns it off).
The speed limits are written to the servos' RAM when the arm connects, so they last until
the arm is power-cycled or another script connects with its own limits.
