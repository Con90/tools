"""Personal style brief written by Claude.

Everything the app has measured (body shape, proportions, colour season,
contrast) plus the person's stated preferences goes to Claude, which returns a
structured brief: style directions, outfit formulas in their palette, and a
shopping list with search terms (used later for product search).

Only this summary is sent, never measurements beyond what's listed below,
and a photo only if the person ticks "include a photo".
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from . import settings

MODEL = "claude-opus-5"
# Server-side refusal fallback: if the model declines, the API re-runs the
# request on Anthropic's recommended fallback model instead of failing.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class BriefError(Exception):
    """Something the person can act on (no key, network, refusal…)."""


# --- API key ------------------------------------------------------------------------------


def saved_key() -> str | None:
    return settings.get("anthropic_api_key")


def save_key(key: str | None) -> None:
    settings.put("anthropic_api_key", key)


def key_status() -> dict:
    if saved_key():
        return {"configured": True, "source": "saved in the app"}
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return {"configured": True, "source": "environment"}
    return {"configured": False, "source": None}


def _client():
    try:
        import anthropic
    except ImportError as e:  # pragma: no cover
        raise BriefError("The 'anthropic' package isn't installed (pip install -r requirements.txt).") from e
    key = saved_key()
    # With no key saved, the SDK falls back to ANTHROPIC_API_KEY or an `ant auth login` profile.
    return anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()


# --- prompt ---------------------------------------------------------------------------------

SYSTEM = """You are an experienced personal stylist writing a style brief for one client.

You're given what an app has measured about them (body shape and proportions, their
seasonal colour type and palette, how much contrast their colouring has) and what they
told you about their life and taste. Build on that analysis rather than contradicting it,
and make the advice specific to this person: name actual garments, cuts, fabrics and
colours, and say briefly why each suits them.

Guidelines:
- Respect their preferences, lifestyle, budget and dislikes. If they dislike something,
  don't recommend it.
- Use colours from their palette. Give each colour a plain name and the hex value from
  the palette you were given.
- Be body-positive. Talk about balance and proportion; never about hiding or fixing a body.
- Outfits should be realistic for their stated occasions and budget.
- Shopping list search queries should be what you'd type into a shop's search box:
  garment, cut, colour and fabric, no brand names unless they asked for brands.
- Plain, warm language. No filler."""

SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "One-line summary of their style, e.g. 'Soft tailoring in warm earth tones'"},
        "summary": {"type": "string", "description": "2-4 sentences tying together shape, colouring and preferences"},
        "directions": {
            "type": "array",
            "description": "2-3 style directions that suit them",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "why_it_suits_you": {"type": "string"},
                    "signature_pieces": {"type": "array", "items": {"type": "string"}},
                    "avoid": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "description", "why_it_suits_you", "signature_pieces", "avoid"],
                "additionalProperties": False,
            },
        },
        "outfits": {
            "type": "array",
            "description": "4-6 outfit formulas for their occasions",
            "items": {
                "type": "object",
                "properties": {
                    "occasion": {"type": "string"},
                    "name": {"type": "string"},
                    "pieces": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "item": {"type": "string"},
                                "colour_name": {"type": "string"},
                                "colour_hex": {"type": "string"},
                            },
                            "required": ["item", "colour_name", "colour_hex"],
                            "additionalProperties": False,
                        },
                    },
                    "styling_note": {"type": "string"},
                },
                "required": ["occasion", "name", "pieces", "styling_note"],
                "additionalProperties": False,
            },
        },
        "shopping_list": {
            "type": "array",
            "description": "8-12 pieces to look for, most useful first",
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "string"},
                    "category": {"type": "string", "enum": ["tops", "knitwear", "outerwear", "dresses", "bottoms",
                                                            "skirts", "shoes", "accessories"]},
                    "colour_name": {"type": "string"},
                    "colour_hex": {"type": "string"},
                    "why": {"type": "string"},
                    "search_query": {"type": "string"},
                },
                "required": ["item", "category", "colour_name", "colour_hex", "why", "search_query"],
                "additionalProperties": False,
            },
        },
        "fit_notes": {"type": "array", "items": {"type": "string"},
                      "description": "3-6 short fit tips specific to their shape and proportions"},
    },
    "required": ["headline", "summary", "directions", "outfits", "shopping_list", "fit_notes"],
    "additionalProperties": False,
}


def build_prompt(facts: dict) -> str:
    """The client profile Claude sees, as readable text."""
    lines = ["Client profile:"]
    lines.append(f"- Shops: {facts['section']}")
    if facts.get("shape"):
        s = facts["shape"]
        lines.append(f"- Body shape: {s['name']}{' (' + s['variant'] + ')' if s.get('variant') else ''}"
                     f"{' (estimated from their usual sizes)' if s.get('estimated') else ''}. {s['summary']}")
        lines.append(f"  Styling goal for this shape: {s['goal']}")
    for tip in facts.get("proportions", []):
        lines.append(f"- {tip}")
    if facts.get("season"):
        c = facts["season"]
        lines.append(f"- Colour season: {c['name']}. {c['summary']}")
        lines.append(f"  Palette neutrals: {', '.join(c['neutrals'])}")
        lines.append(f"  Palette colours: {', '.join(c['colours'])}")
        lines.append(f"  Accents: {', '.join(c['accents'])}")
        lines.append(f"  Harder to wear: {', '.join(c['avoid'])}")
        lines.append(f"  Metals: {c['metals']}")
    for tip in facts.get("colour_tips", []):
        lines.append(f"- {tip}")
    prefs = facts.get("preferences") or {}
    lines.append("")
    lines.append("What they told you:")
    labels = {"lifestyle": "Their week involves", "vibes": "Style words they like", "budget": "Budget",
              "loves": "Pieces they love wearing", "dislikes": "Dislikes / won't wear", "notes": "Anything else"}
    for key, label in labels.items():
        v = prefs.get(key)
        if v:
            lines.append(f"- {label}: {', '.join(v) if isinstance(v, list) else v}")
    if facts.get("photo_attached"):
        lines.append("")
        lines.append("A photo of them is attached, for overall impression (hair, features, colouring).")
    lines.append("")
    lines.append("Write their style brief.")
    return "\n".join(lines)


def _photo_block(path: Path) -> dict:
    im = Image.open(path).convert("RGB")
    im.thumbnail((1024, 1024))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.standard_b64encode(buf.getvalue()).decode("ascii")}}


HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _clean(brief: dict) -> dict:
    """Guard against malformed colours so the UI can use them as CSS directly."""
    def fix(entry):
        if not isinstance(entry.get("colour_hex"), str) or not HEX.match(entry["colour_hex"]):
            entry["colour_hex"] = None

    for outfit in brief.get("outfits", []):
        for piece in outfit.get("pieces", []):
            fix(piece)
    for item in brief.get("shopping_list", []):
        fix(item)
    return brief


def generate(facts: dict, photo_path: Path | None = None, client=None) -> dict:
    """Ask Claude for the brief. Returns the brief plus usage metadata."""
    import anthropic

    client = client or _client()
    facts = {**facts, "photo_attached": photo_path is not None}
    content = ([_photo_block(photo_path)] if photo_path else []) + [{"type": "text", "text": build_prompt(facts)}]
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            messages=[{"role": "user", "content": content}],
            thinking={"type": "adaptive"},
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as e:
        raise BriefError("Your Anthropic API key was rejected. Check it under 'Claude API key'.") from e
    except anthropic.PermissionDeniedError as e:
        raise BriefError("This API key isn't allowed to use the model. Check your Anthropic Console settings.") from e
    except anthropic.RateLimitError as e:
        raise BriefError("Rate limited by the Anthropic API. Try again in a minute.") from e
    except anthropic.APIStatusError as e:
        raise BriefError(f"The Anthropic API returned an error ({e.status_code}). Try again later.") from e
    except anthropic.APIConnectionError as e:
        raise BriefError("Couldn't reach the Anthropic API. Check your internet connection.") from e
    except TypeError as e:  # e.g. no credentials configured at all
        raise BriefError("No Anthropic API key found. Add one under 'Claude API key'.") from e

    if response.stop_reason == "refusal":
        raise BriefError("Claude declined to write this brief. Try rewording your notes.")
    if response.stop_reason == "max_tokens":
        raise BriefError("The brief was cut off before it finished. Please try again.")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise BriefError("Claude returned an empty response. Please try again.")
    try:
        brief = json.loads(text)
    except ValueError as e:
        raise BriefError("Claude's response couldn't be read. Please try again.") from e

    usage = response.usage
    return {
        "brief": _clean(brief),
        "model": response.model,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "usage": {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens},
        "photo_included": photo_path is not None,
    }
