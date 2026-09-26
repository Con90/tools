from app.conversions import clean_label, equivalents, shoe_equivalents
from app.db import guess_size_system


def test_clean_label():
    assert clean_label("uk 12") == "12"
    assert clean_label("W32") == "32"
    assert clean_label("eu 42.0") == "42"
    assert clean_label(" 2xl ") == "XXL"


def test_womens_uk_eu_us():
    assert equivalents("UK", "10", "female", "tops") == {"EU": "38", "US": "6", "Letter": "M"}
    assert equivalents("EU", "44", "female", "tops") == {"UK": "16", "US": "12", "Letter": "L"}


def test_letter_spans_several_sizes():
    assert equivalents("Letter", "M", "female", "tops")["UK"] == "10–12"


def test_mens_trousers():
    assert equivalents("W", "34", "male", "bottoms") == {"EU": "50", "Letter": "L"}


def test_unknown_system_or_size_gives_nothing():
    assert equivalents("Other", "Petite 2", "female", "tops") == {}
    assert equivalents("UK", "99", "female", "tops") == {}


def test_shoes():
    assert shoe_equivalents("UK", "8", "male") == {"UK": "8", "EU": "42", "US": "9", "cm": "26.4"}
    assert shoe_equivalents("EU", "38", "female")["UK"] == "5"
    assert shoe_equivalents("US", "7", "female")["UK"] == "5"


def test_guess_size_system():
    assert guess_size_system(["S", "M", "XL", "2XL"]) == "Letter"
    assert guess_size_system(["W30", "W32"]) == "W"
    assert guess_size_system(["8", "10", "12"]) == "UK"
    assert guess_size_system(["36", "38", "40"]) == "EU"
    assert guess_size_system(["Petite"]) == "Other"
