import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "common"))
from items_sync import README, count_records, stage  # noqa: E402


def test_records_are_counted_by_their_lines(tmp_path):
    assert count_records(tmp_path / "records.jsonl") is None
    (tmp_path / "records.jsonl").write_text('{"a": 1}\n\n{"a": 2}\n')
    assert count_records(tmp_path / "records.jsonl") == 2


def test_the_registry_files_are_copied_next_to_the_data(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "items.yaml").write_text("items: []\n")
    stage(tmp_path / "items", [config / "items.yaml", config / "missing.yaml"])
    assert (tmp_path / "items" / "registry" / "items.yaml").read_text() == "items: []\n"
    assert not (tmp_path / "items" / "registry" / "missing.yaml").exists()


def test_the_card_names_its_companion():
    assert "cleany-ai/cleany_pick" in README.format(namespace="cleany-ai")


def test_the_object_library_is_copied_without_pictures_of_held_out_objects(tmp_path):
    lib = tmp_path / "objects"
    for split in ("train", "test"):
        (lib / split / "x").mkdir(parents=True)
        (lib / split / "x" / "item.yaml").write_text("id: x\n")
        (lib / split / "x" / "thumb.jpg").write_bytes(b"jpg")
    stage(tmp_path / "items", [lib])
    staged = tmp_path / "items" / "registry" / "objects"
    assert (staged / "train" / "x" / "thumb.jpg").exists() and (staged / "test" / "x" / "item.yaml").exists()
    assert not (staged / "test" / "x" / "thumb.jpg").exists()
