from dataclasses import dataclass

from lerobot.configs import PreTrainedConfig
from lerobot.policies.act.configuration_act import ACTConfig


@PreTrainedConfig.register_subclass("act_dino")
@dataclass
class ACTDinoConfig(ACTConfig):
    """ACTConfig with the ResNet replaced by a frozen DINO ViT.

    Every other ACT setting works as before. Defaults that differ from ACT follow
    docs/pipeline-proposal.md for the short hover-to-lifted episodes:
      chunk_size 45 (1.5 s at 30 fps) instead of 100 (3.3 s, nearly the whole episode),
      temporal ensembling (coefficient 0.01, a new chunk every control step).
    Temporal ensembling and n_action_steps only matter at inference; they can be changed there.
    """

    # Hugging Face model id. DINOv3 is gated: accept its licence on the Hub and `hf auth login`.
    dino_backbone: str = "facebook/dinov3-vits16-pretrain-lvd1689m"
    # Used when dino_backbone cannot be loaded. Training stores the backbone it actually used in
    # dino_backbone and clears this, so a trained model never silently runs on another encoder.
    dino_fallback_backbone: str | None = "facebook/dinov2-with-registers-small"
    # Each camera image is resized to this before the encoder, rounded down to the patch size.
    # 240x320 with 16 px patches is a 15x20 grid: 300 tokens per camera, as many as ResNet-18 gives
    # on 480x640. The full 480x640 would be 1200 tokens per camera, too slow for the transformer.
    dino_height: int = 240
    dino_width: int = 320

    chunk_size: int = 45
    n_action_steps: int = 1
    temporal_ensemble_coeff: float | None = 0.01

    # The ResNet that ACT builds and this policy replaces: no weights to download.
    pretrained_backbone_weights: str | None = None

    def __post_init__(self):
        super().__post_init__()
        if self.dino_height < 16 or self.dino_width < 16:
            raise ValueError(f"dino_height/dino_width too small: {self.dino_height}x{self.dino_width}")
