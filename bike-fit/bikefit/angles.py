"""Joint angle definitions (2D, sagittal plane).

Conventions are stated explicitly because fitters disagree on them, and a
published range is meaningless without its convention:

  knee flexion   180 - included angle hip-knee-ankle   (0 = straight leg)
  hip angle      included angle shoulder-hip-knee      (smaller = more closed)
  ankle angle    included angle knee-ankle-toe         (larger = toe pointed down)
  torso angle    hip->shoulder line above horizontal   (0 = flat back)
  shoulder angle included angle hip-shoulder-elbow
  elbow angle    included angle shoulder-elbow-wrist   (180 = locked straight)

All use image coordinates (y down) and assume the camera is level and square
to the bike.
"""

from __future__ import annotations

import numpy as np


def included(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Angle at b between b->a and b->c, in degrees (0-180)."""
    u, v = a - b, c - b
    cos = np.sum(u * v, axis=-1) / (np.linalg.norm(u, axis=-1) * np.linalg.norm(v, axis=-1))
    return np.degrees(np.arccos(np.clip(cos, -1.0, 1.0)))


def torso(hip: np.ndarray, shoulder: np.ndarray, facing: int) -> np.ndarray:
    d = shoulder - hip
    return np.degrees(np.arctan2(-d[..., 1], facing * d[..., 0]))


def compute(xy: dict[str, np.ndarray], facing: int) -> dict[str, np.ndarray]:
    """All per-frame angle series, keyed by name."""
    with np.errstate(invalid="ignore", divide="ignore"):
        return {
            "knee": 180.0 - included(xy["hip"], xy["knee"], xy["ankle"]),
            "hip": included(xy["shoulder"], xy["hip"], xy["knee"]),
            "ankle": included(xy["knee"], xy["ankle"], xy["toe"]),
            "torso": torso(xy["hip"], xy["shoulder"], facing),
            "shoulder": included(xy["hip"], xy["shoulder"], xy["elbow"]),
            "elbow": included(xy["shoulder"], xy["elbow"], xy["wrist"]),
        }


LABELS = {
    "knee": "Knee flexion",
    "hip": "Hip angle",
    "ankle": "Ankle angle",
    "torso": "Torso angle",
    "shoulder": "Shoulder angle",
    "elbow": "Elbow angle",
}
