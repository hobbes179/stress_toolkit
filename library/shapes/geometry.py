"""
library/shapes/geometry.py

Geometry containers for the v2 geometry/analysis separation (design
handoff §2.1). A `SectionGeometry` is the single geometric description a
shape (catalog or imported) hands to the analysis engines:

    • outer boundary polygon (+ interior voids) — always populated
    • optional midline skeleton (nodes / segments / cells) — populated by
      thin-walled catalog shapes in Phase 2; empty for solids and (for now)
      for everything in Phase 1.

No engineering math lives here — see library/analysis/ for that.
Coordinates are (y, z) with the project convention (y right, z up).
"""

from __future__ import annotations
from dataclasses import dataclass

import numpy as np


# ──────────────────────────────────────────────────────────────────────────
# Midline skeleton (thin-walled shapes; populated in Phase 2)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class MidlineSegment:
    """One wall segment of a thin-walled midline skeleton."""
    n1: int      # index into SectionGeometry.nodes
    n2: int      # index into SectionGeometry.nodes
    t:  float    # wall thickness (in)


@dataclass(frozen=True)
class SectionGeometry:
    """
    Geometric description of a cross-section.

    Attributes:
        outer:          (N, 2) closed outer boundary polygon, CCW, in (y, z).
        voids:          tuple of (M, 2) inner loops (holes), CW.
        nodes:          (K, 2) midline node coordinates, or None if the shape
                        has no skeleton (solids, imported polygons).
        segments:       midline wall segments (Phase 2).
        cells:          tuples of segment indices bounding closed cells
                        (Phase 2).
        is_thin_walled: True for the "Open thin-walled" catalog category.
    """
    outer:          np.ndarray
    voids:          tuple = ()
    nodes:          np.ndarray | None = None
    segments:       tuple[MidlineSegment, ...] = ()
    cells:          tuple[tuple[int, ...], ...] = ()
    is_thin_walled: bool = False


# ──────────────────────────────────────────────────────────────────────────
# Winding helpers
# ──────────────────────────────────────────────────────────────────────────
def signed_area(loop) -> float:
    """Signed polygon area (positive = CCW). Handles a trailing dup vertex."""
    p = np.asarray(loop, dtype=float)
    if len(p) >= 2 and np.allclose(p[0], p[-1]):
        p = p[:-1]
    if len(p) < 3:
        return 0.0
    x = p[:, 0]
    y = p[:, 1]
    return float((x * np.roll(y, -1) - np.roll(x, -1) * y).sum() / 2.0)


def ensure_ccw(loop) -> np.ndarray:
    """Return the loop reordered so its winding is counter-clockwise."""
    p = np.asarray(loop, dtype=float)
    return p[::-1].copy() if signed_area(p) < 0.0 else p.copy()


def ensure_cw(loop) -> np.ndarray:
    """Return the loop reordered so its winding is clockwise."""
    p = np.asarray(loop, dtype=float)
    return p[::-1].copy() if signed_area(p) > 0.0 else p.copy()
