"""Find a clear garment picture for try-on, straight from the shop.

Search thumbnails are ~200 px: too small for a good try-on. Shops publish
their main product photo for search engines and link previews, so:

1. Shop product page → the image in its structured data (JSON-LD `Product`),
   `og:image`, `twitter:image` or `image_src`.
2. No shop link in the search result → SerpAPI's product lookup
   (`serpapi_immersive_product_api`, one search credit) for the shops' links
   and Google's full-size product images.
3. Otherwise the search thumbnail.

The first image of a usable size wins; the result is cached per product.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from PIL import Image

from . import db, shop

MIN_SIDE = 400        # smaller than this and try-on quality suffers
MAX_PAGE = 3_000_000  # bytes of HTML to read
MAX_IMAGE = 15_000_000

# Some shops refuse unknown clients; a normal browser identity gets the same public page anyone sees.
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/126.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,image/avif,image/webp,image/*,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


def _get(url: str, limit: int, timeout: float = 12) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers=BROWSER_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(limit)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def is_shop_link(url: str | None) -> bool:
    """A link to the shop itself rather than to Google's product page."""
    if not url or not url.startswith("http"):
        return False
    host = urllib.parse.urlparse(url).netloc.lower()
    return not re.search(r"(^|\.)google\.[a-z.]+$", host)


# --- product page ----------------------------------------------------------------------


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.link_image: str | None = None
        self.ld_json: list[str] = []
        self._in_ld = False
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if key and a.get("content") and key not in self.meta:
                self.meta[key] = a["content"]
        elif tag == "link" and a.get("rel", "").lower() == "image_src" and a.get("href"):
            self.link_image = a["href"]
        elif tag == "script" and "ld+json" in a.get("type", "").lower():
            self._in_ld, self._buf = True, []

    def handle_data(self, data):
        if self._in_ld:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._in_ld:
            self._in_ld = False
            self.ld_json.append("".join(self._buf))


def _ld_images(node) -> list[str]:
    """Image URLs from JSON-LD Product nodes (handles @graph, lists, ImageObject)."""
    found: list[str] = []

    def image_urls(value):
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return [value.get("contentUrl") or value.get("url")] if (value.get("contentUrl") or value.get("url")) else []
        if isinstance(value, list):
            return [u for v in value for u in image_urls(v)]
        return []

    def walk(n):
        if isinstance(n, list):
            for x in n:
                walk(x)
        elif isinstance(n, dict):
            types = n.get("@type")
            types = types if isinstance(types, list) else [types]
            if any(t in ("Product", "ProductGroup", "IndividualProduct") for t in types):
                found.extend(image_urls(n.get("image")))
            for v in n.values():
                if isinstance(v, (dict, list)):
                    walk(v)

    walk(node)
    return found


def page_image_urls(html: str, base_url: str) -> list[str]:
    """Candidate product image URLs from a product page, best first."""
    p = _PageParser()
    try:
        p.feed(html)
    except Exception:  # malformed HTML: use whatever was parsed
        pass
    urls: list[str] = []
    for block in p.ld_json:
        try:
            urls += _ld_images(json.loads(block))
        except ValueError:
            continue
    for key in ("og:image:secure_url", "og:image", "og:image:url", "twitter:image", "twitter:image:src", "image"):
        if p.meta.get(key):
            urls.append(p.meta[key])
    if p.link_image:
        urls.append(p.link_image)
    out = []
    for u in urls:
        full = urllib.parse.urljoin(base_url, u.strip())
        if full.startswith("http") and full not in out:
            out.append(full)
    return out


# --- SerpAPI product lookup ------------------------------------------------------------------


def immersive_lookup(api_url: str) -> tuple[list[str], list[str]]:
    """(shop links, image URLs) from SerpAPI's product lookup.

    The response is read defensively: any list under a "stores"/"sellers"/
    "online_sellers" key with "link"s, and any list of image URLs under
    "thumbnails"/"images"/"media", wherever they appear.
    """
    key = shop.api_key()
    if not api_url or not key:
        return [], []
    sep = "&" if "?" in api_url else "?"
    try:
        data = shop._get_json(f"{api_url}{sep}{urllib.parse.urlencode({'api_key': key})}")
    except shop.ShopError:
        return [], []
    links, images = [], []

    def walk(n):
        if isinstance(n, dict):
            for k, v in n.items():
                if k in ("stores", "sellers", "online_sellers") and isinstance(v, list):
                    links.extend(s.get("link") for s in v if isinstance(s, dict) and is_shop_link(s.get("link")))
                elif k in ("thumbnails", "images", "media") and isinstance(v, list):
                    for x in v:
                        u = x if isinstance(x, str) else isinstance(x, dict) and (x.get("link") or x.get("url") or x.get("image"))
                        if isinstance(u, str) and u.startswith("http"):
                            images.append(u)
                else:
                    walk(v)
        elif isinstance(n, list):
            for x in n:
                walk(x)

    walk(data)
    return list(dict.fromkeys(links)), list(dict.fromkeys(images))


# --- resolve ----------------------------------------------------------------------------------


def _image_size(data: bytes) -> tuple[int, int] | None:
    try:
        return Image.open(io.BytesIO(data)).size
    except Exception:
        return None


def _cache_paths(product: dict):
    d = db.db_path().parent / "cache" / "garments"
    d.mkdir(parents=True, exist_ok=True)
    stem = hashlib.sha1(str(product.get("id") or product.get("link")).encode()).hexdigest()
    return d / f"{stem}.img", d / f"{stem}.json"


def resolve(product: dict, use_lookup: bool = True) -> dict | None:
    """Best garment picture for a saved product.

    Returns {"image": bytes, "source": str, "width": int, "height": int, "origin": url} or None.
    """
    img_path, meta_path = _cache_paths(product)
    if img_path.exists() and meta_path.exists():
        return {**json.loads(meta_path.read_text()), "image": img_path.read_bytes()}

    best = None  # largest usable image seen so far

    def consider(url: str, source: str) -> bool:
        """Download a candidate; True once it's big enough to stop looking."""
        nonlocal best
        thumb = url.startswith("data:") or url == product.get("thumbnail")
        data = shop.fetch_thumbnail(url) if thumb else _get(url, MAX_IMAGE)
        size = data and _image_size(data)
        if not size:
            return False
        if best is None or min(size) > min(best["width"], best["height"]):
            best = {"image": data, "source": source, "width": size[0], "height": size[1], "origin": url}
        return min(size) >= MIN_SIDE

    def try_page(url: str) -> bool:
        html = _get(url, MAX_PAGE)
        if not html:
            return False
        host = urllib.parse.urlparse(url).netloc.removeprefix("www.")
        text = html.decode("utf-8", errors="replace")
        return any(consider(u, f"the product page on {host}") for u in page_image_urls(text, url)[:6])

    done = False
    shop_links = [u for u in (product.get("merchant_link"), product.get("link")) if is_shop_link(u)]
    for url in dict.fromkeys(shop_links):
        if try_page(url):
            done = True
            break
    if not done and use_lookup and product.get("immersive_api"):
        links, images = immersive_lookup(product["immersive_api"])
        done = any(try_page(u) for u in links[:3]) or any(consider(u, "Google's product images") for u in images[:6])
    if not done and product.get("thumbnail"):
        consider(product["thumbnail"], "the search thumbnail")

    if best is None:
        return None
    img_path.write_bytes(best["image"])
    meta_path.write_text(json.dumps({k: v for k, v in best.items() if k != "image"}))
    return best
