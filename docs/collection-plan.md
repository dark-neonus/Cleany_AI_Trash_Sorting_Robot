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
| glass | 2 Полуниця-лайм, brown beer bottle, small sauce bottle | class `other`: **Save other** or **Pick other** |
| other objects | socks, tools, small toys, cables, small boxes… from home | class `other`, pick episodes (grasp variety) |

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

ACT takes no material input and the recorder lets go at `transit` whatever the class, so `other`
objects add grasp variety without touching the bin logic.

| Phase | metal | plastic | other | total | then |
| --- | --- | --- | --- | --- | --- |
| Pilot | 23 | 22 | 15 | **60** | train a quick ACT; fix recorder, pose or camera problems; retrain YOLO |
| Main | 90 | 90 | 60 | **240** | train; evaluate |

240 episodes of ~5 s is ~36 k frames at 30 fps.

**Per item** (*start*): metal 2–3 episodes per can; plastic 8–10 per bottle, each in a different
landing pose (lying along or across the tray, cap left or right, upright); other 2–3 per object.
Spread each item over at least 2 sessions.

**Other objects**: about 25 % of episodes, no more, so the policy doesn't drift towards shapes
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
  colour augmentation at training time covers the rest, as on the old setup.
- **Sessions**: no fixed length.
- **Glass, and anything not metal or plastic that is not a grasp object**: through **Other**, so
  the gallery learns to reject it.

### Item metadata: the object library (since 2026-11-27)

Every object is an entry of [objects/](../objects/README.md): `objects/train/<id>/` (picture,
class, kind, name, N/3 records) or `objects/test/<id>/` (held out). The library was cut from the
two photos above ([cans](../assets/setup_v3_metal_cans_split.jpg),
[bottles](../assets/setup_v3_plastic_bottles_split.jpg): train green, test red). **Bottle caps are
objects of their own** (`c-…`), recorded apart from their bottles.

In the recorder the object is chosen by clicking its picture: required before every record, so
every record, crop and YOLO frame carries its id. A new object goes in with **Add new object**
(photographed on the tray). Test objects are added by hand, in the file system only. The split is
also kept physically, by the separate bag.

**Per object: 3 records** (`target` in its item.yaml; 2–3 pick episodes per object, changed from the
per-class numbers below on 2026-11-27).

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
| **Pick other** (G): a pick episode for an object that is neither metal nor plastic, released at `transit`. **Save other** (O): picture only, then the doors drop it. Both are class `other` (crops in `data/pick/items/crops/other/`, in the gallery) | recorder panel |
| Counts per class against `targets` (phase `pilot` or `main`) | [pick_recording.yaml](../config/pick_recording.yaml), panel |
| Object library with pictures and N/3 per object, required choice, Add new object | [objects/](../objects/README.md), panel |
| Boxes of the library on the setup photos | `python scripts/tools/draw_objects.py` |
| Report of what was collected, per model, with its results on the held-out objects | `scripts/tools/data_report.sh --name <model>`, committed in `docs/reports/` |
| Contact sheet per session, to check by eye | `scripts/tools/contact_sheet.sh` |
| Labels for records made before the library: record time -> object | [item_labels.yaml](../config/item_labels.yaml) |
| Split check over records, crops, YOLO frames and the gallery | `scripts/tools/check_split.sh` |
| Gallery without held-out crops | `scripts/tools/build_gallery.sh --crops data/pick/items/crops` |

The held-out designs are in [objects/test](../objects/README.md), with the held-out clear water bottle
(`p-water-yellow-cap`) and the caps of the held-out bottles.

Switch `targets.phase` to `main` after the pilot.
