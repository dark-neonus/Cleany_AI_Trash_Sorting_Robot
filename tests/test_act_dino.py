"""ACT with a DINO encoder (scripts/policies/lerobot_policy_act_dino) on a tiny random DINO: no
download, no GPU. Checks the patch grid, that only ACT's layers train, and a save/load round trip."""

import sys
from pathlib import Path

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "policies"))
pytest.importorskip("lerobot")
transformers = pytest.importorskip("transformers")

import lerobot_policy_act_dino  # noqa: E402,F401
from lerobot_policy_act_dino import modeling_act_dino  # noqa: E402
from lerobot_policy_act_dino.configuration_act_dino import ACTDinoConfig  # noqa: E402

from lerobot.configs import FeatureType, PolicyFeature, PreTrainedConfig  # noqa: E402
from lerobot.policies import get_policy_class  # noqa: E402

CAMERAS = ("observation.images.front", "observation.images.wrist")


def tiny_dino(patch_size: int):
    config = transformers.Dinov2WithRegistersConfig(hidden_size=32, num_hidden_layers=1, num_attention_heads=2,
                                                    intermediate_size=64, patch_size=patch_size, image_size=64,
                                                    num_register_tokens=4)
    return transformers.Dinov2WithRegistersModel(config)


@pytest.fixture
def fake_hub(monkeypatch):
    """load_dino without the Hub: 'missing/*' fails like a gated model, anything else is a tiny DINO."""
    loaded = []

    def load(name, fallback):
        used = fallback if name.startswith("missing/") else name
        if used is None:
            raise OSError("gated")
        loaded.append(used)
        return tiny_dino(14 if "dinov2" in used else 16), used

    monkeypatch.setattr(modeling_act_dino, "load_dino", load)
    return loaded


def make_config(**kwargs) -> ACTDinoConfig:
    config = ACTDinoConfig(device="cpu", dim_model=64, dim_feedforward=128, n_encoder_layers=1,
                           n_vae_encoder_layers=1, **kwargs)
    config.input_features = {"observation.state": PolicyFeature(FeatureType.STATE, (6,)),
                             **{c: PolicyFeature(FeatureType.VISUAL, (3, 480, 640)) for c in CAMERAS}}
    config.output_features = {"action": PolicyFeature(FeatureType.ACTION, (6,))}
    return config


def batch(n=2, chunk=45):
    return {"observation.state": torch.randn(n, 6), "action": torch.randn(n, chunk, 6),
            "action_is_pad": torch.zeros(n, chunk, dtype=torch.bool),
            **{c: torch.randn(n, 3, 480, 640) for c in CAMERAS}}


def test_registered_and_found_by_lerobot():
    assert "act_dino" in PreTrainedConfig.get_known_choices()
    assert get_policy_class("act_dino").__name__ == "ACTDinoPolicy"
    config = ACTDinoConfig()
    assert config.type == "act_dino"
    assert (config.chunk_size, config.n_action_steps, config.temporal_ensemble_coeff) == (45, 1, 0.01)


@pytest.mark.parametrize("backbone, grid", [("facebook/dinov3-vits16", (15, 20)),
                                            ("facebook/dinov2-with-registers-small", (17, 22))])
def test_patch_tokens_become_a_feature_map(fake_hub, backbone, grid):
    backbone = modeling_act_dino.DinoBackbone(tiny_dino(14 if "dinov2" in backbone else 16), 240, 320)
    out = backbone(torch.randn(2, 3, 480, 640))["feature_map"]
    assert out.shape == (2, 32, *grid)


def test_feature_map_is_the_patch_grid_in_row_order(fake_hub):
    backbone = modeling_act_dino.DinoBackbone(tiny_dino(16), 32, 48)
    images = torch.randn(1, 3, 32, 48)
    tokens = backbone.model(pixel_values=images).last_hidden_state
    feature_map = backbone(images)["feature_map"]
    assert torch.allclose(feature_map[0, :, 1, 2], tokens[0, -6 + 1 * 3 + 2])  # grid 2x3, cell (1, 2)


def test_only_act_layers_train_and_encoder_stays_frozen(fake_hub):
    policy = get_policy_class("act_dino")(make_config())
    encoder = policy.model.backbone.model
    trainable = {id(p) for p in policy.get_optim_params()}
    assert trainable and not any(id(p) in trainable for p in encoder.parameters())
    assert all(id(p) in trainable for p in policy.model.encoder_img_feat_input_proj.parameters())

    policy.train()
    assert not encoder.training  # no dropout in the frozen encoder while ACT trains
    loss, _ = policy.forward(batch())
    loss.backward()
    assert all(p.grad is None for p in encoder.parameters())
    assert policy.model.encoder_img_feat_input_proj.weight.grad is not None


def test_fallback_is_written_into_the_config(fake_hub):
    config = make_config(dino_backbone="missing/dinov3", dino_fallback_backbone="facebook/dinov2-with-registers-small")
    get_policy_class("act_dino")(config)
    assert (config.dino_backbone, config.dino_fallback_backbone) == ("facebook/dinov2-with-registers-small", None)


def test_save_load_round_trip_gives_the_same_actions(fake_hub, tmp_path):
    policy = get_policy_class("act_dino")(make_config(dino_backbone="facebook/dinov3-vits16")).eval()
    policy.save_pretrained(tmp_path)

    config = PreTrainedConfig.from_pretrained(tmp_path)
    assert config.type == "act_dino" and config.dino_fallback_backbone is None
    loaded = get_policy_class(config.type).from_pretrained(tmp_path, config=config).eval()
    obs = {k: v for k, v in batch(1).items() if not k.startswith("action")}
    with torch.no_grad():
        assert torch.allclose(policy.predict_action_chunk(obs), loaded.predict_action_chunk(obs), atol=1e-5)
    # the encoder's weights are in the checkpoint, not taken from the fresh one built at load
    a, b = policy.model.backbone.model, loaded.model.backbone.model
    assert all(torch.equal(x, y) for x, y in zip(a.state_dict().values(), b.state_dict().values()))
