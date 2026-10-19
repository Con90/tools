"""Turn raw per-frame keypoints into smooth, trustworthy joint trajectories.

Steps, in order:
  1. pick the side of the body facing the camera
  2. undo left/right label swaps (the model sometimes flips legs for a frame)
  3. drop low-visibility points and single-frame spikes
  4. fill short gaps by interpolation
  5. zero-lag Butterworth low-pass filter. Default 8 Hz: the textbook 6 Hz
     flattens knee peaks by ~0.5 deg at 100 rpm; on synthetic tests 8 Hz kept
     bias under 0.3 deg from 80-100 rpm with 0-4 px of tracking noise.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.signal import butter, filtfilt

from .landmarks import JOINTS, LEG_JOINTS, Track, other_side

KEY_JOINTS = ("hip", "knee", "ankle")


@dataclass
class Cleaned:
    side: str                       # body side analysed ("left"/"right")
    facing: int                     # +1: rider faces right in the image, -1: left
    fps: float
    xy: dict[str, np.ndarray]       # joint -> (N, 2) filtered pixel coords
    raw: dict[str, np.ndarray]      # joint -> (N, 2) after swap fix, before filtering
    coverage: dict[str, float]      # joint -> fraction of frames with a usable point
    swaps: int
    detected: float                 # fraction of frames with any person found
    notes: list[str] = field(default_factory=list)


def choose_side(track: Track) -> str:
    """The side nearer the camera: the one the model is more confident about."""
    score = {}
    for s in ("left", "right"):
        v = np.concatenate([track.vis(s, j) for j in KEY_JOINTS])
        v = v[np.isfinite(v)]
        score[s] = float(v.mean()) if len(v) else -1.0
    return max(score, key=score.get)


def detected_fraction(track: Track) -> float:
    """Fraction of frames where the model found a person at all."""
    if not track.n:
        return 0.0
    found = np.zeros(track.n, dtype=bool)
    for arr in track.points.values():
        found |= np.isfinite(arr[:, 0])
    return float(found.mean())


def fix_swaps(track: Track, side: str, switch_cost: float = 50.0) -> int:
    """Swap near/far leg labels on frames where they were flipped. In place.

    For each frame, the labels are either right or swapped. Within each
    stretch of continuous tracking, pick the labelling that makes the near
    knee+ankle path smoothest (least total acceleration, in px), plus a small
    cost per change of labelling. This is solved exactly by dynamic
    programming, so one bad frame can't send it down the wrong leg. A smooth
    path can follow either leg, so the leg the model labelled near on most
    frames wins.
    """
    far = other_side(side)

    def leg(s: str) -> np.ndarray:
        return np.hstack([track.xy(s, "knee"), track.xy(s, "ankle")])

    cand = np.stack([leg(side), leg(far)])            # (2, N, 4): option 0 keep, 1 swap
    finite = np.all(np.isfinite(cand), axis=2).all(axis=0)
    swap = np.zeros(track.n, dtype=bool)
    i, n = 0, track.n
    while i < n:
        if not finite[i]:
            i += 1
            continue
        j = i
        while j < n and finite[j]:
            j += 1
        if j - i >= 3:
            labels = _smoothest_labelling(cand[:, i:j], switch_cost)
            swap[i:j] = ~labels if labels.mean() > 0.5 else labels
        i = j
    for jn in LEG_JOINTS:
        p, q = track.points[(side, jn)], track.points[(far, jn)]
        p[swap], q[swap] = q[swap].copy(), p[swap].copy()
    return int(swap.sum())


def _smoothest_labelling(cand: np.ndarray, switch_cost: float) -> np.ndarray:
    """Viterbi over states (label[i-1], label[i]); cand is (2, n, d)."""
    n = cand.shape[1]
    cost = np.array([0.0, switch_cost, switch_cost, 0.0])   # state = 2*prev + cur
    back = np.zeros((n, 4), dtype=np.int8)
    for i in range(2, n):
        new = np.empty(4)
        for state in range(4):
            sp, sc = state >> 1, state & 1
            opts = [cost[2 * spp + sp]
                    + float(np.abs(cand[sc, i] - 2 * cand[sp, i - 1] + cand[spp, i - 2]).sum())
                    for spp in (0, 1)]
            spp = int(opts[1] < opts[0])
            new[state] = opts[spp] + switch_cost * (sc != sp)
            back[i, state] = spp
        cost = new
    labels = np.zeros(n, dtype=bool)
    state = int(np.argmin(cost))
    labels[n - 1], labels[n - 2] = state & 1, state >> 1
    for i in range(n - 1, 1, -1):
        spp = back[i, state]
        labels[i - 2] = spp
        state = 2 * spp + (state >> 1)
    return labels


def detect_facing(track: Track, side: str) -> int:
    """+1 if the rider faces right in the image (drive side view), else -1."""
    d = track.xy(side, "shoulder")[:, 0] - track.xy(side, "hip")[:, 0]
    d = d[np.isfinite(d)]
    if len(d) and abs(np.median(d)) > 1:
        return 1 if np.median(d) > 0 else -1
    d = track.xy(side, "toe")[:, 0] - track.xy(side, "heel")[:, 0]
    d = d[np.isfinite(d)]
    return 1 if (not len(d) or np.median(d) >= 0) else -1


def reject_spikes(xy: np.ndarray, k: float = 6.0, floor_px: float = 3.0,
                  rounds: int = 3) -> np.ndarray:
    """NaN-out single-frame jumps.

    Each point is predicted from its neighbours, using the best predictor the
    available (non-missing) neighbours allow:
      cubic from i-2, i-1, i+1, i+2   - follows pedalling to well under a pixel
      midpoint of i-1, i+1            - error ~ half the frame-to-frame curvature
      extrapolation from one side     - error ~ the frame-to-frame curvature
    Points whose residual is a local maximum and beyond that predictor's
    threshold are removed. Repeated a few times so a spike can't hide its
    neighbour.
    """
    out = xy.copy()
    n = len(out)
    if n < 5:
        return out
    with np.errstate(invalid="ignore"):
        curv = np.linalg.norm(out[2:] - 2 * out[1:-1] + out[:-2], axis=1)
    curv = float(np.nanmedian(curv)) if np.isfinite(curv).any() else 0.0
    for _ in range(rounds):
        pad = np.full((n + 4, 2), np.nan)
        pad[2:-2] = out
        m2, m1, p1, p2 = pad[:-4], pad[1:-3], pad[3:-1], pad[4:]
        preds = [((-m2 + 4 * m1 + 4 * p1 - p2) / 6, 0.0),
                 ((m1 + p1) / 2, 1.0 * curv),
                 (2 * m1 - m2, 2.0 * curv),
                 (2 * p1 - p2, 2.0 * curv)]
        pred = np.full_like(out, np.nan)
        allow = np.full(n, np.nan)
        for p, margin in preds:
            use = np.isnan(pred[:, 0]) & np.all(np.isfinite(p), axis=1)
            pred[use] = p[use]
            allow[use] = margin
        resid = np.linalg.norm(out - pred, axis=1)
        cubic = resid[np.isfinite(resid) & (allow == 0)]
        if len(cubic) < 10:
            break
        scale = 1.4826 * np.median(cubic)
        thresh = np.maximum(k * scale, floor_px) + 2 * np.nan_to_num(allow)
        r = np.nan_to_num(resid, nan=-1.0)
        nb_l = np.concatenate([[-1.0], r[:-1]])
        nb_r = np.concatenate([r[1:], [-1.0]])
        peak = (r > thresh) & (r >= nb_l) & (r >= nb_r)
        if not peak.any():
            break
        out[peak] = np.nan
    return out


def fill_gaps(xy: np.ndarray, max_gap: int) -> np.ndarray:
    """Linearly interpolate NaN runs no longer than max_gap samples."""
    out = xy.copy()
    bad = ~np.all(np.isfinite(xy), axis=1)
    i, n = 0, len(xy)
    while i < n:
        if not bad[i]:
            i += 1
            continue
        j = i
        while j < n and bad[j]:
            j += 1
        if i > 0 and j < n and (j - i) <= max_gap:
            for k in range(i, j):
                f = (k - i + 1) / (j - i + 1)
                out[k] = (1 - f) * xy[i - 1] + f * xy[j]
        else:
            out[i:j] = np.nan
        i = j
    return out


def lowpass(xy: np.ndarray, fps: float, cutoff: float) -> np.ndarray:
    """Zero-lag 4th-order Butterworth, applied to each contiguous finite run."""
    if cutoff <= 0 or cutoff >= fps / 2:
        return xy.copy()
    b, a = butter(4, cutoff / (fps / 2))
    padlen = 3 * max(len(a), len(b))
    out = np.full_like(xy, np.nan)
    good = np.all(np.isfinite(xy), axis=1)
    i, n = 0, len(xy)
    while i < n:
        if not good[i]:
            i += 1
            continue
        j = i
        while j < n and good[j]:
            j += 1
        if j - i > padlen:
            out[i:j] = filtfilt(b, a, xy[i:j], axis=0)
        i = j
    return out


def clean(track: Track, side: str = "auto", cutoff: float = 8.0,
          min_vis: float = 0.5, max_gap_s: float = 0.2) -> Cleaned:
    track = track.copy()
    notes: list[str] = []
    detected = detected_fraction(track)
    if detected < 0.5:
        notes.append(f"The pose model found a person in only {detected:.0%} of frames. Check the "
                     "rider is fully in frame, well lit, and not too small (try --roi to crop).")
    if side == "auto":
        side = choose_side(track)
        if detected > 0:
            notes.append(f"Analysing the {side} side (auto-detected as nearer the camera).")
    swaps = fix_swaps(track, side)
    if swaps:
        notes.append(f"Corrected {swaps} frame(s) where the model swapped left and right legs.")
    facing = detect_facing(track, side)
    if track.fps < 2.5 * cutoff:
        notes.append(f"Frame rate {track.fps:.0f} fps is too low to filter at {cutoff} Hz; "
                     "filtering disabled. Film at 60 fps if you can.")

    max_gap = max(1, int(round(max_gap_s * track.fps)))
    xy, raw, coverage = {}, {}, {}
    for j in JOINTS:
        p = track.points[(side, j)]
        pts = p[:, :2].copy()
        pts[~(p[:, 2] >= min_vis)] = np.nan
        raw[j] = pts.copy()
        pts = reject_spikes(pts)
        pts = fill_gaps(pts, max_gap)
        coverage[j] = float(np.mean(np.all(np.isfinite(pts), axis=1))) if len(pts) else 0.0
        xy[j] = lowpass(pts, track.fps, cutoff)
    return Cleaned(side, facing, track.fps, xy, raw, coverage, swaps, detected, notes)
