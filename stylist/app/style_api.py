"""Style endpoints: body-shape guide, preferences, and the Claude style brief."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import body, brief, db
from .colour_api import colour_summary
from .estimate import body_for
from .seasons import SEASONS

router = APIRouter()

LIFESTYLE = ["Office / business", "Smart casual work", "Creative work", "Working from home", "Active / outdoors",
             "Parenting / on my feet", "Evenings out", "Formal events", "Travel", "Student"]
VIBES = ["Classic", "Minimal", "Relaxed", "Romantic", "Edgy", "Sporty", "Bohemian", "Preppy", "Streetwear",
         "Elegant", "Playful", "Rugged", "Vintage", "Androgynous"]
BUDGETS = ["Budget / high street", "Mid-range", "Premium", "Mix of high and low"]


def _found(row):
    if row is None:
        raise HTTPException(404, "not found")
    return row


def shape_measurements(profile: dict) -> tuple[dict, bool]:
    """Chest/waist from the tops view of the body, hips and legs from the bottoms
    view, so quick-mode estimates use the most relevant usual size for each."""
    top, top_src = body_for(profile, "tops")
    bottom, bottom_src = body_for(profile, "bottoms")
    measured = profile.get("measurements", {}) if profile.get("mode") == "detailed" else {}
    merged = {"chest": top.get("chest"), "waist": top.get("waist") or bottom.get("waist"),
              "hips": bottom.get("hips") or top.get("hips"),
              "inseam": bottom.get("inseam"), "height": measured.get("height")}
    estimated = any(k in top_src for k in ("chest", "waist")) or "hips" in bottom_src
    return {k: v for k, v in merged.items() if v}, estimated


def style_guide(profile: dict) -> dict:
    gender = profile.get("gender", "female")
    settings = profile.get("style") or {}
    measurements, estimated = shape_measurements(profile)
    auto = body.classify(gender, measurements)
    shape_key = settings.get("shape_override") or (auto or {}).get("shape")
    shape = None
    if shape_key in body.SHAPES[gender]:
        shape = {"key": shape_key, **body.SHAPES[gender][shape_key],
                 "variant": None if settings.get("shape_override") else (auto or {}).get("variant"),
                 "estimated": estimated and not settings.get("shape_override"),
                 "overridden": bool(settings.get("shape_override"))}

    props = body.proportions(gender, measurements)
    prop_tips = [body.PROPORTION_TIPS[v] for k in ("height", "legs") if (v := props.get(k)) in body.PROPORTION_TIPS]

    colour = colour_summary(profile)
    colour_tips = []
    level = body.contrast_level(colour.get("features", {}))
    if level:
        colour_tips.append(body.CONTRAST_TIPS[level])
    scores = colour.get("scores") or {}
    if abs(scores.get("clarity", 0)) > 0.25:
        colour_tips.append(body.CLARITY_TIPS["bright" if scores["clarity"] > 0 else "soft"])
    if abs(scores.get("depth", 0)) > 0.35:
        colour_tips.append(body.DEPTH_TIPS["deep" if scores["depth"] > 0 else "light"])

    return {
        "gender": gender,
        "shape": shape,
        "auto_shape": (auto or {}).get("shape"),
        "shape_options": {k: v["name"] for k, v in body.SHAPES[gender].items()},
        "measurements": measurements,
        "proportions": props,
        "proportion_tips": prop_tips,
        "season": colour.get("season"),
        "contrast": level,
        "colour_tips": colour_tips,
        "preferences": settings.get("preferences", {}),
        "brief": settings.get("brief"),
        "options": {"lifestyle": LIFESTYLE, "vibes": VIBES, "budget": BUDGETS},
        "api": brief.key_status(),
        "has_photo": any(p["included"] for p in db.list_photos(profile["id"])),
    }


def brief_facts(guide: dict) -> dict:
    """The summary sent to Claude: derived facts and stated preferences only."""
    gender = guide["gender"]
    facts = {
        "section": "women's clothing" if gender == "female" else "men's clothing",
        "shape": guide["shape"],
        "proportions": guide["proportion_tips"],
        "colour_tips": guide["colour_tips"],
        "preferences": guide["preferences"],
    }
    if guide["season"]:
        facts["season"] = SEASONS[guide["season"]]
    return facts


@router.get("/api/profiles/{pid}/style")
def get_style(pid: int):
    return style_guide(_found(db.get_row("profiles", pid)))


class Preferences(BaseModel):
    lifestyle: list[str] = []
    vibes: list[str] = []
    budget: str | None = None
    loves: str = Field(default="", max_length=500)
    dislikes: str = Field(default="", max_length=500)
    notes: str = Field(default="", max_length=1000)


class StyleSettings(BaseModel):
    preferences: Preferences = Preferences()
    shape_override: str | None = None


@router.put("/api/profiles/{pid}/style")
def put_style(pid: int, body_in: StyleSettings):
    profile = _found(db.get_row("profiles", pid))
    if body_in.shape_override and body_in.shape_override not in body.SHAPES[profile.get("gender", "female")]:
        raise HTTPException(422, "unknown body shape")
    style = {**(profile.get("style") or {}), "preferences": body_in.preferences.model_dump(),
             "shape_override": body_in.shape_override}
    return style_guide(db.update_row("profiles", pid, {"style": style}))


class BriefRequest(BaseModel):
    include_photo: bool = False


@router.post("/api/profiles/{pid}/style/brief")
def make_brief(pid: int, req: BriefRequest):
    profile = _found(db.get_row("profiles", pid))
    guide = style_guide(profile)
    photo_path = None
    if req.include_photo:
        photo = next((p for p in db.list_photos(pid) if p["included"]), None)
        if not photo:
            raise HTTPException(422, "There's no photo to include. Add one in the Colours tab, or untick the photo option.")
        photo_path = db.photos_dir() / photo["filename"]
    try:
        result = brief.generate(brief_facts(guide), photo_path)
    except brief.BriefError as e:
        raise HTTPException(502, str(e)) from e
    style = {**(profile.get("style") or {}), "brief": result}
    return style_guide(db.update_row("profiles", pid, {"style": style}))


@router.get("/api/settings/anthropic-key")
def key_status():
    return brief.key_status()


class KeyIn(BaseModel):
    key: str | None = Field(default=None, max_length=300)


@router.put("/api/settings/anthropic-key")
def set_key(body_in: KeyIn):
    key = (body_in.key or "").strip() or None
    if key and not key.startswith("sk-ant-"):
        raise HTTPException(422, "That doesn't look like an Anthropic API key (they start with sk-ant-).")
    brief.save_key(key)
    return brief.key_status()
