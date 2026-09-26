"""Size matching: compare body measurements against brand size charts.

Size charts store *body* measurement ranges in cm (what brands publish as
"fits chest 86-91"), not garment dimensions. For each chart we score every
size by how far the person's measurements fall outside its ranges and pick the
lowest-cost one, then describe how each measurement will feel.
"""

from __future__ import annotations

from .conversions import equivalents, gender_for_section

MEASUREMENTS = {
    # key: (label, kind) — girth measurements take the fit-preference offset,
    # lengths do not (a relaxed fit doesn't want longer sleeves). Feet read
    # like girths ("snug", "roomy") but take no offset and much less slack.
    "height": ("Height", "length"),
    "chest": ("Chest / bust", "girth"),
    "underbust": ("Underbust", "girth"),
    "waist": ("Waist", "girth"),
    "hips": ("Hips", "girth"),
    "shoulder": ("Shoulder width", "length"),
    "neck": ("Neck", "girth"),
    "sleeve": ("Sleeve / arm length", "length"),
    "inseam": ("Inside leg", "length"),
    "thigh": ("Thigh", "girth"),
    "foot_length": ("Foot length", "foot"),
}

GARMENTS = {
    # key: (label, {measurement: weight}) — weights say which measurements
    # decide the size; anything the chart lists but isn't here gets weight 0.5.
    "tops": ("Tops & shirts", {"chest": 3, "waist": 1, "shoulder": 1.5, "neck": 1.5, "sleeve": 0.5}),
    "knitwear": ("Knitwear", {"chest": 3, "waist": 0.5, "shoulder": 1, "sleeve": 0.5}),
    "outerwear": ("Coats & jackets", {"chest": 3, "shoulder": 2, "waist": 0.5, "sleeve": 1}),
    "dresses": ("Dresses", {"chest": 2, "waist": 2, "hips": 2, "height": 0.5}),
    "bottoms": ("Trousers & jeans", {"waist": 3, "hips": 2, "thigh": 1}),
    "skirts": ("Skirts", {"waist": 3, "hips": 2}),
    "shoes": ("Shoes", {"foot_length": 3}),
}

SECTIONS = {"womens": "Womenswear", "mens": "Menswear", "unisex": "Unisex"}

# How much room each fit preference wants on girth measurements, in cm.
# Slim treats you as slightly smaller (sizes down sooner); relaxed as larger.
FIT_OFFSETS = {"slim": -2.0, "regular": 0.0, "relaxed": 3.0}

# Outside a range by up to this many cm reads as "snug"/"roomy" rather than
# "tight"/"loose". It also scales the scoring, so a few mm matter for shoes.
NEAR_CM = {"foot": 0.4}
DEFAULT_NEAR_CM = 2.0

# Weight of an estimated measurement relative to measured ones in the same size.
ESTIMATE_WEIGHT = 0.2


def _kind(key: str) -> str:
    return MEASUREMENTS.get(key, ("", "girth"))[1]


def _near(key: str) -> float:
    return NEAR_CM.get(_kind(key), DEFAULT_NEAR_CM)


def normalise_range(value) -> tuple[float, float]:
    """Accept [lo, hi] or a single number (treated as ±1 cm)."""
    if isinstance(value, (int, float)):
        return float(value) - 1.0, float(value) + 1.0
    lo, hi = float(value[0]), float(value[1])
    return (lo, hi) if lo <= hi else (hi, lo)


def _describe(key: str, body: float, lo: float, hi: float) -> tuple[str, str]:
    """Return (status, words) for one measurement against one range."""
    if lo <= body <= hi:
        return "good", "fits"
    is_length = _kind(key) == "length"
    near = _near(key)
    if body > hi:
        gap, status = body - hi, "snug" if body - hi <= near else "tight"
        word = "short" if is_length else status
    else:
        gap, status = lo - body, "roomy" if lo - body <= near else "loose"
        word = "long" if is_length else status
    if gap < near / 2:
        return status, f"slightly {word}"
    amount = f"{gap:.1f}" if near < 1 else f"{gap:.0f}"
    return status, f"{amount} cm {word}" if is_length else f"{word} by {amount} cm"


def _score_size(ranges: dict, body: dict, weights: dict, offset: float,
                sources: dict) -> tuple[float, list[dict]] | None:
    cost = 0.0
    used = []
    # When some of the measurements are real, estimates only nudge the choice:
    # a guessed waist shouldn't overrule a measured chest.
    measured = any(k in body and k not in sources for k in ranges)
    for key, raw in ranges.items():
        if key not in body or body[key] in (None, ""):
            continue
        lo, hi = normalise_range(raw)
        actual = float(body[key])
        effective = actual + (offset if _kind(key) == "girth" else 0.0)
        w = weights.get(key, 0.5) * (ESTIMATE_WEIGHT if measured and key in sources else 1.0)
        outside = max(lo - effective, effective - hi, 0.0)
        mid, half = (lo + hi) / 2, max((hi - lo) / 2, 0.5)
        # Squared distance outside the range (in units of that measurement's
        # slack) dominates; the small centring term breaks ties between sizes
        # that both "fit" in favour of the closer match.
        cost += w * ((outside / _near(key)) ** 2 + 0.0125 * ((effective - mid) / half) ** 2)
        # Status is judged against the fit you want; the note states the plain
        # body-vs-chart difference so "snug by 1 cm" still reads true for slim.
        status = _describe(key, effective, lo, hi)[0]
        words = _describe(key, actual, lo, hi)[1]
        used.append({"measurement": key, "label": MEASUREMENTS.get(key, (key,))[0],
                     "body": actual, "range": [lo, hi], "status": status, "note": words,
                     "estimated_from": sources.get(key)})
    if not used:
        return None
    return cost, used


def _verdict(details: list[dict]) -> str:
    # Judge on real measurements when there are any; estimates are shown but
    # don't make a fit "poor" on their own.
    considered = [d for d in details if not d.get("estimated_from")] or details
    statuses = {d["status"] for d in considered}
    if statuses <= {"good"}:
        return "great"
    if statuses <= {"good", "snug", "roomy"}:
        return "good"
    return "poor"


def match_chart(chart: dict, body: dict, fit: str = "regular", gender: str = "female",
                sources: dict | None = None) -> dict | None:
    """Recommend a size (and length, if the chart has lengths) from one chart.

    `sources` maps measurements that were estimated (not measured) to a
    description of where they came from, e.g. "your usual tops size M".
    """
    weights = GARMENTS.get(chart["garment"], ("", {}))[1]
    offset = FIT_OFFSETS.get(fit, 0.0)
    sources = sources or {}
    system = chart.get("size_system", "Other")
    gender = gender_for_section(chart.get("section", ""), gender)

    def eq(label):
        return equivalents(system, label, gender, chart["garment"])

    scored = []
    for size in chart.get("sizes", []):
        result = _score_size(size.get("ranges", {}), body, weights, offset, sources)
        if result:
            scored.append((result[0], size["label"], result[1]))
    if not scored:
        return None
    scored.sort(key=lambda s: s[0])
    best_cost, best_label, best_details = scored[0]

    alternative = None
    if len(scored) > 1:
        alt_cost, alt_label, alt_details = scored[1]
        # Only mention a runner-up when it's genuinely close — "between sizes".
        if alt_cost - best_cost <= max(0.25, best_cost * 0.5) and _verdict(alt_details) != "poor":
            alternative = {"size": alt_label, "details": alt_details, "verdict": _verdict(alt_details),
                           "equivalents": eq(alt_label)}

    length = None
    if chart.get("lengths") and body.get("inseam"):
        options = []
        for opt in chart["lengths"]:
            lo, hi = normalise_range(opt["inseam"])
            inseam = float(body["inseam"])
            options.append((max(lo - inseam, inseam - hi, 0.0), abs(inseam - (lo + hi) / 2), opt["label"], lo, hi))
        options.sort()
        _, _, label, lo, hi = options[0]
        status, note = _describe("inseam", float(body["inseam"]), lo, hi)
        length = {"label": label, "status": status, "note": note, "estimated_from": sources.get("inseam")}

    details = best_details
    verdict = _verdict(details)
    if length and length["status"] in ("tight", "loose") and verdict != "poor":
        verdict = "good"
    return {
        "chart_id": chart.get("id"),
        "brand": chart["brand"],
        "section": chart.get("section"),
        "garment": chart["garment"],
        "size": best_label,
        "size_system": system,
        "equivalents": eq(best_label),
        "estimated": any(d["estimated_from"] for d in details),
        "verdict": verdict,
        "details": details,
        "alternative": alternative,
        "length": length,
    }


def match_all(charts: list[dict], body: dict, garment: str, fit: str = "regular",
              sections: list[str] | None = None, gender: str = "female",
              sources: dict | None = None) -> list[dict]:
    """Best size per chart for a garment type, best-fitting brands first."""
    rank = {"great": 0, "good": 1, "poor": 2}
    results = []
    for chart in charts:
        if chart["garment"] != garment:
            continue
        if sections and chart.get("section") not in sections:
            continue
        m = match_chart(chart, body, fit, gender, sources)
        if m:
            results.append(m)
    results.sort(key=lambda r: (rank[r["verdict"]], r["brand"].lower()))
    return results
