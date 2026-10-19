"""Per-stroke metrics, reference ranges, data-quality grading, recommendations.

Only knee extension drives a numeric recommendation (saddle height). It is the
one measure with a well-established dynamic range and a clean geometric link
to a component adjustment. Everything else is reported against rule-of-thumb
ranges as context, and produces at most a qualitative suggestion.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .cycles import Strokes


@dataclass
class Range:
    lo: float
    hi: float
    basis: str
    strength: str       # "established" | "rule of thumb"


TORSO_STYLES = {
    "endurance": (40, 50),
    "road": (33, 43),
    "aggressive": (25, 35),
    "tt": (10, 25),
}


def reference_ranges(style: str = "road") -> dict[str, Range]:
    t_lo, t_hi = TORSO_STYLES[style]
    return {
        "knee_ext": Range(33, 43, "Dynamic (video / motion capture) knee flexion at full "
                          "extension, Ferrer-Roca et al. 2012. Static goniometer methods "
                          "(e.g. Holmes, 25-35 deg) read 5-10 deg less flexion, so don't "
                          "compare against those.", "established"),
        "knee_top": Range(105, 115, "Typical peak knee flexion; mostly set by saddle height "
                          "and crank length.", "rule of thumb"),
        "hip_closed": Range(40, 55, "Most-closed hip angle at the top of the stroke. Very "
                            "closed can mean saddle low, cranks long or bars low.",
                            "rule of thumb"),
        "ankle_rom": Range(15, 35, "Ankle range of motion over a stroke. Large values can "
                           "mask a saddle that is too high (toe-pointing to reach).",
                           "rule of thumb"),
        "torso": Range(t_lo, t_hi, f"Torso angle for a '{style}' position; a goal, not a "
                       "rule. Depends on flexibility and event.", "rule of thumb"),
        "shoulder": Range(80, 95, "Torso to upper arm, on the hoods.", "rule of thumb"),
        "elbow": Range(150, 165, "A slight bend absorbs road buzz and lets the torso "
                       "settle; near 180 means locked out.", "rule of thumb"),
    }


METRICS = {
    # key: (label, unit, description)
    "knee_ext": ("Knee flexion at full extension", "deg", "most extended point of each stroke"),
    "knee_top": ("Knee flexion at peak bend", "deg", "most bent point of each stroke"),
    "hip_closed": ("Hip angle, most closed", "deg", "near the top of the stroke"),
    "ankle_at_ext": ("Ankle angle at full extension", "deg", "knee-ankle-toe"),
    "ankle_rom": ("Ankle range of motion", "deg", "max - min per stroke"),
    "torso": ("Torso angle", "deg", "median over the stroke"),
    "shoulder": ("Shoulder angle", "deg", "median over the stroke"),
    "elbow": ("Elbow angle", "deg", "median over the stroke"),
    "ext_crank_angle": ("Crank angle at full extension", "deg", "estimated; ~150-180 typical"),
}


def _peak(y: np.ndarray, i: int) -> float:
    """Sub-frame value of an extreme at sample i, by parabolic interpolation."""
    if 0 < i < len(y) - 1:
        a, b, c = y[i - 1], y[i], y[i + 1]
        den = a - 2 * b + c
        if den != 0 and np.isfinite(den):
            return float(b - (a - c) ** 2 / (8 * den))
    return float(y[i])


def per_stroke(angles: dict[str, np.ndarray], xy: dict[str, np.ndarray],
               strokes: Strokes) -> list[dict]:
    rows = []
    thigh = np.linalg.norm(xy["hip"] - xy["knee"], axis=1)
    shank = np.linalg.norm(xy["knee"] - xy["ankle"], axis=1)
    for a, b in strokes.bounds:
        sl = slice(a, b + 1)
        knee = angles["knee"][sl]
        if not np.all(np.isfinite(knee)):
            continue
        i_ext, i_top = int(np.argmin(knee)), int(np.argmax(knee))
        ph = strokes.phase[a + i_ext]
        ankle = angles["ankle"][sl]
        row = {
            "start": a, "end": b, "ext_index": a + i_ext, "top_index": a + i_top,
            "knee_ext": _peak(knee, i_ext),
            "knee_top": _peak(knee, i_top),
            "hip_closed": float(np.nanmin(angles["hip"][sl])),
            "ankle_at_ext": float(ankle[i_ext]),
            "ankle_rom": float(np.nanmax(ankle) - np.nanmin(ankle)),
            "torso": float(np.nanmedian(angles["torso"][sl])),
            "shoulder": float(np.nanmedian(angles["shoulder"][sl])),
            "elbow": float(np.nanmedian(angles["elbow"][sl])),
            "ext_crank_angle": float(np.degrees(ph) % 360),
            "thigh_px": float(np.nanmedian(thigh[sl])),
            "shank_px": float(np.nanmedian(shank[sl])),
        }
        rows.append(row)
    return rows


def summarise(rows: list[dict]) -> dict[str, dict]:
    out = {}
    for key in list(METRICS) + ["thigh_px", "shank_px"]:
        v = np.array([r[key] for r in rows], dtype=float)
        v = v[np.isfinite(v)]
        if not len(v):
            out[key] = {"median": None, "sd": None, "p25": None, "p75": None, "n": 0}
            continue
        if key == "ext_crank_angle":     # circular: unwrap around the median
            ref = np.degrees(np.angle(np.mean(np.exp(1j * np.radians(v))))) % 360
            v = (v - ref + 180) % 360 - 180 + ref
        out[key] = {"median": float(np.median(v)), "sd": float(np.std(v, ddof=1)) if len(v) > 1 else 0.0,
                    "p25": float(np.percentile(v, 25)), "p75": float(np.percentile(v, 75)),
                    "n": int(len(v))}
    return out


# --- scale -----------------------------------------------------------------

@dataclass
class Scale:
    mm_per_px: float | None
    method: str


def make_scale(leg_mm: float | None, mm_per_px: float | None,
               ref: tuple[float, float, float, float, float] | None,
               thigh_px: float | None, shank_px: float | None) -> Scale:
    if mm_per_px:
        return Scale(mm_per_px, "given directly (--mm-per-px)")
    if ref:
        x1, y1, x2, y2, mm = ref
        px = float(np.hypot(x2 - x1, y2 - y1))
        return Scale(mm / px, f"reference length {mm:g} mm over {px:.0f} px (--ref)")
    if leg_mm and thigh_px and shank_px:
        return Scale(leg_mm / (thigh_px + shank_px),
                     f"leg length {leg_mm:g} mm vs tracked thigh+shank (--leg-mm)")
    return Scale(None, "none - pass --leg-mm to get millimetre recommendations")


# --- saddle-height geometry ----------------------------------------------------

def hip_ankle_distance(flex_deg: float, thigh: float, shank: float) -> float:
    inc = np.radians(180.0 - flex_deg)
    return float(np.sqrt(thigh ** 2 + shank ** 2 - 2 * thigh * shank * np.cos(inc)))


def saddle_change(flex_now: float, flex_target: float, thigh: float, shank: float) -> float:
    """Change in hip-to-ankle distance (units of thigh/shank) to move knee
    flexion at full extension from flex_now to flex_target. Positive = raise.

    Assumes the saddle moves along the hip-ankle line and the ankle does not
    compensate. In practice riders ankle a little differently after a change,
    which is why changes are capped and you re-film afterwards.
    """
    return hip_ankle_distance(flex_target, thigh, shank) - hip_ankle_distance(flex_now, thigh, shank)


# --- data quality ------------------------------------------------------------------

GRADES = ("good", "fair", "poor")


@dataclass
class Check:
    name: str
    value: str
    grade: str
    advice: str = ""


def quality(fps: float, n_strokes: int, rejected: int, summary: dict, rows: list[dict],
            coverage: dict[str, float], swaps: int, n_frames: int,
            detected: float = 1.0) -> tuple[str, list[Check]]:
    checks = []

    def grade(v, good, fair, higher_better=True):
        if v is None or not np.isfinite(v):
            return "poor"
        if higher_better:
            return "good" if v >= good else "fair" if v >= fair else "poor"
        return "good" if v <= good else "fair" if v <= fair else "poor"

    g = grade(detected, 0.95, 0.8)
    checks.append(Check("Person detected", f"{detected:.0%} of frames", g,
                        "" if g == "good" else "Keep the whole rider in frame, light them evenly, "
                        "and fill more of the frame (or use --roi)."))
    g = grade(fps, 50, 25)
    checks.append(Check("Frame rate", f"{fps:.0f} fps", g,
                        "" if g == "good" else "Film at 60 fps or higher."))
    g = grade(n_strokes, 15, 8)
    checks.append(Check("Pedal strokes analysed", f"{n_strokes} ({rejected} rejected)", g,
                        "" if g == "good" else "Film 45-60 s of steady pedalling."))
    cov = min(coverage[j] for j in ("hip", "knee", "ankle"))
    g = grade(cov, 0.9, 0.7)
    checks.append(Check("Hip/knee/ankle tracked", f"{cov:.0%} of frames", g,
                        "" if g == "good" else "Improve lighting and contrast; wear tight "
                        "clothing; make sure the whole leg stays in frame."))
    sd = summary["knee_ext"]["sd"]
    g = grade(sd, 2.0, 4.0, higher_better=False)
    checks.append(Check("Stroke-to-stroke knee spread", "n/a" if sd is None else f"{sd:.1f} deg SD", g,
                        "" if g == "good" else "Noisy tracking or uneven pedalling. Hold a "
                        "steady cadence; check the overlay video for jumpy points."))
    cvs = []
    for k in ("thigh_px", "shank_px"):
        v = np.array([r[k] for r in rows])
        if len(v) > 1:
            cvs.append(np.std(v) / np.mean(v))
    cv = max(cvs) if cvs else None
    g = grade(cv, 0.04, 0.08, higher_better=False)
    checks.append(Check("Segment length stability", "n/a" if cv is None else f"{cv:.1%} variation", g,
                        "" if g == "good" else "Thigh/shank lengths change between strokes: "
                        "camera may not be square to the bike, or the knee is moving in and "
                        "out of plane. Re-square the camera."))
    if swaps:
        frac = swaps / max(n_frames, 1)
        g = "good" if frac < 0.05 else "fair"     # corrected, so never "poor" on its own
        checks.append(Check("Left/right leg swaps fixed", f"{swaps} frames ({frac:.0%})", g,
                            "" if g == "good" else "The model often confused the legs (corrected, "
                            "but check the overlay). Better light or a contrasting sock on the "
                            "near leg helps."))
    overall = max((c.grade for c in checks), key=GRADES.index)
    return overall, checks


# --- recommendations -------------------------------------------------------------------

@dataclass
class Recommendation:
    area: str
    action: str
    detail: str
    confidence: str          # "medium" | "low" | "info"
    change_mm: float | None = None


CAP_MM = 10.0


def recommend(summary: dict, ranges: dict[str, Range], scale: Scale,
              overall_quality: str) -> list[Recommendation]:
    recs: list[Recommendation] = []
    if overall_quality == "poor":
        recs.append(Recommendation(
            "Data quality", "Re-film before changing anything",
            "At least one data-quality check is poor, so the numbers below may be off by "
            "more than the adjustments they suggest. Fix the flagged checks and re-film.",
            "info"))

    k = summary["knee_ext"]["median"]
    r = ranges["knee_ext"]
    thigh, shank = summary["thigh_px"]["median"], summary["shank_px"]["median"]
    if k is not None and thigh and shank:
        conf = "medium" if overall_quality == "good" else "low"
        per_deg_px = abs(saddle_change(k, k - 1, thigh, shank))
        per_deg = (f"{per_deg_px * scale.mm_per_px:.1f} mm" if scale.mm_per_px
                   else f"{per_deg_px:.1f} px")
        if r.lo <= k <= r.hi:
            recs.append(Recommendation(
                "Saddle height", "No change",
                f"Knee flexion at full extension is {k:.1f} deg, inside the {r.lo:g}-{r.hi:g} "
                f"deg dynamic range. (Here, 1 deg of knee angle is about {per_deg} of saddle "
                "height.)", conf, 0.0))
        else:
            target = r.hi - 2 if k > r.hi else r.lo + 2
            d_px = saddle_change(k, target, thigh, shank)
            verb = "Raise" if d_px > 0 else "Lower"
            why = ("more bent than the range: saddle likely low" if k > r.hi
                   else "straighter than the range: saddle likely high")
            if scale.mm_per_px:
                mm = d_px * scale.mm_per_px
                step = float(np.clip(mm, -CAP_MM, CAP_MM))
                action = f"{verb} saddle about {abs(step):.0f} mm"
                extra = (f" The full estimate is {abs(mm):.0f} mm. Change at most {CAP_MM:.0f} mm "
                         "at a time, ride it for a few days, then re-film."
                         if abs(mm) > CAP_MM else " Re-film after the change to confirm.")
                recs.append(Recommendation(
                    "Saddle height", action,
                    f"Knee flexion at full extension is {k:.1f} deg, {why} "
                    f"({r.lo:g}-{r.hi:g} deg). Targeting {target:g} deg.{extra}",
                    conf, round(step, 1)))
            else:
                recs.append(Recommendation(
                    "Saddle height", f"{verb} saddle (size unknown without a scale)",
                    f"Knee flexion at full extension is {k:.1f} deg, {why} "
                    f"({r.lo:g}-{r.hi:g} deg). Targeting {target:g} deg needs "
                    f"{abs(d_px):.0f} px of change. Re-run with --leg-mm to convert to mm.",
                    conf))

    rom = summary["ankle_rom"]["median"]
    if rom is not None and k is not None and rom > ranges["ankle_rom"].hi and k <= r.hi:
        recs.append(Recommendation(
            "Ankle", "Watch for toe-pointing",
            f"Ankle range of motion is {rom:.0f} deg (typical up to "
            f"{ranges['ankle_rom'].hi:g}). Riders often point the toe to reach a saddle that "
            "is too high, which makes the knee angle look fine. Treat the saddle height "
            "result as an upper limit.", "low"))

    hip = summary["hip_closed"]["median"]
    if hip is not None and hip < ranges["hip_closed"].lo:
        recs.append(Recommendation(
            "Hip", "Hip angle is very closed",
            f"Most-closed hip angle is {hip:.0f} deg (typical {ranges['hip_closed'].lo:g}-"
            f"{ranges['hip_closed'].hi:g}). Possible causes: saddle low, cranks long, or "
            "bars low/far. Fix saddle height first, then reassess.", "low"))

    elbow = summary["elbow"]["median"]
    shoulder = summary["shoulder"]["median"]
    if elbow is not None and elbow > 170:
        recs.append(Recommendation(
            "Reach", "Arms nearly locked",
            f"Elbow angle is {elbow:.0f} deg. Either bend the elbows more, or the reach "
            "may be long or the bars low: consider a shorter or higher stem.", "low"))
    elif shoulder is not None and shoulder > ranges["shoulder"].hi + 5:
        recs.append(Recommendation(
            "Reach", "Reach looks long",
            f"Shoulder angle is {shoulder:.0f} deg (typical {ranges['shoulder'].lo:g}-"
            f"{ranges['shoulder'].hi:g}). A shorter stem may help.", "low"))
    elif shoulder is not None and shoulder < ranges["shoulder"].lo - 5:
        recs.append(Recommendation(
            "Reach", "Reach looks short",
            f"Shoulder angle is {shoulder:.0f} deg (typical {ranges['shoulder'].lo:g}-"
            f"{ranges['shoulder'].hi:g}). A longer stem may help.", "low"))

    recs.append(Recommendation(
        "Not measured", "Saddle fore/aft, cleats, hip rock, knee tracking",
        "A side view can't see these. Fore/aft needs the pedal spindle tracked; knee "
        "tracking and hip rock need a front or rear view.", "info"))
    return recs

