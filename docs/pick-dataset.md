# Pick dataset: what is recorded and what ACT trains on

Part of the [Cleany README](../README.md). The dataset for the box pipeline's pick model
([box-pipeline.md](box-pipeline.md#pick-model-act-with-a-dino-encoder)): hover pose to item lifted,
all materials. Agreed on 2026-11-20; nothing of it is implemented yet.

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
