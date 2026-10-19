"""Machine-readable outputs: metrics.json, strokes.csv, curves.csv, summary.md,
and comparing two runs."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from . import __version__
from .cycles import GRID
from .fitting import METRICS


def _clean(v):
    if isinstance(v, float) and not np.isfinite(v):
        return None
    if isinstance(v, (np.floating,)):
        return None if not np.isfinite(v) else float(v)
    if isinstance(v, np.integer):
        return int(v)
    return v


def metrics_dict(an) -> dict:
    metrics = {}
    for key, (label, unit, desc) in METRICS.items():
        rng = an.ranges.get(key)
        metrics[key] = {
            "label": label, "unit": unit, "description": desc, **an.summary[key],
            "range": None if rng is None else {"lo": rng.lo, "hi": rng.hi, "strength": rng.strength,
                                                "basis": rng.basis},
        }
    return {
        "tool": f"bike-fit {__version__}",
        "settings": {k: _clean(v) for k, v in an.settings.items()},
        "scale": asdict(an.scale),
        "quality": {"overall": an.quality, "checks": [asdict(c) for c in an.checks]},
        "metrics": metrics,
        "segment_px": {"thigh": an.summary["thigh_px"]["median"], "shank": an.summary["shank_px"]["median"]},
        "recommendations": [asdict(r) for r in an.recommendations],
        "notes": an.notes,
    }


def status(value, rng) -> str:
    if value is None or rng is None:
        return "n/a"
    if value < rng.lo:
        return "below"
    if value > rng.hi:
        return "above"
    return "in range"


def summary_markdown(an) -> str:
    """Compact text to paste into a chat with an AI assistant for interpretation."""
    s = an.settings
    lines = [
        "# Bike fit measurements (side-on video, rider on a trainer)",
        "",
        f"- Tool: bike-fit {__version__}; side analysed: {s['side']}; "
        f"{len(an.rows)} pedal strokes; cadence {s['cadence_rpm']:.0f} rpm; {s['fps']:.0f} fps",
        f"- Data quality: {an.quality.upper()}"
        + "".join(f"; {c.name}: {c.value} ({c.grade})" for c in an.checks),
        f"- Scale: {an.scale.method}",
        "- Angle conventions: knee flexion = 180 - hip-knee-ankle included angle (0 = straight); "
        "hip = shoulder-hip-knee included; ankle = knee-ankle-toe included; torso = hip->shoulder "
        "above horizontal; elbow 180 = locked.",
        "",
        "| Metric | Median | SD across strokes | Reference | Status |",
        "|---|---|---|---|---|",
    ]
    for key, (label, unit, _) in METRICS.items():
        m = an.summary[key]
        rng = an.ranges.get(key)
        ref = "-" if rng is None else f"{rng.lo:g}-{rng.hi:g} ({rng.strength})"
        med = "-" if m["median"] is None else f"{m['median']:.1f}"
        sd = "-" if m["sd"] is None else f"{m['sd']:.1f}"
        lines.append(f"| {label} | {med} | {sd} | {ref} | {status(m['median'], rng)} |")
    lines += ["", "## Tool's recommendations", ""]
    for r in an.recommendations:
        lines.append(f"- **{r.area}: {r.action}** ({r.confidence}). {r.detail}")
    if an.notes:
        lines += ["", "## Notes", ""] + [f"- {n}" for n in an.notes]
    lines += ["", "Please interpret these numbers for me: what stands out, what you'd change first, "
              "and what you can't tell from this data."]
    return "\n".join(lines) + "\n"


def write_all(an, out: Path) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    p = out / "metrics.json"
    p.write_text(json.dumps(metrics_dict(an), indent=2, default=_clean))
    files["metrics"] = p

    p = out / "strokes.csv"
    if an.rows:
        with open(p, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["stroke"] + list(an.rows[0]))
            w.writeheader()
            for i, r in enumerate(an.rows):
                w.writerow({"stroke": i + 1, **{k: (f"{v:.3f}" if isinstance(v, float) else v)
                                                for k, v in r.items()}})
        files["strokes"] = p

    p = out / "curves.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        names = list(an.curves)
        w.writerow(["crank_deg"] + [f"{n}_{s}" for n in names for s in ("mean", "sd")])
        for i, g in enumerate(GRID):
            row = [f"{g:g}"]
            for n in names:
                for s in ("mean", "sd"):
                    v = an.curves[n][s][i]
                    row.append("" if not np.isfinite(v) else f"{v:.3f}")
            w.writerow(row)
    files["curves"] = p

    p = out / "summary.md"
    p.write_text(summary_markdown(an))
    files["summary"] = p
    return files


COMPARE_KEYS = ["knee_ext", "knee_top", "hip_closed", "ankle_at_ext", "ankle_rom", "torso",
                "shoulder", "elbow"]


def compare(before: Path, after: Path) -> str:
    a, b = json.loads(Path(before).read_text()), json.loads(Path(after).read_text())
    rows = [("Metric", "Before", "After", "Change", "Reference")]
    for k in COMPARE_KEYS:
        ma, mb = a["metrics"].get(k, {}), b["metrics"].get(k, {})
        va, vb = ma.get("median"), mb.get("median")
        rng = mb.get("range") or {}
        ref = f"{rng['lo']:g}-{rng['hi']:g}" if rng else "-"
        d = "-" if va is None or vb is None else f"{vb - va:+.1f}"
        rows.append((ma.get("label", k), "-" if va is None else f"{va:.1f}",
                     "-" if vb is None else f"{vb:.1f}", d, ref))
    rows.append(("Data quality", a["quality"]["overall"], b["quality"]["overall"], "", ""))
    widths = [max(len(r[i]) for r in rows) for i in range(5)]
    out = []
    for n, r in enumerate(rows):
        out.append("  ".join(c.ljust(w) if i == 0 else c.rjust(w) for i, (c, w) in enumerate(zip(r, widths))))
        if n == 0:
            out.append("  ".join("-" * w for w in widths))
    return "\n".join(out)
