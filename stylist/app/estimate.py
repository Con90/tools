"""Estimate body measurements from the sizes someone usually buys.

Quick mode lets people skip the tape measure: "I'm usually an M / EU 40 /
W32 L32 / shoe 42". Each usual size is converted into the reference charts'
size system and replaced by the middle of that size's ranges. The reference
is the bundled starter charts file (not the editable database copy), so
deleting a chart in the app never breaks estimation.
"""

from __future__ import annotations

import json
from functools import lru_cache

from . import db
from .conversions import clean_label, convert, foot_length_for_uk, shoe_uk_from

USUAL_CATEGORIES = {
    # key: (label, reference garment)
    "tops": ("Tops", "tops"),
    "bottoms": ("Trousers & jeans", "bottoms"),
    "dresses": ("Dresses", "dresses"),
    "shoes": ("Shoes", "shoes"),
}

# When matching a garment, which usual sizes to draw on, most relevant first.
PRECEDENCE = {
    "tops": ["tops", "dresses", "bottoms"],
    "knitwear": ["tops", "dresses", "bottoms"],
    "outerwear": ["tops", "dresses", "bottoms"],
    "dresses": ["dresses", "tops", "bottoms"],
    "bottoms": ["bottoms", "dresses", "tops"],
    "skirts": ["bottoms", "dresses", "tops"],
    "shoes": ["shoes"],
}


@lru_cache(maxsize=1)
def _reference() -> list[dict]:
    return json.loads((db.APP_DIR / "starter_charts.json").read_text())


def _reference_chart(gender: str, garment: str) -> dict | None:
    section = "womens" if gender == "female" else "mens"
    for chart in _reference():
        if chart["section"] == section and chart["garment"] == garment:
            return chart
    return None


def _mid(r) -> float:
    if isinstance(r, (int, float)):
        return float(r)
    return (float(r[0]) + float(r[1])) / 2


def estimate_category(cat: str, entry: dict, gender: str) -> dict[str, float]:
    """Measurements implied by one usual size, e.g. tops M → chest, waist."""
    system, size = entry.get("system"), entry.get("size")
    if not system or not size:
        return {}
    if cat == "shoes":
        try:
            return {"foot_length": foot_length_for_uk(shoe_uk_from(system, float(clean_label(size)), gender))}
        except ValueError:
            return {}

    chart = _reference_chart(gender, USUAL_CATEGORIES[cat][1])
    if not chart:
        return {}
    ref_system = chart["size_system"]
    labels = [clean_label(size)] if system == ref_system else convert(system, size, gender, chart["garment"], ref_system)
    sizes = [s for s in chart["sizes"] if clean_label(s["label"]) in labels]

    out: dict[str, float] = {}
    if sizes:
        keys = {k for s in sizes for k in s["ranges"]}
        for key in keys:
            mids = [_mid(s["ranges"][key]) for s in sizes if key in s["ranges"]]
            out[key] = round(sum(mids) / len(mids), 1)

    length = entry.get("length")
    if length:
        for opt in chart.get("lengths", []):
            if clean_label(opt["label"]).lstrip("L") == clean_label(length).lstrip("L"):
                out["inseam"] = round(_mid(opt["inseam"]), 1)
    return out


def body_for(profile: dict, garment: str) -> tuple[dict[str, float], dict[str, str]]:
    """Measurements to match with, plus which ones were estimated and from what.

    Detailed mode: your measurements, gaps filled from usual sizes.
    Quick mode: usual sizes only.
    """
    gender = profile.get("gender", "female")
    usual = profile.get("usual_sizes") or {}
    body: dict[str, float] = {}
    sources: dict[str, str] = {}
    for cat in PRECEDENCE.get(garment, []):
        entry = usual.get(cat)
        if not entry:
            continue
        for key, value in estimate_category(cat, entry, gender).items():
            if key not in body:
                body[key] = value
                sources[key] = describe_usual(cat, entry)

    if profile.get("mode", "detailed") == "detailed":
        for key, value in (profile.get("measurements") or {}).items():
            if value:
                body[key] = float(value)
                sources.pop(key, None)
    return body, sources


def describe_usual(cat: str, entry: dict) -> str:
    system, size = entry["system"], entry["size"]
    name = {"Letter": "", "W": "W"}.get(system, f"{system} ")
    text = f"{name}{clean_label(size) if system != 'Letter' else size}"
    if entry.get("length"):
        length = entry["length"]
        text += f" L{length}" if length[0].isdigit() else f" {length}"
    return f"your usual {USUAL_CATEGORIES[cat][0].lower()} size {text}"
