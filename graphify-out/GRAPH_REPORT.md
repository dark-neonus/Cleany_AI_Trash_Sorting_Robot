# Graph Report - Cleany_AI_Trash_Sorting_Robot  (2026-10-07)

## Corpus Check
- 8 files · ~2,742 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 1 file(s) not represented in the graph (top: (none) 1)

## Summary
- 35 nodes · 29 edges · 9 communities (4 shown, 5 thin omitted)
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `803941aa`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- calibrate_follower.sh
- ELECTRONICS.md
- calibrate_leader.sh
- Power Supply
- install_lerobot.sh
- Data Connections
- Power Demand
- run_teleop.sh
- README.md

## God Nodes (most connected - your core abstractions)
1. `Power Supply` - 6 edges
2. `Data Connections` - 5 edges
3. `Power Demand` - 5 edges
4. `Components` - 4 edges
5. `calibrate_follower.sh script` - 1 edges
6. `PATH` - 1 edges
7. `calibrate_leader.sh script` - 1 edges
8. `PATH` - 1 edges
9. `install_lerobot.sh script` - 1 edges
10. `PATH` - 1 edges

## Surprising Connections (you probably didn't know these)
- None detected - all connections are within the same source files.

## Import Cycles
- None detected.

## Communities (9 total, 5 thin omitted)

### Community 1 - "ELECTRONICS.md"
Cohesion: 0.40
Nodes (4): Components, LeRobot SO-101 (Follower Arm), Operational Box, Trash Drop Mechanism

### Community 3 - "Power Supply"
Cohesion: 0.33
Nodes (6): All Power Connections, LeRobot SO-101 (Follower Arm), Operational Box, Power Modules, Power Supply, Trash Drop Mechanism

### Community 5 - "Data Connections"
Cohesion: 0.40
Nodes (5): All Data Connections, Data Connections, LeRobot SO-101 (Follower Arm), Operational Box, Trash Drop Mechanism

### Community 6 - "Power Demand"
Cohesion: 0.40
Nodes (5): LeRobot SO-101 (Follower Arm), Operational Box, Power Demand, Summary per Rail, Trash Drop Mechanism

## Knowledge Gaps
- **25 isolated node(s):** `calibrate_follower.sh script`, `PATH`, `calibrate_leader.sh script`, `PATH`, `install_lerobot.sh script` (+20 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 26 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Power Supply` connect `Power Supply` to `ELECTRONICS.md`?**
  _High betweenness centrality (0.152) - this node is a cross-community bridge._
- **What connects `calibrate_follower.sh script`, `PATH`, `calibrate_leader.sh script` to the rest of the system?**
  _25 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Why does `Data Connections` connect `Data Connections` to `ELECTRONICS.md`?**
  _High betweenness centrality (0.125) - this node is a cross-community bridge._
- **Why does `Power Demand` connect `Power Demand` to `ELECTRONICS.md`?**
  _High betweenness centrality (0.125) - this node is a cross-community bridge._