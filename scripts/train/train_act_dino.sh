#!/usr/bin/env bash
set -e

# Train ACT with a frozen DINO image encoder instead of ResNet-18 (policy type act_dino,
# scripts/policies/lerobot_policy_act_dino). Same arguments, resume and `exit` as train_act.sh.
#
# Usage: scripts/train/train_act_dino.sh <plastic|metal> [--resume [run_dir]] [extra lerobot-train args...]
#   scripts/train/train_act_dino.sh metal --steps=2000                    # quick smoke test
#   scripts/train/train_act_dino.sh metal --policy.dino_backbone=facebook/dinov2-with-registers-small
#   scripts/train/train_act_dino.sh metal --policy.dino_height=480 --policy.dino_width=640   # 4x the tokens
#   POLICY=act_dino scripts/train/upload_model.sh metal                   # upload the latest run
#
# Defaults (docs/pipeline-proposal.md): DINOv3 ViT-S/16 (falls back to DINOv2 with registers if
# the gated model cannot be downloaded), images resized to 240x320 = 300 tokens per camera,
# chunk_size 45, temporal ensembling 0.01. Only ACT's own layers train; the encoder stays frozen.
# STEPS defaults to 50000 here: the hover-to-lifted dataset is about a quarter of the old one.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export POLICY=act_dino
# A resumed run keeps the step count it was started with unless STEPS is given.
if [ "$2" != "--resume" ]; then export STEPS="${STEPS:-50000}"; fi
exec "$SCRIPT_DIR/train_act.sh" "$@"
