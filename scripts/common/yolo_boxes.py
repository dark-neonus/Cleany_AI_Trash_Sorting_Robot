"""YOLO as a box finder: every box above conf, whatever its class (the material comes from the
DINO classifier). Used by the box pipeline and the pick recorder."""

from __future__ import annotations

import numpy as np


class YoloBoxes:
    """Every YOLO box above conf, whatever its class: the material comes from the classifier."""

    def __init__(self, weights: str, conf: float, device: str):
        import cv2
        from ultralytics import YOLO

        self.cv2, self.model, self.conf, self.device = cv2, YOLO(weights), conf, device

    def __call__(self, frame_rgb: np.ndarray) -> list[dict]:
        h, w = frame_rgb.shape[:2]
        sx, sy = 640 / w, 480 / h  # boxes in 640x480 coordinates, like the regions
        result = self.model.predict(self.cv2.cvtColor(frame_rgb, self.cv2.COLOR_RGB2BGR), conf=self.conf,
                                    device=self.device, verbose=False)[0]
        return [{"class": self.model.names[int(c)], "conf": round(p, 2),
                 "box": [b[0] * sx, b[1] * sy, b[2] * sx, b[3] * sy]}
                for c, p, b in zip(result.boxes.cls.tolist(), result.boxes.conf.tolist(), result.boxes.xyxy.tolist())]
