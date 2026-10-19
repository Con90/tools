"""Skeleton overlays: annotated stills for the report, and a full overlay video
so you can check the tracking with your own eyes (the most important check)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from .landmarks import BONES

LINE = (60, 200, 255)       # BGR amber: filtered skeleton
RAW = (255, 120, 60)        # BGR blue: raw model points
INK = (25, 25, 25)


def read_frame(video: Path | None, frame: int) -> np.ndarray | None:
    if not video or not Path(video).exists():
        return None
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame))
    ok, img = cap.read()
    cap.release()
    return img if ok else None


def _blank(width: int, height: int) -> np.ndarray:
    return np.full((height, width, 3), 236, np.uint8)


def _label(img: np.ndarray, text: str, at: tuple[int, int], scale: float) -> None:
    font = cv2.FONT_HERSHEY_SIMPLEX
    th = max(1, int(round(2 * scale)))
    (w, h), base = cv2.getTextSize(text, font, scale, th)
    x, y = at
    x = int(np.clip(x, 2, img.shape[1] - w - 4))
    y = int(np.clip(y, h + 4, img.shape[0] - base - 2))
    cv2.rectangle(img, (x - 4, y - h - 4), (x + w + 4, y + base + 2), (20, 20, 20), -1)
    cv2.putText(img, text, (x, y), font, scale, (255, 255, 255), th, cv2.LINE_AA)


def draw_skeleton(img: np.ndarray, pts: dict[str, np.ndarray], scale: float,
                  color=LINE, labels: dict[str, str] | None = None, facing: int = 1) -> None:
    th = max(2, int(round(4 * scale)))
    for a, b in BONES:
        p, q = pts.get(a), pts.get(b)
        if p is None or q is None or not (np.all(np.isfinite(p)) and np.all(np.isfinite(q))):
            continue
        p, q = tuple(int(v) for v in p), tuple(int(v) for v in q)
        cv2.line(img, p, q, INK, th + 3, cv2.LINE_AA)
        cv2.line(img, p, q, color, th, cv2.LINE_AA)
    for j, p in pts.items():
        if np.all(np.isfinite(p)):
            cv2.circle(img, tuple(int(v) for v in p), th + 2, INK, -1, cv2.LINE_AA)
            cv2.circle(img, tuple(int(v) for v in p), th, (255, 255, 255), -1, cv2.LINE_AA)
    for j, text in (labels or {}).items():
        p = pts.get(j)
        if p is not None and np.all(np.isfinite(p)):
            off = int(18 * scale)
            _label(img, text, (int(p[0] + facing * off), int(p[1] - off)), 0.7 * scale)


def rider_box(xy: dict[str, np.ndarray], width: int, height: int, margin: float = 0.12):
    allpts = np.concatenate([v for v in xy.values()])
    allpts = allpts[np.all(np.isfinite(allpts), axis=1)]
    if not len(allpts):
        return 0, 0, width, height
    lo, hi = np.percentile(allpts, 1, axis=0), np.percentile(allpts, 99, axis=0)
    pad = (hi - lo) * margin
    x0, y0 = np.maximum(lo - pad, 0).astype(int)
    x1, y1 = np.minimum(hi + pad, [width, height]).astype(int)
    return int(x0), int(y0), int(x1), int(y1)


def still(an, sample: int, max_width: int = 900) -> bytes:
    """JPEG of one frame with the analysed skeleton and joint angles drawn on."""
    tr, c = an.track, an.cleaned
    img = read_frame(Path(tr.source) if tr.source else None, int(tr.frames[sample]))
    if img is None:
        img = _blank(tr.width, tr.height)
    pts = {j: c.xy[j][sample] for j in c.xy}
    a = {k: v[sample] for k, v in an.angles.items()}
    fmt = lambda v: "-" if not np.isfinite(v) else f"{v:.0f}"
    labels = {"knee": f"knee {fmt(a['knee'])}", "hip": f"hip {fmt(a['hip'])}",
              "ankle": f"ankle {fmt(a['ankle'])}", "elbow": f"elbow {fmt(a['elbow'])}",
              "shoulder": f"torso {fmt(a['torso'])}"}
    x0, y0, x1, y1 = rider_box(c.xy, tr.width, tr.height)
    scale = max(1.0, (y1 - y0) / 700)
    draw_skeleton(img, pts, scale, labels=labels, facing=c.facing)
    crop = img[y0:y1, x0:x1]
    if crop.shape[1] > max_width:
        f = max_width / crop.shape[1]
        crop = cv2.resize(crop, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes()


def overlay_video(an, out_path: Path, log: Callable[[str], None] = print) -> Path | None:
    """Every frame with raw (blue dots) and filtered (amber skeleton) points."""
    tr, c = an.track, an.cleaned
    if not tr.source or not Path(tr.source).exists():
        return None
    cap = cv2.VideoCapture(tr.source)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(tr.frames[0]))
    tmp = out_path.with_suffix(".tmp.mp4")
    writer = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), tr.fps, (tr.width, tr.height))
    scale = max(1.0, tr.height / 1080)
    knee, phase = an.angles["knee"], an.strokes.phase
    for i in range(tr.n):
        ok, img = cap.read()
        if not ok:
            break
        for j, p in c.raw.items():
            if np.all(np.isfinite(p[i])):
                cv2.circle(img, tuple(int(v) for v in p[i]), int(5 * scale), RAW, -1, cv2.LINE_AA)
        draw_skeleton(img, {j: c.xy[j][i] for j in c.xy}, scale, facing=c.facing)
        crank = "-" if not np.isfinite(phase[i]) else f"{np.degrees(phase[i]) % 360:.0f}"
        kv = "-" if not np.isfinite(knee[i]) else f"{knee[i]:.0f}"
        _label(img, f"frame {int(tr.frames[i])}  crank~{crank}  knee flex {kv}",
               (int(20 * scale), int(50 * scale)), 0.9 * scale)
        writer.write(img)
    cap.release()
    writer.release()
    if shutil.which("ffmpeg"):           # re-encode as H.264 so browsers can play it
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp), "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", "-crf", "26", "-preset", "veryfast", str(out_path)])
        if r.returncode == 0:
            tmp.unlink()
            return out_path
    tmp.rename(out_path)
    return out_path
