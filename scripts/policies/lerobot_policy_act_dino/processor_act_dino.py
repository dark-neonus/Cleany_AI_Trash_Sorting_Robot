from lerobot.policies.act.processor_act import make_act_pre_post_processors

from .configuration_act_dino import ACTDinoConfig


def make_act_dino_pre_post_processors(config: ACTDinoConfig, dataset_stats=None):
    """Same as ACT. Images are normalised with ImageNet mean/std (lerobot-train's default
    dataset.use_imagenet_stats=true), which is what DINO expects."""
    return make_act_pre_post_processors(config, dataset_stats)
