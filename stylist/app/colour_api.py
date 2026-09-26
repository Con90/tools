"""Colour-analysis endpoints: upload photos, adjust samples, get the season."""

from __future__ import annotations

import io
import uuid
from typing import Literal

import numpy as np
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from PIL import Image
from pydantic import BaseModel, Field

from . import db, face
from .colour import lab_to_hex, lch, linear_to_lab, white_gains
from .seasons import NATURAL_HAIR, SEASONS, describe_scores, rank_seasons, scores

router = APIRouter()

MAX_UPLOAD = 25 * 1024 * 1024
Feature = Literal["skin", "hair", "eyes", "white"]


def _found(row):
    if row is None:
        raise HTTPException(404, "not found")
    return row


def _load_image(photo: dict) -> np.ndarray:
    return np.array(Image.open(db.photos_dir() / photo["filename"]).convert("RGB"))


def _analyse(img: np.ndarray) -> dict:
    try:
        return face.analyse(img)
    except face.AnalysisError as e:
        return {"error": str(e), "samples": {}, "points": {}, "warnings": []}


# --- per-photo colours ----------------------------------------------------------------


def photo_colours(photo: dict) -> dict:
    """Final Lab colour per feature for one photo, after manual picks and white balance."""
    analysis, manual = photo["analysis"], photo["manual"]
    white = manual.get("white")
    gains = white_gains(white["sample"]) if white and white.get("sample") else np.ones(3)
    out = {}
    for feature in face.FEATURES:
        if feature in manual and manual[feature].get("sample"):
            lin, source = manual[feature]["sample"], "picked"
        else:
            lin, source = analysis.get("samples", {}).get(feature), "auto"
        if lin is None:
            continue
        lab = linear_to_lab(np.array(lin) * gains)
        out[feature] = {"lab": [round(float(v), 2) for v in lab], "hex": lab_to_hex(lab), "source": source}
    return out


def _photo_out(photo: dict) -> dict:
    a = photo["analysis"]
    points = {k: v for k, v in a.get("points", {}).items()}
    for feature, pick in photo["manual"].items():
        points[feature] = [pick["point"]]
    return {
        "id": photo["id"], "width": photo["width"], "height": photo["height"],
        "included": bool(photo["included"]), "error": a.get("error"),
        "warnings": a.get("warnings", []), "points": points, "face_box": a.get("face_box"),
        "white_balanced": "white" in photo["manual"],
        "colours": photo_colours(photo),
    }


# --- summary across photos --------------------------------------------------------------


def colour_summary(profile: dict) -> dict:
    settings = profile.get("colour") or {}
    photos = [p for p in db.list_photos(profile["id"]) if p["included"]]
    per_feature: dict[str, list] = {f: [] for f in face.FEATURES}
    for p in photos:
        for feature, c in photo_colours(p).items():
            per_feature[feature].append(c["lab"])

    features = {}
    for feature, labs in per_feature.items():
        if labs:
            lab = np.median(np.array(labs), axis=0)
            features[feature] = {"lab": [round(float(v), 2) for v in lab], "hex": lab_to_hex(lab),
                                 "photos": len(labs), "source": "photos"}
    hair_key = settings.get("natural_hair")
    if hair_key in NATURAL_HAIR:
        label, lab = NATURAL_HAIR[hair_key]
        features["hair"] = {"lab": lab, "hex": lab_to_hex(lab), "photos": 0, "source": f"natural hair: {label}"}

    result = {"photos": len(photos), "features": features, "settings": settings,
              "season": settings.get("season_override")}
    if "skin" in features:
        s = scores(features["skin"]["lab"],
                   features.get("hair", {}).get("lab"), features.get("eyes", {}).get("lab"))
        ranked = rank_seasons(s)
        result.update({
            "scores": s,
            "words": describe_scores(s),
            "ranked": [{**r, "name": SEASONS[r["season"]]["name"]} for r in ranked[:4]],
            "auto_season": ranked[0]["season"],
        })
        result["season"] = result["season"] or ranked[0]["season"]
        # Some context the UI shows next to each measured colour.
        result["details"] = {f: dict(zip(("L", "C", "h"), (round(v, 1) for v in lch(features[f]["lab"]))))
                             for f in features}
    if result["season"]:
        result["palette"] = {"key": result["season"], **SEASONS[result["season"]]}
    return result


# --- routes ----------------------------------------------------------------------------------


@router.get("/api/seasons")
def list_seasons():
    return {"seasons": SEASONS, "natural_hair": {k: label for k, (label, _) in NATURAL_HAIR.items()}}


@router.get("/api/profiles/{pid}/photos")
def list_photos(pid: int):
    _found(db.get_row("profiles", pid))
    return [_photo_out(p) for p in db.list_photos(pid)]


@router.post("/api/profiles/{pid}/photos", status_code=201)
async def upload_photo(pid: int, request: Request):
    _found(db.get_row("profiles", pid))
    data = await request.body()
    if not data:
        raise HTTPException(400, "empty upload")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "That photo is too large (25 MB max).")
    try:
        im = face.load_upload(data)
    except face.AnalysisError as e:
        raise HTTPException(422, str(e)) from e
    filename = f"{uuid.uuid4().hex}.jpg"
    im.save(db.photos_dir() / filename, "JPEG", quality=92)
    analysis = _analyse(np.array(im))
    photo = db.create_row("photos", {"profile_id": pid, "filename": filename, "width": im.width,
                                     "height": im.height, "analysis": analysis, "manual": {}})
    return _photo_out(photo)


@router.get("/api/photos/{photo_id}/image")
def photo_image(photo_id: int):
    photo = _found(db.get_row("photos", photo_id))
    return FileResponse(db.photos_dir() / photo["filename"], media_type="image/jpeg")


@router.get("/api/photos/{photo_id}/face")
def photo_face(photo_id: int, size: int = 320):
    """Square-ish crop around the face, for colour comparisons."""
    photo = _found(db.get_row("photos", photo_id))
    im = Image.open(db.photos_dir() / photo["filename"])
    box = photo["analysis"].get("face_box")
    if box:
        im = im.crop((int(box[0] * im.width), int(box[1] * im.height),
                      int(box[2] * im.width), int(box[3] * im.height)))
    im.thumbnail((size, size))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return Response(buf.getvalue(), media_type="image/jpeg")


class Pick(BaseModel):
    feature: Feature
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


@router.post("/api/photos/{photo_id}/pick")
def pick(photo_id: int, body: Pick):
    photo = _found(db.get_row("photos", photo_id))
    sample = face.sample_point(_load_image(photo), body.x, body.y, body.feature)
    if sample is None:
        raise HTTPException(422, "Couldn't sample there. Try a spot further from the edge.")
    manual = {**photo["manual"], body.feature: {"point": [body.x, body.y], "sample": sample}}
    return _photo_out(db.update_row("photos", photo_id, {"manual": manual}))


@router.delete("/api/photos/{photo_id}/pick/{feature}")
def unpick(photo_id: int, feature: Feature):
    photo = _found(db.get_row("photos", photo_id))
    manual = {k: v for k, v in photo["manual"].items() if k != feature}
    return _photo_out(db.update_row("photos", photo_id, {"manual": manual}))


class PhotoPatch(BaseModel):
    included: bool


@router.patch("/api/photos/{photo_id}")
def patch_photo(photo_id: int, body: PhotoPatch):
    _found(db.get_row("photos", photo_id))
    return _photo_out(db.update_row("photos", photo_id, {"included": int(body.included)}))


@router.delete("/api/photos/{photo_id}", status_code=204)
def delete_photo(photo_id: int):
    photo = _found(db.get_row("photos", photo_id))
    (db.photos_dir() / photo["filename"]).unlink(missing_ok=True)
    db.delete_row("photos", photo_id)


@router.get("/api/profiles/{pid}/colour")
def get_colour(pid: int):
    return colour_summary(_found(db.get_row("profiles", pid)))


class ColourSettings(BaseModel):
    season_override: str | None = None
    natural_hair: str | None = None


@router.put("/api/profiles/{pid}/colour")
def put_colour(pid: int, body: ColourSettings):
    profile = _found(db.get_row("profiles", pid))
    if body.season_override and body.season_override not in SEASONS:
        raise HTTPException(422, "unknown season")
    if body.natural_hair and body.natural_hair not in NATURAL_HAIR:
        raise HTTPException(422, "unknown hair colour")
    settings = {k: v for k, v in body.model_dump().items() if v}
    profile = db.update_row("profiles", pid, {"colour": settings})
    return colour_summary(profile)


def delete_profile_photos(pid: int) -> None:
    for photo in db.list_photos(pid):
        (db.photos_dir() / photo["filename"]).unlink(missing_ok=True)
        db.delete_row("photos", photo["id"])
