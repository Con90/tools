from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

PROFILE = {"name": "Me", "sections": ["womens"], "fit": "regular",
           "measurements": {"chest": 90, "waist": 72, "hips": 98, "inseam": 78}}


def test_index_and_static_served():
    assert "Stylist" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200


def test_starter_charts_seeded():
    charts = client.get("/api/charts").json()
    assert {c["garment"] for c in charts} >= {"tops", "bottoms", "dresses"}


def test_profile_crud():
    created = client.post("/api/profiles", json=PROFILE).json()
    assert created["measurements"]["chest"] == 90

    updated = client.put(f"/api/profiles/{created['id']}", json={**PROFILE, "fit": "slim"}).json()
    assert updated["fit"] == "slim"

    assert client.delete(f"/api/profiles/{created['id']}").status_code == 204
    assert client.get(f"/api/profiles/{created['id']}").status_code == 404


def test_rejects_unknown_measurement():
    r = client.post("/api/profiles", json={**PROFILE, "measurements": {"wingspan": 180}})
    assert r.status_code == 422


def test_match_uses_profile_sections():
    pid = client.post("/api/profiles", json=PROFILE).json()["id"]
    results = client.get("/api/match", params={"profile_id": pid, "garment": "bottoms"}).json()
    assert [r["brand"] for r in results] == ["Generic UK (starter)"]
    assert results[0]["size"] == "12"
    assert results[0]["length"]["label"] == "Regular"


def test_chart_crud_and_match():
    chart = {"brand": "My Brand", "section": "womens", "garment": "tops",
             "sizes": [{"label": "S", "ranges": {"chest": [86, 92]}},
                       {"label": "M", "ranges": {"chest": [92, 98]}}]}
    cid = client.post("/api/charts", json=chart).json()["id"]
    pid = client.post("/api/profiles", json=PROFILE).json()["id"]
    results = client.get("/api/match", params={"profile_id": pid, "garment": "tops"}).json()
    assert {"My Brand": "S"}.items() <= {r["brand"]: r["size"] for r in results}.items()

    assert client.delete(f"/api/charts/{cid}").status_code == 204


def test_chart_validation():
    bad = {"brand": "X", "section": "womens", "garment": "hats",
           "sizes": [{"label": "S", "ranges": {"chest": [1, 2, 3]}}]}
    assert client.post("/api/charts", json=bad).status_code == 422


def test_concurrent_first_requests_seed_once():
    from concurrent.futures import ThreadPoolExecutor

    from app import db
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda _: db.list_rows("size_charts"), range(8)))
    charts = db.list_rows("size_charts")
    keys = [(c["brand"], c["section"], c["garment"]) for c in charts]
    assert len(keys) == len(set(keys))
