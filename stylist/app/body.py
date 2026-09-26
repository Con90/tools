"""Body shape and proportions from measurements, with styling guidance.

Women's shapes follow the FFIT method (Simmons, Istook & Devarajan, 2004),
which classifies by the differences between bust, waist and hips, with an
extra "apple" category when the waist is as wide as bust and hips. Men's
shapes use the chest-to-waist drop. The guidance is the standard dressing
advice for each shape: the aim is balance, never "hiding" anything.
"""

from __future__ import annotations

# FFIT thresholds are in inches; converted once here.
IN = 2.54


def female_shape(bust: float, waist: float, hips: float) -> tuple[str, str | None]:
    """(shape, variant). FFIT's "bottom hourglass" is reported as a pear with a
    defined waist and "top hourglass" as a top-heavy hourglass, which is how
    most shops and stylists describe them."""
    bh, hb = bust - hips, hips - bust
    bw, hw = bust - waist, hips - waist
    if waist >= 0.9 * bust and waist >= 0.9 * hips:
        return "apple", None
    if bh <= 1 * IN and hb < 3.6 * IN and (bw >= 9 * IN or hw >= 10 * IN):
        return "hourglass", None
    if 3.6 * IN <= hb < 10 * IN and hw >= 9 * IN:
        return "pear", "with a defined waist"
    if 1 * IN < bh < 10 * IN and bw >= 9 * IN:
        return "hourglass", "a little fuller on top"
    if hb >= 3.6 * IN:
        return "pear", None
    if bh >= 3.6 * IN:
        return "inverted_triangle", None
    return "rectangle", None


def male_shape(chest: float, waist: float, hips: float | None = None) -> str:
    drop = chest - waist
    if waist >= chest:
        return "oval"
    if hips is not None and hips - chest >= 5:
        return "triangle"
    if drop >= 20:
        return "inverted_triangle"
    if drop >= 10:
        return "trapezoid"
    return "rectangle"


def proportions(gender: str, body: dict) -> dict:
    """Height class and leg length relative to height, when known."""
    out = {}
    h = body.get("height")
    if h:
        petite, tall = (160, 175) if gender == "female" else (170, 188)
        out["height"] = "petite" if h < petite else "tall" if h > tall else "average"
        if body.get("inseam"):
            ratio = body["inseam"] / h
            out["legs"] = "long" if ratio > 0.47 else "short" if ratio < 0.43 else "balanced"
            out["leg_ratio"] = round(ratio, 3)
    return out


def classify(gender: str, body: dict) -> dict | None:
    """Shape key plus the numbers it was based on, or None if not enough measurements."""
    chest, waist, hips = body.get("chest"), body.get("waist"), body.get("hips")
    if gender == "female":
        if not (chest and waist and hips):
            return None
        shape, variant = female_shape(chest, waist, hips)
    else:
        if not (chest and waist):
            return None
        shape, variant = male_shape(chest, waist, hips), None
    return {"shape": shape, "variant": variant, "measurements": {k: body[k] for k in ("chest", "waist", "hips") if body.get(k)}}


# --- guidance ------------------------------------------------------------------------------

SHAPES = {
    "female": {
        "hourglass": {
            "name": "Hourglass",
            "summary": "Bust and hips are balanced, with a clearly defined waist.",
            "goal": "Follow your curves and mark the waist, so the shape of the clothes matches yours.",
            "wear": ["Wrap dresses and tops", "Belted coats and dresses", "V- and scoop necklines",
                     "High-waisted, straight or bootcut trousers", "Pencil and A-line skirts",
                     "Fitted, stretch or fluid fabrics that drape"],
            "avoid": ["Boxy, shapeless cuts that hide the waist", "Very stiff, bulky fabrics",
                      "Drop waists", "Oversized everything at once (balance one loose piece with one fitted)"],
        },
        "pear": {
            "name": "Pear (triangle)",
            "summary": "Hips are wider than bust and shoulders, often with a defined waist.",
            "goal": "Add width and interest on top and keep lines clean and simple below.",
            "wear": ["Boat, square and off-shoulder necklines", "Structured shoulders and jackets that end at the hip bone",
                     "Colour, pattern and detail on top", "A-line and fit-and-flare skirts and dresses",
                     "Dark, plain trousers with a straight or wide leg", "Belts at the natural waist"],
            "avoid": ["Skinny trousers paired with a clingy top", "Pockets, embellishment or bold prints on the hips",
                      "Tops that end at the widest point of the hips", "Very tapered legs"],
        },
        "inverted_triangle": {
            "name": "Inverted triangle",
            "summary": "Shoulders or bust are broader than the hips.",
            "goal": "Keep the top clean and soft, and add volume and interest below.",
            "wear": ["V-necks and deep scoop necklines", "Raglan or dropped sleeves, soft unstructured shoulders",
                     "Wide-leg trousers, full or A-line skirts", "Prints, colour and detail on the bottom half",
                     "Peplum and wrap tops", "Single-breasted, longer jackets"],
            "avoid": ["Shoulder pads and puffed sleeves", "Boat necks, halters and high necks",
                      "Bold patterns or embellishment on top", "Skinny trousers with a big top"],
        },
        "rectangle": {
            "name": "Rectangle (straight)",
            "summary": "Bust, waist and hips are similar; a straight, athletic line.",
            "goal": "Either create curves (belts, peplums, structure) or lean into long, clean, straight lines.",
            "wear": ["Belted dresses and jackets", "Peplum and wrap tops", "Layers and textures",
                     "Straight and wide-leg trousers, pleated skirts", "Tailored shirts and blazers",
                     "Shift dresses and column silhouettes"],
            "avoid": ["Clingy, shapeless jersey without structure", "Very boxy pieces head to toe"],
        },
        "apple": {
            "name": "Apple (round)",
            "summary": "Fuller through the middle, often with slim legs and arms.",
            "goal": "Create a long vertical line and show off legs and neckline.",
            "wear": ["V-necks and open collars", "Empire lines and tops that skim, not cling",
                     "Long open cardigans, longline jackets", "Straight and bootcut trousers, slim legs",
                     "Structured fabrics with some weight", "Monochrome or tonal outfits"],
            "avoid": ["Belts at the natural waist", "Clingy fabrics around the middle",
                      "Cropped, boxy jackets", "Horizontal stripes across the middle"],
        },
    },
    "male": {
        "inverted_triangle": {
            "name": "Inverted triangle (V)",
            "summary": "Broad shoulders and chest with a narrow waist.",
            "goal": "Keep the top balanced and give the legs enough presence.",
            "wear": ["Slim or tailored (not skin-tight) tops", "V-necks and crew necks",
                     "Straight or relaxed trousers with some leg width", "Unstructured blazers, soft shoulders",
                     "Horizontal detail or texture on the lower half"],
            "avoid": ["Very skinny jeans", "Padded shoulders", "Tight, stretchy tops everywhere"],
        },
        "trapezoid": {
            "name": "Trapezoid",
            "summary": "Shoulders a little broader than the waist; the most balanced men's shape.",
            "goal": "Most cuts work; choose a clean, tailored fit.",
            "wear": ["Tailored shirts and jackets", "Slim-straight trousers", "Most necklines and layers"],
            "avoid": ["Very baggy cuts that hide your proportions"],
        },
        "rectangle": {
            "name": "Rectangle",
            "summary": "Shoulders, chest and waist are similar widths.",
            "goal": "Add shape at the shoulders and create the look of a taper.",
            "wear": ["Structured blazers and jackets with defined shoulders", "Layering (overshirts, gilets)",
                     "Horizontal stripes and chest pockets", "Slim or tapered trousers",
                     "Crew necks and henleys"],
            "avoid": ["Loose, boxy shirts with no structure", "Very low-rise trousers"],
        },
        "triangle": {
            "name": "Triangle",
            "summary": "Hips or waist wider than the chest and shoulders.",
            "goal": "Build up the shoulders and keep the lower half simple.",
            "wear": ["Structured jackets with defined shoulders", "Detail and pattern on the chest",
                     "Straight-leg, darker trousers", "Layers on top"],
            "avoid": ["Skinny trousers", "Tight tops", "Detail on the hips"],
        },
        "oval": {
            "name": "Oval",
            "summary": "Fuller through the middle.",
            "goal": "Create a long, clean vertical line with structure.",
            "wear": ["Structured, single-breasted jackets worn open", "V-necks and open collars",
                     "Vertical patterns and tonal outfits", "Straight trousers with a mid or high rise",
                     "Fabrics with some weight that skim rather than cling"],
            "avoid": ["Clingy knits", "Horizontal stripes", "Very slim fits and very baggy fits alike"],
        },
    },
}

PROPORTION_TIPS = {
    "petite": "Petite: one colour top to bottom (or matching shoes and trousers) lengthens; choose cropped jackets, "
              "high waists and smaller-scale prints; shop petite ranges for sleeve and leg lengths.",
    "tall": "Tall: you carry longer lines, bigger prints and layering well; check sleeve and leg lengths "
            "(tall ranges), and use colour-blocking or belts to break up the length if you like.",
    "long": "Long legs: mid- and low-rise, longer tops and cropped trousers all balance you well.",
    "short": "Shorter legs: high-rise trousers, shoes that match your trousers and tops tucked or ending at the "
             "waist add leg length.",
}


def contrast_level(colour_features: dict) -> str | None:
    """Value contrast between hair, skin and eyes: a big driver of how bold outfits can be."""
    skin = colour_features.get("skin", {}).get("lab")
    others = [colour_features[f]["lab"] for f in ("hair", "eyes") if f in colour_features]
    if not skin or not others:
        return None
    diff = max(abs(skin[0] - o[0]) for o in others)
    return "high" if diff > 45 else "low" if diff < 25 else "medium"


CONTRAST_TIPS = {
    "high": "High contrast colouring: you can wear strong contrasts (black and white, navy and ivory, bold "
            "colour-blocking) without being overpowered. Very low-contrast outfits can look washed out on you.",
    "medium": "Medium contrast colouring: pair a mid-tone with a light or dark (e.g. camel with navy); "
              "avoid extreme black-and-white combinations right next to the face.",
    "low": "Low contrast colouring: tonal, blended outfits (shades of one colour, soft neutrals together) look "
           "harmonious; stark black and white can overpower you.",
}

CLARITY_TIPS = {
    "bright": "Clear colouring: crisp fabrics, clean prints, a bit of shine and saturated colours suit you.",
    "soft": "Soft colouring: matte and textured fabrics (wool, linen, suede), heathered knits and blended, "
            "watercolour-style prints suit you better than shine and hard-edged graphics.",
}

DEPTH_TIPS = {
    "deep": "Deep colouring: richer, darker base colours carry well; pastels work best as small accents.",
    "light": "Light colouring: lighter base colours suit you; keep very dark colours away from the face "
             "or break them up with a lighter scarf or collar.",
}
