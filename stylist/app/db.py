"""SQLite storage for profiles and size charts.

Measurements and chart sizes are stored as JSON — they're always read and
written whole, and the set of measurements is expected to grow.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DEFAULT_DB = APP_DIR.parent / "data" / "stylist.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    sections     TEXT NOT NULL DEFAULT '["womens","mens","unisex"]',
    fit          TEXT NOT NULL DEFAULT 'regular',
    measurements TEXT NOT NULL DEFAULT '{}',
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS size_charts (
    id         INTEGER PRIMARY KEY,
    brand      TEXT NOT NULL,
    section    TEXT NOT NULL,
    garment    TEXT NOT NULL,
    notes      TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    sizes      TEXT NOT NULL DEFAULT '[]',
    lengths    TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

PROFILE_JSON = ("sections", "measurements")
CHART_JSON = ("sizes", "lengths")


def db_path() -> Path:
    return Path(os.environ.get("STYLIST_DB", DEFAULT_DB))


SCHEMA_VERSION = 1


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    _initialise(conn)
    conn.isolation_level = ""  # back to normal implicit transactions
    return conn


def _initialise(conn: sqlite3.Connection) -> None:
    """Create tables and seed starter charts exactly once.

    Several requests can open a brand-new database at the same moment, so the
    check-and-seed runs under a write lock with the version kept in the file.
    """
    if conn.execute("PRAGMA user_version").fetchone()[0] >= SCHEMA_VERSION:
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        if conn.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    conn.execute(statement)
            _seed(conn)
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
    """Load the starter size charts into a brand-new database."""
    charts = json.loads((APP_DIR / "starter_charts.json").read_text())
    for chart in charts:
        _insert(conn, "size_charts", chart, CHART_JSON)


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

TABLES = {"profiles": PROFILE_JSON, "size_charts": CHART_JSON}


def list_rows(table: str) -> list[dict]:
    order = "name" if table == "profiles" else "brand, section, garment"
    with session() as conn:
        return [_row(r, TABLES[table]) for r in conn.execute(f"SELECT * FROM {table} ORDER BY {order}")]


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
