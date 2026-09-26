"""Find the face in a photo and sample skin, hair and eye colours.

Uses two MediaPipe models, run locally (downloaded once, ~20 MB):

- Face Landmarker: 478 face points including the irises, used to place the
  cheek / forehead patches and the eye samples.
- Selfie Multiclass Segmenter: labels each pixel as hair, face skin, clothes,
  background…, used for the hair sample and to keep skin patches on skin.

Samples are stored as trimmed means in *linear* RGB so that a white-balance
correction (a per-channel gain) can be applied exactly afterwards.
"""

from __future__ import annotations

import atexit
import io
import os
import threading
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from .colour import linear_to_lab, rgb_to_lab, srgb_to_linear

MODELS_DIR = Path(os.environ.get("STYLIST_MODELS", Path(__file__).resolve().parent.parent / "data" / "models"))
MODEL_URLS = {
    "face_landmarker.task":
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
    "selfie_multiclass_256x256.tflite":
        "https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite",
}

MAX_SIDE = 2600  # photos are downscaled to this on upload (keeps detail in full-length shots)

# Face-mesh landmark indices.
CHEEKS = (50, 280)
FOREHEAD = 151
RIGHT_IRIS, LEFT_IRIS = (468, 469, 470, 471, 472), (473, 474, 475, 476, 477)
RIGHT_EYE = (33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246)
LEFT_EYE = (362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398)

# Segmenter classes.
HAIR, FACE_SKIN = 1, 3

FEATURES = ("skin", "hair", "eyes")


class AnalysisError(Exception):
    """A problem the person can fix (no face found, unreadable file…)."""


# --- models -----------------------------------------------------------------------

_lock = threading.Lock()
_models: dict = {}


def _model_path(name: str) -> Path:
    path = MODELS_DIR / name
    if not path.exists():
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        try:
            urllib.request.urlretrieve(MODEL_URLS[name], tmp)
        except OSError as e:
            raise AnalysisError(
                f"Couldn't download the face model ({name}). Check your internet connection "
                f"and try again. It's only needed once. ({e})") from e
        tmp.replace(path)
    return path


def _get_models():
    if not _models:
        try:
            from mediapipe.tasks.python import BaseOptions, vision
        except ImportError as e:  # pragma: no cover - depends on install
            raise AnalysisError("Automatic analysis needs the 'mediapipe' package "
                                "(pip install -r requirements.txt). You can still pick colours by hand.") from e
        _models["landmarker"] = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(_model_path("face_landmarker.task"))), num_faces=3))
        _models["segmenter"] = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
            base_options=BaseOptions(model_asset_path=str(_model_path("selfie_multiclass_256x256.tflite"))),
            output_category_mask=True))
    return _models


@atexit.register
def _close_models() -> None:
    # Close explicitly: MediaPipe's own finaliser fails if it runs after
    # its native library has been unloaded at interpreter exit.
    for model in _models.values():
        model.close()
    _models.clear()


def _run_models(img: np.ndarray):
    import mediapipe as mp
    with _lock:  # MediaPipe graphs aren't safe to call from several threads at once
        models = _get_models()
        frame = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(img))
        faces = models["landmarker"].detect(frame).face_landmarks
        mask = models["segmenter"].segment(frame).category_mask.numpy_view().squeeze().copy()
    return faces, mask


# --- images -----------------------------------------------------------------------

try:  # iPhone photos
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:  # pragma: no cover
    pass


def load_upload(data: bytes) -> Image.Image:
    """Decode an upload, apply camera rotation, drop alpha, downscale."""
    try:
        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im)
    except Exception as e:
        raise AnalysisError("That file isn't an image this app can read. Try a JPEG or PNG.") from e
    im = im.convert("RGB")
    im.thumbnail((MAX_SIDE, MAX_SIDE))
    return im


# --- sampling ---------------------------------------------------------------------


def _trimmed_linear(pixels: np.ndarray, trim=(0.15, 0.85)) -> list[float] | None:
    """Mean linear RGB after dropping the darkest/brightest pixels (shadow, shine)."""
    px = np.asarray(pixels, dtype=np.float64).reshape(-1, 3)
    if len(px) < 8:
        return None
    lin = srgb_to_linear(px)
    lum = lin @ np.array([0.2126, 0.7152, 0.0722])
    lo, hi = np.quantile(lum, trim)
    keep = lin[(lum >= lo) & (lum <= hi)]
    if len(keep) < 4:
        keep = lin
    return [float(v) for v in keep.mean(axis=0)]


def _disc(shape, cx, cy, r, inner=0.0) -> np.ndarray:
    yy, xx = np.ogrid[:shape[0], :shape[1]]
    d2 = (xx - cx) ** 2 + (yy - cy) ** 2
    return (d2 <= r * r) & (d2 >= (inner * r) ** 2)


def _polygon(shape, points) -> np.ndarray:
    m = Image.new("L", (shape[1], shape[0]), 0)
    ImageDraw.Draw(m).polygon([tuple(p) for p in points], fill=1)
    return np.array(m, dtype=bool)


def sample_point(img: np.ndarray, x: float, y: float, feature: str) -> list[float] | None:
    """Sample around a point the person clicked (x, y normalised 0–1)."""
    h, w = img.shape[:2]
    r = max(4, min(h, w) * (0.008 if feature in ("eyes", "white") else 0.02))
    mask = _disc(img.shape, x * w, y * h, r)
    if feature == "white":
        # For a white reference use the brighter part of the patch (skip texture/shadow).
        return _trimmed_linear(img[mask], trim=(0.5, 0.98))
    return _trimmed_linear(img[mask])


def _head_box(seg: np.ndarray, shape) -> tuple[int, int, int, int] | None:
    """Square crop around the face-skin region the segmenter found, with room for hair."""
    h, w = shape[:2]
    if seg.shape != (h, w):
        seg = np.array(Image.fromarray(seg).resize((w, h), Image.NEAREST))
    ys, xs = np.nonzero(seg == FACE_SKIN)
    if len(xs) < 50:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    cx, cy, side = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0) * 2.2
    return (int(max(0, cx - side / 2)), int(max(0, cy - side / 2)),
            int(min(w, cx + side / 2)), int(min(h, cy + side / 2)))


def analyse(img: np.ndarray, _scale: float = 1.0) -> dict:
    """Automatic skin / hair / eye sampling for one photo.

    The face detector is made for close-ups; in a full-length photo the face
    is too small for it. Then the head is located with the segmenter, cropped,
    enlarged and analysed, and the results are mapped back onto the photo.
    """
    h, w = img.shape[:2]
    faces, seg = _run_models(img)
    if not faces and _scale == 1.0:
        box = _head_box(seg, img.shape)
        if box:
            x0, y0, x1, y1 = box
            crop = Image.fromarray(img[y0:y1, x0:x1])
            scale = max(1.0, 640 / max(crop.size))
            if scale > 1:
                crop = crop.resize((round(crop.width * scale), round(crop.height * scale)), Image.LANCZOS)
            try:
                sub = analyse(np.array(crop), _scale=scale)
            except AnalysisError:
                sub = None
            if sub:
                cw, ch = x1 - x0, y1 - y0

                def to_full(pt):
                    return [(x0 + pt[0] * cw) / w, (y0 + pt[1] * ch) / h]

                sub["points"] = {k: [to_full(p) for p in v] for k, v in sub["points"].items()}
                bx0, by0 = to_full(sub["face_box"][:2])
                bx1, by1 = to_full(sub["face_box"][2:])
                sub["face_box"] = [bx0, by0, bx1, by1]
                return sub
    if not faces:
        raise AnalysisError("No face found. Use a clear, front-facing photo with your whole face visible.")
    warnings = []
    if len(faces) > 1:
        warnings.append("More than one face found; used the largest.")

    def pts(face, idx):
        return np.array([[face[i].x * w, face[i].y * h] for i in idx])

    face = max(faces, key=lambda f: np.ptp([p.x for p in f]) * np.ptp([p.y for p in f]))
    all_pts = pts(face, range(len(face)))
    x0, y0 = all_pts.min(axis=0)
    x1, y1 = all_pts.max(axis=0)
    face_w = x1 - x0
    if face_w / _scale < 200:
        warnings.append("Your face is quite small in this photo; a closer shot gives more reliable colours.")

    if seg.shape != (h, w):  # the segmenter may return its own resolution
        seg = np.array(Image.fromarray(seg).resize((w, h), Image.NEAREST))
    skin_mask_all = seg == FACE_SKIN

    samples, points = {}, {}

    # Skin: both cheeks and the forehead, kept to pixels the segmenter calls face skin.
    skin_mask = np.zeros((h, w), dtype=bool)
    skin_centres = []
    for idx, scale in ((CHEEKS[0], 0.07), (CHEEKS[1], 0.07), (FOREHEAD, 0.08)):
        cx, cy = pts(face, [idx])[0]
        skin_mask |= _disc(img.shape, cx, cy, face_w * scale)
        skin_centres.append([cx / w, cy / h])
    skin_mask &= skin_mask_all
    samples["skin"] = _trimmed_linear(img[skin_mask], trim=(0.2, 0.8))
    points["skin"] = skin_centres

    # Eyes: a ring inside each iris (skips the pupil), clipped to the open eye
    # so eyelids and lashes are left out; the brightest pixels (catch-lights) are trimmed.
    eye_px, eye_centres, radii, sclera = [], [], [], []
    for iris, contour in ((RIGHT_IRIS, RIGHT_EYE), (LEFT_IRIS, LEFT_EYE)):
        ip = pts(face, iris)
        centre, r = ip[0], np.linalg.norm(ip[1:] - ip[0], axis=1).mean()
        radii.append(r)
        opening = _polygon(img.shape, pts(face, contour))
        ring = _disc(img.shape, centre[0], centre[1], r * 0.9, inner=0.4) & opening
        eye_px.append(img[ring])
        eye_centres.append([centre[0] / w, centre[1] / h])
        sclera.append(img[opening & ~_disc(img.shape, centre[0], centre[1], r * 1.15)])
    samples["eyes"] = _trimmed_linear(np.concatenate(eye_px), trim=(0.1, 0.75))
    points["eyes"] = eye_centres
    if min(radii) / _scale < 5:  # enlarging a crop adds no real detail
        warnings.append("Eyes are too small in this photo to read their colour reliably.")
        samples["eyes"] = None

    # Hair: whatever the segmenter labels hair.
    hair = seg == HAIR
    if hair.sum() < face_w * face_w * 0.03:
        warnings.append("Not enough hair visible to read its colour; you can pick it by hand or set your natural hair colour.")
        samples["hair"] = None
    else:
        samples["hair"] = _trimmed_linear(img[hair], trim=(0.1, 0.9))
        ys, xs = np.nonzero(hair)
        i = np.argmin((xs - xs.mean()) ** 2 + (ys - ys.min() - (ys.max() - ys.min()) * 0.3) ** 2)
        points["hair"] = [[xs[i] / w, ys[i] / h]]

    # Lighting check from the whites of the eyes: they're never perfectly white,
    # but a strong tint means coloured light that would skew the reading.
    lighting_issue = False
    white = _trimmed_linear(np.concatenate(sclera), trim=(0.6, 0.97))
    if white is not None:
        _, a, b = linear_to_lab(np.array(white))
        if b > 14:
            lighting_issue = True
            warnings.append("The light looks warm/yellow (indoor bulbs or golden hour); results may lean warm. "
                            "Daylight is best, or mark something white in the photo.")
        elif b < -3:
            lighting_issue = True
            warnings.append("The light looks cool/blue (shade or screens); results may lean cool. "
                            "Daylight is best, or mark something white in the photo.")

    # Exposure check: a face far darker than the room behind it is backlit or
    # lit from above, and would read as much deeper colouring than it is.
    if samples["skin"] is not None:
        skin_L = float(linear_to_lab(np.array(samples["skin"]))[0])
        background = img[seg == 0]
        if len(background) > 100:
            bg_L = float(np.median(rgb_to_lab(background[:: max(1, len(background) // 20000)])[:, 0]))
            if skin_L < 45 and bg_L - skin_L > 30:
                lighting_issue = True
                warnings.append("Your face is much darker than the room behind you, which usually means the light "
                                "is behind or above you. Your colouring will read darker than it is. Face a window "
                                "in daylight for a reliable result.")

    pad = 0.35
    box = [max(0, x0 - face_w * pad) / w, max(0, y0 - face_w * pad * 1.3) / h,
           min(w, x1 + face_w * pad) / w, min(h, y1 + face_w * pad * 0.6) / h]
    return {"samples": samples, "points": points, "face_box": box, "warnings": warnings,
            "lighting_issue": lighting_issue}
