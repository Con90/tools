import base64
import io
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import garments, settings, shop, tryon
from app.main import app

client = TestClient(app)


def img(size, colour=(180, 80, 60), fmt="JPEG"):
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, fmt)
    return buf.getvalue()


# --- page parsing ------------------------------------------------------------------------------


def test_json_ld_product_image_comes_first():
    html = """<html><head>
      <meta property="og:image" content="https://cdn.shop/og.jpg">
      <script type="application/ld+json">{"@context": "https://schema.org", "@graph": [
        {"@type": "BreadcrumbList"},
        {"@type": "Product", "name": "Dress", "image": [{"@type": "ImageObject", "contentUrl": "/img/front.jpg"},
                                                        "https://cdn.shop/back.jpg"]}]}</script>
      <link rel="image_src" href="//cdn.shop/src.jpg">
    </head></html>"""
    assert garments.page_image_urls(html, "https://shop.example/p/1") == [
        "https://shop.example/img/front.jpg", "https://cdn.shop/back.jpg", "https://cdn.shop/og.jpg", "https://cdn.shop/src.jpg"]


def test_meta_tags_and_broken_json():
    html = """<meta name="twitter:image" content="https://cdn/t.jpg">
      <script type="application/ld+json">{not json</script>
      <meta property="og:image:secure_url" content="https://cdn/secure.jpg">"""
    assert garments.page_image_urls(html, "https://s/") == ["https://cdn/secure.jpg", "https://cdn/t.jpg"]
    assert garments.page_image_urls("<p>no images</p>", "https://s/") == []


def test_is_shop_link():
    assert garments.is_shop_link("https://www.zara.com/uk/en/dress-p1.html")
    assert not garments.is_shop_link("https://www.google.com/shopping/product/123")
    assert not garments.is_shop_link("https://www.google.co.uk/shopping/product/123")
    assert not garments.is_shop_link(None)


# --- resolving -----------------------------------------------------------------------------------


class FakeWeb:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def __call__(self, url, limit, timeout=12):
        self.calls.append(url)
        return self.pages.get(url)


@pytest.fixture
def thumbs(monkeypatch):
    monkeypatch.setattr(shop, "fetch_thumbnail", lambda url: img((150, 150)) if url else None)


PRODUCT = {"id": "p1", "title": "Rust Wrap Dress", "link": "https://shop.example/p1",
           "merchant_link": "https://shop.example/p1", "thumbnail": "https://thumb/p1", "garment": "dresses"}


def test_uses_the_shop_page_image(monkeypatch, thumbs):
    web = FakeWeb({"https://shop.example/p1": b'<meta property="og:image" content="/big.jpg">',
                   "https://shop.example/big.jpg": img((900, 1200))})
    monkeypatch.setattr(garments, "_get", web)
    found = garments.resolve(PRODUCT)
    assert (found["width"], found["height"]) == (900, 1200)
    assert found["source"] == "the product page on shop.example"
    # cached: no more network on the second call
    web.calls.clear()
    assert garments.resolve(PRODUCT)["width"] == 900 and web.calls == []


def test_small_page_image_falls_through_to_product_lookup(monkeypatch, thumbs):
    lookup = {"product_results": {"title": "Dress", "thumbnails": ["https://g/full1.jpg"],
                                  "stores": [{"name": "Other shop", "link": "https://other.example/dress"}]}}
    web = FakeWeb({"https://shop.example/p1": b'<meta property="og:image" content="https://shop.example/tiny.jpg">',
                   "https://shop.example/tiny.jpg": img((120, 160)),
                   "https://other.example/dress": b'<meta property="og:image" content="https://other.example/x.jpg">',
                   "https://other.example/x.jpg": img((1000, 1000))})
    monkeypatch.setattr(garments, "_get", web)
    monkeypatch.setattr(shop, "_get_json", lambda url: lookup)
    settings.put("serpapi_api_key", "abc123")
    found = garments.resolve({**PRODUCT, "immersive_api": "https://serpapi.com/search.json?engine=google_immersive_product&page_token=t"})
    assert found["source"] == "the product page on other.example" and found["width"] == 1000


def test_google_only_result_uses_lookup_images(monkeypatch, thumbs):
    lookup = {"product_results": {"media": [{"type": "image", "link": "https://g/full.jpg"}]}}
    monkeypatch.setattr(garments, "_get", FakeWeb({"https://g/full.jpg": img((800, 1000))}))
    monkeypatch.setattr(shop, "_get_json", lambda url: lookup)
    settings.put("serpapi_api_key", "abc123")
    product = {**PRODUCT, "id": "p2", "link": "https://www.google.com/shopping/product/9", "merchant_link": None,
               "immersive_api": "https://serpapi.com/search.json?engine=google_immersive_product&page_token=t"}
    found = garments.resolve(product)
    assert found["source"] == "Google's product images" and found["width"] == 800


def test_falls_back_to_thumbnail(monkeypatch, thumbs):
    monkeypatch.setattr(garments, "_get", FakeWeb({}))  # shop blocks us
    found = garments.resolve({**PRODUCT, "id": "p3"})
    assert found["source"] == "the search thumbnail" and found["width"] == 150


def test_nothing_found(monkeypatch):
    monkeypatch.setattr(garments, "_get", FakeWeb({}))
    monkeypatch.setattr(shop, "fetch_thumbnail", lambda url: None)
    assert garments.resolve({**PRODUCT, "id": "p4"}) is None


# --- API + try-on ------------------------------------------------------------------------------------


def test_preview_endpoint_and_tryon_use_the_shop_picture(monkeypatch, thumbs):
    web = FakeWeb({"https://shop.example/p1": b'<meta property="og:image" content="https://shop.example/big.png">',
                   "https://shop.example/big.png": img((600, 800), fmt="PNG")})
    monkeypatch.setattr(garments, "_get", web)
    sent = {}

    def subscribe(model_name, inputs):
        sent.update(inputs)
        return SimpleNamespace(id="x", status="completed", error=None, credits_used=1,
                               output=["data:image/jpeg;base64," + base64.b64encode(img((300, 400))).decode()])
    monkeypatch.setattr(tryon, "_client", lambda: SimpleNamespace(predictions=SimpleNamespace(subscribe=subscribe)))

    pid = client.post("/api/profiles", json={"name": "G"}).json()["id"]
    saved = client.post(f"/api/profiles/{pid}/saved", json={"product": PRODUCT}).json()
    info = client.get(f"/api/saved/{saved['saved_id']}/garment").json()
    assert info == {"found": True, "source": "the product page on shop.example", "width": 600, "height": 800,
                    "clear": True, "url": f"/api/saved/{saved['saved_id']}/garment.jpg"}
    pic = client.get(info["url"])
    assert pic.headers["content-type"] == "image/png"

    photo = client.post(f"/api/profiles/{pid}/body-photos", content=img((400, 600)),
                        headers={"Content-Type": "image/jpeg"}).json()
    r = client.post(f"/api/profiles/{pid}/tryons", json={"photo_id": photo["id"], "saved_id": saved["saved_id"]})
    assert r.status_code == 201
    garment_sent = Image.open(io.BytesIO(base64.b64decode(sent["garment_image"].split(",")[1])))
    assert garment_sent.size == (600, 800)  # the shop's picture, not the 150px thumbnail
