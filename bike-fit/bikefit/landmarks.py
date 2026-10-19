"""Keypoint tracks: the data handed from pose extraction to analysis.

A Track holds, for every joint on both sides of the body, an (N, 3) array of
x pixel, y pixel and visibility (0-1) per video frame. Missing points are NaN.
Tracks round-trip through a plain CSV so you can re-run the analysis without
re-processing the video, inspect the numbers in a spreadsheet, or hand-correct
a bad frame.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

JOINTS = ("shoulder", "elbow", "wrist", "hip", "knee", "ankle", "heel", "toe")
SIDES = ("left", "right")
LEG_JOINTS = ("hip", "knee", "ankle", "heel", "toe")

# MediaPipe Pose landmark index for each (side, joint). "toe" is MediaPipe's
# foot_index landmark (tip of the foot).
MEDIAPIPE_INDEX = {
    ("left", "shoulder"): 11, ("right", "shoulder"): 12,
    ("left", "elbow"): 13, ("right", "elbow"): 14,
    ("left", "wrist"): 15, ("right", "wrist"): 16,
    ("left", "hip"): 23, ("right", "hip"): 24,
    ("left", "knee"): 25, ("right", "knee"): 26,
    ("left", "ankle"): 27, ("right", "ankle"): 28,
    ("left", "heel"): 29, ("right", "heel"): 30,
    ("left", "toe"): 31, ("right", "toe"): 32,
}

# Lines drawn between joints in overlays.
BONES = (
    ("shoulder", "elbow"), ("elbow", "wrist"), ("shoulder", "hip"),
    ("hip", "knee"), ("knee", "ankle"), ("ankle", "heel"), ("heel", "toe"),
    ("ankle", "toe"),
)


def other_side(side: str) -> str:
    return "left" if side == "right" else "right"


@dataclass
class Track:
    fps: float
    width: int
    height: int
    frames: np.ndarray                      # source video frame index per sample
    points: dict[tuple[str, str], np.ndarray] = field(default_factory=dict)
    source: str = ""

    @property
    def n(self) -> int:
        return len(self.frames)

    @property
    def t(self) -> np.ndarray:
        return self.frames / self.fps

    def xy(self, side: str, joint: str) -> np.ndarray:
        return self.points[(side, joint)][:, :2]

    def vis(self, side: str, joint: str) -> np.ndarray:
        return self.points[(side, joint)][:, 2]

    def copy(self) -> "Track":
        return Track(self.fps, self.width, self.height, self.frames.copy(),
                     {k: v.copy() for k, v in self.points.items()}, self.source)

    @classmethod
    def empty(cls, n: int, fps: float, width: int, height: int, source: str = "") -> "Track":
        pts = {(s, j): np.full((n, 3), np.nan) for s in SIDES for j in JOINTS}
        return cls(fps, width, height, np.arange(n), pts, source)


def save_csv(track: Track, path: Path) -> None:
    cols = [f"{s}_{j}_{c}" for s in SIDES for j in JOINTS for c in ("x", "y", "vis")]
    with open(path, "w", newline="") as f:
        f.write(f"# bike-fit keypoints v1 fps={track.fps:.6g} width={track.width} "
                f"height={track.height} source={track.source}\n")
        w = csv.writer(f)
        w.writerow(["frame"] + cols)
        for i in range(track.n):
            row = [int(track.frames[i])]
            for s in SIDES:
                for j in JOINTS:
                    for v in track.points[(s, j)][i]:
                        row.append("" if np.isnan(v) else f"{v:.2f}")
            w.writerow(row)


def load_csv(path: Path) -> Track:
    with open(path, newline="") as f:
        header = f.readline()
        if not header.startswith("# bike-fit keypoints"):
            raise ValueError(f"{path} is not a bike-fit keypoints file")
        meta = {}
        for tok in header[1:].split():
            if "=" in tok:
                k, v = tok.split("=", 1)
                meta[k] = v
        source = header.split("source=", 1)[1].strip() if "source=" in header else ""
        rows = list(csv.reader(f))
    names = rows[0]
    data = np.array([[float(v) if v != "" else np.nan for v in r] for r in rows[1:]])
    if data.size == 0:
        data = np.zeros((0, len(names)))
    track = Track(float(meta["fps"]), int(meta["width"]), int(meta["height"]),
                  data[:, 0].astype(int), {}, source)
    for s in SIDES:
        for j in JOINTS:
            idx = [names.index(f"{s}_{j}_{c}") for c in ("x", "y", "vis")]
            track.points[(s, j)] = data[:, idx]
    return track
