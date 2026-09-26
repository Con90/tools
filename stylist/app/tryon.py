"""Virtual try-on via FASHN (hosted), using the official `fashn` SDK.

The person's photo and a garment image are sent to FASHN's `tryon-v1.6`
model, which returns a photo of them wearing the garment. `return_base64` is
set so FASHN returns the image directly instead of storing it on their CDN;
the result is saved only in data/tryons.
"""

from __future__ import annotations

import base64
import io
import os

from PIL import Image

from . import settings

MODEL = "tryon-v1.6"

# App garment types → FASHN categories. Shoes and accessories aren't supported.
CATEGORIES = {"tops": "tops", "knitwear": "tops", "outerwear": "tops",
              "bottoms": "bottoms", "skirts": "bottoms", "dresses": "one-pieces"}

ERROR_HELP = {
    "PoseError": "Couldn't make out your body pose. Use a photo facing the camera, standing, with arms by your sides.",
    "ImageLoadError": "One of the images couldn't be read. Try a different garment image.",
    "ContentModerationError": "The try-on service's content filter blocked this image.",
}


class TryOnError(Exception):
    """Something the person can act on."""


def api_key() -> str | None:
    return settings.get("fashn_api_key") or os.environ.get("FASHN_API_KEY")


def key_status() -> dict:
    if settings.get("fashn_api_key"):
        return {"configured": True, "source": "saved in the app"}
    if os.environ.get("FASHN_API_KEY"):
        return {"configured": True, "source": "environment"}
    return {"configured": False, "source": None}


def _client():
    try:
        from fashn import Fashn
    except ImportError as e:  # pragma: no cover
        raise TryOnError("The 'fashn' package isn't installed (pip install -r requirements.txt).") from e
    key = api_key()
    if not key:
        raise TryOnError("Add a FASHN API key to use try-on.")
    return Fashn(api_key=key)


def to_data_url(image_bytes: bytes, max_side: int = 1536) -> str:
    """JPEG data URL (FASHN needs the data:image/…;base64, prefix), downscaled."""
    try:
        im = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as e:
        raise TryOnError("That image couldn't be read. Try a JPEG or PNG.") from e
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def from_data_url(data_url: str) -> bytes:
    try:
        return base64.b64decode(data_url.split(",", 1)[1], validate=True)
    except (IndexError, ValueError) as e:
        raise TryOnError("That image data couldn't be read.") from e


def check_image(data: bytes) -> None:
    """Fail before calling (and paying for) the service if an input isn't an image."""
    try:
        Image.open(io.BytesIO(data)).verify()
    except Exception as e:
        raise TryOnError("The garment image couldn't be read. Try a JPEG or PNG.") from e


def run(person_jpeg: bytes, garment_bytes: bytes, garment_type: str, client=None) -> dict:
    """Returns {"image": bytes, "credits_used": int | None, "id": str}."""
    import fashn

    category = CATEGORIES.get(garment_type, "auto")
    client = client or _client()
    try:
        result = client.predictions.subscribe(
            model_name=MODEL,
            inputs={
                "model_image": to_data_url(person_jpeg),
                "garment_image": to_data_url(garment_bytes),
                "category": category,
                "garment_photo_type": "auto",
                "mode": "balanced",
                "output_format": "jpeg",
                "return_base64": True,  # don't keep the result on FASHN's CDN
            },
        )
    except fashn.AuthenticationError as e:
        raise TryOnError("FASHN rejected the API key. Check it in the Try on tab.") from e
    except fashn.RateLimitError as e:
        raise TryOnError("Too many try-ons at once. Wait a moment and try again.") from e
    except fashn.APIStatusError as e:
        if e.status_code == 402:
            raise TryOnError("Your FASHN account is out of credits.") from e
        raise TryOnError(f"The try-on service returned an error ({e.status_code}).") from e
    except fashn.APIConnectionError as e:
        raise TryOnError("Couldn't reach the try-on service. Check your internet connection.") from e

    if result.status != "completed" or not result.output:
        err = result.error
        if err is not None:
            raise TryOnError(ERROR_HELP.get(err.name, f"Try-on failed: {err.message}"))
        if result.status == "time_out":
            raise TryOnError("The try-on took too long. Please try again.")
        raise TryOnError(f"Try-on didn't finish ({result.status}).")
    return {"image": from_data_url(result.output[0]), "credits_used": result.credits_used, "id": result.id}
