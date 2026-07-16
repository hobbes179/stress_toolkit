"""
library/analysis/polygon_props.py

Green's-theorem (shoelace) section properties for an arbitrary polygon with
optional interior voids. Pure functions — no Streamlit / matplotlib imports.

Coordinate system (project-wide):
    y = horizontal, z = vertical. Origin arbitrary; all returned second
    moments are reduced to the section centroid. Project conventions:

        Iy  = ∫ z² dA    (bending about Y → stress ∝ z)
        Iz  = ∫ y² dA    (bending about Z → stress ∝ y)
        Iyz = ∫ y·z dA   (product of inertia)

Closed-form vertex-sum expressions, for a single closed loop with vertices
(u_i, v_i) = (y_i, z_i), index n wrapping to 0, and

        cross_i = u_i·v_{i+1} − u_{i+1}·v_i :

    A      = ½   Σ cross_i
    ∫u dA  = 1/6  Σ (u_i + u_{i+1})·cross_i
    ∫v dA  = 1/6  Σ (v_i + v_{i+1})·cross_i
    ∫u² dA = 1/12 Σ (u_i² + u_i·u_{i+1} + u_{i+1}²)·cross_i
    ∫v² dA = 1/12 Σ (v_i² + v_i·v_{i+1} + v_{i+1}²)·cross_i
    ∫uv dA = 1/24 Σ (u_i·v_{i+1} + 2·u_i·v_i + 2·u_{i+1}·v_{i+1}
                     + u_{i+1}·v_i)·cross_i

Voids (interior loops) are subtracted. The winding order of the inputs does
NOT matter: each loop is normalized (outer → positive area; voids →
subtracted as positive-area regions) before accumulation, so callers may
pass loops in either orientation.

Reference: standard polygon area-moment formulas; see e.g. Steger, "On the
calculation of arbitrary moments of polygons" (1996), or any section-
properties text derived from the divergence/Green's theorem.
"""

from __future__ import annotations
from dataclasses import dataclass
import math

import numpy as np


# ──────────────────────────────────────────────────────────────────────────
# Raw (origin-referenced) moment accumulation for one loop
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class _RawMoments:
    """Origin-referenced integrals over one loop (signed by winding)."""
    a:   float   # ∫ dA
    mu:  float   # ∫ u dA         (u = y)
    mv:  float   # ∫ v dA         (v = z)
    iuu: float   # ∫ u² dA
    ivv: float   # ∫ v² dA
    iuv: float   # ∫ u·v dA


def _loop_raw(loop) -> _RawMoments:
    """
    Signed origin-referenced integrals for one polygon loop. A trailing
    duplicate closing vertex (loop[0] == loop[-1]) is dropped automatically.
    Degenerate loops (< 3 distinct vertices) contribute zero.
    """
    p = np.asarray(loop, dtype=float)
    if len(p) >= 2 and np.allclose(p[0], p[-1]):
        p = p[:-1]
    n = len(p)
    if n < 3:
        return _RawMoments(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    u = p[:, 0]
    v = p[:, 1]
    u1 = np.roll(u, -1)
    v1 = np.roll(v, -1)
    cross = u * v1 - u1 * v

    a   = cross.sum() / 2.0
    mu  = ((u + u1) * cross).sum() / 6.0
    mv  = ((v + v1) * cross).sum() / 6.0
    iuu = ((u * u + u * u1 + u1 * u1) * cross).sum() / 12.0
    ivv = ((v * v + v * v1 + v1 * v1) * cross).sum() / 12.0
    iuv = ((u * v1 + 2.0 * u * v + 2.0 * u1 * v1 + u1 * v) * cross).sum() / 24.0
    return _RawMoments(a, mu, mv, iuu, ivv, iuv)


# ──────────────────────────────────────────────────────────────────────────
# Public result container
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class PolygonProps:
    """
    Centroidal section properties from Green's theorem.

    All second moments are about the section centroid, on the geometric
    (y, z) axes. `principal_angle_rad` is the rotation from the geometric
    axes to the principal axes (positive = counter-clockwise).
    """
    A:      float
    y_bar:  float
    z_bar:  float
    Iy:     float   # ∫z² dA about centroid
    Iz:     float   # ∫y² dA about centroid
    Iyz:    float   # ∫yz dA about centroid
    I1:     float   # major principal second moment
    I2:     float   # minor principal second moment
    principal_angle_rad: float
    r_gy:   float   # radius of gyration about Y = √(Iy/A)
    r_gz:   float   # radius of gyration about Z = √(Iz/A)


# ──────────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────────
def polygon_section_props(outer, voids=()) -> PolygonProps:
    """
    Compute centroidal section properties for a polygon with optional voids.

    Args:
        outer: (N, 2) array-like of (y, z) vertices for the outer boundary.
               Winding order does not matter.
        voids: iterable of (M, 2) inner-loop vertex arrays, each subtracted.

    Returns:
        PolygonProps (centroidal).

    Raises:
        ValueError: if the net area is non-positive (bad geometry / voids
                    that exceed or fall outside the outer boundary).
    """
    r = _loop_raw(outer)
    so = 1.0 if r.a >= 0.0 else -1.0   # normalize outer to positive area
    a   = so * r.a
    mu  = so * r.mu
    mv  = so * r.mv
    iuu = so * r.iuu
    ivv = so * r.ivv
    iuv = so * r.iuv

    for void in voids:
        vr = _loop_raw(void)
        sv = 1.0 if vr.a >= 0.0 else -1.0   # normalize void to +area, then subtract
        a   -= sv * vr.a
        mu  -= sv * vr.mu
        mv  -= sv * vr.mv
        iuu -= sv * vr.iuu
        ivv -= sv * vr.ivv
        iuv -= sv * vr.iuv

    if a <= 0.0:
        raise ValueError(
            "Polygon net area is non-positive — check loop winding, void "
            "placement, or degenerate geometry."
        )

    y_bar = mu / a
    z_bar = mv / a

    # Parallel-axis reduction to the centroid.
    Iz  = iuu - a * y_bar * y_bar     # ∫y² about centroid
    Iy  = ivv - a * z_bar * z_bar     # ∫z² about centroid
    Iyz = iuv - a * y_bar * z_bar     # ∫yz about centroid

    # Principal moments / angle (Mohr's circle of second moments).
    avg  = (Iy + Iz) / 2.0
    diff = (Iy - Iz) / 2.0
    R = math.hypot(diff, Iyz)
    I1 = avg + R
    I2 = avg - R
    if abs(Iyz) < 1e-14 and abs(Iz - Iy) < 1e-14:
        angle = 0.0
    else:
        angle = 0.5 * math.atan2(2.0 * Iyz, Iz - Iy)

    r_gy = math.sqrt(Iy / a) if Iy > 0.0 else 0.0
    r_gz = math.sqrt(Iz / a) if Iz > 0.0 else 0.0

    return PolygonProps(
        A=a, y_bar=y_bar, z_bar=z_bar,
        Iy=Iy, Iz=Iz, Iyz=Iyz,
        I1=I1, I2=I2, principal_angle_rad=angle,
        r_gy=r_gy, r_gz=r_gz,
    )
