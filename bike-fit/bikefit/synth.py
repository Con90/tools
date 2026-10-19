"""Synthetic rider: known geometry in, keypoint Track out.

Used by the tests (does the pipeline recover the true angles? does a saddle
recommendation, applied, land the knee in range?) and by `bike_fit.py demo`.
Coordinates are millimetres with the bottom bracket at the origin, y up,
rider facing +x; they are converted to image pixels at the end.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import cv2
import numpy as np

from .landmarks import BONES, JOINTS, LEG_JOINTS, Track


@dataclass
class Rider:
    crank: float = 172.5
    thigh: float = 430.0          # hip centre -> knee centre
    shank: float = 440.0          # knee centre -> ankle
    foot_back: float = 105.0      # pedal spindle -> ankle
    toe_fwd: float = 75.0         # pedal spindle -> toe tip
    seat_angle: float = 73.0
    saddle: float = 725.0         # BB -> hip centre, along the seat tube
    setback_extra: float = 0.0
    torso_len: float = 540.0
    torso_angle: float = 40.0
    upper_arm: float = 300.0
    forearm: float = 270.0
    hands: tuple[float, float] = (660.0, 720.0)
    ankle_mean: float = 108.0     # knee-ankle-toe angle, mean over the stroke (deg)
    ankle_swing: float = 12.0     # ankling amplitude (deg); range of motion = 2x
    cadence: float = 90.0
    fps: float = 60.0
    seconds: float = 30.0
    px_per_mm: float = 0.65
    width: int = 1920
    height: int = 1080
    facing: int = 1               # +1 faces right in image (drive side view)

    @property
    def leg(self) -> float:
        return self.thigh + self.shank


def _two_link(p: np.ndarray, q: np.ndarray, l1: float, l2: float, sign: float) -> np.ndarray:
    """Joint between p and q with segment lengths l1 (from p), l2 (from q)."""
    d_vec = q - p
    d = np.linalg.norm(d_vec, axis=-1, keepdims=True)
    d_c = np.clip(d, abs(l1 - l2) + 1e-6, l1 + l2 - 1e-6)
    a = (l1 ** 2 - l2 ** 2 + d_c ** 2) / (2 * d_c)
    h = np.sqrt(np.maximum(l1 ** 2 - a ** 2, 0))
    u = d_vec / d
    perp = np.stack([-u[..., 1], u[..., 0]], axis=-1)
    return p + a * u + sign * h * perp


def pose_mm(r: Rider, side_phase: float = 0.0) -> dict[str, np.ndarray]:
    """Joint positions (mm) for every frame. side_phase=pi gives the far leg."""
    n = int(r.seconds * r.fps)
    t = np.arange(n) / r.fps
    phi = 2 * np.pi * r.cadence / 60 * t + side_phase          # 0 = top, forward positive
    pedal = r.crank * np.stack([np.sin(phi), np.cos(phi)], axis=1)
    sa = np.radians(r.seat_angle)
    hip0 = np.array([-r.saddle * np.cos(sa) - r.setback_extra, r.saddle * np.sin(sa)])
    hip = hip0 + _bob(phi - side_phase)        # small saddle bob, same for both legs
    # Ankle angle follows the stroke (most pointed just after the bottom). The
    # foot's orientation that gives it depends on the shin, which depends on
    # where the ankle is, so solve by fixed-point iteration.
    target = np.radians(r.ankle_mean + r.ankle_swing * np.cos(phi - np.radians(200)))
    foot_dir = np.full(n, np.radians(-10.0))    # direction ankle -> toe
    for _ in range(6):
        back = -np.stack([np.cos(foot_dir), np.sin(foot_dir)], axis=1)
        ankle = pedal + r.foot_back * back
        knee = _two_link(hip, ankle, r.thigh, r.shank, +1)
        shin = np.arctan2(knee[:, 1] - ankle[:, 1], knee[:, 0] - ankle[:, 0])
        foot_dir = shin - target
    back = -np.stack([np.cos(foot_dir), np.sin(foot_dir)], axis=1)
    ankle = pedal + r.foot_back * back
    knee = _two_link(hip, ankle, r.thigh, r.shank, +1)
    toe = pedal - r.toe_fwd * back
    heel = ankle + 45 * back + np.array([0.0, -55.0])
    ta = np.radians(r.torso_angle)
    shoulder = hip + r.torso_len * np.array([np.cos(ta), np.sin(ta)])
    hands = np.broadcast_to(np.array(r.hands, float), shoulder.shape)
    elbow = _two_link(shoulder, hands, r.upper_arm, r.forearm, -1)
    return {"shoulder": shoulder, "elbow": elbow, "wrist": hands.copy(), "hip": hip,
            "knee": knee, "ankle": ankle, "heel": heel, "toe": toe}


def _bob(phi: np.ndarray) -> np.ndarray:
    return np.stack([2 * np.sin(2 * phi), 3 * np.sin(2 * phi + 1)], axis=1)


def to_px(r: Rider, mm: np.ndarray) -> np.ndarray:
    ox, oy = r.width / 2 - r.facing * 60, r.height * 0.8
    return np.stack([ox + r.facing * mm[..., 0] * r.px_per_mm, oy - mm[..., 1] * r.px_per_mm], axis=-1)


def truth(r: Rider) -> dict[str, float]:
    """Ground-truth knee flexion at full extension and peak bend, deg."""
    p = pose_mm(replace(r, seconds=60 / r.cadence, fps=2000))
    u, v = p["hip"] - p["knee"], p["ankle"] - p["knee"]
    inc = np.degrees(np.arccos(np.sum(u * v, 1) / (np.linalg.norm(u, axis=1) * np.linalg.norm(v, axis=1))))
    flex = 180 - inc
    return {"knee_ext": float(flex.min()), "knee_top": float(flex.max())}


def make_track(r: Rider, noise_px: float = 0.0, dropout: float = 0.0, swaps: float = 0.0,
               spikes: float = 0.0, swap_runs: int = 0, seed: int = 0) -> Track:
    """Synthetic Track. The near side is the right leg (drive-side view)."""
    rng = np.random.default_rng(seed)
    near, far = pose_mm(r), pose_mm(r, np.pi)
    n = len(near["hip"])
    track = Track.empty(n, r.fps, r.width, r.height, source="synthetic")
    for side, pose, vis in (("right", near, 0.95), ("left", far, 0.6)):
        for j in JOINTS:
            src = pose[j] if (j in LEG_JOINTS or side == "right") else near[j]
            px = to_px(r, src) + rng.normal(0, noise_px, (n, 2)) if noise_px else to_px(r, src)
            track.points[(side, j)] = np.column_stack([px, np.full(n, vis)])
    if dropout:
        for j in JOINTS:
            m = rng.random(n) < dropout
            track.points[("right", j)][m, 2] = 0.1
    if spikes:
        for j in JOINTS:
            m = rng.random(n) < spikes
            track.points[("right", j)][m, :2] += rng.normal(0, 80, (m.sum(), 2))
    if swaps or swap_runs:
        m = rng.random(n) < swaps
        for _ in range(swap_runs):                 # the model flipping legs for a while
            i = rng.integers(0, n - 60)
            m[i:i + rng.integers(5, 60)] = True
        for j in LEG_JOINTS:
            a, b = track.points[("right", j)], track.points[("left", j)]
            a[m], b[m] = b[m].copy(), a[m].copy()
    return track


def render_video(r: Rider, path: str) -> None:
    """Draw a simple bike-and-rider animation, for the demo report and overlays."""
    near, far = pose_mm(r), pose_mm(r, np.pi)
    n = len(near["hip"])
    phi = 2 * np.pi * r.cadence / 60 * np.arange(n) / r.fps
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), r.fps, (r.width, r.height))
    sa = np.radians(r.seat_angle)
    P = lambda mm: tuple(int(v) for v in to_px(r, np.asarray(mm, float)))
    seat_top = np.array([-560 * np.cos(sa), 560 * np.sin(sa)])
    head = np.array([590.0, 640.0])
    for i in range(n):
        img = np.full((r.height, r.width, 3), (236, 238, 240), np.uint8)
        cv2.rectangle(img, (0, P((0, -270))[1]), (r.width, r.height), (205, 208, 212), -1)
        for axle in ((-410, 70), (600, 70)):
            cv2.circle(img, P(axle), int(340 * r.px_per_mm), (70, 70, 70), 6, cv2.LINE_AA)
        for a_, b_ in (((0, 0), (-410, 70)), ((0, 0), seat_top), (seat_top, head),
                       (head, (600, 70)), ((0, 0), head), (seat_top, (-410, 70))):
            cv2.line(img, P(a_), P(b_), (60, 90, 160), 10, cv2.LINE_AA)
        saddle = np.array([-r.saddle * np.cos(sa), r.saddle * np.sin(sa) - 85])
        cv2.line(img, P(saddle - (120, 0)), P(saddle + (130, 0)), (30, 30, 30), 12, cv2.LINE_AA)
        for pose, col, th in ((far, (150, 150, 150), 26), (near, (90, 60, 40), 30)):
            for a_, b_ in BONES:
                if pose is far and a_ not in LEG_JOINTS:
                    continue
                cv2.line(img, P(pose[a_][i]), P(pose[b_][i]), col, th, cv2.LINE_AA)
        for sgn in (1, -1):
            pedal = sgn * r.crank * np.array([np.sin(phi[i]), np.cos(phi[i])])
            cv2.line(img, P((0, 0)), P(pedal), (40, 40, 40), 8, cv2.LINE_AA)
        hd = near["shoulder"][i] + np.array([150, 170])
        cv2.circle(img, P(hd), int(110 * r.px_per_mm), (90, 60, 40), -1, cv2.LINE_AA)
        w.write(img)
    w.release()
