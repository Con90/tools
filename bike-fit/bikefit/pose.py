"""Video -> keypoint Track, using MediaPipe Pose Landmarker.

This is the only module that touches the pose model. Anything that can produce
a Track (another model, a coloured-marker tracker, hand-placed points) can
replace it without changing the analysis.
"""

from __future__ import annotations

import time
import urllib.request
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from .landmarks import MEDIAPIPE_INDEX, Track

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
             "pose_landmarker_{v}/float16/latest/pose_landmarker_{v}.task")


def ensure_model(variant: str = "heavy", log: Callable[[str], None] = print) -> Path:
    """Return the path to a pose model, downloading it on first use."""
    path = MODELS_DIR / f"pose_landmarker_{variant}.task"
    if not path.exists():
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        url = MODEL_URL.format(v=variant)
        log(f"Downloading pose model ({variant}) ...")
        tmp = path.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.rename(path)
    return path


def video_info(path: Path) -> tuple[float, int, int, int]:
    """(fps, width, height, frame_count) of a video."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return fps, w, h, n


def find_rider_roi(video: Path, start: float | None = None, end: float | None = None,
                   log: Callable[[str], None] = print) -> tuple[int, int, int, int] | None:
    """Quick pass (lite model, every 3rd frame) to find a square crop around the rider.

    The pose model squashes each frame to a small square input, so a rider who
    fills only part of a wide frame gets few effective pixels. Cropping first
    noticeably improves joint placement.
    """
    fps, width, height, _ = video_info(video)
    track = _run(video, "lite", start, end, None, log=lambda m: None, stride=3)
    pts = np.concatenate([a[:, :2] for a in track.points.values()])
    pts = pts[np.all(np.isfinite(pts), axis=1)]
    if len(pts) < 50:
        log("  auto-crop: rider not found in quick pass; using the full frame")
        return None
    lo, hi = np.percentile(pts, 0.5, axis=0), np.percentile(pts, 99.5, axis=0)
    side = int(max(hi - lo) * 1.6)          # joints exclude the head; the model needs it
    cx, cy = (lo + hi) / 2
    side = min(side, max(width, height))
    x0 = int(np.clip(cx - side / 2, 0, max(width - side, 0)))
    y0 = int(np.clip(cy - side / 2, 0, max(height - side, 0)))
    w, h = min(side, width - x0), min(side, height - y0)
    if w * h > 0.8 * width * height:
        return None
    log(f"  auto-crop: rider found, analysing a {w}x{h} region of the {width}x{height} frame")
    return x0, y0, w, h


def extract_keypoints(
    video: Path,
    variant: str = "heavy",
    start: float | None = None,
    end: float | None = None,
    roi: tuple[int, int, int, int] | str | None = "auto",
    log: Callable[[str], None] = print,
) -> Track:
    """Run the pose model on every frame between start and end (seconds).

    roi=(x, y, w, h) crops each frame before detection; "auto" finds the rider
    first; None uses the full frame. Coordinates are mapped back to the full
    frame either way.
    """
    if roi == "auto":
        roi = find_rider_roi(video, start, end, log)
    return _run(video, variant, start, end, roi, log)


def _run(video: Path, variant: str, start: float | None, end: float | None,
         roi: tuple[int, int, int, int] | None, log: Callable[[str], None],
         stride: int = 1) -> Track:
    from mediapipe import Image, ImageFormat
    from mediapipe.tasks.python import BaseOptions, vision

    fps, width, height, count = video_info(video)
    first = int(round(start * fps)) if start else 0
    last = min(int(round(end * fps)), count) if end else count
    model = ensure_model(variant, log)

    options = vision.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(model)),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    cap = cv2.VideoCapture(str(video))
    if first:
        cap.set(cv2.CAP_PROP_POS_FRAMES, first)

    rows: list[np.ndarray] = []
    frames: list[int] = []
    ox, oy = (roi[0], roi[1]) if roi else (0, 0)
    t0 = last_log = time.time()
    total = max(last - first, 1)
    with vision.PoseLandmarker.create_from_options(options) as landmarker:
        i = first
        while i < last:
            ok, bgr = cap.read()
            if not ok:
                break
            if (i - first) % stride:
                i += 1
                continue
            if roi:
                x, y, w, h = roi
                bgr = bgr[y:y + h, x:x + w]
            fh, fw = bgr.shape[:2]
            rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            result = landmarker.detect_for_video(
                Image(image_format=ImageFormat.SRGB, data=rgb), int(round(i * 1000 / fps)))
            row = np.full((33, 3), np.nan)
            if result.pose_landmarks:
                for k, lm in enumerate(result.pose_landmarks[0]):
                    vis = lm.visibility if lm.visibility is not None else (
                        lm.presence if lm.presence is not None else 1.0)
                    row[k] = (lm.x * fw + ox, lm.y * fh + oy, vis)
            rows.append(row)
            frames.append(i)
            i += 1
            if time.time() - last_log > 3:
                done = i - first
                rate = done / (time.time() - t0)
                log(f"  pose: {done}/{total} frames ({rate:.0f} fps, "
                    f"~{(total - done) / max(rate, 1e-6):.0f}s left)")
                last_log = time.time()
    cap.release()
    if not rows:
        raise ValueError("No frames could be read from the video.")

    data = np.stack(rows)
    track = Track(fps, width, height, np.array(frames), {}, str(video))
    for key, idx in MEDIAPIPE_INDEX.items():
        track.points[key] = data[:, idx, :].copy()
    return track
