from app.sizing import match_all, match_chart, normalise_range

TOPS = {
    "brand": "Test", "section": "mens", "garment": "tops",
    "sizes": [
        {"label": "S", "ranges": {"chest": [86, 94], "waist": [72, 80]}},
        {"label": "M", "ranges": {"chest": [94, 100], "waist": [80, 86]}},
        {"label": "L", "ranges": {"chest": [100, 106], "waist": [86, 92]}},
    ],
}


def test_normalise_range():
    assert normalise_range([90, 86]) == (86, 90)
    assert normalise_range(81) == (80, 82)


def test_exact_fit_is_great():
    r = match_chart(TOPS, {"chest": 97, "waist": 83})
    assert r["size"] == "M"
    assert r["verdict"] == "great"
    assert all(d["status"] == "good" for d in r["details"])


def test_chest_outweighs_waist():
    # Chest says L, waist says M: tops are sized by chest.
    r = match_chart(TOPS, {"chest": 103, "waist": 84})
    assert r["size"] == "L"


def test_fit_preference_shifts_size():
    body = {"chest": 95}
    assert match_chart(TOPS, body, "slim")["size"] == "S"
    assert match_chart(TOPS, body, "regular")["size"] == "M"
    assert match_chart(TOPS, {"chest": 99}, "relaxed")["size"] == "L"


def test_slim_note_still_reports_real_difference():
    r = match_chart(TOPS, {"chest": 95}, "slim")
    chest = r["details"][0]
    assert chest["status"] == "good"  # judged against the fit asked for
    assert chest["note"] == "snug by 1 cm"  # but honest about the body


def test_out_of_range_is_poor():
    r = match_chart(TOPS, {"chest": 115})
    assert r["size"] == "L"
    assert r["verdict"] == "poor"
    assert r["details"][0]["note"] == "tight by 9 cm"


def test_between_sizes_offers_alternative():
    r = match_chart(TOPS, {"chest": 99.5})
    assert r["size"] == "M"
    assert r["alternative"]["size"] == "L"


def test_chart_without_matching_measurements_is_skipped():
    assert match_chart(TOPS, {"inseam": 80}) is None


def test_lengths_pick_leg_length():
    chart = {
        "brand": "Jeans", "section": "mens", "garment": "bottoms",
        "sizes": [{"label": "W32", "ranges": {"waist": [80, 83]}}],
        "lengths": [{"label": "L30", "inseam": [74, 78]}, {"label": "L32", "inseam": [79, 83]}],
    }
    r = match_chart(chart, {"waist": 81, "inseam": 81})
    assert (r["size"], r["length"]["label"]) == ("W32", "L32")


def test_length_note_uses_long_short_words():
    chart = {"brand": "X", "section": "womens", "garment": "bottoms",
             "sizes": [{"label": "10", "ranges": {"waist": [66, 70], "inseam": [76, 81]}}]}
    r = match_chart(chart, {"waist": 68, "inseam": 85})
    inseam = next(d for d in r["details"] if d["measurement"] == "inseam")
    assert inseam["note"] == "4 cm short"


def test_match_all_filters_and_ranks():
    good = dict(TOPS, brand="Alpha")
    bad = dict(TOPS, brand="Beta", sizes=[{"label": "XS", "ranges": {"chest": [70, 75]}}])
    womens = dict(TOPS, brand="Gamma", section="womens")
    trousers = dict(TOPS, brand="Delta", garment="bottoms")
    results = match_all([bad, good, womens, trousers], {"chest": 97}, "tops", sections=["mens"])
    assert [r["brand"] for r in results] == ["Alpha", "Beta"]
