"""
tests/golden_values.py

Single source of truth for analytic golden reference values, shared by the
pytest suite (tests/) and the in-app Validation page (design handoff §7,
Phase 7). Plain data + small pure helpers only — no pytest, no Streamlit
imports, so either side can consume it.

Every value here is hand-derivable; the derivation is given in comments so
a reviewer can check it without running code.

Coordinate / moment conventions (project-wide):
    Iy  = ∫ z² dA    Iz  = ∫ y² dA    Iyz = ∫ y·z dA   (about centroid)
"""

from __future__ import annotations
import math

import numpy as np


# ──────────────────────────────────────────────────────────────────────────
# Polygon generators (also useful as an untrusted-input harness later)
# ──────────────────────────────────────────────────────────────────────────
def rectangle_polygon(b: float, h: float, cy: float = 0.0, cz: float = 0.0) -> np.ndarray:
    """CCW rectangle b (width, y) × h (height, z), centroid at (cy, cz)."""
    return np.array([
        (cy - b / 2, cz - h / 2),
        (cy + b / 2, cz - h / 2),
        (cy + b / 2, cz + h / 2),
        (cy - b / 2, cz + h / 2),
    ])


def rotate_polygon(poly: np.ndarray, angle_rad: float) -> np.ndarray:
    """Rotate polygon vertices about the origin by angle_rad (CCW)."""
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    R = np.array([[c, -s], [s, c]])
    return (np.asarray(poly, dtype=float) @ R.T)


# ──────────────────────────────────────────────────────────────────────────
# Analytic section properties
# ──────────────────────────────────────────────────────────────────────────
def rectangle_props(b: float, h: float) -> dict:
    """Solid rectangle b×h about its centroid."""
    # Iy = ∫z² dA = b·h³/12 ; Iz = ∫y² dA = h·b³/12 ; Iyz = 0 (symmetric).
    return dict(A=b * h, Iy=b * h**3 / 12.0, Iz=h * b**3 / 12.0, Iyz=0.0)


def circle_props(d: float) -> dict:
    """Solid circle, diameter d."""
    r = d / 2.0
    return dict(
        A=math.pi * r**2,
        Iy=math.pi * d**4 / 64.0,
        Iz=math.pi * d**4 / 64.0,
        J=math.pi * d**4 / 32.0,
        tau_max_per_T=16.0 / (math.pi * d**3),   # τ = 16T/(πd³)
    )


def thin_ring_props(r: float, t: float) -> dict:
    """Thin-walled ring, mean radius r, wall t (t << r)."""
    # A = 2πrt ; I = πr³t ; J = 2πr³t ; Bredt τ = T/(2·Am·t), Am = πr².
    return dict(
        A=2.0 * math.pi * r * t,
        I=math.pi * r**3 * t,
        J=2.0 * math.pi * r**3 * t,
        bredt_tau_per_T=1.0 / (2.0 * math.pi * r**2 * t),
    )


def offset_rectangle_iyz_about_origin(b: float, h: float,
                                      dy: float, dz: float) -> float:
    """
    ∫y·z dA about the ORIGIN for a rectangle whose centroid sits at (dy, dz).

    Centroidal Iyz of an axis-aligned rectangle is 0, so by the parallel-
    axis theorem Iyz_origin = Iyz_centroid + A·dy·dz = A·dy·dz.
    """
    return (b * h) * dy * dz


def uniform_channel_shear_center_offset(b: float, h: float) -> float:
    """
    Distance e from the web midline to the shear center of a uniform-
    thickness channel (midline flange width b, web height h):

        e = 3·b² / (h + 6·b)

    (Used in Phase 2/3 — kept here so the golden lives in one place.)
    """
    return 3.0 * b**2 / (h + 6.0 * b)


# ──────────────────────────────────────────────────────────────────────────
# Interaction-curve goldens (design handoff §3.6 / §7.1)
# ──────────────────────────────────────────────────────────────────────────
# (Ra, Rb, Rs, expected MS) — both are exact zero-margin states.
INTERACTION_GOLDENS = [
    (0.5, 0.5, 0.0, 0.0),   # pure axial+bending at the envelope
    (0.0, 0.0, 1.0, 0.0),   # pure shear at the envelope
]
