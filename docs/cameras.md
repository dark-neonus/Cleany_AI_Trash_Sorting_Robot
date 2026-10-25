# Cameras and recording performance

Part of the [Cleany README](../README.md).

## Cameras and recording performance

Both laptops must capture images that look the same and arrive with the same delay, or a
model trained on data from one laptop behaves differently on the other. The scripts handle
this automatically:

- **Fixed camera settings.** Auto exposure and auto white balance change with the light, so
  images (and frame timing) differ between sessions. `scripts/tools/tune_cameras.sh` finds
  manual settings that match what auto mode picks under the current lighting and saves them to
  `scripts/config/camera_settings.sh`; every script applies them before opening the cameras.
  **Re-run it whenever the lighting or a camera position changes, and commit the file.**
  Without the file, the cameras run in auto mode.
- **30 fps in dim light.** Dynamic frame rate is off and mains is set to 50 Hz on both cameras
  (the front C270 otherwise dropped to ~12 fps).
- **Video encoding on the GPU.** Datasets are encoded with `h264_nvenc` (~3 ms of CPU per
  frame) instead of LeRobot's default CPU AV1 encoder (~100 ms of CPU per frame, enough to
  saturate a weak CPU and delay the cameras). `record.sh` test-encodes first and stops if
  NVENC does not work. Keep `VIDEO_CODEC` the same for the whole team: episodes from both
  laptops end up in the same video files.
- **Display options.** To turn the Rerun viewer off completely (saves CPU on a weak laptop):
  `DISPLAY_DATA=false scripts/dataset/record.sh plastic 10`. If the viewer shows no new data,
  close stale viewers first with `pkill -x rerun`: LeRobot reuses a viewer that is already
  running instead of starting a new one.
