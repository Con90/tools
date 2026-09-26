"""Try-on endpoints: body photos, running a try-on, results gallery, FASHN key."""

from __future__ import annotations

import io
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from PIL import Image
from pydantic import BaseModel, Field

from . import db, face, garments, settings, tryon

router = APIRouter()

MAX_UPLOAD = 25 * 1024 * 1024


def _found(row):
    if row is None:
        raise HTTPException(404, "not found")
    return row


def _tryon_dir():
    d = db.db_path().parent / "tryons"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _tryon_out(t: dict) -> dict:
    return {"id": t["id"], "photo_id": t["photo_id"], "created_at": t["created_at"], **t["meta"]}


# --- body photos -------------------------------------------------------------------------


@router.get("/api/profiles/{pid}/body-photos")
def body_photos(pid: int):
    _found(db.get_row("profiles", pid))
    return [{"id": p["id"], "width": p["width"], "height": p["height"]} for p in db.list_photos(pid, kind="body")]


@router.post("/api/profiles/{pid}/body-photos", status_code=201)
async def upload_body_photo(pid: int, request: Request):
    _found(db.get_row("profiles", pid))
    data = await request.body()
    if not data or len(data) > MAX_UPLOAD:
        raise HTTPException(413 if data else 400, "Upload a photo up to 25 MB.")
    try:
        im = face.load_upload(data)
    except face.AnalysisError as e:
        raise HTTPException(422, str(e)) from e
    filename = f"{uuid.uuid4().hex}.jpg"
    im.save(db.photos_dir() / filename, "JPEG", quality=92)
    row = db.create_row("photos", {"profile_id": pid, "filename": filename, "width": im.width, "height": im.height,
                                   "analysis": {}, "manual": {}, "kind": "body"})
    return {"id": row["id"], "width": row["width"], "height": row["height"]}


# --- try-on ------------------------------------------------------------------------------------


class TryOnIn(BaseModel):
    photo_id: int
    saved_id: int | None = None
    # Optional better garment picture (data URL), since shop thumbnails are small.
    garment_image: str | None = Field(default=None, max_length=20_000_000)
    garment_type: str | None = None


@router.post("/api/profiles/{pid}/tryons", status_code=201)
def make_tryon(pid: int, req: TryOnIn):
    _found(db.get_row("profiles", pid))
    photo = _found(db.get_row("photos", req.photo_id))
    if photo["profile_id"] != pid:
        raise HTTPException(404, "not found")

    item = None
    if req.saved_id is not None:
        saved = _found(db.get_row("saved_items", req.saved_id))
        item = saved["product"]
    garment_type = req.garment_type or (item or {}).get("garment") or "tops"
    if garment_type not in tryon.CATEGORIES:
        raise HTTPException(422, "Try-on works for tops, coats, knitwear, trousers, skirts and dresses.")

    if req.garment_image:
        try:
            garment = tryon.from_data_url(req.garment_image)
        except tryon.TryOnError as e:
            raise HTTPException(422, "The garment image couldn't be read.") from e
    elif item:
        found = garments.resolve(item)
        if not found:
            raise HTTPException(422, "Couldn't get a picture of this product from the shop. Upload one instead.")
        garment = found["image"]
    else:
        raise HTTPException(422, "Choose a saved item or upload a garment image.")

    try:
        tryon.check_image(garment)
    except tryon.TryOnError as e:
        raise HTTPException(422, str(e)) from e
    person = (db.photos_dir() / photo["filename"]).read_bytes()
    try:
        result = tryon.run(person, garment, garment_type)
    except tryon.TryOnError as e:
        raise HTTPException(502, str(e)) from e

    filename = f"{uuid.uuid4().hex}.jpg"
    (_tryon_dir() / filename).write_bytes(result["image"])
    meta = {"garment_type": garment_type, "credits_used": result["credits_used"],
            "item": item and {k: item.get(k) for k in ("title", "link", "source", "price", "thumbnail")},
            "custom_garment": bool(req.garment_image)}
    row = db.create_row("tryons", {"profile_id": pid, "photo_id": photo["id"], "filename": filename, "meta": meta})
    return _tryon_out(row)


@router.get("/api/profiles/{pid}/tryons")
def list_tryons(pid: int):
    _found(db.get_row("profiles", pid))
    return [_tryon_out(t) for t in reversed(db.list_tryons(pid))]


@router.get("/api/tryons/{tid}/image")
def tryon_image(tid: int):
    t = _found(db.get_row("tryons", tid))
    return FileResponse(_tryon_dir() / t["filename"], media_type="image/jpeg")


@router.delete("/api/tryons/{tid}", status_code=204)
def delete_tryon(tid: int):
    t = _found(db.get_row("tryons", tid))
    (_tryon_dir() / t["filename"]).unlink(missing_ok=True)
    db.delete_row("tryons", tid)


def delete_profile_tryons(pid: int) -> None:
    for t in db.list_tryons(pid):
        (_tryon_dir() / t["filename"]).unlink(missing_ok=True)
        db.delete_row("tryons", t["id"])


# --- garment pictures ----------------------------------------------------------------------


@router.get("/api/saved/{saved_id}/garment")
def garment_info(saved_id: int):
    """Find (and cache) the clearest picture of a saved product, from the shop's own page if possible."""
    item = _found(db.get_row("saved_items", saved_id))["product"]
    found = garments.resolve(item)
    if not found:
        return {"found": False}
    return {"found": True, "source": found["source"], "width": found["width"], "height": found["height"],
            "clear": min(found["width"], found["height"]) >= garments.MIN_SIDE,
            "url": f"/api/saved/{saved_id}/garment.jpg"}


@router.get("/api/saved/{saved_id}/garment.jpg")
def garment_image(saved_id: int):
    item = _found(db.get_row("saved_items", saved_id))["product"]
    found = garments.resolve(item)
    if not found:
        raise HTTPException(404, "not found")
    fmt = (Image.open(io.BytesIO(found["image"])).format or "JPEG").lower()
    return Response(found["image"], media_type=f"image/{'jpeg' if fmt == 'jpg' else fmt}")


# --- key ---------------------------------------------------------------------------------------


@router.get("/api/settings/fashn")
def fashn_status():
    return tryon.key_status()


class FashnKeyIn(BaseModel):
    key: str | None = Field(default=None, max_length=300)


@router.put("/api/settings/fashn")
def set_fashn(body: FashnKeyIn):
    key = (body.key or "").strip()
    if key and (" " in key or len(key) < 10):
        raise HTTPException(422, "That doesn't look like a FASHN API key.")
    settings.put("fashn_api_key", key or None)
    return tryon.key_status()
