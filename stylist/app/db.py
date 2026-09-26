"""SQLite storage for profiles and size charts.

Measurements and chart sizes are stored as JSON — they're always read and
written whole, and the set of measurements is expected to grow.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DEFAULT_DB = APP_DIR.parent / "data" / "stylist.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    gender       TEXT NOT NULL DEFAULT 'female',
    sections     TEXT NOT NULL DEFAULT '["womens","unisex"]',
    fit          TEXT NOT NULL DEFAULT 'regular',
    mode         TEXT NOT NULL DEFAULT 'quick',
    measurements TEXT NOT NULL DEFAULT '{}',
    usual_sizes  TEXT NOT NULL DEFAULT '{}',
    colour       TEXT NOT NULL DEFAULT '{}',
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS size_charts (
    id         INTEGER PRIMARY KEY,
    brand      TEXT NOT NULL,
    section    TEXT NOT NULL,
    garment    TEXT NOT NULL,
    size_system TEXT NOT NULL DEFAULT 'Other',
    notes      TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    sizes      TEXT NOT NULL DEFAULT '[]',
    lengths    TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
""" + """
CREATE TABLE IF NOT EXISTS photos (
    id         INTEGER PRIMARY KEY,
    profile_id INTEGER NOT NULL,
    filename   TEXT NOT NULL,
    width      INTEGER NOT NULL,
    height     INTEGER NOT NULL,
    analysis   TEXT NOT NULL DEFAULT '{}',
    manual     TEXT NOT NULL DEFAULT '{}',
    included   INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

PROFILE_JSON = ("sections", "measurements", "usual_sizes", "colour")
CHART_JSON = ("sizes", "lengths")
PHOTO_JSON = ("analysis", "manual")


def db_path() -> Path:
    return Path(os.environ.get("STYLIST_DB", DEFAULT_DB))


def photos_dir() -> Path:
    """Uploaded photos live next to the database, so they stay on this computer."""
    d = db_path().parent / "photos"
    d.mkdir(parents=True, exist_ok=True)
    return d


SCHEMA_VERSION = 3


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    _initialise(conn)
    conn.isolation_level = ""  # back to normal implicit transactions
    return conn


def _initialise(conn: sqlite3.Connection) -> None:
    """Create or upgrade tables and seed starter charts exactly once.

    Several requests can open a brand-new database at the same moment, so the
    check-and-seed runs under a write lock with the version kept in the file.
    """
    if conn.execute("PRAGMA user_version").fetchone()[0] >= SCHEMA_VERSION:
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    conn.execute(statement)
            _seed(conn)
        else:
            if version < 2:
                _migrate_v2(conn)
            if version < 3:
                _migrate_v3(conn)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


@contextmanager
def session():
    """Connection that commits on success and is always closed."""
    conn = connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _seed(conn: sqlite3.Connection) -> None:
    """Load starter size charts, skipping any brand/section/garment already present."""
    have = {tuple(r) for r in conn.execute("SELECT brand, section, garment FROM size_charts")}
    for chart in json.loads((APP_DIR / "starter_charts.json").read_text()):
        if (chart["brand"], chart["section"], chart["garment"]) not in have:
            _insert(conn, "size_charts", chart, CHART_JSON)


def _migrate_v2(conn: sqlite3.Connection) -> None:
    """v1 → v2: gender, quick mode and usual sizes on profiles; size systems on charts."""
    conn.execute("ALTER TABLE profiles ADD COLUMN gender TEXT NOT NULL DEFAULT 'female'")
    # Existing profiles were built from measurements, so keep them in detailed mode.
    conn.execute("ALTER TABLE profiles ADD COLUMN mode TEXT NOT NULL DEFAULT 'detailed'")
    conn.execute("ALTER TABLE profiles ADD COLUMN usual_sizes TEXT NOT NULL DEFAULT '{}'")
    conn.execute("ALTER TABLE size_charts ADD COLUMN size_system TEXT NOT NULL DEFAULT 'Other'")
    for pid, sections in conn.execute("SELECT id, sections FROM profiles").fetchall():
        if "mens" in json.loads(sections) and "womens" not in json.loads(sections):
            conn.execute("UPDATE profiles SET gender = 'male' WHERE id = ?", (pid,))
    for cid, sizes in conn.execute("SELECT id, sizes FROM size_charts").fetchall():
        conn.execute("UPDATE size_charts SET size_system = ? WHERE id = ?",
                     (guess_size_system([s["label"] for s in json.loads(sizes)]), cid))
    _seed(conn)  # adds the new starter shoe charts


def _migrate_v3(conn: sqlite3.Connection) -> None:
    """v2 → v3: colour analysis (photos table, colour settings on profiles)."""
    conn.execute("ALTER TABLE profiles ADD COLUMN colour TEXT NOT NULL DEFAULT '{}'")
    photos = SCHEMA[SCHEMA.index("CREATE TABLE IF NOT EXISTS photos"):]
    conn.execute(photos.split(";")[0])


def guess_size_system(labels: list[str]) -> str:
    labels = [str(l).strip().upper() for l in labels]
    if labels and all(re.fullmatch(r"W\d+", l) for l in labels):
        return "W"
    if labels and all(re.fullmatch(r"(X*S|M|X*L|\dXL)", l) for l in labels):
        return "Letter"
    if labels and all(re.fullmatch(r"\d+(\.\d+)?", l) for l in labels):
        return "UK" if max(float(l) for l in labels) < 30 else "EU"
    return "Other"


def _row(row: sqlite3.Row | None, json_cols) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for col in json_cols:
        d[col] = json.loads(d[col])
    return d


def _encode(data: dict, json_cols) -> dict:
    return {k: json.dumps(v) if k in json_cols else v for k, v in data.items()}


def _insert(conn, table: str, data: dict, json_cols) -> int:
    data = _encode(data, json_cols)
    cols = ", ".join(data)
    marks = ", ".join("?" for _ in data)
    cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(data.values()))
    return cur.lastrowid


# --- generic CRUD, parameterised by table --------------------------------

TABLES = {"profiles": PROFILE_JSON, "size_charts": CHART_JSON, "photos": PHOTO_JSON}


def list_rows(table: str) -> list[dict]:
    order = {"profiles": "name", "size_charts": "brand, section, garment", "photos": "id"}[table]
    with session() as conn:
        return [_row(r, TABLES[table]) for r in conn.execute(f"SELECT * FROM {table} ORDER BY {order}")]


def list_photos(profile_id: int) -> list[dict]:
    with session() as conn:
        rows = conn.execute("SELECT * FROM photos WHERE profile_id = ? ORDER BY id", (profile_id,))
        return [_row(r, PHOTO_JSON) for r in rows]


def get_row(table: str, row_id: int) -> dict | None:
    with session() as conn:
        return _row(conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone(), TABLES[table])


def create_row(table: str, data: dict) -> dict:
    with session() as conn:
        row_id = _insert(conn, table, data, TABLES[table])
    return get_row(table, row_id)


def update_row(table: str, row_id: int, data: dict) -> dict | None:
    data = _encode(data, TABLES[table])
    sets = ", ".join(f"{k} = ?" for k in data)
    with session() as conn:
        cur = conn.execute(f"UPDATE {table} SET {sets}, updated_at = datetime('now') WHERE id = ?",
                           [*data.values(), row_id])
        if cur.rowcount == 0:
            return None
    return get_row(table, row_id)


def delete_row(table: str, row_id: int) -> bool:
    with session() as conn:
        return conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,)).rowcount > 0
