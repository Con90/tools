"""Keypoint Track -> complete fit analysis."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import angles as ang
from .clean import Cleaned, clean
from .cycles import GRID, Strokes, segment, stroke_curves
from .fitting import (Check, Range, Recommendation, Scale, make_scale, per_stroke,
                      quality, recommend, reference_ranges, summarise)
from .landmarks import Track


@dataclass
class Analysis:
    track: Track
    cleaned: Cleaned
    angles: dict[str, np.ndarray]
    strokes: Strokes
    rows: list[dict]
    summary: dict[str, dict]
    curves: dict[str, dict[str, np.ndarray]]    # angle -> {"mean", "sd"} over GRID
    ranges: dict[str, Range]
    scale: Scale
    quality: str
    checks: list[Check]
    recommendations: list[Recommendation]
    settings: dict

    @property
    def notes(self) -> list[str]:
        return self.cleaned.notes + self.strokes.notes


def analyse(track: Track, side: str = "auto", cutoff: float = 8.0,
            leg_mm: float | None = None, mm_per_px: float | None = None,
            ref: tuple | None = None, style: str = "road") -> Analysis:
    c = clean(track, side=side, cutoff=cutoff)
    a = ang.compute(c.xy, c.facing)
    strokes = segment(c.xy["ankle"], c.facing, track.fps,
                      required=[c.xy["hip"], c.xy["knee"]])
    rows = per_stroke(a, c.xy, strokes)
    summary = summarise(rows)

    curves = {}
    for name, series in a.items():
        per = stroke_curves(series, strokes)
        with np.errstate(all="ignore"):
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                curves[name] = {"mean": np.nanmean(per, axis=0) if len(per) else np.full(len(GRID), np.nan),
                                "sd": np.nanstd(per, axis=0) if len(per) else np.full(len(GRID), np.nan)}

    ranges = reference_ranges(style)
    scale = make_scale(leg_mm, mm_per_px, ref,
                       summary["thigh_px"]["median"], summary["shank_px"]["median"])
    overall, checks = quality(track.fps, len(rows), strokes.rejected, summary, rows,
                              c.coverage, c.swaps, track.n, c.detected)
    recs = recommend(summary, ranges, scale, overall)
    settings = {"side": c.side, "facing": "right" if c.facing > 0 else "left",
                "cutoff_hz": cutoff, "style": style, "leg_mm": leg_mm,
                "fps": track.fps, "frames": track.n, "source": track.source,
                "cadence_rpm": strokes.cadence}
    return Analysis(track, c, a, strokes, rows, summary, curves, ranges, scale,
                    overall, checks, recs, settings)
