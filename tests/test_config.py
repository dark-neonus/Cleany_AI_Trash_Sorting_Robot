"""config/default.yaml names every model a script uses; no network needed for these checks."""

import pytest
import yaml

from models import CONFIG, model, resolve


def test_config_has_every_model_the_scripts_ask_for():
    models = yaml.safe_load(CONFIG.read_text())["models"]
    assert {"act_plastic", "act_metal", "yolo", "yolo_base"} <= set(models)


def test_act_models_are_repo_ids_and_yolo_models_are_files():
    models = yaml.safe_load(CONFIG.read_text())["models"]
    for name in ("act_plastic", "act_metal"):
        assert len(models[name].split("/")) == 2, f"{name} should be '<owner>/<repo>'"
    for name in ("yolo", "yolo_base"):
        assert models[name].endswith(".pt"), f"{name} should be '<owner>/<repo>/<file>.pt'"


def test_repo_ids_and_local_paths_are_returned_unchanged(tmp_path):
    assert resolve("cleany-ai/some_act_model") == "cleany-ai/some_act_model"
    weights = tmp_path / "best.pt"
    weights.write_bytes(b"")
    assert resolve(str(weights)) == str(weights)
    assert model("act_plastic").startswith("cleany-ai/")


def test_unknown_model_name_fails_clearly():
    with pytest.raises(KeyError, match="No model"):
        model("does_not_exist")
