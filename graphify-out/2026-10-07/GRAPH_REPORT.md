# Graph Report - Cleany_AI_Trash_Sorting_Robot  (2026-10-06)

## Corpus Check
- Corpus is ~2,349 words - fits in a single context window. You may not need a graph.

## Summary
- 31 nodes · 42 edges · 5 communities (4 shown, 1 thin omitted)
- Extraction: 83% EXTRACTED · 17% INFERRED · 0% AMBIGUOUS · INFERRED: 7 edges (avg confidence: 0.75)
- Token cost: 46,407 input · 0 output

## Community Hubs (Navigation)
- Follower Arm Servo Bus
- Trash Drop Mechanism
- Leader Arm Teleop
- Cameras and USB Hub
- LeRobot Installation

## God Nodes (most connected - your core abstractions)
1. `USB Hub Dynamode BYL-2218TU` - 8 edges
2. `Electronics Documentation` - 5 edges
3. `LeRobot SO-101 Follower Arm` - 5 edges
4. `Feetech STS3215-C001 12V Servo (x6)` - 4 edges
5. `Feetech FE-URT-2 Bus Adapter (CH343P)` - 4 edges
6. `Operational Box` - 4 edges
7. `RDS3115 7.2V Servo (x4)` - 4 edges
8. `Power Demand Budget per Rail` - 4 edges
9. `Wrist Camera (AIT SEMIC UVC)` - 3 edges
10. `Ambient Camera (Logitech C270)` - 3 edges

## Surprising Connections (you probably didn't know these)
- `Cleany AI Trash Sorting Robot` --conceptually_related_to--> `Electronics Documentation`  [INFERRED]
  README.md → electronics/ELECTRONICS.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **USB hub data topology to Host PC** — electronics_electronics_usb_hub, electronics_electronics_fe_urt_2, electronics_electronics_wrist_camera, electronics_electronics_ambient_camera, electronics_electronics_esp32_s3_super_mini, electronics_electronics_leader_arm_control_board, electronics_electronics_host_pc [EXTRACTED 1.00]
- **Cleany robot hardware subsystems** — electronics_electronics_so101_follower_arm, electronics_electronics_operational_box, electronics_electronics_trash_drop_mechanism [EXTRACTED 1.00]

## Communities (5 total, 1 thin omitted)

### Community 0 - "Follower Arm Servo Bus"
Cohesion: 0.25
Nodes (7): 12V Power Supply Rail, Feetech FE-URT-2 Bus Adapter (CH343P), Light Source (2x LED Lamp LN-12-6--50-4 12V), LeRobot SO-101 Follower Arm, Feetech STS3215-C001 12V Servo (x6), PATH, calibrate_follower.sh script

### Community 1 - "Trash Drop Mechanism"
Cohesion: 0.38
Nodes (6): Electronics Documentation, ESP32-S3 Super Mini Servo Controller, RDS3115 7.2V Servo (x4), TBD 5-7.2V Servo Supply, Trash Drop Mechanism, Cleany AI Trash Sorting Robot

### Community 2 - "Leader Arm Teleop"
Cohesion: 0.29
Nodes (5): Leader Arm Control Board, PATH, calibrate_leader.sh script, PATH, run_teleop.sh script

### Community 3 - "Cameras and USB Hub"
Cohesion: 0.60
Nodes (5): Ambient Camera (Logitech C270), Host PC, Operational Box, USB Hub Dynamode BYL-2218TU, Wrist Camera (AIT SEMIC UVC)

## Knowledge Gaps
- **10 isolated node(s):** `calibrate_follower.sh script`, `PATH`, `calibrate_leader.sh script`, `PATH`, `install_lerobot.sh script` (+5 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 10 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `USB Hub Dynamode BYL-2218TU` connect `Cameras and USB Hub` to `Follower Arm Servo Bus`, `Trash Drop Mechanism`, `Leader Arm Teleop`?**
  _High betweenness centrality (0.333) - this node is a cross-community bridge._
- **What connects `calibrate_follower.sh script`, `PATH`, `calibrate_leader.sh script` to the rest of the system?**
  _10 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Why does `LeRobot SO-101 Follower Arm` connect `Follower Arm Servo Bus` to `Trash Drop Mechanism`, `Cameras and USB Hub`?**
  _High betweenness centrality (0.231) - this node is a cross-community bridge._
- **Why does `Leader Arm Control Board` connect `Leader Arm Teleop` to `Cameras and USB Hub`?**
  _High betweenness centrality (0.201) - this node is a cross-community bridge._