"""Product search (SerpAPI Google Shopping) with palette and size matching.

For each result the app downloads the product thumbnail, finds the garment's
main colour, and compares it with the person's seasonal palette. It also
works out which size to buy: from a matching brand size chart when the shop
is one of theirs, otherwise from their general size.

Searches are cached on disk for a day, because the free SerpAPI plan only
allows ~100 searches a month.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

from . import db, settings
from .colour import hex_to_lab, lab_to_hex, rgb_to_lab

SEARCH_URL = "https://serpapi.com/search.json"
ACCOUNT_URL = "https://serpapi.com/account.json"
CACHE_SECONDS = 24 * 3600

COUNTRIES = {
    # SerpAPI `gl` code: label
    "uk": "United Kingdom", "us": "United States", "ie": "Ireland", "ca": "Canada", "au": "Australia",
    "nz": "New Zealand", "de": "Germany", "fr": "France", "es": "Spain", "it": "Italy", "nl": "Netherlands",
}


class ShopError(Exception):
    """Something the person can act on (no key, quota used up, network…)."""


def api_key() -> str | None:
    return settings.get("serpapi_api_key")


def _cache_dir(kind: str) -> Path:
    d = db.db_path().parent / "cache" / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def _http_get(url: str, timeout: float = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Stylist/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _get_json(url: str) -> dict:
    try:
        return json.loads(_http_get(url))
    except urllib.error.HTTPError as e:
        try:
            message = json.loads(e.read()).get("error")
        except (ValueError, AttributeError):
            message = None
        if e.code == 401:
            raise ShopError("SerpAPI rejected the API key. Check it under 'Search API key'.") from e
        if e.code == 429:
            raise ShopError("You've used up your SerpAPI searches for now. Try again later or check your plan.") from e
        raise ShopError(f"The search service returned an error: {message or e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ShopError("Couldn't reach the search service. Check your internet connection.") from e
    except ValueError as e:
        raise ShopError("The search service sent an unreadable response.") from e


# --- search -------------------------------------------------------------------------------


def normalise(item: dict) -> dict | None:
    """One SerpAPI shopping result → the fields the app uses.

    `link` goes to the shop itself when the result has one, otherwise to
    Google's product page; `immersive_api` is SerpAPI's product lookup, used
    later to find the shop and full-size pictures for try-on.
    """
    merchant = item.get("link") if item.get("link") and "google." not in item.get("link", "") else None
    link = merchant or item.get("product_link") or item.get("link")
    if not item.get("title") or not link:
        return None
    price = item.get("extracted_price")
    return {
        "id": str(item.get("product_id") or hashlib.sha1(link.encode()).hexdigest()[:16]),
        "title": item["title"],
        "source": item.get("source") or "",
        "price": item.get("price") or "",
        "value": float(price) if isinstance(price, (int, float)) else None,
        "link": link,
        "merchant_link": merchant,
        "immersive_api": item.get("serpapi_immersive_product_api"),
        "thumbnail": item.get("thumbnail"),
        "rating": item.get("rating"),
        "reviews": item.get("reviews"),
        "delivery": item.get("delivery"),
    }


def search(query: str, country: str = "uk") -> tuple[list[dict], bool]:
    """Returns (products, from_cache)."""
    key = api_key()
    if not key:
        raise ShopError("Add a SerpAPI key to search shops (free plan: ~100 searches a month).")
    params = {"engine": "google_shopping", "q": query, "gl": country, "hl": "en", "api_key": key}
    cache = _cache_dir("search") / (hashlib.sha1(json.dumps([query, country]).encode()).hexdigest() + ".json")
    if cache.exists() and time.time() - cache.stat().st_mtime < CACHE_SECONDS:
        return json.loads(cache.read_text()), True
    data = _get_json(f"{SEARCH_URL}?{urllib.parse.urlencode(params)}")
    if data.get("error"):
        if "hasn't returned any results" in data["error"]:
            data = {}
        else:
            raise ShopError(f"The search service returned an error: {data['error']}")
    products = [p for p in (normalise(i) for i in data.get("shopping_results", [])) if p]
    cache.write_text(json.dumps(products))
    return products, False


def searches_left() -> int | None:
    key = api_key()
    if not key:
        return None
    try:
        return _get_json(f"{ACCOUNT_URL}?{urllib.parse.urlencode({'api_key': key})}").get("total_searches_left")
    except ShopError:
        return None


# --- product colour ---------------------------------------------------------------------------


def fetch_thumbnail(url: str) -> bytes | None:
    """Thumbnail bytes, cached on disk (they're also used for try-on later)."""
    if not url:
        return None
    if url.startswith("data:image"):
        try:
            return base64.b64decode(url.split(",", 1)[1])
        except (IndexError, ValueError):
            return None
    cache = _cache_dir("thumbs") / hashlib.sha1(url.encode()).hexdigest()
    if cache.exists():
        return cache.read_bytes()
    try:
        data = _http_get(url, timeout=8)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    cache.write_bytes(data)
    return data


def _kmeans(x: np.ndarray, k: int = 3, iters: int = 12) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(0)
    centres = x[rng.choice(len(x), size=min(k, len(x)), replace=False)]
    for _ in range(iters):
        labels = np.argmin(((x[:, None, :] - centres[None]) ** 2).sum(-1), axis=1)
        centres = np.array([x[labels == i].mean(0) if np.any(labels == i) else centres[i] for i in range(len(centres))])
    return centres, np.bincount(labels, minlength=len(centres))


def dominant_colour(image_bytes: bytes) -> list[float] | None:
    """Main garment colour (Lab) of a product photo.

    Product shots are usually a garment on a plain background, so: take the
    central area, drop pixels close to the background colour (read from the
    border), cluster the rest, and return the biggest cluster.
    """
    try:
        im = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return None
    im.thumbnail((120, 120))
    rgb = np.asarray(im, dtype=np.float64)
    h, w, _ = rgb.shape
    lab = rgb_to_lab(rgb)
    border = np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])
    bg = np.median(border, axis=0)
    centre = lab[int(h * 0.15):int(h * 0.9), int(w * 0.2):int(w * 0.8)].reshape(-1, 3)
    garment = centre[np.linalg.norm(centre - bg, axis=1) > 12]
    if len(garment) < 30:  # garment fills the frame, or matches the background
        garment = centre
    centres, counts = _kmeans(garment)
    return [round(float(v), 2) for v in centres[np.argmax(counts)]]


# --- palette & size ----------------------------------------------------------------------------

MATCH_RANK = {"great": 0, "good": 1, "unknown": 2, "off": 3, "avoid": 4}


def palette_match(lab, palette: dict | None) -> dict:
    if lab is None or not palette:
        return {"label": "unknown"}
    wearable = palette["neutrals"] + palette["colours"] + palette["accents"]
    # Lightness differences matter less than hue/chroma for "is this my colour?",
    # and photos shift lightness a lot, so L* is down-weighted.
    def dist(hex_colour):
        L2, a2, b2 = hex_to_lab(hex_colour)
        return float(np.sqrt(((lab[0] - L2) * 0.5) ** 2 + (lab[1] - a2) ** 2 + (lab[2] - b2) ** 2))

    best = min(wearable, key=dist)
    d_best = dist(best)
    worst = min(palette["avoid"], key=dist)
    d_avoid = dist(worst)
    if d_avoid < 10 and d_avoid < d_best:
        label = "avoid"
    elif d_best <= 10:
        label = "great"
    elif d_best <= 20:
        label = "good"
    else:
        label = "off"
    return {"label": label, "nearest": best, "distance": round(d_best, 1)}


STOPWORDS = {"anything", "nothing", "things", "stuff", "really", "very", "with", "without", "that", "this",
             "those", "these", "wear", "wearing", "like", "dont", "don't", "won't", "wont", "never", "much",
             "too", "and", "the", "any", "all", "not", "also"}


def dislike_words(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z'-]+", (text or "").lower())
    return {w for w in words if len(w) >= 4 and w not in STOPWORDS}


def flagged(title: str, words: set[str]) -> list[str]:
    t = title.lower()
    return sorted(w for w in words if re.search(rf"\b{re.escape(w.rstrip('s'))}", t))


def brand_chart(product: dict, charts: list[dict], garment: str, sections: list[str]) -> dict | None:
    """A size chart whose brand appears in the shop name or product title."""
    hay = f"{product['source']} {product['title']}".lower()
    for chart in charts:
        if chart["garment"] != garment or chart.get("section") not in sections:
            continue
        brand = chart["brand"].lower()
        if "(starter)" in brand:
            continue
        if re.search(rf"\b{re.escape(brand)}\b", hay):
            return chart
    return None


def rank(products: list[dict]) -> list[dict]:
    """Palette match first, then fewer dislike flags, keeping search order otherwise."""
    return sorted(products, key=lambda p: (MATCH_RANK[p["colour"]["label"]], len(p["flags"]), p["position"]))


def annotate(products: list[dict], palette: dict | None) -> None:
    """Add colour information to each product (thumbnails fetched in parallel)."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        images = list(pool.map(lambda p: fetch_thumbnail(p.get("thumbnail")), products))
    for p, img in zip(products, images):
        lab = dominant_colour(img) if img else None
        p["colour"] = palette_match(lab, palette)
        if lab is not None:
            p["colour"]["hex"] = lab_to_hex(lab)
            p["colour"]["lab"] = lab

