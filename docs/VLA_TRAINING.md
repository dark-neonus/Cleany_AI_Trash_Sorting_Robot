# Training a VLA (SmolVLA) for trash sorting

Pipeline: teleoperate with the leader arm → record a LeRobot dataset → fine-tune
`lerobot/smolvla_base` → run the policy on the follower arm.

All scripts use the hardware config in `scripts/config/hardware.sh` and capture both
cameras at full FOV through `scripts/lerobot_wide_fov.py`.

## 1. Record the dataset

```bash
scripts/record_dataset.sh "Put the plastic bottle into the yellow bin" 10
scripts/record_dataset.sh "Put the paper into the blue bin" 10
```

Each run appends episodes to `data/cleany_trash_sorting`. The task text is the
language instruction the VLA is conditioned on, so use one consistent phrasing per
object/bin pair.

Keys while recording:

| Key | Action                                     |
| --- | ------------------------------------------ |
| →   | finish the current episode early           |
| ←   | discard and re-record the current episode  |
| Esc | stop recording and save                    |

Env overrides: `EPISODE_TIME_S` (default 30), `RESET_TIME_S` (10),
`DATASET_REPO_ID` (`local/cleany_trash_sorting`), `PUSH_TO_HUB` (`false`).

### What makes a good dataset

- **Amount:** at least 50 episodes per task, 200–300+ total for several trash types.
- **Variation:** change object position, orientation and the object itself (different
  bottles, cans, papers) every episode. Spread positions over the whole workspace.
- **Consistency:** same strategy every time: start from the same rest pose, grasp,
  move to the bin, release, return to rest. Avoid hesitations and corrections.
- **Cameras:** don't move the front camera or change the lighting between sessions.
  The policy will only work in conditions it has seen.
- **Failures:** press ← to re-record a botched episode instead of keeping it.

Inspect the result:

```bash
.venv/bin/lerobot-dataset-viz --repo-id local/cleany_trash_sorting \
  --root data/cleany_trash_sorting --episode-index 0
```

## 2. Train

```bash
scripts/train_smolvla.sh --steps=500        # smoke test first
scripts/train_smolvla.sh                    # full run, 20k steps
```

Checkpoints go to `outputs/train/<job>/checkpoints/`. The defaults (`BATCH_SIZE=4`,
AMP) target the local RTX 2050 with 4 GB of VRAM, which is tight and slow. For a real
run use a cloud GPU (Colab, RunPod, Lambda) with `BATCH_SIZE=64`: push the dataset to
the Hugging Face Hub (`PUSH_TO_HUB=true DATASET_REPO_ID=<hf_user>/cleany_trash_sorting`
while recording) and train there with the same script.

## 3. Run the policy

```bash
scripts/run_policy.sh outputs/train/<job>/checkpoints/last/pretrained_model \
  "Put the plastic bottle into the yellow bin" 60
```

Use exactly the same task text as during recording.

### Motion limits

LeRobot sets the servos to maximum acceleration, so the arm snaps to every target.
`run_policy.sh` limits the follower servos in hardware instead:

| Flag (env default)                         | Default | Meaning                                                |
| ------------------------------------------ | ------- | ------------------------------------------------------ |
| `--max-velocity` (`SERVO_MAX_VELOCITY_DEG`) | 90      | max joint speed, deg/s (demos peak ~110–120 deg/s p99) |
| `--acceleration` (`SERVO_ACCELERATION`)     | 40      | 0–254, units of 100 steps/s² (LeRobot default 254)     |
| `--max-step` (`MAX_STEP_DEG`)               | 10      | max joint change per control step, clips sudden jumps  |

```bash
scripts/run_policy.sh --max-velocity 60 --acceleration 20 <checkpoint> "<task>"
```

### Recording and replaying runs

Add `--record` to save camera video, joint states and actions as a LeRobot dataset:

```bash
scripts/run_policy.sh --record outputs/train/<job>/checkpoints/last/pretrained_model "<task>" 60
```

The run lands in `recordings/rollout_<job>_<step>_<YYYYmmdd_HHMMSS>/` with a
`rollout_info.json` (policy path, task, motion limits). Replay it on the arm, optionally
slower; motion limits default to the ones the run was recorded with:

```bash
scripts/replay_recording.sh --speed 0.5 recordings/rollout_<job>_<step>_<timestamp>
```
