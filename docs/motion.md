# Scripted arm motion

Every motion the scripts make themselves (go to a pose, the poses viewer, the recorder's hover / place / home,
the pipeline's moves and grasp plan, the leader aligning to the follower) is built in one place:
[box_logic.py](../scripts/common/box_logic.py) (`profile`, `ramped`, `trajectory`, `approach_waypoint`) and
[paced_move.py](../scripts/common/paced_move.py) (one command per tick, paced by how far the arm lags).
Teleoperation and the policy are not scripted moves and are not touched.

## Acceleration ramps (idea of 2026-11-23)

The arm twitched at the start and the end of moves. A move now speeds up linearly for `motion.ramp_s` (0.15 s in
[box_pipeline.yaml](../config/box_pipeline.yaml)), cruises at `motion.speed_deg_s`, and slows down linearly for
`ramp_s` before the end (a trapezoidal speed profile; constant acceleration). `ramp_s` missing: the old
minimum-jerk bell. A move's duration is distance / cruise speed + `ramp_s`; a move shorter than its two ramps is a
triangle. The pose viewer, the recorder and the pipeline all read `motion.ramp_s`.

**What was measured (follower, hover <-> home, 2026-11-23).** Position is read at about 30 Hz and the servo
quantises it, so peak acceleration and jerk computed from it are dominated by noise (about 1000 deg/s2 either way);
with ramps of 0.15 and 0.3 s the numbers moved by less than that noise (jerk 9.7k baseline, 9.4k and 9.0k).
Servo current and load along the plain hover -> home path are smooth (no surge near the end), and the command
leads the arm by a steady 4-6 degrees. So the ramps are in, are correct (tests), and are free, but a measured
smoothing could not be shown with this instrument; judge it on the arm.

## The twitch just before home

Seen by the user right before home is reached; thought to be parts in the way. What was tried, hover -> home, 3
repeats each, "roughness" = mean change of the observed speed of elbow / shoulder while elbow > 76 or shoulder < -84
(plain path: elbow 3.8-5.4, shoulder 3.4-3.9):

| Variant | Result |
| --- | --- |
| elbow first (shoulder held at -80 until the elbow folded) | elbow 2.4-3.9, shoulder 3.1: a little smoother |
| same with the shoulder held at -88 / -95 | no better than plain |
| shoulder first, then the elbow | worse (elbow 5-6) |
| wrist_flex 100 or 55 on the way | worse |
| elbow folded with the shoulder at -60 / -70 | the elbow is blocked (MoveError "not following") |
| home less folded by 2.4 / 3 or 5.4 / 6 degrees | no change |
| wrist_flex 88 at home | the elbow is blocked |

So the arm is blocked by something when the shoulder is raised and the elbow folds, and when the wrist is bent
back; the plain path stays clear. The option `motion.approach` (e.g. `home: {shoulder_lift: -80}`) is in
the code and tested but off: its gain is within the noise and it runs 10 degrees from a blocked pose.
Next measurement if the twitch is still seen: read the position at several hundred Hz (a thread on the bus) or film
it, to say which joint and at what angles, then change the home pose in `config/poses.yaml`
(scripts/tools/capture_poses.sh) or the path.

## Never drop the arm

A script that moves the arm must end at `home` before it disconnects: a disconnect switches the torque off and
the arm falls to its stop. If it cannot get home it leaves the torque on.
