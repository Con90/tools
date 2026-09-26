import numpy as np

from app.colour import delta_e, hex_to_lab, lab_to_hex, lch, linear_to_lab, rgb_to_lab, srgb_to_linear, white_gains


def test_reference_values():
    assert np.allclose(rgb_to_lab(np.array([255, 255, 255])), [100, 0, 0], atol=0.01)
    assert np.allclose(rgb_to_lab(np.array([0, 0, 0])), [0, 0, 0], atol=0.01)
    # sRGB red in CIELAB (D65) is about (53.24, 80.09, 67.20)
    assert np.allclose(rgb_to_lab(np.array([255, 0, 0])), [53.24, 80.09, 67.20], atol=0.05)


def test_hex_round_trip():
    for h in ("#c1442e", "#8fd3dc", "#000000", "#ffffff", "#7a4e3a"):
        assert lab_to_hex(hex_to_lab(h)) == h


def test_lch():
    L, C, h = lch([50, 0, 20])
    assert (L, round(C, 6), round(h, 6)) == (50, 20, 90)


def test_white_gains_neutralise_cast():
    warm_white = srgb_to_linear(np.array([255, 235, 200]))
    corrected = linear_to_lab(warm_white * white_gains(warm_white))
    assert abs(corrected[1]) < 0.5 and abs(corrected[2]) < 0.5


def test_delta_e():
    assert delta_e([50, 0, 0], [53, 4, 0]) == 5
