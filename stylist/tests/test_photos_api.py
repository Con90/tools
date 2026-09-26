"""Photo upload and colour analysis, end to end on a real portrait.

Needs MediaPipe and its models (downloaded once into data/models); skipped
where those aren't available.
"""
import io
from pathlib import Path

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
