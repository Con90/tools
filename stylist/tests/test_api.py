from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

PROFILE = {"name": "Me", "gender": "female", "sections": ["womens"], "fit": "regular", "mode": "detailed",
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


def _match(pid, garment):
    return client.get("/api/match", params={"profile_id": pid, "garment": garment}).json()


def test_results_include_european_equivalents():
    pid = client.post("/api/profiles", json=PROFILE).json()["id"]
    r = _match(pid, "dresses")[0]
    assert (r["size_system"], r["size"]) == ("UK", "12")
    assert r["equivalents"] == {"EU": "40", "US": "8", "Letter": "M"}


def test_quick_mode_uses_usual_sizes():
    profile = {"name": "Quick", "gender": "male", "sections": ["mens", "unisex"], "mode": "quick",
               "measurements": {"chest": 130},  # ignored in quick mode
               "usual_sizes": {"tops": {"system": "EU", "size": "48"},
                               "bottoms": {"system": "W", "size": "32", "length": "32"},
                               "shoes": {"system": "EU", "size": "43"}}}
    pid = client.post("/api/profiles", json=profile).json()["id"]

    tops = _match(pid, "tops")[0]
    assert tops["size"] == "M" and tops["estimated"]
    assert tops["details"][0]["estimated_from"] == "your usual tops size EU 48"

    bottoms = _match(pid, "bottoms")[0]
    assert (bottoms["size"], bottoms["length"]["label"]) == ("W32", "L32")

    shoes = _match(pid, "shoes")[0]
    assert shoes["equivalents"]["EU"] == "43"


def test_detailed_mode_fills_gaps_from_usual_sizes():
    profile = {**PROFILE, "measurements": {"chest": 90},
               "usual_sizes": {"tops": {"system": "UK", "size": "12"}}}
    pid = client.post("/api/profiles", json=profile).json()["id"]
    details = {d["measurement"]: d for d in _match(pid, "tops")[0]["details"]}
    assert details["chest"]["estimated_from"] is None
    assert details["chest"]["body"] == 90
    assert "UK 12" in details["waist"]["estimated_from"]


def test_shoes_match_on_foot_length():
    pid = client.post("/api/profiles", json={**PROFILE, "measurements": {"foot_length": 24.0}}).json()["id"]
    r = _match(pid, "shoes")[0]
    assert r["size"] == "5"
    assert r["equivalents"]["EU"] == "38"


def test_meta_lists_size_options():
    meta = client.get("/api/meta").json()
    assert "EU" in meta["size_options"]["female"]["dresses"]
    assert "dresses" not in meta["size_options"]["male"]
    assert meta["size_options"]["male"]["bottoms"]["W"][0] == "28"


def test_migrates_v1_database(tmp_path, monkeypatch):
    import json
    import sqlite3

    from app import db
    path = tmp_path / "v1.db"
    monkeypatch.setenv("STYLIST_DB", str(path))
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE profiles (id INTEGER PRIMARY KEY, name TEXT NOT NULL,
            sections TEXT NOT NULL, fit TEXT NOT NULL, measurements TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE TABLE size_charts (id INTEGER PRIMARY KEY, brand TEXT NOT NULL, section TEXT NOT NULL,
            garment TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL DEFAULT '',
            sizes TEXT NOT NULL, lengths TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL DEFAULT (datetime('now')));
        PRAGMA user_version = 1;
    """)
    old.execute("INSERT INTO profiles (name, sections, fit, measurements) VALUES ('Old', ?, 'regular', ?)",
                (json.dumps(["mens"]), json.dumps({"chest": 97})))
    old.execute("INSERT INTO size_charts (brand, section, garment, sizes) VALUES ('Mine', 'mens', 'tops', ?)",
                (json.dumps([{"label": "M", "ranges": {"chest": [94, 100]}}]),))
    old.commit()
    old.close()

    profile = db.list_rows("profiles")[0]
    assert (profile["gender"], profile["mode"], profile["usual_sizes"]) == ("male", "detailed", {})
    charts = db.list_rows("size_charts")
    assert next(c for c in charts if c["brand"] == "Mine")["size_system"] == "Letter"
    assert any(c["garment"] == "shoes" for c in charts)
