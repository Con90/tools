import io
import json
import urllib.error
import urllib.parse

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app import settings, shop
from app.colour import lab_to_hex
from app.main import app
from app.seasons import SEASONS

client = TestClient(app)


def garment_png(colour, background=(255, 255, 255), full=False):
    """A product-style photo: a garment shape on a plain background."""
    im = Image.new("RGB", (200, 240), background)
    d = ImageDraw.Draw(im)
    if full:
        d.rectangle([0, 0, 200, 240], fill=colour)
    else:
        d.polygon([(40, 30), (160, 30), (175, 90), (150, 95), (150, 220), (50, 220), (50, 95), (25, 90)], fill=colour)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


RUST, HOT_PINK, NAVY = (183, 85, 60), (255, 105, 180), (31, 43, 77)

RESULTS = {"shopping_results": [
    {"position": 1, "title": "Women's Hot Pink Cropped Jumper", "product_link": "https://shop/p1", "product_id": "1",
     "source": "Shop A", "price": "£25.00", "extracted_price": 25.0, "thumbnail": "https://img/pink"},
    {"position": 2, "title": "Women's Rust Wrap Dress", "product_link": "https://shop/p2", "product_id": "2",
     "source": "ZARA", "price": "£49.99", "extracted_price": 49.99, "thumbnail": "https://img/rust"},
    {"position": 3, "title": "Women's Navy Midi Dress", "link": "https://shop/p3",
     "source": "Shop C", "price": "£120.00", "extracted_price": 120.0, "thumbnail": "https://img/navy"},
    {"position": 4, "title": "No link, dropped"},
]}
IMAGES = {"https://img/pink": garment_png(HOT_PINK), "https://img/rust": garment_png(RUST),
          "https://img/navy": garment_png(NAVY, full=True)}


class FakeWeb:
    def __init__(self, search_response=RESULTS):
        self.calls = []
        self.search_response = search_response

    def __call__(self, url, timeout=20):
        self.calls.append(url)
        if url.startswith(shop.SEARCH_URL):
            if isinstance(self.search_response, Exception):
                raise self.search_response
            return json.dumps(self.search_response).encode()
        if url.startswith(shop.ACCOUNT_URL):
            return json.dumps({"total_searches_left": 87}).encode()
        return IMAGES[url]


@pytest.fixture
def web(monkeypatch):
    fake = FakeWeb()
    monkeypatch.setattr(shop, "_http_get", fake)
    settings.put("serpapi_api_key", "abc123")
    return fake


# --- units ------------------------------------------------------------------------------------


def test_dominant_colour_ignores_background():
    lab = shop.dominant_colour(garment_png(RUST))
    assert lab_to_hex(lab) in {"#b7553c", "#b7553b", "#b8553c"}
    assert shop.dominant_colour(garment_png(NAVY, full=True)) is not None
    assert shop.dominant_colour(b"not an image") is None


def test_palette_match():
    autumn = SEASONS["true_autumn"]
    rust = shop.dominant_colour(garment_png(RUST))
    pink = shop.dominant_colour(garment_png(HOT_PINK))
    assert shop.palette_match(rust, autumn)["label"] == "great"
    assert shop.palette_match(pink, autumn)["label"] == "avoid"
    assert shop.palette_match(None, autumn) == {"label": "unknown"}
    assert shop.palette_match(rust, None) == {"label": "unknown"}


def test_dislikes():
    words = shop.dislike_words("anything cropped, and no crop tops or heels")
    assert words == {"cropped", "crop", "tops", "heels"}
    assert shop.flagged("Women's Cropped Jumper", {"cropped", "heels"}) == ["cropped"]
    assert shop.flagged("Block heel boots", {"heels"}) == ["heels"]


def test_normalise_prefers_product_link():
    p = shop.normalise({"title": "T", "product_link": "https://a", "link": "https://b", "extracted_price": 10})
    assert p["link"] == "https://a" and p["value"] == 10.0
    assert shop.normalise({"title": "T"}) is None


# --- API --------------------------------------------------------------------------------------


def _profile():
    pid = client.post("/api/profiles", json={
        "name": "S", "gender": "female", "mode": "quick", "sections": ["womens", "unisex"],
        "usual_sizes": {"dresses": {"system": "UK", "size": "12"}}}).json()["id"]
    client.put(f"/api/profiles/{pid}/colour", json={"season_override": "true_autumn"})
    client.put(f"/api/profiles/{pid}/style", json={"preferences": {"dislikes": "anything cropped"}})
    return pid


def _search(pid, **kw):
    return client.post(f"/api/profiles/{pid}/shop/search", json={"query": "midi dress", "garment": "dresses", **kw})


def test_search_ranks_by_palette_and_flags_dislikes(web):
    r = _search(_profile()).json()
    assert r["query"] == "women's midi dress"
    assert "q=women%27s+midi+dress" in web.calls[0] and "gl=uk" in web.calls[0]
    titles = [p["title"] for p in r["results"]]
    assert titles[0] == "Women's Rust Wrap Dress"             # in palette → first
    assert titles[-1] == "Women's Hot Pink Cropped Jumper"     # avoid colour → last
    pink = r["results"][-1]
    assert pink["colour"]["label"] == "avoid" and pink["flags"] == ["cropped"]
    assert r["general_size"]["size"] == "12" and r["general_size"]["equivalents"]["EU"] == "40"
    assert r["total"] == 3 and r["season"]["key"] == "true_autumn"


def test_brand_chart_gives_brand_size(web):
    client.post("/api/charts", json={"brand": "Zara", "section": "womens", "garment": "dresses", "size_system": "EU",
                                     "sizes": [{"label": "38", "ranges": {"chest": [84, 88], "waist": [66, 70], "hips": [92, 96]}},
                                               {"label": "40", "ranges": {"chest": [88, 92], "waist": [70, 74], "hips": [96, 100]}}]})
    r = _search(_profile()).json()
    zara = next(p for p in r["results"] if p["source"] == "ZARA")
    assert zara["size"]["brand"] == "Zara" and zara["size"]["size"] == "40"
    assert all(p["size"] is None for p in r["results"] if p["source"] != "ZARA")


def test_price_filter_and_cache(web):
    pid = _profile()
    r = _search(pid, max_price=60).json()
    assert r["shown"] == 2 and r["total"] == 3 and not r["cached"]
    searches = sum(u.startswith(shop.SEARCH_URL) for u in web.calls)
    r2 = _search(pid, min_price=100).json()
    assert r2["cached"] and [p["title"] for p in r2["results"]] == ["Women's Navy Midi Dress"]
    assert sum(u.startswith(shop.SEARCH_URL) for u in web.calls) == searches  # served from cache


def test_search_errors(monkeypatch):
    pid = _profile()
    settings.put("serpapi_api_key", None)
    assert "Add a SerpAPI key" in _search(pid).json()["detail"]

    settings.put("serpapi_api_key", "bad")
    err = urllib.error.HTTPError(shop.SEARCH_URL, 401, "Unauthorized", {}, io.BytesIO(b'{"error": "Invalid API key."}'))
    monkeypatch.setattr(shop, "_http_get", FakeWeb(err))
    r = _search(pid, query="a different query")
    assert r.status_code == 502 and "rejected the API key" in r.json()["detail"]

    monkeypatch.setattr(shop, "_http_get", FakeWeb({"error": "Google Shopping hasn't returned any results for this query."}))
    assert _search(pid, query="zzz no results").json()["results"] == []


def test_saved_items(web):
    pid = _profile()
    product = _search(pid).json()["results"][0]
    saved = client.post(f"/api/profiles/{pid}/saved", json={"product": product}).json()
    again = client.post(f"/api/profiles/{pid}/saved", json={"product": product}).json()
    assert saved["saved_id"] == again["saved_id"] and saved["id"] == product["id"]
    assert saved["colour"]["label"] == "great"
    assert [s["title"] for s in client.get(f"/api/profiles/{pid}/saved").json()] == [product["title"]]
    assert _search(pid).json()["results"][0]["saved"] is True
    assert client.delete(f"/api/saved/{saved['saved_id']}").status_code == 204
    assert client.get(f"/api/profiles/{pid}/saved").json() == []


def test_serpapi_settings(web):
    assert client.put("/api/settings/serpapi", json={"key": "not a key!"}).status_code == 422
    s = client.put("/api/settings/serpapi", json={"key": "abc123", "country": "de"}).json()
    assert s["configured"] and s["country"] == "de"
    assert client.get("/api/settings/serpapi", params={"check": True}).json()["searches_left"] == 87
    assert client.put("/api/settings/serpapi", json={"country": "xx"}).status_code == 422


def test_accessories_skip_sizing(web):
    r = _search(_profile(), garment="accessories", query="leather belt").json()
    assert r["general_size"] is None and all(p["size"] is None for p in r["results"])
    assert _search(_profile(), garment="hats").status_code == 422


def test_general_size_falls_back_to_tops_for_coats(web):
    r = _search(_profile(), garment="outerwear", query="coat").json()
    assert r["general_size"]["size"] == "12"
