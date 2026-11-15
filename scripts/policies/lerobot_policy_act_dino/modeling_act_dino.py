"""ACT whose camera features come from a frozen DINO ViT instead of ResNet-18.

ACT turns each camera image into a feature map B x C x H x W, projects C to dim_model with a 1x1
convolution and feeds every map cell to the transformer as one token, with a 2D sine position
embedding. DINO gives one token per 16x16 (DINOv3) or 14x14 (DINOv2) patch, so the patch tokens,
reshaped to their grid, are exactly such a map: only the backbone and the projection change.

The encoder is frozen (no gradients, always in eval mode); only ACT's own layers train. Its
weights are saved with the policy, so a checkpoint holds the encoder it was trained with.
"""

import warnings

import torch
import torch.nn.functional as F
from torch import nn

from lerobot.policies.act.modeling_act import ACT, ACTPolicy, ACTTemporalEnsembler
from lerobot.policies.pretrained import PreTrainedPolicy

from .configuration_act_dino import ACTDinoConfig


def load_dino(name: str, fallback: str | None) -> tuple[nn.Module, str]:
    from transformers import AutoModel

    try:
        return AutoModel.from_pretrained(name), name
    except OSError as error:  # gated (401/403), offline, or no such repo
        if not fallback:
            raise
        warnings.warn(f"Cannot load {name} ({str(error).splitlines()[0][:120]}). Using {fallback}. "
                      f"For DINOv3, accept its licence at https://huggingface.co/{name} "
                      f"and log in with `hf auth login`.", stacklevel=2)
        return AutoModel.from_pretrained(fallback), fallback


class DinoBackbone(nn.Module):
    """Normalised images (B, 3, H, W) -> {"feature_map": (B, hidden, rows, cols)} patch grid."""

    def __init__(self, model: nn.Module, height: int, width: int):
        super().__init__()
        self.model = model.requires_grad_(False).eval()
        patch = model.config.patch_size
        self.grid = (height // patch, width // patch)
        self.size = (self.grid[0] * patch, self.grid[1] * patch)
        self.out_channels = model.config.hidden_size

    def train(self, mode: bool = True):
        return super().train(False)  # frozen: no dropout or drop-path, also while ACT trains

    def forward(self, images: torch.Tensor) -> dict[str, torch.Tensor]:
        if tuple(images.shape[-2:]) != self.size:
            images = F.interpolate(images, size=self.size, mode="bilinear", align_corners=False, antialias=True)
        with torch.no_grad():
            tokens = self.model(pixel_values=images).last_hidden_state  # [CLS, registers..., patches]
        rows, cols = self.grid
        patches = tokens[:, -rows * cols:]  # patch tokens come last, row by row
        return {"feature_map": patches.transpose(1, 2).reshape(len(images), -1, rows, cols)}


class ACTDino(ACT):
    def __init__(self, config: ACTDinoConfig):
        super().__init__(config)  # builds an untrained ResNet-18 (no download), replaced below
        if not config.image_features:
            return
        model, used = load_dino(config.dino_backbone, config.dino_fallback_backbone)
        # The checkpoint must name the encoder it holds, so loading it never swaps in another one.
        config.dino_backbone, config.dino_fallback_backbone = used, None
        self.backbone = DinoBackbone(model, config.dino_height, config.dino_width)
        self.encoder_img_feat_input_proj = nn.Conv2d(self.backbone.out_channels, config.dim_model, kernel_size=1)


class ACTDinoPolicy(ACTPolicy):
    config_class = ACTDinoConfig
    name = "act_dino"

    def __init__(self, config: ACTDinoConfig, **kwargs):
        PreTrainedPolicy.__init__(self, config)  # ACTPolicy.__init__ would build the ResNet ACT
        config.validate_features()
        self.config = config
        self.model = ACTDino(config)
        if config.temporal_ensemble_coeff is not None:
            self.temporal_ensembler = ACTTemporalEnsembler(config.temporal_ensemble_coeff, config.chunk_size)
        self.reset()

    def get_optim_params(self) -> list:
        return [p for p in self.parameters() if p.requires_grad]  # the encoder is frozen
