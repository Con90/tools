"""App settings kept on this computer only (data/settings.json): API keys and preferences."""

from __future__ import annotations

import json
from pathlib import Path

from . import db


def _path() -> Path:
    return db.db_path().parent / "settings.json"


def _load() -> dict:
    try:
        return json.loads(_path().read_text())
    except (OSError, ValueError):
        return {}


def get(key: str, default=None):
    return _load().get(key, default)


def put(key: str, value) -> None:
    settings = _load()
    if value in (None, ""):
        settings.pop(key, None)
    else:
        settings[key] = value
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings))
    try:
        path.chmod(0o600)  # may hold API keys; readable by this user only
    except OSError:
        pass
