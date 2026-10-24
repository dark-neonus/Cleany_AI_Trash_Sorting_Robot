# Dataset collection

Part of the [Cleany README](../README.md).

## Dataset collection

One dataset per ACT model, picked by the model name (`plastic` or `metal`):

| Model     | Local folder           | Hub repo                   | Task                                     |
| --------- | ---------------------- | -------------------------- | ---------------------------------------- |
| `plastic` | `data/cleany_plastic/` | `cleany-ai/cleany_plastic` | Put the plastic item into the right hole |
| `metal`   | `data/cleany_metal/`   | `cleany-ai/cleany_metal`   | Put the metal item into the left hole    |

**Once per machine:** run `scripts/setup/install_dependencies.sh`, then `.venv/bin/hf auth login`
(see [One-time setup](cloud-storage.md#one-time-setup)). The arm calibration in `calibration/` is shared via git.

### Record

```bash
pkill -x rerun; scripts/teleop/run_teleop.sh   # 1. check arm and both cameras, Ctrl+C to stop
scripts/dataset/sync.sh pull plastic           # 2. get the shared copy (skip for the first recording)
scripts/dataset/record.sh plastic 10           # 3. record 10 episodes (appends to the dataset)
scripts/dataset/sync.sh push plastic           # 4. upload
```

A **control panel** window opens next to Rerun. It shows the phase, the episode number and a
countdown, and nothing is recorded until you press **Start**:

1. **READY** (not recorded, no time limit): arm at the start position, item in the start zone.
   Press **Start episode**.
2. **RECORDING** (30 s countdown): grasp the item, drop it into its bin, return to the start
   position. Press **End episode** as soon as the arm is back, or let the countdown finish.
3. **RESET** (not recorded, no time limit): put the next item in place, then **Start episode**
   for the next one, or **Discard last episode** if the one you just recorded went wrong.

| Button         | Key (terminal focused) | Effect                                             |
| -------------- | ---------------------- | -------------------------------------------------- |
| Start episode  | **→**                  | Start recording the next episode                   |
| End episode    | **→**                  | End the current episode now                        |
| Discard        | **←**                  | Drop the current (or just recorded) episode, redo it |
| Stop session   | **Esc**                | Stop; episodes recorded so far are kept            |

Options: `record.sh --push plastic 10` uploads at the end; `EPISODE_TIME_S=20` changes the
episode length; `DISPLAY_DATA=false` turns the viewer off; `RECORD_PANEL=false` disables the
panel (plain LeRobot behaviour: episodes start automatically after a `RESET_TIME_S` reset).

### Review and manage

```bash
scripts/dataset/view.sh plastic 9                          # watch episode 9 (counted from 0), no robot needed
scripts/dataset/replay.sh --speed 0.5 --episode 9 plastic  # play it back on the real arm
scripts/dataset/delete_last_episode.sh plastic             # drop the last episode
scripts/dataset/sync.sh status                             # episode counts, local vs Hub
```

To see the start positions of all episodes at once (to spot positions that are missing or
over-represented), make one image per dataset from the first top-camera frame of every episode,
labelled with the episode index:

```bash
scripts/tools/start_frames.sh            # both datasets -> outputs/start_frames/plastic.jpg, metal.jpg
scripts/tools/start_frames.sh metal      # just one
```

To delete other episodes, e.g. 3 and 7, then swap the result in:

```bash
.venv/bin/lerobot-edit-dataset --repo_id=cleany-ai/cleany_plastic --root=data/cleany_plastic \
  --new_root=data/cleany_plastic.edited --operation.type=delete_episodes --operation.episode_indices="[3, 7]"
mv data/cleany_plastic data/cleany_plastic.old && mv data/cleany_plastic.edited data/cleany_plastic
```

After deleting episodes, upload with `scripts/dataset/sync.sh push plastic --force` (the Hub
copy has more episodes, so a normal push refuses).

### Recommendations

- **Same start and end pose** in every episode: the position the pipeline returns the arm to.
- **Vary the items**: different objects, landing spots and orientations in the start zone.
- **Keep the cameras fixed**: never move them between sessions; a moved camera makes earlier
  episodes much less useful. Re-run `scripts/tools/tune_cameras.sh` only when the final
  lighting or a camera changes for good.
- **Vary the lighting a little**: for about a quarter of the episodes, move a lamp or switch the
  room light, with the box light always on. This makes the models robust to light changes.
- **Smooth, decisive moves**: hesitations are copied by the model; re-record (**←**) messy ones.
- **Review before pushing**: watch a few episodes with `view.sh`, drop bad ones.
- **Amount**: 50+ good episodes per model before the first serious training run.
- **One person per model at a time**: pull before recording, push right after (see [Team rules](cloud-storage.md#team-rules)).
