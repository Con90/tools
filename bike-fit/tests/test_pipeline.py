"""End-to-end checks against a synthetic rider whose true angles are known.

Run:  .venv/bin/pip install pytest && .venv/bin/python -m pytest
"""

from dataclasses import replace

import numpy as np
import pytest

from bikefit.analysis import analyse
from bikefit.angles import included
from bikefit.clean import fix_swaps, reject_spikes
from bikefit.export import compare, write_all
from bikefit.landmarks import Track, load_csv, save_csv
from bikefit.report import build
from bikefit.synth import Rider, make_track, truth

NOISY = dict(noise_px=3, dropout=0.02, swaps=0.01, swap_runs=4, spikes=0.005)


def saddle_rec(an):
    return next(r for r in an.recommendations if r.area == "Saddle height")


def test_included_angle():
    a, b, c = np.array([1.0, 0]), np.array([0.0, 0]), np.array([0.0, 1])
    assert included(a, b, c) == pytest.approx(90)
    assert included(a, b, -a) == pytest.approx(180)


def test_csv_roundtrip(tmp_path):
    tr = make_track(Rider(seconds=2), noise_px=1, dropout=0.1, seed=3)
    tr.points[("left", "toe")][5] = np.nan
    save_csv(tr, tmp_path / "k.csv")
    back = load_csv(tmp_path / "k.csv")
    assert back.fps == tr.fps and back.n == tr.n and back.width == tr.width
    for k in tr.points:
        np.testing.assert_allclose(back.points[k], tr.points[k], atol=0.006)


@pytest.mark.parametrize("cadence", [75, 90, 105])
def test_recovers_knee_angles_clean(cadence):
    r = Rider(cadence=cadence)
    t = truth(r)
    an = analyse(make_track(r))
    assert an.summary["knee_ext"]["median"] == pytest.approx(t["knee_ext"], abs=0.4)
    assert an.summary["knee_top"]["median"] == pytest.approx(t["knee_top"], abs=0.4)
    assert an.strokes.cadence == pytest.approx(cadence, abs=0.5)
    assert an.quality == "good"


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_recovers_knee_angles_noisy(seed):
    r = Rider()
    t = truth(r)
    an = analyse(make_track(r, seed=seed, **NOISY))
    assert an.summary["knee_ext"]["median"] == pytest.approx(t["knee_ext"], abs=1.0)
    assert an.summary["knee_ext"]["sd"] < 1.5
    assert len(an.rows) >= 40


def test_facing_left_matches_facing_right():
    right = analyse(make_track(Rider(facing=1)))
    left = analyse(make_track(Rider(facing=-1)))
    assert left.cleaned.facing == -1 and right.cleaned.facing == 1
    for k in ("knee_ext", "knee_top", "hip_closed", "torso", "elbow"):
        assert left.summary[k]["median"] == pytest.approx(right.summary[k]["median"], abs=0.2)


def test_swap_fixer_repairs_runs():
    r = Rider()
    ref = make_track(r, seed=5)
    tr = make_track(r, seed=5, swaps=0.03, swap_runs=8)
    wrong = lambda t: (np.linalg.norm(t.xy("right", "ankle") - ref.xy("right", "ankle"), axis=1) > 50).sum()
    assert wrong(tr) > 100
    fix_swaps(tr, "right")
    assert wrong(tr) == 0


def test_spike_next_to_gap_is_removed():
    t = np.arange(200) / 60
    xy = np.column_stack([100 * np.sin(2 * np.pi * 1.5 * t), 100 * np.cos(2 * np.pi * 1.5 * t)])
    xy[50] = np.nan
    xy[51] += 120                                   # spike right beside a dropout
    xy[120] += 90
    out = reject_spikes(xy)
    assert np.isnan(out[51]).all() and np.isnan(out[120]).all()
    assert np.isfinite(out).all(axis=1).sum() == 197  # nothing else removed


def test_saddle_recommendation_closes_the_loop():
    r = Rider(saddle=714)
    an = analyse(make_track(r, seed=1, **NOISY), leg_mm=r.leg)
    rec = saddle_rec(an)
    assert rec.action.startswith("Raise") and 5 <= rec.change_mm <= 10
    after = truth(replace(r, saddle=r.saddle + rec.change_mm))["knee_ext"]
    assert an.ranges["knee_ext"].lo <= after <= an.ranges["knee_ext"].hi


def test_saddle_too_high_says_lower():
    r = Rider(saddle=752)
    an = analyse(make_track(r), leg_mm=r.leg)
    assert saddle_rec(an).action.startswith("Lower")


def test_in_range_says_no_change():
    an = analyse(make_track(Rider()), leg_mm=Rider().leg)
    assert saddle_rec(an).action == "No change"


def test_scale_from_leg_length():
    r = Rider()
    an = analyse(make_track(r), leg_mm=r.leg)
    assert an.scale.mm_per_px == pytest.approx(1 / r.px_per_mm, rel=0.01)


def test_no_scale_gives_direction_only():
    an = analyse(make_track(Rider(saddle=714)))
    rec = saddle_rec(an)
    assert rec.change_mm is None and "--leg-mm" in rec.detail


def test_nothing_detected_is_graceful():
    an = analyse(Track.empty(300, 60, 1920, 1080))
    assert an.quality == "poor" and not an.rows
    assert any("found a person" in n for n in an.notes)


def test_outputs_and_compare(tmp_path):
    r = Rider(seconds=15)
    before = analyse(make_track(replace(r, saddle=714)), leg_mm=r.leg)
    after = analyse(make_track(r), leg_mm=r.leg)
    write_all(before, tmp_path / "a")
    write_all(after, tmp_path / "b")
    html = build(after, tmp_path / "b", None).read_text()
    assert "Bike fit report" in html and "data:image/jpeg;base64," in html
    assert (tmp_path / "b" / "summary.md").read_text().count("|") > 20
    table = compare(tmp_path / "a" / "metrics.json", tmp_path / "b" / "metrics.json")
    assert "Knee flexion at full extension" in table and "-" in table
