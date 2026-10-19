"""Find pedal strokes and put every stroke on a common crank-angle axis.

There is no pedal tracking, so crank angle is estimated from the ankle, which
traces a closed loop around the bottom bracket. 0 deg = top of the stroke,
90 deg = forward (3 o'clock for a drive-side view), 180 deg = bottom. Because
the ankle sits above and behind the pedal spindle, this estimate can be offset
from the true crank angle by 10-20 deg. Headline metrics use per-stroke
extremes (e.g. the most extended knee in each stroke), which do not depend on
the crank-angle estimate at all.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

GRID = np.arange(0, 361, 2.0)       # crank-angle grid for averaged curves, deg


@dataclass
class Strokes:
    phase: np.ndarray               # (N,) unwrapped crank angle, rad; NaN where unknown
    bounds: list[tuple[int, int]]   # sample index range [i0, i1] of each accepted stroke
    centre: np.ndarray              # (2,) centre of the ankle loop, px
    cadence: float                  # rpm, median over accepted strokes
    rejected: int                   # strokes thrown out (stalls, gaps, odd timing)
    notes: list[str]


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    out, i, n = [], 0, len(mask)
    while i < n:
        if not mask[i]:
            i += 1
            continue
        j = i
        while j < n and mask[j]:
            j += 1
        out.append((i, j))
        i = j
    return out


def segment(ankle: np.ndarray, facing: int, fps: float,
            required: list[np.ndarray] | None = None) -> Strokes:
    """Split the clip into pedal strokes.

    required: other per-frame arrays that must be finite for a stroke to count.
    """
    notes: list[str] = []
    n = len(ankle)
    ok = np.all(np.isfinite(ankle), axis=1)
    for arr in required or []:
        ok &= np.isfinite(arr) if arr.ndim == 1 else np.all(np.isfinite(arr), axis=1)
    phase = np.full(n, np.nan)
    if ok.sum() < 10:
        return Strokes(phase, [], np.array([np.nan, np.nan]), float("nan"), 0,
                       ["Not enough tracked frames to find pedal strokes."])

    pts = ankle[ok]
    lo, hi = np.percentile(pts, 2, axis=0), np.percentile(pts, 98, axis=0)
    centre = (lo + hi) / 2
    d = ankle - centre
    wrapped = np.arctan2(facing * d[:, 0], -d[:, 1])     # 0 at top, + in pedalling direction

    spans = []
    for i, j in _runs(ok):
        if j - i < 3:
            continue
        phase[i:j] = np.unwrap(wrapped[i:j])
        spans.append((i, j))

    steps = np.diff(phase)
    steps = steps[np.isfinite(steps)]
    if len(steps) and np.median(steps) < 0:
        phase = -phase
        notes.append("Ankle loop runs the 'wrong' way for the detected facing; "
                     "assuming the facing guess was wrong.")

    bounds, durations = [], []
    rejected = 0
    for i, j in spans:
        p = phase[i:j]
        first = np.ceil(p[0] / (2 * np.pi))
        last = np.floor(p[-1] / (2 * np.pi))
        for k in np.arange(first, last):
            lo_p, hi_p = 2 * np.pi * k, 2 * np.pi * (k + 1)
            idx = np.nonzero((p >= lo_p) & (p <= hi_p))[0]
            if len(idx) < 8:
                rejected += 1
                continue
            a, b = i + idx[0], i + idx[-1]
            # include the samples bracketing each boundary so interpolation spans 0-360
            a, b = max(a - 1, i), min(b + 1, j - 1)
            seg = phase[a:b + 1]
            if np.any(np.diff(seg) <= 0):
                rejected += 1
                continue
            bounds.append((a, b))
            durations.append((b - a) / fps)

    if not bounds:
        return Strokes(phase, [], centre, float("nan"), rejected,
                       notes + ["No complete pedal strokes found."])
    med = float(np.median(durations))
    keep = [(bd, du) for bd, du in zip(bounds, durations) if 0.7 * med <= du <= 1.4 * med]
    rejected += len(bounds) - len(keep)
    bounds = [bd for bd, _ in keep]
    rate = [(phase[b] - phase[a]) / (b - a) for a, b in bounds]     # rad per frame
    cadence = float(np.median(rate)) * fps / (2 * np.pi) * 60
    return Strokes(phase, bounds, centre, cadence, rejected, notes)


def stroke_curves(signal: np.ndarray, strokes: Strokes) -> np.ndarray:
    """Resample a per-frame signal onto GRID for every stroke. -> (n_strokes, len(GRID))."""
    out = np.full((len(strokes.bounds), len(GRID)), np.nan)
    for s, (a, b) in enumerate(strokes.bounds):
        p = strokes.phase[a:b + 1]
        deg = np.degrees(p - 2 * np.pi * np.floor(p[1] / (2 * np.pi)))
        v = signal[a:b + 1]
        if np.all(np.isfinite(v)):
            out[s] = np.interp(GRID, deg, v)
    return out
