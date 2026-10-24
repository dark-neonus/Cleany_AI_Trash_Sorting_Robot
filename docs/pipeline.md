# Sorting pipeline

Part of the [Cleany README](../README.md).

## Running the sorting pipeline

`scripts/run/run_pipeline.sh` puts the models together as in [Approach](../README.md#approach):
YOLO watches the front camera, and once it is sure about an item it runs the `metal` or
`plastic` ACT, waits until the arm is back in its start pose and looks again. It uses the
models from [Available models](running-models.md#available-models) (downloaded from the Hub on the first run).

Not in it yet: the ESP32 drop mechanism and the `other` class, since the box and the setup
are not final. Items that are neither metal nor plastic are simply not picked.

### Test without the arm

Check what YOLO sees and what the pipeline would do, with only the front camera plugged in:

```bash
scripts/run/run_pipeline.sh --recording false --dry-run --display
```

Rerun shows the front image with the detections (grey boxes: the bins, whose contents are
ignored); the terminal prints every decision, e.g. `locked cls=metal conf=0.91` and
`act_simulated cls=metal model=...`. Nothing moves: the ACT step only waits 3 s. A recorded
video or a photo works instead of the camera:

```bash
scripts/run/run_pipeline.sh --recording false --dry-run --source data/cleany_metal/videos/observation.images.front/chunk-000/file-000.mp4
```

### Run on the arm

1. Plug in the follower arm and both cameras (no leader arm needed).
2. Put the arm in its **rest pose**, the pose the recordings start and end in: the pipeline
   takes the pose it finds at start as "home", and every ACT run starts and ends there.
3. Put **one item** on the table (in the start zone of the recordings), with the bins in place.
4. Start it and stay next to the arm. Type `exit` + Enter (or Ctrl+C) to stop: the arm eases
   home, and with `--recording true` the video is made after that:

```bash
scripts/run/run_pipeline.sh --recording true --max-velocity 60 --display
```

When the arm has put the item away, put the next one. Every run is logged to
`logs/pipeline/<timestamp>.jsonl` (detections, which model ran, how each run ended).

**`--recording true|false` is required.** With `true` both cameras are recorded to
`recordings/pipeline_<YYYYmmdd_HHMMSS>/` and, once the run ends, `showcase.mp4` is made there:

- the front camera in 720p (960×720, its 4:3 kept), with the wrist camera in sync in the
  bottom-right corner (1/4 of the width);
- while YOLO decides: its boxes with class and confidence, and how long the class has held;
- top-right: `YOLO`, `Plastic ACT` or `Metal ACT`, whichever is in control.

The raw `front.avi`/`wrist.avi` (about 2.5 GB per hour together) stay next to it. To make the
video again, e.g. if it was interrupted: `python scripts/run/pipeline_recording.py recordings/pipeline_<timestamp>`.

| Option | Default | Effect |
| ------ | ------- | ------ |
| `--recording true\|false` | **required** | Record both cameras and make `showcase.mp4` at the end |
| `--dry-run` | off | No arm: front camera (or `--source <video\|image>`), YOLO and decisions only |
| `--display` | off | Show the front image, detections and state in Rerun |
| `--max-velocity DEG_S`, `--acceleration N`, `--max-step DEG` | 90, 40, 10 | Arm speed limits, as for `run_policy.sh` |
| `--conf X` | 0.5 | Minimum YOLO confidence for a detection to count |
| `--lock-seconds S` | 5 | Seconds the same class must win every frame before its ACT runs |
| `--episode-time S` | 40 | Longest ACT run; the arm then goes home anyway |
| `--home-tolerance-deg D` | 12 | How close to the start pose counts as "back home" |
| `--home-still-s S`, `--still-deg D` | 5, 3 | How long the arm must stay at home, moving less than D degrees, before YOLO looks again |
| `--max-attempts N` | 3 | Tries on the same item before it is skipped |
| `--ignore-region X0,Y0,X1,Y1` | the two bins | Area of the 640×480 front image to ignore (repeatable, `none` for no area). Set it again if the bins move |
| `--device cpu` | `cuda` if available | Run the models on the CPU |

Other models: `PLASTIC_MODEL=<repo or folder> METAL_MODEL=... YOLO_MODEL=<best.pt> scripts/run/run_pipeline.sh --recording false ...`
(defaults: [config/default.yaml](../config/default.yaml)).

### How it decides

1. **Detect.** YOLO runs on every front frame. Items whose centre is inside a bin are
   ignored, so sorted items are not picked again. A class is locked when it is the most
   confident detection (≥ `--conf`) in every frame for `--lock-seconds` (5 s); any other
   result in between starts the count again.
2. **Act.** The locked class's ACT drives the arm at 30 fps; YOLO is not consulted. The run
   ends when the arm has left the start pose (any joint more than 20° away), is back within
   `--home-tolerance-deg` and has stayed there without moving for 5 s (`--home-still-s`), or
   after `--episode-time` seconds. The ACT keeps running during those 5 s, so it can still
   try again.
3. **Home.** The arm is eased back to the exact start pose over 3 s, then YOLO takes over.
4. **Retry or skip.** If the same class shows up again at the same place, the item was not
   moved and the ACT tries again. After `--max-attempts` tries that class is skipped until
   it has been out of view for 3 s (e.g. you took the item away), so a stuck item does not
   keep the arm busy forever.
