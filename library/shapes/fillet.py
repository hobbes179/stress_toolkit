"""
library/shapes/fillet.py

Re-entrant corner fillets for section boundary polygons.

Rounds RE-ENTRANT (reflex — interior material angle > 180°) corners of a
section's loops at a single user radius, so the FEM corner stress converges
instead of being singular (resolves the "model a fillet for real corner
stress" caveat). Convex/exterior corners are never rounded.

Pure geometry. Operates on (y, z) loops in the project's orientation
convention — outer boundary CCW, voids CW — which keeps material on the LEFT
of the direction of travel for EVERY loop. Consequently a right turn at a
vertex (signed cross product < 0) is exactly a re-entrant corner, for any
corner angle, not just 90°. Void corners (material wraps ~270°) are detected
the same way, so a rectangular tube's four bore corners round correctly.

A corner whose fillet would not fit on its adjacent edges (radius too large)
is left sharp and reported — the output polygon is never self-intersecting.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

import numpy as np


@dataclass
class FilletReport:
    """Outcome of a fillet pass over a whole section (all loops)."""
    radius: float
    n_reentrant: int = 0                       # re-entrant corners found
    n_filleted: int = 0                        # actually rounded
    skipped: list = field(default_factory=list)   # (y, z) of corners left sharp

    @property
    def n_skipped(self) -> int:
        return len(self.skipped)

    @property
    def any_skipped(self) -> bool:
        return bool(self.skipped)


def _strip_closing_dup(loop) -> np.ndarray:
    """Drop a trailing duplicate closing vertex (curved loops close on self)."""
    p = np.asarray(loop, dtype=float)
    if len(p) >= 2 and np.allclose(p[0], p[-1]):
        p = p[:-1]
    return p


def _corner_info(p: np.ndarray, radius: float, min_deflection_deg: float = 30.0):
    """
    Per-vertex (is_reentrant, turn_angle δ, setback t). With material on the
    LEFT (outer CCW / voids CW), cross < 0 is a re-entrant corner. The setback
    along each edge for a tangent fillet of radius r is t = r·tan(δ/2), where
    δ is the path deflection angle — valid for any corner angle.

    A corner counts as re-entrant only if it also deflects by at least
    `min_deflection_deg`; this rejects the tiny reflex vertices produced by the
    polygonal faceting of a smooth curve (e.g. a tube's inner circle), which
    are not real corners.
    """
    n = len(p)
    min_delta = math.radians(min_deflection_deg)
    info = []
    for i in range(n):
        a_vec = p[i] - p[i - 1]
        b_vec = p[(i + 1) % n] - p[i]
        la = math.hypot(a_vec[0], a_vec[1])
        lb = math.hypot(b_vec[0], b_vec[1])
        if la < 1e-12 or lb < 1e-12:
            info.append((False, 0.0, 0.0))
            continue
        ah = a_vec / la
        bh = b_vec / lb
        cross = ah[0] * bh[1] - ah[1] * bh[0]
        dot = float(np.clip(ah[0] * bh[0] + ah[1] * bh[1], -1.0, 1.0))
        delta = math.atan2(abs(cross), dot)          # deflection in [0, π]
        reentrant = (cross < 0) and (delta >= min_delta)  # real re-entrant corner
        t = radius * math.tan(delta / 2.0) if reentrant else 0.0
        info.append((reentrant, delta, t))
    return info


def _arc_points(p_prev, v, p_next, radius, delta, t, seg_per_90):
    """
    Tessellated circular arc replacing re-entrant vertex `v`, tangent to both
    edges at setback `t`. Returns points from the incoming tangent point P1 to
    the outgoing tangent point P2 inclusive. The arc bulges into the notch
    (adds material); its centre sits on the material side.
    """
    a_vec = v - p_prev
    b_vec = p_next - v
    ah = a_vec / math.hypot(a_vec[0], a_vec[1])
    bh = b_vec / math.hypot(b_vec[0], b_vec[1])

    P1 = v - ah * t                       # on incoming edge
    P2 = v + bh * t                       # on outgoing edge
    # Re-entrant fillet is concave toward the material, so its centre sits on
    # the NOTCH/air side (right of travel, since material is on the left).
    n_air = np.array([ah[1], -ah[0]])
    C = P1 + radius * n_air               # arc centre

    a1 = math.atan2(P1[1] - C[1], P1[0] - C[0])
    a2 = math.atan2(P2[1] - C[1], P2[0] - C[0])
    # Re-entrant corner = right turn ⇒ sweep clockwise (negative) by δ.
    sweep = a2 - a1
    while sweep > 0:
        sweep -= 2 * math.pi
    while sweep <= -2 * math.pi:
        sweep += 2 * math.pi

    nseg = max(1, round(seg_per_90 * math.degrees(delta) / 90.0))
    angs = a1 + sweep * np.linspace(0.0, 1.0, nseg + 1)
    return np.column_stack([C[0] + radius * np.cos(angs),
                            C[1] + radius * np.sin(angs)])


def fillet_loop(loop, radius: float, seg_per_90: int = 6):
    """
    Round the re-entrant corners of a single loop. Returns
    (new_loop (M,2), skipped_corners list[(y,z)]). A corner is skipped (left
    sharp) if its fillet plus any adjacent fillet would overrun the shared
    edge.
    """
    p = _strip_closing_dup(loop)
    n = len(p)
    if n < 3 or radius <= 0:
        return p.copy(), []

    info = _corner_info(p, radius)
    elen = [math.hypot(*(p[(i + 1) % n] - p[i])) for i in range(n)]  # edge i: p[i]->p[i+1]

    do = [False] * n
    for i in range(n):
        reent, _delta, t = info[i]
        if not reent:
            continue
        len_in = elen[i - 1]                       # edge p[i-1]->p[i]
        len_out = elen[i]                          # edge p[i]->p[i+1]
        t_prev = info[i - 1][2] if info[i - 1][0] else 0.0
        t_next = info[(i + 1) % n][2] if info[(i + 1) % n][0] else 0.0
        fits = (t <= len_in + 1e-9 and t <= len_out + 1e-9
                and t + t_prev <= len_in + 1e-9
                and t + t_next <= len_out + 1e-9)
        do[i] = fits

    new: list = []
    skipped: list = []
    for i in range(n):
        reent, delta, t = info[i]
        if do[i]:
            new.extend(_arc_points(p[i - 1], p[i], p[(i + 1) % n],
                                   radius, delta, t, seg_per_90))
        else:
            if reent:
                skipped.append((float(p[i][0]), float(p[i][1])))
            new.append(p[i])
    return np.asarray(new, dtype=float), skipped


def count_reentrant(outer, voids=()) -> int:
    """Number of re-entrant corners across the outer boundary and all voids
    (radius-independent — for UI feedback before a radius is chosen)."""
    total = 0
    for loop in (outer, *voids):
        p = _strip_closing_dup(loop)
        if len(p) >= 3:
            total += sum(1 for r, _, _ in _corner_info(p, 1.0) if r)
    return total


def fillet_section(outer, voids=(), radius: float = 0.0, seg_per_90: int = 6):
    """
    Round the re-entrant corners of a whole section. Returns
    (new_outer, new_voids (tuple), FilletReport).
    """
    report = FilletReport(radius=radius)
    report.n_reentrant = count_reentrant(outer, voids)

    new_outer, sk = fillet_loop(outer, radius, seg_per_90)
    report.skipped.extend(sk)

    new_voids = []
    for v in voids:
        nv, sk = fillet_loop(v, radius, seg_per_90)
        report.skipped.extend(sk)
        new_voids.append(nv)

    report.n_filleted = report.n_reentrant - report.n_skipped
    return new_outer, tuple(new_voids), report
