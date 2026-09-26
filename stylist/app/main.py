"""Stylist web app: FastAPI backend serving a static single-page front end."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import db
from .sizing import FIT_OFFSETS, GARMENTS, MEASUREMENTS, SECTIONS, match_all

STATIC = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Stylist")

Section = Literal["womens", "mens", "unisex"]
Fit = Literal["slim", "regular", "relaxed"]
Range = list[float] | float


def _check_measurements(values: dict[str, float]) -> dict[str, float]:
    for key, v in values.items():
        if key not in MEASUREMENTS:
            raise ValueError(f"unknown measurement '{key}'")
        if not 0 < v < 300:
            raise ValueError(f"{key} must be between 0 and 300 cm")
    return values


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    sections: list[Section] = ["womens", "mens", "unisex"]
    fit: Fit = "regular"
    measurements: dict[str, float] = {}

    _valid = field_validator("measurements")(_check_measurements)


class Size(BaseModel):
    label: str = Field(min_length=1, max_length=20)
    ranges: dict[str, Range]

    @field_validator("ranges")
    @classmethod
    def _ranges(cls, v):
        for key, r in v.items():
            if key not in MEASUREMENTS:
                raise ValueError(f"unknown measurement '{key}'")
            if isinstance(r, list) and len(r) != 2:
                raise ValueError(f"{key}: a range needs exactly two numbers")
        return v


class Length(BaseModel):
    label: str = Field(min_length=1, max_length=20)
    inseam: Range


class ChartIn(BaseModel):
    brand: str = Field(min_length=1, max_length=80)
    section: Section
    garment: str
    notes: str = ""
    source_url: str = ""
    sizes: list[Size] = Field(min_length=1)
    lengths: list[Length] = []

    @field_validator("garment")
    @classmethod
    def _garment(cls, v):
        if v not in GARMENTS:
            raise ValueError(f"unknown garment type '{v}'")
        return v


def _found(row):
    if row is None:
        raise HTTPException(404, "not found")
    return row


@app.get("/api/meta")
def meta():
    return {
        "measurements": {k: {"label": label, "kind": kind} for k, (label, kind) in MEASUREMENTS.items()},
        "garments": {k: {"label": label, "measurements": list(weights)} for k, (label, weights) in GARMENTS.items()},
        "sections": SECTIONS,
        "fits": list(FIT_OFFSETS),
    }


# --- profiles --------------------------------------------------------------

@app.get("/api/profiles")
def list_profiles():
    return db.list_rows("profiles")


@app.post("/api/profiles", status_code=201)
def create_profile(p: ProfileIn):
    return db.create_row("profiles", p.model_dump())


@app.get("/api/profiles/{pid}")
def get_profile(pid: int):
    return _found(db.get_row("profiles", pid))


@app.put("/api/profiles/{pid}")
def update_profile(pid: int, p: ProfileIn):
    return _found(db.update_row("profiles", pid, p.model_dump()))


@app.delete("/api/profiles/{pid}", status_code=204)
def delete_profile(pid: int):
    if not db.delete_row("profiles", pid):
        raise HTTPException(404, "not found")


# --- size charts -----------------------------------------------------------

@app.get("/api/charts")
def list_charts():
    return db.list_rows("size_charts")


@app.post("/api/charts", status_code=201)
def create_chart(c: ChartIn):
    return db.create_row("size_charts", c.model_dump())


@app.get("/api/charts/{cid}")
def get_chart(cid: int):
    return _found(db.get_row("size_charts", cid))


@app.put("/api/charts/{cid}")
def update_chart(cid: int, c: ChartIn):
    return _found(db.update_row("size_charts", cid, c.model_dump()))


@app.delete("/api/charts/{cid}", status_code=204)
def delete_chart(cid: int):
    if not db.delete_row("size_charts", cid):
        raise HTTPException(404, "not found")


# --- matching --------------------------------------------------------------

@app.get("/api/match")
def match(profile_id: int, garment: str, fit: Fit | None = None):
    if garment not in GARMENTS:
        raise HTTPException(400, f"unknown garment type '{garment}'")
    profile = _found(db.get_row("profiles", profile_id))
    return match_all(db.list_rows("size_charts"), profile["measurements"], garment,
                     fit or profile["fit"], profile["sections"])


# --- front end -------------------------------------------------------------

app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
