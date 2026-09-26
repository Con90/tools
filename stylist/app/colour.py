"""Colour science helpers: sRGB ↔ CIELAB, white balance, robust sampling.

CIELAB is used for everything because its distances roughly match what people
see: L* is lightness (0 black – 100 white), a* runs green→red, b* blue→yellow.
Chroma C* = √(a*² + b*²) is how vivid a colour is, and the hue angle
h = atan2(b*, a*) says whether skin leans pink (lower h) or golden (higher h).
"""

from __future__ import annotations

import numpy as np

# sRGB (D65) → XYZ
_M = np.array([
    [0.4124564, 0.3575761, 0.1804375],
    [0.2126729, 0.7151522, 0.0721750],
    [0.0193339, 0.1191920, 0.9503041],
])
_M_INV = np.linalg.inv(_M)
_WHITE = np.array([0.95047, 1.0, 1.08883])


def srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(lin: np.ndarray) -> np.ndarray:
    c = np.clip(lin, 0, 1)
    c = np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)
    return c * 255.0


def linear_to_lab(lin: np.ndarray) -> np.ndarray:
    """(..., 3) linear RGB (0–1) → Lab."""
    xyz = np.asarray(lin, dtype=np.float64) @ _M.T / _WHITE
    f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], axis=-1)


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """(..., 3) uint8-range sRGB → (..., 3) Lab."""
    return linear_to_lab(srgb_to_linear(rgb))


def lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    lab = np.asarray(lab, dtype=np.float64)
    fy = (lab[..., 0] + 16) / 116
    f = np.stack([fy + lab[..., 1] / 500, fy, fy - lab[..., 2] / 200], axis=-1)
    xyz = np.where(f > 6 / 29, f ** 3, 3 * (6 / 29) ** 2 * (f - 4 / 29)) * _WHITE
    return linear_to_srgb(xyz @ _M_INV.T)


def lab_to_hex(lab) -> str:
    r, g, b = (int(round(v)) for v in lab_to_rgb(np.asarray(lab)))
    return f"#{r:02x}{g:02x}{b:02x}"


def hex_to_lab(hex_colour: str) -> np.ndarray:
    h = hex_colour.lstrip("#")
    return rgb_to_lab(np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)]))


def lch(lab) -> tuple[float, float, float]:
    """Lab → (L*, chroma, hue angle in degrees 0–360)."""
    L, a, b = (float(v) for v in lab)
    return L, float(np.hypot(a, b)), float(np.degrees(np.arctan2(b, a)) % 360)


def white_gains(white_linear) -> np.ndarray:
    """Von Kries gains that make `white_linear` neutral, keeping overall brightness.

    Multiply linear-RGB samples by these to correct a colour cast.
    """
    white = np.maximum(np.asarray(white_linear, dtype=np.float64), 1e-4)
    return white.mean() / white


def delta_e(lab1, lab2) -> float:
    return float(np.linalg.norm(np.asarray(lab1, float) - np.asarray(lab2, float)))
