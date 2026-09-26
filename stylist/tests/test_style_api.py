import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import brief
from app.main import app

client = TestClient(app)

FAKE_BRIEF = {
    "headline": "Soft tailoring in warm earth tones",
    "summary": "…",
    "directions": [{"name": "Relaxed classic", "description": "…", "why_it_suits_you": "…",
                    "signature_pieces": ["camel coat"], "avoid": ["stiff shoulder pads"]}],
    "outfits": [{"occasion": "Office", "name": "Camel and cream", "styling_note": "…",
                 "pieces": [{"item": "Wrap dress", "colour_name": "Rust", "colour_hex": "#b5553c"},
                            {"item": "Belt", "colour_name": "Tan", "colour_hex": "tan"},
                            {"item": "Shoes", "colour_name": "Nude", "colour_hex": None}]}],
    "shopping_list": [{"item": "Wrap dress", "category": "dresses", "colour_name": "Rust", "colour_hex": "#b5553c",
                       "why": "…", "search_query": "rust midi wrap dress"}],
    "fit_notes": ["Mark the waist."],
}


class FakeClient:
    """Records the request and returns a canned structured response."""

    def __init__(self, stop_reason="end_turn", text=json.dumps(FAKE_BRIEF)):
        self.calls = []
        self._response = SimpleNamespace(
            stop_reason=stop_reason, model="claude-opus-5",
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=1800, output_tokens=2400))
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


@pytest.fixture
def fake(monkeypatch):
    f = FakeClient()
    monkeypatch.setattr(brief, "_client", lambda: f)
    return f


def _profile(**extra):
    data = {"name": "S", "gender": "female", "mode": "detailed",
            "measurements": {"chest": 90, "waist": 70, "hips": 98, "height": 158, "inseam": 70}, **extra}
    return client.post("/api/profiles", json=data).json()["id"]


def test_guide_from_measurements():
    g = client.get(f"/api/profiles/{_profile()}/style").json()
    assert g["shape"]["key"] == "hourglass" and not g["shape"]["estimated"]
    assert g["proportions"]["height"] == "petite"
    assert any(t.startswith("Petite") for t in g["proportion_tips"])
    assert "Classic" in g["options"]["vibes"]


def test_guide_from_usual_sizes_is_marked_estimated():
    pid = client.post("/api/profiles", json={
        "name": "Q", "gender": "female", "mode": "quick",
        "usual_sizes": {"tops": {"system": "UK", "size": "10"}, "bottoms": {"system": "UK", "size": "16"}},
    }).json()["id"]
    g = client.get(f"/api/profiles/{pid}/style").json()
    assert g["shape"]["key"] == "pear" and g["shape"]["estimated"]


def test_preferences_and_shape_override():
    pid = _profile()
    prefs = {"lifestyle": ["Office / business"], "vibes": ["Classic", "Minimal"], "budget": "Mid-range",
             "loves": "wide trousers", "dislikes": "anything cropped", "notes": ""}
    g = client.put(f"/api/profiles/{pid}/style", json={"preferences": prefs, "shape_override": "rectangle"}).json()
    assert g["shape"]["key"] == "rectangle" and g["shape"]["overridden"]
    assert g["preferences"]["vibes"] == ["Classic", "Minimal"]
    assert client.put(f"/api/profiles/{pid}/style", json={"shape_override": "oval"}).status_code == 422  # men's shape


def test_brief_request_and_storage(fake):
    pid = _profile()
    client.put(f"/api/profiles/{pid}/style", json={"preferences": {"dislikes": "anything cropped", "vibes": ["Classic"]}})
    g = client.post(f"/api/profiles/{pid}/style/brief", json={"include_photo": False}).json()

    call = fake.calls[0]
    assert call["model"] == "claude-opus-5"
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["thinking"] == {"type": "adaptive"}
    assert call["output_config"]["format"]["type"] == "json_schema"
    content = call["messages"][0]["content"]
    assert [b["type"] for b in content] == ["text"]  # no photo unless asked
    prompt = content[0]["text"]
    assert "Hourglass" in prompt and "anything cropped" in prompt and "Petite" in prompt
    assert "90" not in prompt  # raw measurements aren't sent

    b = g["brief"]
    assert b["brief"]["headline"] == FAKE_BRIEF["headline"]
    assert b["brief"]["outfits"][0]["pieces"][1]["colour_hex"] is None  # "tan" isn't a hex colour
    assert b["brief"]["outfits"][0]["pieces"][2]["colour_hex"] is None
    assert b["usage"] == {"input_tokens": 1800, "output_tokens": 2400} and not b["photo_included"]
    assert client.get(f"/api/profiles/{pid}/style").json()["brief"]["brief"]["headline"] == FAKE_BRIEF["headline"]


def test_brief_photo_needs_a_photo(fake):
    r = client.post(f"/api/profiles/{_profile()}/style/brief", json={"include_photo": True})
    assert r.status_code == 422 and "no photo" in r.json()["detail"]
    assert not fake.calls


def test_brief_with_photo_attaches_image(fake, tmp_path):
    from PIL import Image
    from app import db
    pid = _profile()
    Image.new("RGB", (300, 300), (200, 170, 150)).save(db.photos_dir() / "p.jpg")
    db.create_row("photos", {"profile_id": pid, "filename": "p.jpg", "width": 300, "height": 300,
                             "analysis": {}, "manual": {}})
    client.post(f"/api/profiles/{pid}/style/brief", json={"include_photo": True})
    content = fake.calls[0]["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/jpeg"


@pytest.mark.parametrize("stop_reason,text,message", [
    ("refusal", "", "declined"),
    ("max_tokens", "{", "cut off"),
    ("end_turn", "not json", "couldn't be read"),
])
def test_brief_failures_are_explained(monkeypatch, stop_reason, text, message):
    monkeypatch.setattr(brief, "_client", lambda: FakeClient(stop_reason, text))
    r = client.post(f"/api/profiles/{_profile()}/style/brief", json={})
    assert r.status_code == 502 and message in r.json()["detail"]


def test_api_key_settings(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert client.get("/api/settings/anthropic-key").json()["configured"] is False
    assert client.put("/api/settings/anthropic-key", json={"key": "hello"}).status_code == 422
    assert client.put("/api/settings/anthropic-key", json={"key": "sk-ant-test"}).json() == \
        {"configured": True, "source": "saved in the app"}
    assert brief.saved_key() == "sk-ant-test"
    assert client.put("/api/settings/anthropic-key", json={"key": ""}).json()["configured"] is False
