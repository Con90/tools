import pytest


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Every test gets its own fresh database (seeded with the starter charts)."""
    monkeypatch.setenv("STYLIST_DB", str(tmp_path / "test.db"))
