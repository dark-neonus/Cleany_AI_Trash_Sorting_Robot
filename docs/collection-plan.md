# Pick dataset: collection plan

What to record, how much, from which items, and how to test without leakage. The tool and the
recorded features are in [pick-dataset.md](pick-dataset.md); this page is the strategy. Agreed on
2026-11-23. Numbers marked *start* are starting points, to revisit after the pilot.

## Items

From the photos [setup_v3_metal_cans.jpg](../assets/setup_v3_metal_cans.jpg) and
[setup_v3_plastic_bottles.jpg](../assets/setup_v3_plastic_bottles.jpg) (counts approximate):

| Class | What there is | Use |
| --- | --- | --- |
| metal | ~65 cans in ~28 designs: Hell ~25 (many black look-alikes), Monster ~9, Non Stop ~8, Red Bull ~6 (4–5 Peach), singles (Kvas Taras, Solidgate Lemonade, tall orange); 2+ already crushed | pick episodes |
| plastic | ~13 bottles: clear water bottles (green / blue / yellow caps), 2–3 Mojo, 1886, a large ridged one, a black sports bottle; loose caps | pick episodes |
| glass | 2 Полуниця-лайм, brown beer bottle, small sauce bottle | **Other** (classify, drop through) |
| generic | socks, tools, small toys, cables… from home | pick episodes, class `other` (grasp variety only) |

### Train / test split: by design

A held-out design is out of **everything**: no YOLO frames, no DINO gallery crops, no ACT
episodes. Keep the held-out items in a separate bag so they never reach the box during recording.

| | Held out (test) | ~count |
| --- | --- | --- |
| metal | Kvas Taras, Solidgate Lemonade, Red Bull Peach (all copies), Monster Ultra white, Non Stop Boost, Hell Peach-Lemon | ~12 cans |
| plastic | both Mojo bottles, 1886, one clear water bottle | ~4 bottles |

Every brand stays in training; the test looks are new.

### Copies

At most **2 copies per design** in training, preferring copies that differ (one dented or
crushed). Leftover copies are not recorded: they would only add the same look again.
Result: ~22 designs, ~40 cans in training.

### Plastic is scarce

~9 training bottles against ~40 cans. Collect more plastic over the coming weeks (aim 20+:
bottles of other shapes, crushed bottles, yogurt cups, food trays). Meanwhile, balance by
**episodes**, not items: more episodes per bottle, each in a different landing pose.

## How much

ACT takes no material input and the recorder lets go at `transit` whatever the class, so generic
objects add grasp variety without touching the bin logic.

| Phase | metal | plastic | generic | total | then |
| --- | --- | --- | --- | --- | --- |
| Pilot | 23 | 22 | 15 | **60** | train a quick ACT; fix recorder, pose or camera problems; retrain YOLO |
| Main | 90 | 90 | 60 | **240** | train; evaluate |

240 episodes of ~5 s is ~36 k frames at 30 fps.

**Per item** (*start*): metal 2–3 episodes per can; plastic 8–10 per bottle, each in a different
landing pose (lying along or across the tray, cap left or right, upright); generic 2–3 per object.
Spread each item over at least 2 sessions.

**Generic objects**: about 25 % of episodes, no more, so the policy doesn't drift towards shapes
that never reach the box. Prefer rigid and semi-rigid objects; no long cables (they tangle in the
doors).

**Retries**: a miss during an episode is not a reason to discard it: regrasp within the same
episode (the 20 s timeout allows it). On top, ~10 % of episodes (~24) start with a deliberate
near-miss so ACT learns to recover. Episodes that end without a grasp: discard (Backspace).

**Grasp style**: freestyle. If ACT later hesitates between two ways of grasping the same item,
a fixed grasp rule is the first thing to try.

**One item per cycle**, as in real use. No distractor episodes for now; several items at once
would need ACT to be told which item to take (a later model change).

## Process

- **Placement: mix.** After each episode the item falls back onto the tray at `transit`; every few
  episodes throw it in through the entry again for a natural landing pose, and place it by hand
  only to fill pose gaps (upright bottles, for example). Hands out before Metal / Plastic.
- **Light**: whatever the room gives for now (the enclosed box will fix it); brightness and
  colour augmentation at training time covers the rest, as on setup_v2.
- **Sessions**: no fixed length.
- **Glass, and anything not metal or plastic that is not a grasp object**: through **Other**, so
  the gallery learns to reject it.

### Item metadata: filled in after each session

No stickers, no registry to fill in by hand. During recording, type a short name in the panel if
you like (`hell black`, `water green cap`); it is a hint, not an ID. Never type the name of a
held-out item: the recorder refuses names of held-out items anyway. After each session the agent
(Claude) goes through the session's crops and records, recognises the items and writes
`config/items.yaml` (id, class, brand, design group, crushed or not, train or test) plus an item ID
per episode, and flags any held-out design found in the training data. The split itself is kept
at recording time by the separate bag.

From the second session on, `items.yaml` exists, and the panel can offer the item picker with
counts per item and per class against the targets above.

### YOLO and the DINO gallery

- One item at a time, so the YOLO label box is the change from the empty-tray photo (already in
  the recorder; glance at the orange box).
- After the pilot (~300 frames with the Other items), retrain YOLO as a one-class `item` detector
  and switch to it.
- Rebuild the DINO gallery after each phase from **training items only**.

## Evaluation

On the real arm, full pipeline, held-out items only: **20 cycles with the held-out cans** and
**20 with the held-out plastic** (5 per bottle). Per cycle, log: classification right or wrong,
grasp success, right bin, cycle time. Run it after the pilot (a quick check) and after the main
phase.

## Tools

| What | Where |
| --- | --- |
| **Pick other** (G): a pick episode for a generic object, class `generic`, released at `transit`; crops in `data/pick/items/crops/generic/`, outside the gallery. **Other** (O) stays classify-and-drop | recorder panel |
| Counts per class against `targets` (phase `pilot` or `main`) | [pick_recording.yaml](../config/pick_recording.yaml), panel |
| Item list with per-item counts, the least-recorded item per class, refusal of held-out items | [items.yaml](../config/items.yaml), panel |
| Contact sheet per session, to label from | `scripts/tools/contact_sheet.sh` |
| Labels: record time -> item | [item_labels.yaml](../config/item_labels.yaml) |
| Split check over records, crops, YOLO frames and the gallery | `scripts/tools/check_split.sh` |
| Gallery without held-out crops | `scripts/tools/build_gallery.sh --crops data/pick/items/crops` |

The held-out designs are already in `items.yaml`. Still to add: the held-out clear water bottle
(pick one).

Switch `targets.phase` to `main` after the pilot.
