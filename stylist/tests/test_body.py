import pytest

from app.body import SHAPES, classify, contrast_level, female_shape, male_shape, proportions


@pytest.mark.parametrize("bust,waist,hips,expected", [
    (90, 70, 98, ("hourglass", None)),
    (90.5, 72.5, 108.5, ("pear", "with a defined waist")),   # FFIT "bottom hourglass"
    (88, 84, 104, ("pear", None)),
    (104, 74, 94, ("hourglass", "a little fuller on top")),  # FFIT "top hourglass"
    (104, 88, 92, ("inverted_triangle", None)),
    (86, 78, 88, ("rectangle", None)),
    (100, 95, 102, ("apple", None)),
])
def test_female_shapes(bust, waist, hips, expected):
    assert female_shape(bust, waist, hips) == expected


@pytest.mark.parametrize("chest,waist,hips,expected", [
    (110, 82, None, "inverted_triangle"),
    (100, 86, None, "trapezoid"),
    (96, 90, None, "rectangle"),
    (100, 104, None, "oval"),
    (95, 85, 102, "triangle"),
])
def test_male_shapes(chest, waist, hips, expected):
    assert male_shape(chest, waist, hips) == expected


def test_classify_needs_enough_measurements():
    assert classify("female", {"chest": 90, "waist": 70}) is None
    assert classify("male", {"chest": 100, "waist": 86})["shape"] == "trapezoid"


def test_proportions():
    assert proportions("female", {"height": 155, "inseam": 64}) == {"height": "petite", "legs": "short", "leg_ratio": 0.413}
    assert proportions("male", {"height": 192})["height"] == "tall"
    assert proportions("female", {}) == {}


def test_contrast_level():
    assert contrast_level({"skin": {"lab": [75, 10, 15]}, "hair": {"lab": [15, 1, 1]}}) == "high"
    assert contrast_level({"skin": {"lab": [70, 10, 15]}, "hair": {"lab": [60, 5, 20]}}) == "low"
    assert contrast_level({"skin": {"lab": [70, 10, 15]}}) is None


def test_every_shape_has_guidance():
    for gender, shapes in SHAPES.items():
        for key, s in shapes.items():
            assert s["name"] and s["summary"] and s["goal"] and s["wear"] and s["avoid"], (gender, key)
