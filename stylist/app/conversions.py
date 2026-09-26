"""Size-system conversions (UK / EU / US / letters / waist inches, and shoes).

Clothing conversions are lookup tables: each row is one size, and a system can
list the same label on several rows (letter "M" spans UK 10 and 12), so
converting joins every row that matches. Shoes use the standard last-length
formulas instead. All of these are the common high-street conventions; brands
vary, which is why real brand charts still beat conversions.
"""

from __future__ import annotations

import re

SYSTEMS = {
    "UK": "UK",
    "EU": "EU",
    "US": "US",
    "Letter": "Letters (XS–XXL)",
    "W": "Waist inches (W32)",
    "Other": "Other / brand-specific",
}

_WOMENS = [
    # UK, EU, US, letter
    ("4", "32", "0", "XXS"), ("6", "34", "2", "XS"), ("8", "36", "4", "S"),
    ("10", "38", "6", "M"), ("12", "40", "8", "M"), ("14", "42", "10", "L"),
    ("16", "44", "12", "L"), ("18", "46", "14", "XL"), ("20", "48", "16", "XL"),
    ("22", "50", "18", "XXL"), ("24", "52", "20", "XXL"),
]
_MENS_TOPS = [
    # letter, EU (≈ chest cm / 2), UK & US (chest inches)
    ("XS", "44", "34"), ("S", "46", "36"), ("M", "48", "38"), ("L", "50", "40"),
    ("L", "52", "42"), ("XL", "54", "44"), ("XXL", "56", "46"), ("XXXL", "58", "48"),
]
_MENS_BOTTOMS = [
    # waist inches, EU, letter
    ("28", "44", "XS"), ("29", "", "S"), ("30", "46", "S"), ("31", "", "M"),
    ("32", "48", "M"), ("33", "", "L"), ("34", "50", "L"), ("36", "52", "XL"),
    ("38", "54", "XXL"), ("40", "56", "XXXL"),
]

TABLES = {
    ("female", "clothing"): [{"UK": uk, "EU": eu, "US": us, "Letter": l} for uk, eu, us, l in _WOMENS],
    ("female", "bottoms"): [{"UK": uk, "EU": eu, "US": us, "Letter": l} for uk, eu, us, l in _WOMENS],
    ("male", "clothing"): [{"Letter": l, "EU": eu, "UK": uk, "US": uk} for l, eu, uk in _MENS_TOPS],
    ("male", "bottoms"): [{"W": w, "EU": eu, "Letter": l} for w, eu, l in _MENS_BOTTOMS],
}

# Which systems to offer, first one is the default/canonical for that table.
CLOTHING_SYSTEMS = {
    ("female", "clothing"): ["UK", "EU", "US", "Letter"],
    ("female", "bottoms"): ["UK", "EU", "US", "Letter"],
    ("male", "clothing"): ["Letter", "EU", "UK", "US"],
    ("male", "bottoms"): ["W", "EU", "Letter"],
}
SHOE_SYSTEMS = ["UK", "EU", "US"]

MENS_LENGTHS = [str(n) for n in range(28, 37, 2)]  # L28 … L36
WOMENS_LENGTHS = ["Short", "Regular", "Long"]


def category(garment: str) -> str:
    if garment == "shoes":
        return "shoes"
    if garment in ("bottoms", "skirts"):
        return "bottoms"
    return "clothing"


def gender_for_section(section: str, fallback: str = "female") -> str:
    return {"womens": "female", "mens": "male"}.get(section, fallback)


def clean_label(label: str) -> str:
    """'uk 12' → '12', 'W32' → '32', ' m ' → 'M', 'EU 42.0' → '42'."""
    s = str(label).strip().upper()
    s = re.sub(r"^(UK|EU|US|W)\s*", "", s)
    if re.fullmatch(r"\d+(\.\d+)?", s):
        n = float(s)
        return str(int(n)) if n.is_integer() else str(n)
    return {"2XL": "XXL", "3XL": "XXXL", "XXXS": "XXS"}.get(s, s)


# --- shoes -------------------------------------------------------------------
# UK adult size = 3 × last length (in) − 25; the last is ~1.5 cm longer than
# the foot. EU (Paris point) = 1.5 × last length (cm). US is UK + 1 for men and
# UK + 2 for women.

LAST_ALLOWANCE_CM = 1.5


def _round_half(x: float) -> float:
    return round(x * 2) / 2


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else str(x)


def shoe_uk_from(system: str, size: float, gender: str) -> float:
    if system == "UK":
        return size
    if system == "US":
        return size - (2 if gender == "female" else 1)
    if system == "EU":
        return size / 1.27 - 25
    raise ValueError(f"unknown shoe size system '{system}'")


def foot_length_for_uk(uk: float) -> float:
    return round((uk + 25) / 3 * 2.54 - LAST_ALLOWANCE_CM, 1)


def shoe_equivalents(system: str, label: str, gender: str) -> dict[str, str]:
    uk = shoe_uk_from(system, float(clean_label(label)), gender)
    return {
        "UK": _fmt(_round_half(uk)),
        "EU": _fmt(_round_half(1.27 * (uk + 25))),
        "US": _fmt(_round_half(uk + (2 if gender == "female" else 1))),
        "cm": f"{foot_length_for_uk(uk):.1f}",
    }


def shoe_options(system: str, gender: str) -> list[str]:
    uk_range = (2, 9.5) if gender == "female" else (5, 14)
    if system == "EU":
        lo, hi = (int(1.27 * (u + 25) + 0.5) for u in uk_range)
        return [_fmt(x / 2) for x in range(lo * 2, hi * 2 + 1)]
    offset = 0 if system == "UK" else (2 if gender == "female" else 1)
    return [_fmt(uk_range[0] + offset + i / 2) for i in range(int((uk_range[1] - uk_range[0]) * 2) + 1)]


# --- clothing ------------------------------------------------------------------


def _rows(gender: str, cat: str, system: str, label: str) -> list[dict]:
    want = clean_label(label)
    return [row for row in TABLES.get((gender, cat), []) if row.get(system) == want]


def equivalents(system: str, label: str, gender: str, garment: str) -> dict[str, str]:
    """Other-system names for a size, e.g. UK 12 → {EU: 40, US: 8, Letter: M}.

    Returns {} when the size or system isn't in the tables (e.g. 'Other')."""
    cat = category(garment)
    try:
        if cat == "shoes":
            if system not in SHOE_SYSTEMS:
                return {}
            eq = shoe_equivalents(system, label, gender)
            eq.pop(system, None)
            return eq
    except ValueError:
        return {}
    rows = _rows(gender, cat, system, label)
    out = {}
    for other in CLOTHING_SYSTEMS.get((gender, cat), []):
        if other == system:
            continue
        values = []
        for row in rows:
            v = row.get(other)
            if v and v not in values:
                values.append(v)
        if values:
            out[other] = values[0] if len(values) == 1 else f"{values[0]}–{values[-1]}"
    return out


def convert(system: str, label: str, gender: str, garment: str, target: str) -> list[str]:
    """All labels in `target` that a size corresponds to."""
    rows = _rows(gender, category(garment), system, label)
    out = []
    for row in rows:
        v = row.get(target)
        if v and v not in out:
            out.append(v)
    return out


def size_options(gender: str, cat: str) -> dict[str, list[str]]:
    """Selectable labels per system, for the 'usual sizes' form."""
    if cat == "shoes":
        return {s: shoe_options(s, gender) for s in SHOE_SYSTEMS}
    out = {}
    for system in CLOTHING_SYSTEMS[(gender, cat)]:
        labels = []
        for row in TABLES[(gender, cat)]:
            v = row.get(system)
            if v and v not in labels:
                labels.append(v)
        out[system] = labels
    return out
