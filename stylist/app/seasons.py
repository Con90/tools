"""Seasonal colour analysis: measured colours → 12-season type → palette.

A person is scored on three axes, each −1…+1:

- warmth  (cool −, warm +): mostly skin hue angle, plus how golden the hair is
- depth   (light −, deep +): hair and skin lightness
- clarity (soft −, bright +): hair/skin contrast and how vivid the eyes are

Each of the 12 seasons sits at a point in that space (e.g. True Autumn is very
warm, a little deep, soft). The nearest seasons win. This mirrors how human
analysts reason (a season's "dominant" trait plus two secondary ones) but it is
a starting point: lighting, make-up and dyed hair all move the numbers, so the
app also offers side-by-side colour comparisons and a manual override.
"""

from __future__ import annotations

import numpy as np

from .colour import lch


def _clamp(x: float) -> float:
    return float(max(-1.0, min(1.0, x)))


def neutral_skin_hue(L: float) -> float:
    """Hue angle of a neutral undertone, for skin of lightness L*.

    Lighter skin shows more of the blood beneath it, so it reads redder
    (lower hue) at the same undertone: measured skin hue averages about 50°
    for fair European skin and nearer 57–60° for deeper skin. Judging all
    skin against one reference made fair skin read pink.
    """
    return 50 + 8 * max(0.0, min(1.0, (65 - L) / 20))


def scores(skin, hair=None, eyes=None) -> dict:
    """Lab colours → warmth / depth / clarity scores."""
    sL, sC, sh = lch(skin)
    parts_w = [(0.55, _clamp((sh - neutral_skin_hue(sL)) / 10))]  # pink (low hue) ↔ golden (high hue)
    parts_d = [(0.4, _clamp((65 - sL) / 15))]
    parts_c = [(0.1, _clamp((sC - 20) / 8))]       # clear vs greyed skin

    if hair is not None:
        hL, hC, hh = lch(hair)
        # Very dark hair (and eyes) are naturally low in chroma, which says
        # nothing about warmth or softness, so those terms only apply to
        # lighter hair/eyes; contrast carries the signal for dark features.
        if hL > 28:  # golden/red hair is warm, ash is cool
            parts_w.append((0.3, _clamp((hC - 0.3 * hL - 5) / 8)))
            parts_c.append((0.15, _clamp((hC - 0.25 * hL - 6) / 8)))  # saturated vs ashy hair
        parts_d.append((0.6, _clamp((40 - hL) / 20)))
        parts_c.append((0.3, _clamp((abs(sL - hL) - 25) / 25)))       # light/dark contrast
    if eyes is not None:
        eL, eC, eh = lch(eyes)
        if eC > 6 and 160 < eh < 300:    # blue / blue-grey: cool
            eye_w = -0.7
        elif eC <= 6:                     # grey: slightly cool
            eye_w = -0.3
        elif 40 < eh < 110:               # amber / hazel / green-gold: warm evidence only
            eye_w = max(0.0, _clamp((eC - 12) / 12))
        else:
            eye_w = 0.0
        parts_w.append((0.15, eye_w))
        parts_d.append((0.15, _clamp((45 - eL) / 15)))
        if eL >= 35:
            parts_c.append((0.4, _clamp((eC - 18) / 10)))  # vivid vs greyed eyes

    def avg(parts):
        total = sum(w for w, _ in parts)
        return round(sum(w * v for w, v in parts) / total, 3)

    return {"warmth": avg(parts_w), "depth": avg(parts_d), "clarity": avg(parts_c)}


# (warmth, depth, clarity) for each season.
PROTOTYPES = {
    "light_spring": (0.5, -1.0, 0.3),
    "true_spring": (1.0, -0.4, 0.5),
    "bright_spring": (0.4, -0.2, 1.0),
    "light_summer": (-0.5, -1.0, -0.3),
    "true_summer": (-1.0, -0.3, -0.5),
    "soft_summer": (-0.4, -0.1, -1.0),
    "soft_autumn": (0.4, 0.1, -1.0),
    "true_autumn": (1.0, 0.4, -0.5),
    "deep_autumn": (0.5, 1.0, -0.3),
    "deep_winter": (-0.5, 1.0, 0.3),
    "true_winter": (-1.0, 0.4, 0.5),
    "bright_winter": (-0.4, 0.2, 1.0),
}

# People rarely reach the extremes, so prototypes are compared at this scale.
PROTOTYPE_SCALE = 0.6


def rank_seasons(s: dict) -> list[dict]:
    """All seasons, closest first, with a 0–100 match percentage."""
    p = np.array([s["warmth"], s["depth"], s["clarity"]])
    ranked = []
    for key, proto in PROTOTYPES.items():
        d = float(np.linalg.norm(p - np.array(proto) * PROTOTYPE_SCALE))
        ranked.append({"season": key, "distance": round(d, 3)})
    ranked.sort(key=lambda r: r["distance"])
    # Softmax over negative distance → relative match strengths.
    weights = np.exp(-np.array([r["distance"] for r in ranked]) * 4)
    for r, wgt in zip(ranked, weights / weights.sum()):
        r["match"] = int(round(wgt * 100))
    return ranked


def describe_scores(s: dict) -> list[str]:
    words = []
    for axis, (neg, pos) in {"warmth": ("cool", "warm"), "depth": ("light", "deep"),
                             "clarity": ("soft / muted", "bright / clear")}.items():
        v = s[axis]
        if abs(v) < 0.15:
            words.append(f"neutral {'undertone' if axis == 'warmth' else 'depth' if axis == 'depth' else 'clarity'}")
        else:
            strength = "very " if abs(v) > 0.6 else "" if abs(v) > 0.3 else "slightly "
            words.append(f"{strength}{pos if v > 0 else neg}")
    return words


# --- palettes -------------------------------------------------------------------------
# Hand-picked swatches per season. "neutrals" are wardrobe basics, "colours" the
# core palette, "accents" statement colours, "avoid" the classic mismatches.

SEASONS = {
    "light_spring": {
        "name": "Light Spring", "family": "Spring",
        "summary": "Light, warm and fresh. Delicate, clear colours with a golden base; nothing heavy or dusty.",
        "neutrals": ["#f6efe0", "#e8d8bd", "#cdb28a", "#a8906e", "#8b8f94", "#6b7fa1"],
        "colours": ["#f7c9b5", "#f4a68c", "#f58f7c", "#f4b860", "#f9dc7a", "#e8e89a",
                    "#a8d8a0", "#7dcfb6", "#8fd3dc", "#9cc3ea", "#b7b2e8", "#e7a9c9"],
        "accents": ["#ff7f6a", "#2cb5a0", "#4a9fe0"],
        "avoid": ["#000000", "#4b2e2a", "#5a2d53", "#3d4a2a", "#7a7a7a"],
        "metals": "Light gold, rose gold, champagne",
        "tips": "Swap black for soft navy, camel or light grey. Keep contrast gentle; head-to-toe dark overwhelms you.",
    },
    "true_spring": {
        "name": "True (Warm) Spring", "family": "Spring",
        "summary": "Warm, clear and lively. Sunny, golden-based colours with plenty of energy.",
        "neutrals": ["#f5ead3", "#e3c99b", "#c49a63", "#8c6a45", "#2f4a7a", "#5b6b3b"],
        "colours": ["#ff8a65", "#ff6f4e", "#f7a541", "#ffd24d", "#c7d95a", "#6cbf5b",
                    "#2fb7a3", "#3fb8d6", "#4a8fe0", "#ef7fa3", "#e2574c", "#b37fcf"],
        "accents": ["#ff5a36", "#00a88f", "#f2b705"],
        "avoid": ["#000000", "#6d6f78", "#8a6f8f", "#c0c6d6", "#4a2445"],
        "metals": "Yellow gold, brass, copper",
        "tips": "Camel, warm beige and bright navy are your basics. Choose ivory over stark white.",
    },
    "bright_spring": {
        "name": "Bright (Clear) Spring", "family": "Spring",
        "summary": "Bright, clear and slightly warm. Vivid, saturated colours and crisp contrast.",
        "neutrals": ["#fbf7ee", "#d9c6a5", "#1f2b4d", "#3b3b3f", "#8a7a66", "#2a5a73"],
        "colours": ["#ff4f5e", "#ff6b3d", "#ffb000", "#ffe14d", "#7ed957", "#00b386",
                    "#00b3c7", "#1f7ae0", "#6a4de8", "#e03fa5", "#ff7eb6", "#e8f07a"],
        "accents": ["#ff2e4d", "#00c2a8", "#2d5bff"],
        "avoid": ["#9e8f87", "#b8a39a", "#6e6a5e", "#c3b4a2", "#7d6b5d"],
        "metals": "Polished gold, bright silver",
        "tips": "You can wear black, but pair it with a vivid colour near the face. Dusty, greyed colours make you look tired.",
    },
    "light_summer": {
        "name": "Light Summer", "family": "Summer",
        "summary": "Light, cool and soft. Airy pastels with a cool base, like sea glass and sweet peas.",
        "neutrals": ["#f4f1ec", "#d9d6d2", "#a9adb5", "#7d8698", "#5b6d8c", "#b8a7a0"],
        "colours": ["#f2c4d0", "#e8a3b8", "#d98fa8", "#c9b3e0", "#a7b5e8", "#8fb8e0",
                    "#9fd0d8", "#9fd6c2", "#c7e3b8", "#f2e6a6", "#e6b3a3", "#b8c9e6"],
        "accents": ["#d46a93", "#4f8fcf", "#3fa7a0"],
        "avoid": ["#000000", "#ff6a00", "#6b4a2b", "#c79a2b", "#3f2a1d"],
        "metals": "Silver, white gold, platinum, soft rose gold",
        "tips": "Soft grey, grey-navy and dove are your basics instead of black. Keep contrast low to medium.",
    },
    "true_summer": {
        "name": "True (Cool) Summer", "family": "Summer",
        "summary": "Cool and gently muted. Blue-based colours softened with grey, like a summer sky at dusk.",
        "neutrals": ["#eeeef0", "#c9cbd1", "#8e95a3", "#5a6680", "#2f3d5c", "#7a6e78"],
        "colours": ["#e89bb5", "#d46a8c", "#b84a6e", "#a88bc7", "#7b7fc4", "#5b8fd1",
                    "#6fb0d4", "#5fa8a0", "#8cc0a8", "#e0d7a8", "#c7a4c9", "#9fb3d9"],
        "accents": ["#c2185b", "#3949ab", "#00897b"],
        "avoid": ["#ff7a00", "#d4a017", "#8b5a2b", "#f5e6c8", "#5c4a1f"],
        "metals": "Silver, pewter, white gold",
        "tips": "Swap black for charcoal or deep navy; swap cream for soft white. Rose and raspberry beat coral.",
    },
    "soft_summer": {
        "name": "Soft Summer", "family": "Summer",
        "summary": "Soft, cool and misty. Greyed, blended colours with low contrast, like weathered stone and lavender.",
        "neutrals": ["#e6e2dc", "#c2bcb4", "#8f8a86", "#6b6e75", "#4c5563", "#7e7466"],
        "colours": ["#d4a5b0", "#b8808f", "#9c6b7c", "#a295b8", "#8290ad", "#7896ad",
                    "#7fa3a3", "#8aa892", "#b4b98f", "#d9c9a3", "#c29a8f", "#a3b5c7"],
        "accents": ["#8c4a64", "#4f6d8f", "#4f7a6e"],
        "avoid": ["#000000", "#ff3b30", "#ffcc00", "#ffffff", "#ff6600"],
        "metals": "Brushed silver, pewter, soft rose gold",
        "tips": "Tone-on-tone outfits suit you. Avoid pure black and pure white near your face.",
    },
    "soft_autumn": {
        "name": "Soft Autumn", "family": "Autumn",
        "summary": "Soft, warm and muted. Earthy, blended colours with a gentle golden base, like dried herbs and sandstone.",
        "neutrals": ["#efe6d6", "#d6c3a3", "#b09878", "#8a7560", "#6e6a5a", "#5e6b73"],
        "colours": ["#e3a58a", "#d4876b", "#c47a5a", "#d9b06a", "#c9b872", "#a6ad78",
                    "#86a07f", "#6f9a8f", "#7f9aa6", "#b38b8f", "#c9978a", "#a38f6e"],
        "accents": ["#b5553c", "#4f7f73", "#a3712a"],
        "avoid": ["#000000", "#ff1f5a", "#1f3fff", "#ffffff", "#c000ff"],
        "metals": "Brushed gold, bronze, rose gold",
        "tips": "Camel, mushroom and olive make great basics. Keep contrast low; soft layers of similar tones work best.",
    },
    "true_autumn": {
        "name": "True (Warm) Autumn", "family": "Autumn",
        "summary": "Warm, rich and earthy. Golden, spicy colours like autumn leaves, cinnamon and moss.",
        "neutrals": ["#f1e4c8", "#d2b48c", "#a67b4f", "#6b4a2b", "#4a4a2a", "#2f4a4a"],
        "colours": ["#e07a3f", "#c65a2e", "#b5452a", "#d99a2b", "#c9a227", "#9a9a2e",
                    "#6b8e3a", "#3f7f5f", "#2f7f7f", "#b5652f", "#8f3f2f", "#7a5a8a"],
        "accents": ["#d2691e", "#008b8b", "#b8860b"],
        "avoid": ["#ff69b4", "#c0c0ff", "#000000", "#e0e8ff", "#8a2be2"],
        "metals": "Yellow gold, copper, bronze, brass",
        "tips": "Chocolate brown, olive and camel are better than black. Cream beats bright white.",
    },
    "deep_autumn": {
        "name": "Deep Autumn", "family": "Autumn",
        "summary": "Deep, warm and rich. Dark, saturated earth tones, like espresso, paprika and forest green.",
        "neutrals": ["#efe3cc", "#bfa27a", "#6b4a2b", "#3f2a1d", "#2a2a22", "#1f3a3a"],
        "colours": ["#c1442e", "#a33a2a", "#8b2e2e", "#d98a1f", "#b8860b", "#7f7a1f",
                    "#4f6b2a", "#1f5f4a", "#1f5f6b", "#7a2e4a", "#5a2e5a", "#b85a2e"],
        "accents": ["#e25822", "#00695c", "#9b1b30"],
        "avoid": ["#ffc0cb", "#b0c4de", "#e6e6fa", "#c0c0c0", "#ff77ff"],
        "metals": "Antique gold, bronze, copper",
        "tips": "Dark chocolate, deep olive and near-black brown make great basics. Pastels wash you out.",
    },
    "deep_winter": {
        "name": "Deep Winter", "family": "Winter",
        "summary": "Deep, cool and striking. Dark, rich jewel tones with high contrast.",
        "neutrals": ["#ffffff", "#c0c0c8", "#4a4a55", "#1f1f2a", "#000000", "#1f2a4a"],
        "colours": ["#9b1b30", "#c21e56", "#e0115f", "#7a1f5c", "#4b1f6f", "#2e2e8f",
                    "#0f4c81", "#006d6f", "#00674f", "#2f4f2f", "#b22222", "#5a2a7a"],
        "accents": ["#dc143c", "#0047ab", "#009b77"],
        "avoid": ["#f5deb3", "#d2b48c", "#ffa07a", "#e9967a", "#c2b280"],
        "metals": "Silver, platinum, gunmetal, white gold",
        "tips": "Black and white are yours. Wear deep jewel tones rather than earthy browns or dusty pastels.",
    },
    "true_winter": {
        "name": "True (Cool) Winter", "family": "Winter",
        "summary": "Cool, clear and high-contrast. Icy and vivid blue-based colours; crisp black and white.",
        "neutrals": ["#ffffff", "#e6ecf5", "#9aa0ab", "#3a3f4a", "#000000", "#14213d"],
        "colours": ["#e0115f", "#c71585", "#dc143c", "#8a2be2", "#4b0082", "#0047ab",
                    "#1e90ff", "#008b8b", "#00a86b", "#d6e8ff", "#f0d0ff", "#ff69b4"],
        "accents": ["#ff0066", "#0033cc", "#00a693"],
        "avoid": ["#d2691e", "#daa520", "#8b7355", "#f5deb3", "#808000"],
        "metals": "Silver, platinum, white gold",
        "tips": "Contrast is your friend: black with white, navy with icy pastels. Avoid golden browns and orange.",
    },
    "bright_winter": {
        "name": "Bright (Clear) Winter", "family": "Winter",
        "summary": "Bright, clear and slightly cool. Electric, saturated colours with maximum contrast.",
        "neutrals": ["#ffffff", "#d9dce3", "#5a5f6a", "#1f2230", "#000000", "#0d1b52"],
        "colours": ["#ff0f5b", "#ff1493", "#e0115f", "#9400d3", "#6a0dad", "#1f3fff",
                    "#0096ff", "#00ced1", "#00c878", "#ffe600", "#ff3860", "#e6e6ff"],
        "accents": ["#ff0080", "#00b3ff", "#00e676"],
        "avoid": ["#b8a38a", "#a38f7a", "#8f8f70", "#c9b8a0", "#9e7f6b"],
        "metals": "Bright silver, platinum",
        "tips": "Pair black or white with one vivid colour. Muted, earthy or dusty shades fall flat on you.",
    },
}

NATURAL_EYES = {
    # Typical iris colours in Lab: photos often lose eye colour (small, shadowed,
    # grey-green reading as grey), so people can say what their eyes really are.
    "dark_brown": ("Dark brown", [24, 6, 9]),
    "light_brown": ("Light brown", [35, 8, 18]),
    "hazel": ("Hazel", [40, 4, 20]),
    "amber": ("Amber", [45, 10, 30]),
    "green": ("Green", [45, -6, 15]),
    "grey_green": ("Grey-green", [48, -4, 7]),
    "blue": ("Blue", [52, -3, -22]),
    "grey_blue": ("Grey-blue", [55, -2, -10]),
    "grey": ("Grey", [55, -1, 1]),
}

NATURAL_HAIR = {
    # Typical natural hair colours in Lab, for people whose hair is dyed or hidden.
    "black": ("Black", [16, 1, 1]),
    "dark_brown": ("Dark brown", [24, 4, 7]),
    "medium_brown": ("Medium brown", [34, 6, 12]),
    "light_brown": ("Light brown", [45, 6, 15]),
    "ash_brown": ("Ash brown", [40, 2, 7]),
    "dark_blonde": ("Dark blonde", [52, 5, 18]),
    "golden_blonde": ("Golden blonde", [65, 5, 28]),
    "ash_blonde": ("Ash blonde", [66, 1, 11]),
    "red": ("Red / copper", [42, 22, 30]),
    "auburn": ("Auburn", [32, 16, 16]),
    "strawberry_blonde": ("Strawberry blonde", [60, 14, 26]),
    "grey": ("Grey / white", [70, 0, 3]),
}
