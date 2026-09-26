"""Shop endpoints: search with palette/size matching, saved items, search key."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import db, settings, shop
from .colour_api import colour_summary
from .estimate import body_for
from .seasons import SEASONS
from .sizing import GARMENTS, match_all, match_chart

router = APIRouter()

GENERAL_FALLBACK = {"outerwear": ("tops",), "knitwear": ("tops",), "skirts": ("bottoms",), "dresses": ("tops",)}


def _found(row):
    if row is None:
        raise HTTPException(404, "not found")
    return row


def _gender_words(query: str, gender: str) -> str:
    """Add "women's"/"men's" unless the query already says who it's for."""
    if any(w in query.lower() for w in ("women", "woman", "ladies", "men's", "mens ", " men", "unisex", "girl", "boy")):
        return query
    return f"{'women' if gender == 'female' else 'men'}'s {query}"


def _sizes(profile: dict, garment: str):
    """General size (from the starter charts) plus a function giving the size
    for a product whose shop or title names one of the person's brand charts."""
    body, sources = body_for(profile, garment) if garment in GARMENTS else ({}, {})
    if not body:
        return None, lambda product: None
    charts = db.list_rows("size_charts")
    args = (profile["fit"], profile["gender"], sources)
    general = None
    # No starter chart for, say, women's coats: fall back to the closest garment's sizing.
    for g in (garment, *GENERAL_FALLBACK.get(garment, ())):
        results = match_all(charts, body, g, profile["fit"], profile["sections"], profile["gender"], sources)
        general = next((r for r in results if "(starter)" in r["brand"]), None)
        if general:
            break

    def brand_size(product):
        chart = shop.brand_chart(product, charts, garment, profile["sections"])
        m = chart and match_chart(chart, body, *args)
        return m and {"brand": chart["brand"], "size": m["size"], "verdict": m["verdict"],
                      "length": (m.get("length") or {}).get("label"), "equivalents": m["equivalents"]}

    return general, brand_size


class SearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=150)
    garment: str = "tops"
    country: str = "uk"
    min_price: float | None = Field(default=None, ge=0)
    max_price: float | None = Field(default=None, ge=0)


@router.post("/api/profiles/{pid}/shop/search")
def search(pid: int, req: SearchIn):
    profile = _found(db.get_row("profiles", pid))
    if req.garment not in GARMENTS and req.garment != "accessories":
        raise HTTPException(422, "unknown garment type")
    if req.country not in shop.COUNTRIES:
        raise HTTPException(422, "unknown country")
    query = _gender_words(req.query.strip(), profile["gender"])
    try:
        products, cached = shop.search(query, req.country)
    except shop.ShopError as e:
        raise HTTPException(502, str(e)) from e

    total = len(products)
    products = [p for p in products if p["value"] is None or (
        (req.min_price is None or p["value"] >= req.min_price) and (req.max_price is None or p["value"] <= req.max_price))]

    season = colour_summary(profile).get("season")
    palette = SEASONS.get(season) if season else None
    shop.annotate(products, palette)

    dislikes = shop.dislike_words(((profile.get("style") or {}).get("preferences") or {}).get("dislikes", ""))
    general, brand_size = _sizes(profile, req.garment)
    saved_ids = {s["product"]["id"] for s in db.list_saved(pid)}
    for i, p in enumerate(products):
        p["position"] = i
        p["flags"] = shop.flagged(p["title"], dislikes)
        p["size"] = brand_size(p)
        p["saved"] = p["id"] in saved_ids
        p["garment"] = req.garment

    return {
        "query": query, "cached": cached, "total": total, "shown": len(products),
        "season": palette and {"key": season, "name": palette["name"]},
        "general_size": general and {"size": general["size"], "system": general["size_system"],
                                     "equivalents": general["equivalents"], "estimated": general["estimated"],
                                     "length": (general.get("length") or {}).get("label")},
        "results": shop.rank(products),
    }


# --- saved items ---------------------------------------------------------------------------


class SaveIn(BaseModel):
    product: dict


@router.get("/api/profiles/{pid}/saved")
def list_saved(pid: int):
    _found(db.get_row("profiles", pid))
    return [{**s["product"], "saved_id": s["id"]} for s in db.list_saved(pid)]


@router.post("/api/profiles/{pid}/saved", status_code=201)
def save_item(pid: int, body: SaveIn):
    _found(db.get_row("profiles", pid))
    product = {k: body.product.get(k) for k in ("id", "title", "source", "price", "value", "link", "thumbnail",
                                                "colour", "size", "garment")}
    if not product["id"] or not product["title"] or not product["link"]:
        raise HTTPException(422, "product needs an id, title and link")
    existing = next((s for s in db.list_saved(pid) if s["product"]["id"] == product["id"]), None)
    row = existing or db.create_row("saved_items", {"profile_id": pid, "product": product})
    return {**row["product"], "saved_id": row["id"]}


@router.delete("/api/saved/{item_id}", status_code=204)
def delete_saved(item_id: int):
    if not db.delete_row("saved_items", item_id):
        raise HTTPException(404, "not found")


# --- settings ---------------------------------------------------------------------------------


@router.get("/api/settings/serpapi")
def serpapi_status(check: bool = False):
    configured = bool(shop.api_key())
    return {"configured": configured, "countries": shop.COUNTRIES,
            "country": settings.get("shop_country", "uk"),
            "searches_left": shop.searches_left() if configured and check else None}


class SerpKeyIn(BaseModel):
    key: str | None = Field(default=None, max_length=200)
    country: str | None = None


@router.put("/api/settings/serpapi")
def set_serpapi(body: SerpKeyIn):
    if body.key is not None:
        key = body.key.strip()
        if key and not key.isalnum():
            raise HTTPException(422, "That doesn't look like a SerpAPI key (letters and numbers only).")
        settings.put("serpapi_api_key", key or None)
    if body.country:
        if body.country not in shop.COUNTRIES:
            raise HTTPException(422, "unknown country")
        settings.put("shop_country", body.country)
    return serpapi_status()


def delete_profile_saved(pid: int) -> None:
    for s in db.list_saved(pid):
        db.delete_row("saved_items", s["id"])
