"""Material of an item crop from a frozen DINO encoder: metal, plastic or other.

No training: the encoder turns a crop into an embedding, and the crop is compared with a stored
gallery of labelled crops (scripts/tools/build_gallery.sh). Unknown items are the ones far from
everything known, so the open-ended `other` class needs no examples (examples help, though: a
gallery may also hold `other` crops).

Decision rule (cost-aware: a wrong item in a bin contaminates it, a recyclable in the mixed bin
only loses one item):

    d_c    = mean cosine distance to the k nearest gallery crops of class c
    best   = the class with the smallest d_c
    metal or plastic only if best is one of them, d_best < max_distance and the runner-up
    class is at least min_margin farther; otherwise other.

Softmax confidence is not used for rejection: it stays high on unknown inputs.

The backbone is a config entry. DINOv3 is gated on the Hugging Face Hub (accept its licence on
the model page while logged in); if it cannot be downloaded, the fallback (DINOv2 with
registers, same size) is used and a warning says so. A gallery only works with the backbone it
was built with, which is stored in it.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from box_logic import SORTABLE


class Embedder:
    """Frozen DINO ViT: RGB crops -> L2-normalised CLS embeddings."""

    def __init__(self, backbone: str, fallback: str | None = None, device: str = "cpu"):
        import torch
        from transformers import AutoImageProcessor, AutoModel

        self.torch = torch
        self.device = device
        try:
            self.processor = AutoImageProcessor.from_pretrained(backbone)
            self.model = AutoModel.from_pretrained(backbone)
            self.backbone = backbone
        except OSError as error:  # gated (401/403), offline, or no such repo
            if not fallback:
                raise
            warnings.warn(f"Cannot load {backbone} ({str(error).splitlines()[0][:120]}). Using {fallback}. "
                          f"For DINOv3, accept its licence at https://huggingface.co/{backbone} "
                          f"and log in with `hf auth login`.", stacklevel=2)
            self.processor = AutoImageProcessor.from_pretrained(fallback)
            self.model = AutoModel.from_pretrained(fallback)
            self.backbone = fallback
        self.model = self.model.to(device).eval()

    def __call__(self, crops_rgb: list[np.ndarray], batch_size: int = 32) -> np.ndarray:
        if not crops_rgb:
            return np.zeros((0, self.model.config.hidden_size), dtype=np.float32)
        out = []
        with self.torch.inference_mode():
            for i in range(0, len(crops_rgb), batch_size):
                inputs = self.processor(images=list(crops_rgb[i:i + batch_size]), return_tensors="pt").to(self.device)
                outputs = self.model(**inputs)
                cls = outputs.pooler_output if getattr(outputs, "pooler_output", None) is not None \
                    else outputs.last_hidden_state[:, 0]
                out.append(cls.float().cpu().numpy())
        return normalise(np.concatenate(out))


def normalise(x: np.ndarray) -> np.ndarray:
    return x / np.maximum(np.linalg.norm(x, axis=-1, keepdims=True), 1e-8)


@dataclass
class Gallery:
    embeddings: np.ndarray  # (N, D), L2-normalised
    labels: np.ndarray  # (N,) class names
    groups: np.ndarray  # (N,) where each crop came from (episode or item), for held-out evaluation
    backbone: str

    def save(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, embeddings=self.embeddings, labels=self.labels, groups=self.groups,
                            backbone=np.array(self.backbone))

    @classmethod
    def load(cls, path: Path) -> "Gallery":
        data = np.load(Path(path), allow_pickle=False)
        return cls(data["embeddings"], data["labels"], data["groups"], str(data["backbone"]))

    def subset(self, mask: np.ndarray) -> "Gallery":
        return Gallery(self.embeddings[mask], self.labels[mask], self.groups[mask], self.backbone)


@dataclass
class Decision:
    cls: str
    distances: dict[str, float]
    reason: str


def decide(embedding: np.ndarray, gallery: Gallery, k: int, max_distance: float, min_margin: float) -> Decision:
    """The rule in the module docstring, for one (averaged) embedding."""
    embedding = normalise(np.asarray(embedding, dtype=np.float32))
    distances = {}
    for cls in np.unique(gallery.labels):
        sims = gallery.embeddings[gallery.labels == cls] @ embedding
        nearest = np.sort(1.0 - sims)[:k]
        distances[str(cls)] = round(float(nearest.mean()), 4)
    if not distances:
        return Decision("other", distances, "empty gallery")
    ranked = sorted(distances, key=distances.get)
    best = ranked[0]
    if best not in SORTABLE:
        return Decision("other", distances, f"closest to {best}")
    if distances[best] >= max_distance:
        return Decision("other", distances, f"unlike anything known ({distances[best]:.3f} >= {max_distance})")
    if len(ranked) > 1 and distances[ranked[1]] - distances[best] < min_margin:
        return Decision("other", distances, f"{best} vs {ranked[1]} too close")
    return Decision(best, distances, "ok")


class Classifier:
    """Embedder + gallery + rule, with settings from config/box_pipeline.yaml (classifier:)."""

    def __init__(self, config: dict, device: str, project_root: Path):
        self.gallery = Gallery.load(project_root / config["gallery"])
        self.embedder = Embedder(config["backbone"], config.get("fallback_backbone"), device)
        if self.embedder.backbone != self.gallery.backbone:
            raise ValueError(f"The gallery was built with {self.gallery.backbone} but {self.embedder.backbone} "
                             f"is loaded: rebuild it with scripts/tools/build_gallery.sh")
        self.k = config.get("k", 5)
        self.max_distance = config["max_distance"]
        self.min_margin = config["min_margin"]

    def classify(self, crops_rgb: list[np.ndarray]) -> Decision:
        """One decision from all crops of one item (the settled frames): embeddings averaged."""
        if not crops_rgb:
            return Decision("other", {}, "no crop")
        mean = self.embedder(crops_rgb).mean(axis=0)
        return decide(mean, self.gallery, self.k, self.max_distance, self.min_margin)
