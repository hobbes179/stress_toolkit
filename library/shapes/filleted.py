"""
library/shapes/filleted.py

`FilletedSection` — a thin wrapper that rounds the re-entrant corners of a
section's FEM geometry while leaving everything else untouched (design
decision "Option A": fillet ONLY the FEM geometry; keep the closed-form
section properties and the dual solver exactly as they are).

How it stays surgical
---------------------
The wrapper delegates every attribute/method to the wrapped base section via
`__getattr__` and overrides just two:

    geometry()          → outer/voids are FILLETED; nodes/segments (the
                          thin-walled midline skeleton) and is_thin_walled are
                          copied straight from the base.
    polygon_vertices()  → the FILLETED loops, so the section diagram draws the
                          rounded corners the FEM actually analyses.

The classical midline solvers (library/analysis/solvers.py) read ONLY
`geom.nodes` / `geom.segments`, and the closed-form properties (area, Iy, Iz,
Iyz, J, section_props, key_points, cy, cz, tau_T, …) are all delegated to the
base and evaluated on the base's SHARP geometry. Consequently the classical
stress table is identical with or without fillets, and only the FEM stress
field / mesh / FEM properties see the rounded corners — which is the whole
point (the sharp-corner torsion singularity becomes a converged value).

`make_filleted()` is the entry point: it returns the base UNCHANGED when there
is nothing to round (radius ≤ 0, no FEM backend need, or no re-entrant
corners), so callers never have to special-case.
"""
from __future__ import annotations

import numpy as np

from library.shapes.geometry import SectionGeometry
from library.shapes.fillet import fillet_section, count_reentrant


class FilletedSection:
    """Delegating wrapper that rounds a section's re-entrant corners for FEM.

    Attributes:
        base:        the wrapped Section (sharp — owns all closed-form props).
        radius:      fillet radius (in) applied to every re-entrant corner.
        seg_per_90:  arc points per 90° of fillet (drives FEM elements/arc).
        report:      FilletReport (corners found / filleted / skipped).
        is_filleted: always True (duck-type marker).
    """

    is_filleted = True

    def __init__(self, base, radius: float, seg_per_90: int = 6):
        self.base = base
        self.radius = float(radius)
        self.seg_per_90 = int(seg_per_90)

        # Fillet the base's NORMALISED geometry once (CCW outer / CW voids),
        # then cache the rounded SectionGeometry — reused by geometry() and
        # polygon_vertices() so we never round twice.
        bg = base.geometry()
        new_outer, new_voids, report = fillet_section(
            bg.outer, bg.voids, self.radius, self.seg_per_90
        )
        self.report = report
        self._fg = SectionGeometry(
            outer=new_outer,
            voids=new_voids,
            nodes=bg.nodes,               # midline skeleton unchanged →
            segments=bg.segments,         # classical solvers see the base
            cells=bg.cells,
            is_thin_walled=bg.is_thin_walled,
        )

    # ── Delegation: anything not overridden falls through to the base ──────
    def __getattr__(self, name):
        # Only reached for attributes NOT set on the wrapper itself, so the
        # closed-form properties, key_points, dims, name, is_imported, etc. all
        # resolve on the base (its own SHARP geometry) — Option A.
        return getattr(self.base, name)

    # ── FEM geometry (the only thing that sees the fillets) ────────────────
    def geometry(self) -> SectionGeometry:
        return self._fg

    def polygon_vertices(self):
        """Filleted loops (outer first, then voids) for the section diagram."""
        return [np.asarray(self._fg.outer)] + [
            np.asarray(v) for v in self._fg.voids
        ]

    # ── Cache identity: two fillet settings must not collide ───────────────
    @property
    def fillet_key(self) -> tuple:
        return (round(self.radius, 9), self.seg_per_90)


def make_filleted(section, radius: float, seg_per_90: int = 6):
    """
    Wrap `section` so its FEM geometry has rounded re-entrant corners, or
    return it unchanged when there is nothing to round.

    Returns the base section untouched if `radius <= 0` or the section has no
    re-entrant corners, so callers can wrap unconditionally.
    """
    if radius is None or radius <= 0:
        return section
    g = section.geometry()
    if count_reentrant(g.outer, g.voids) == 0:
        return section
    return FilletedSection(section, radius, seg_per_90)
