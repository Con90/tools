import re

import pytest

from app.seasons import NATURAL_HAIR, PROTOTYPES, SEASONS, rank_seasons, scores

ARCHETYPES = [
    # skin, hair, eyes (Lab) → acceptable seasons (top two must include one)
    (([72, 12, 22], [65, 5, 28], [50, -2, -15]), {"light_spring"}),
    (([70, 14, 12], [16, 1, 1], [30, 4, 6]), {"true_winter", "bright_winter"}),
    (([70, 13, 13], [66, 1, 11], [55, -2, -7]), {"light_summer", "true_summer"}),
    (([40, 12, 19], [16, 1, 1], [25, 6, 8]), {"deep_autumn"}),
    (([40, 13, 12], [14, 1, 0], [22, 5, 5]), {"deep_winter"}),
    (([62, 12, 15], [40, 2, 7], [50, -1, -4]), {"soft_summer"}),
    (([60, 13, 24], [32, 16, 16], [45, 2, 18]), {"true_autumn"}),
    (([68, 12, 24], [60, 14, 26], [55, -18, 24]), {"true_spring", "bright_spring"}),
]


@pytest.mark.parametrize("colours,expected", ARCHETYPES)
def test_archetypes_land_in_top_two(colours, expected):
    top_two = {r["season"] for r in rank_seasons(scores(*colours))[:2]}
    assert top_two & expected


def test_axes_move_the_right_way():
    base = scores([65, 12, 18], [40, 5, 12], [45, 3, 10])
    assert scores([65, 12, 24], [40, 5, 12], [45, 3, 10])["warmth"] > base["warmth"]  # more golden skin
    assert scores([65, 12, 18], [20, 2, 3], [45, 3, 10])["depth"] > base["depth"]     # darker hair
    assert scores([65, 12, 18], [40, 5, 12], [50, -8, -30])["clarity"] > base["clarity"]  # vivid eyes


def test_works_with_skin_only():
    s = scores([70, 12, 20])
    assert set(s) == {"warmth", "depth", "clarity"}
    assert len(rank_seasons(s)) == 12


def test_ranking_matches_sum_to_about_100():
    assert 97 <= sum(r["match"] for r in rank_seasons(scores([65, 12, 18]))) <= 103


def test_every_season_has_a_complete_palette():
    assert set(SEASONS) == set(PROTOTYPES)
    for key, s in SEASONS.items():
        for field in ("neutrals", "colours", "accents", "avoid"):
            assert s[field], (key, field)
            for h in s[field]:
                assert re.fullmatch(r"#[0-9a-f]{6}", h), (key, h)
        assert s["name"] and s["summary"] and s["metals"] and s["tips"]


def test_natural_hair_presets():
    assert all(len(lab) == 3 for _, lab in NATURAL_HAIR.values())


def test_fair_skin_is_judged_against_a_fair_skin_reference():
    from app.seasons import neutral_skin_hue
    assert neutral_skin_hue(70) == 50 and neutral_skin_hue(40) == 58
    # Typical fair skin (hue ~50°) reads neutral rather than pink/cool…
    assert abs(scores([70, 16, 19])["warmth"]) < 0.1
    # …while the same hue on deeper skin still reads cool.
    assert scores([45, 16, 19])["warmth"] < -0.3
