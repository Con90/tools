"""Photo upload and colour analysis, end to end on a real portrait.

Needs MediaPipe and its models (downloaded once into data/models); skipped
where those aren't available.
"""
import io
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import db, face
from app.main import app

pytest.importorskip("mediapipe")

PORTRAIT = (Path(__file__).parent / "fixtures" / "portrait.jpg").read_bytes()
client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def models_available():
    try:
        face._get_models()
    except face.AnalysisError as e:
        pytest.skip(str(e))


def _profile():
    return client.post("/api/profiles", json={"name": "P"}).json()["id"]


def _upload(pid, data=PORTRAIT):
    return client.post(f"/api/profiles/{pid}/photos", content=data, headers={"Content-Type": "image/jpeg"})


def test_upload_analyses_face():
    pid = _profile()
    r = _upload(pid)
    assert r.status_code == 201
    photo = r.json()
    assert photo["error"] is None
    assert set(photo["colours"]) == {"skin", "hair", "eyes"}
    assert len(photo["points"]["eyes"]) == 2
    assert client.get(f"/api/photos/{photo['id']}/image").status_code == 200
    assert client.get(f"/api/photos/{photo['id']}/face").headers["content-type"] == "image/jpeg"


def test_colour_summary_gives_season_and_palette():
    pid = _profile()
    _upload(pid)
    summary = client.get(f"/api/profiles/{pid}/colour").json()
    assert summary["photos"] == 1
    assert summary["season"] == summary["auto_season"]
    assert summary["palette"]["colours"]
    assert len(summary["ranked"]) == 4
    # Her warm, golden colouring should read as a warm season.
    assert summary["scores"]["warmth"] > 0.3
    assert summary["season"].endswith(("spring", "autumn"))


def test_photo_without_face_can_still_be_picked_by_hand():
    pid = _profile()
    blank = io.BytesIO()
    Image.new("RGB", (400, 400), (200, 170, 150)).save(blank, "JPEG")
    photo = _upload(pid, blank.getvalue()).json()
    assert "No face found" in photo["error"]
    picked = client.post(f"/api/photos/{photo['id']}/pick", json={"feature": "skin", "x": 0.5, "y": 0.5}).json()
    assert picked["colours"]["skin"]["source"] == "picked"
    assert client.get(f"/api/profiles/{pid}/colour").json()["season"]


def test_white_balance_pick_changes_colours():
    pid = _profile()
    photo = _upload(pid).json()
    before = photo["colours"]["skin"]["lab"]
    # Treat a patch of the (warm, beige) background wall as white: removes its yellow cast.
    after = client.post(f"/api/photos/{photo['id']}/pick", json={"feature": "white", "x": 0.05, "y": 0.6}).json()
    assert after["white_balanced"]
    assert after["colours"]["skin"]["lab"][2] < before[2]
    undone = client.delete(f"/api/photos/{photo['id']}/pick/white").json()
    assert undone["colours"]["skin"]["lab"] == before


def test_exclude_override_and_natural_hair():
    pid = _profile()
    photo = _upload(pid).json()
    client.patch(f"/api/photos/{photo['id']}", json={"included": False})
    assert client.get(f"/api/profiles/{pid}/colour").json()["photos"] == 0

    client.patch(f"/api/photos/{photo['id']}", json={"included": True})
    s = client.put(f"/api/profiles/{pid}/colour", json={"season_override": "deep_winter", "natural_hair": "black"}).json()
    assert s["season"] == "deep_winter" and s["auto_season"] != "deep_winter"
    assert s["features"]["hair"]["source"].startswith("natural hair")
    assert client.put(f"/api/profiles/{pid}/colour", json={"season_override": "nope"}).status_code == 422


def test_rejects_non_image_and_cleans_up_on_delete():
    pid = _profile()
    assert _upload(pid, b"not an image").status_code == 422
    photo = _upload(pid).json()
    files_before = len(list(db.photos_dir().iterdir()))
    assert client.delete(f"/api/profiles/{pid}").status_code == 204
    assert client.get(f"/api/photos/{photo['id']}/image").status_code == 404
    assert len(list(db.photos_dir().iterdir())) == files_before - 1


def test_full_length_photo_zooms_in_on_the_face():
    """A small face in a big photo is missed by the face detector alone."""
    portrait = Image.open(io.BytesIO(PORTRAIT)).resize((200, 210))
    canvas = Image.new("RGB", (1800, 2400), (225, 222, 215))
    canvas.paste(portrait, (800, 120))
    buf = io.BytesIO()
    canvas.save(buf, "JPEG")
    photo = _upload(_profile(), buf.getvalue()).json()
    assert photo["error"] is None
    assert "skin" in photo["colours"] and "hair" in photo["colours"]
    assert any("small" in w for w in photo["warnings"])
    x0, y0, x1, y1 = photo["face_box"]
    assert 0.4 < x0 < x1 < 0.6 and y1 < 0.2  # mapped back onto the full photo


def test_backlit_photo_is_flagged_and_result_provisional():
    img = np.array(Image.open(io.BytesIO(PORTRAIT)).convert("RGB")).astype(float)
    normal = face.analyse(img.astype(np.uint8))
    assert normal["lighting_issue"] is False
    # Darken the face and brighten the room around it, like a window behind the person.
    h, w, _ = img.shape
    x0, y0, x1, y1 = [int(v * s) for v, s in zip(normal["face_box"], (w, h, w, h))]
    yy, xx = np.mgrid[:h, :w]
    outside = ~((xx >= x0) & (xx < x1) & (yy >= y0) & (yy < y1))
    backlit = img * 0.4
    backlit[outside] = np.clip(img[outside] * 1.25 + 40, 0, 255)
    buf = io.BytesIO()
    Image.fromarray(backlit.astype(np.uint8)).save(buf, "JPEG")

    pid = _profile()
    photo = _upload(pid, buf.getvalue()).json()
    assert any("darker than the room" in w for w in photo["warnings"])
    assert client.get(f"/api/profiles/{pid}/colour").json()["poor_light_photos"] == 1
    client.patch(f"/api/photos/{photo['id']}", json={"included": False})
    _upload(pid)
    assert client.get(f"/api/profiles/{pid}/colour").json()["poor_light_photos"] == 0
