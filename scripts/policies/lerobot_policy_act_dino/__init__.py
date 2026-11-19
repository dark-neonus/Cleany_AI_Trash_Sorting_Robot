"""ACT with a frozen DINO ViT as the image encoder (`--policy.type=act_dino`).

A LeRobot policy plugin: importing this package registers the `act_dino` config, and LeRobot
finds the policy and processors from it by naming convention (modeling_act_dino.ACTDinoPolicy,
processor_act_dino.make_act_dino_pre_post_processors). The project scripts import it themselves
(scripts/common/train_with_controls.py, scripts/run/sort_pipeline.Policy), so it does not need to
be pip-installed.

Why and how: docs/pipeline-proposal.md (Grasp model) and docs/box-pipeline.md (Pick model).
"""

from .configuration_act_dino import ACTDinoConfig

__all__ = ["ACTDinoConfig"]
