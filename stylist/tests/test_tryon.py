import base64
import io
from types import SimpleNamespace

import fashn
import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import settings, shop, tryon
from app.main import app

client = TestClient(app)


def jpeg(colour=(120, 120, 120), size=(300, 400)):
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, "JPEG")
    return buf.getvalue()


RESULT = "data:image/jpeg;base64," + base64.b64encode(jpeg((10, 200, 10))).decode()


class FakeFashn:
    def __init__(self, response=None, raises=None):
        self.calls = []
        self.response = response or SimpleNamespace(id="pred_1", status="completed", output=[RESULT],
                                                     error=None, credits_used=1)
        self.raises = raises
        self.predictions = SimpleNamespace(subscribe=self._subscribe)

    def _subscribe(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise self.raises
        return self.response


@pytest.fixture
def fake(monkeypatch):
    f = FakeFashn()
    monkeypatch.setattr(tryon, "_client", lambda: f)
    monkeypatch.setattr(shop, "fetch_thumbnail", lambda url: jpeg((200, 60, 40)) if url else None)
    return f


def _setup():
    pid = client.post("/api/profiles", json={"name": "T"}).json()["id"]
    photo = client.post(f"/api/profiles/{pid}/body-photos", content=jpeg(),
                        headers={"Content-Type": "image/jpeg"}).json()
    item = client.post(f"/api/profiles/{pid}/saved", json={"product": {
        "id": "p1", "title": "Rust Wrap Dress", "link": "https://shop/p1", "source": "Shop",
        "thumbnail": "https://img/p1", "garment": "dresses"}}).json()
    return pid, photo["id"], item["saved_id"]


def test_body_photos_are_separate_from_colour_photos(fake):
    pid, photo_id, _ = _setup()
    assert [p["id"] for p in client.get(f"/api/profiles/{pid}/body-photos").json()] == [photo_id]
    assert client.get(f"/api/profiles/{pid}/photos").json() == []          # not in colour analysis
    assert client.get(f"/api/profiles/{pid}/colour").json()["photos"] == 0


def test_tryon_request_and_result(fake):
    pid, photo_id, saved_id = _setup()
    r = client.post(f"/api/profiles/{pid}/tryons", json={"photo_id": photo_id, "saved_id": saved_id})
    assert r.status_code == 201
    t = r.json()
    call = fake.calls[0]
    assert call["model_name"] == "tryon-v1.6"
    inputs = call["inputs"]
    assert inputs["category"] == "one-pieces" and inputs["return_base64"] is True
    assert inputs["model_image"].startswith("data:image/jpeg;base64,")
    assert inputs["garment_image"].startswith("data:image/jpeg;base64,")
    assert t["item"]["title"] == "Rust Wrap Dress" and t["credits_used"] == 1

    img = client.get(f"/api/tryons/{t['id']}/image")
    assert Image.open(io.BytesIO(img.content)).getpixel((5, 5))[1] > 150  # the green fake result
    assert [x["id"] for x in client.get(f"/api/profiles/{pid}/tryons").json()] == [t["id"]]
    assert client.delete(f"/api/tryons/{t['id']}").status_code == 204
    assert client.get(f"/api/profiles/{pid}/tryons").json() == []


def test_uploaded_garment_image_and_type(fake):
    pid, photo_id, _ = _setup()
    garment = "data:image/png;base64," + base64.b64encode(jpeg((0, 0, 200))).decode()
    t = client.post(f"/api/profiles/{pid}/tryons", json={"photo_id": photo_id, "garment_image": garment,
                                                         "garment_type": "bottoms"}).json()
    assert fake.calls[0]["inputs"]["category"] == "bottoms" and t["custom_garment"]


def test_tryon_validation(fake):
    pid, photo_id, saved_id = _setup()
    r = client.post(f"/api/profiles/{pid}/tryons", json={"photo_id": photo_id})
    assert r.status_code == 422 and "Choose a saved item" in r.json()["detail"]
    r = client.post(f"/api/profiles/{pid}/tryons", json={"photo_id": photo_id, "saved_id": saved_id, "garment_type": "shoes"})
    assert r.status_code == 422
    other = client.post("/api/profiles", json={"name": "Other"}).json()["id"]
    assert client.post(f"/api/profiles/{other}/tryons", json={"photo_id": photo_id, "saved_id": saved_id}).status_code == 404
    r = client.post(f"/api/profiles/{pid}/tryons", json={"photo_id": photo_id, "garment_image": "data:image/png;base64,@@@"})
    assert r.status_code == 422
    assert not fake.calls


def _status_error(cls, code):
    return cls("err", response=httpx.Response(code, request=httpx.Request("POST", "https://api.fashn.ai/v1/run")), body=None)


@pytest.mark.parametrize("fake_client,message", [
    (FakeFashn(SimpleNamespace(id="x", status="failed", output=None, credits_used=0,
                               error=SimpleNamespace(name="PoseError", message="no pose"))), "body pose"),
    (FakeFashn(SimpleNamespace(id="x", status="time_out", output=None, credits_used=0, error=None)), "too long"),
    (FakeFashn(raises=_status_error(fashn.AuthenticationError, 401)), "rejected the API key"),
    (FakeFashn(raises=_status_error(fashn.APIStatusError, 402)), "out of credits"),
])
def test_tryon_errors_are_explained(monkeypatch, fake_client, message):
    monkeypatch.setattr(tryon, "_client", lambda: fake_client)
    monkeypatch.setattr(shop, "fetch_thumbnail", lambda url: jpeg())
    pid, photo_id, saved_id = _setup()
    r = client.post(f"/api/profiles/{pid}/tryons", json={"photo_id": photo_id, "saved_id": saved_id})
    assert r.status_code == 502 and message in r.json()["detail"]


def test_no_key_and_key_settings(monkeypatch):
    monkeypatch.delenv("FASHN_API_KEY", raising=False)
    pid, photo_id, saved_id = _setup()
    monkeypatch.setattr(shop, "fetch_thumbnail", lambda url: jpeg())
    r = client.post(f"/api/profiles/{pid}/tryons", json={"photo_id": photo_id, "saved_id": saved_id})
    assert r.status_code == 502 and "Add a FASHN API key" in r.json()["detail"]
    assert client.put("/api/settings/fashn", json={"key": "short"}).status_code == 422
    assert client.put("/api/settings/fashn", json={"key": "fa-1234567890abcdef"}).json()["configured"]
    assert settings.get("fashn_api_key") == "fa-1234567890abcdef"


def test_profile_delete_removes_tryons(fake):
    pid, photo_id, saved_id = _setup()
    client.post(f"/api/profiles/{pid}/tryons", json={"photo_id": photo_id, "saved_id": saved_id})
    client.delete(f"/api/profiles/{pid}")
    assert client.get(f"/api/photos/{photo_id}/image").status_code == 404
