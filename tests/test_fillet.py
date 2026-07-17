"""
tests/test_fillet.py

Re-entrant corner fillet geometry (library/shapes/fillet.py). This is the
"risky math" of the fillet feature, so it is locked independently of any UI:
correct corner detection at any angle, exact material added, curve faceting
rejected, oversized radii skipped, and filleted output still a valid
(re-importable) polygon.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from library.shapes import make_section
from library.shapes.fillet import (
    fillet_section, count_reentrant, fillet_loop,
)
from library.analysis.polygon_props import polygon_section_props


# Physically-expected re-entrant corner count per catalog shape (default dims).
_REENTRANT = {
    "Rectangle": 0, "Circle": 0, "Ellipse": 0, "Circular Tube": 0,
    "Rect Tube (HSS)": 4,                 # four bore corners (material ~270°)
    "I-Beam / W-Shape": 4,                # four web–flange junctions
    "T-Beam": 2, "L-Beam / Angle": 1,
    "C-Beam / Channel": 2, "Z-Beam": 2, "Plus / Cross": 4,
}
_DEFAULT_DIMS = {
    "Rectangle": [2, 3, None, None], "Circle": [3, None, None, None],
    "Ellipse": [2, 1, None, None], "Rect Tube (HSS)": [3, 4, 0.25, 0.25],
    "Circular Tube": [4, 0.25, None, None],
    "I-Beam / W-Shape": [4, 6, 0.375, 0.25], "T-Beam": [4, 0.375, 4, 0.25],
    "L-Beam / Angle": [3, 3, 0.25, 0.25], "C-Beam / Channel": [3, 6, 0.375, 0.25],
    "Z-Beam": [3, 6, 0.375, 0.25], "Plus / Cross": [3, 3, 0.25, 0.25],
}


@pytest.mark.parametrize("name,expected", list(_REENTRANT.items()))
def test_reentrant_corner_counts(name, expected):
    sec = make_section(name, _DEFAULT_DIMS[name])
    g = sec.geometry()
    assert count_reentrant(g.outer, g.voids) == expected


def test_curved_shapes_have_no_reentrant_corners():
    # The polygonal facets of a smooth curve must NOT be mistaken for corners.
    for name in ("Circle", "Ellipse", "Circular Tube"):
        sec = make_section(name, _DEFAULT_DIMS[name])
        g = sec.geometry()
        _, _, rep = fillet_section(g.outer, g.voids, 0.1, 6)
        assert rep.n_reentrant == 0 and rep.n_filleted == 0


@pytest.mark.parametrize("name", [
    "I-Beam / W-Shape", "T-Beam", "L-Beam / Angle",
    "C-Beam / Channel", "Z-Beam", "Plus / Cross", "Rect Tube (HSS)",
])
def test_fillet_adds_exact_material(name):
    # A 90° re-entrant fillet of radius r adds exactly r²(1 − π/4) per corner.
    r = 0.06
    sec = make_section(name, _DEFAULT_DIMS[name])
    g = sec.geometry()
    new_o, new_v, rep = fillet_section(g.outer, g.voids, r, 12)

    def area(o, v):
        return polygon_section_props(np.asarray(o),
                                     [np.asarray(x) for x in v]).A

    a0 = area(g.outer, g.voids)
    a1 = area(new_o, new_v)
    expected_add = rep.n_filleted * r**2 * (1.0 - math.pi / 4.0)
    assert a1 > a0                                   # fillets ADD material
    assert (a1 - a0) == pytest.approx(expected_add, rel=0.03)


def test_convex_corners_are_never_filleted():
    # A solid rectangle is all convex corners → nothing to fillet.
    sec = make_section("Rectangle", [2, 3, None, None])
    g = sec.geometry()
    new_o, _, rep = fillet_section(g.outer, g.voids, 0.2, 6)
    assert rep.n_filleted == 0
    assert len(new_o) == 4                            # geometry unchanged


def test_oversized_radius_skips_and_reports():
    # Channel: the two corners share the 5.25 in web face, so 2·t ≤ 5.25 ⇒
    # r ≤ ~2.62. A larger radius must leave BOTH corners sharp and report them.
    sec = make_section("C-Beam / Channel", [3, 6, 0.375, 0.25])
    g = sec.geometry()
    _, _, ok = fillet_section(g.outer, g.voids, 2.0, 6)
    assert ok.n_filleted == 2 and not ok.any_skipped
    _, _, big = fillet_section(g.outer, g.voids, 3.0, 6)
    assert big.n_filleted == 0 and big.n_skipped == 2


def test_seg_per_90_controls_arc_tessellation():
    # More segments per 90° ⇒ more boundary points on the fillet (this is what
    # drives FEM elements-per-arc once wired to the mesh density control).
    sec = make_section("L-Beam / Angle", [3, 3, 0.25, 0.25])
    g = sec.geometry()
    coarse, _ = fillet_loop(g.outer, 0.08, seg_per_90=3)
    fine, _ = fillet_loop(g.outer, 0.08, seg_per_90=9)
    assert len(fine) > len(coarse)


@pytest.mark.parametrize("name", [
    "I-Beam / W-Shape", "C-Beam / Channel", "Rect Tube (HSS)", "Plus / Cross",
])
def test_filleted_polygon_reimports(name):
    pytest.importorskip("sectionproperties")
    pytest.importorskip("shapely")
    from library.shapes.import_section import make_imported_section
    sec = make_section(name, _DEFAULT_DIMS[name])
    g = sec.geometry()
    new_o, new_v, rep = fillet_section(g.outer, g.voids, 0.08, 6)
    assert rep.n_filleted > 0
    isec, _res = make_imported_section([new_o] + list(new_v))   # must not raise
    assert isec.area() > 0


# ── FilletedSection wrapper (Option A: FEM geometry only) ──────────────────
def test_make_filleted_noops_without_reentrant_corners():
    # No inside corners (solid rectangle) or zero radius ⇒ return base as-is.
    from library.shapes.filleted import make_filleted
    sec = make_section("Rectangle", [2, 3, None, None])
    assert make_filleted(sec, 0.2) is sec              # nothing to round
    ch = make_section("C-Beam / Channel", [3, 6, 0.375, 0.25])
    assert make_filleted(ch, 0.0) is ch                # radius disabled


def test_filleted_section_delegates_closed_form_to_base():
    # Option A: every closed-form property comes from the SHARP base.
    from library.shapes.filleted import make_filleted, FilletedSection
    base = make_section("C-Beam / Channel", [3, 6, 0.375, 0.25])
    fil = make_filleted(base, 0.125, 6)
    assert isinstance(fil, FilletedSection)
    assert fil.name == base.name and fil.dims == base.dims
    for attr in ("area", "Iy", "Iz", "J_torsion", "Iyz"):
        assert getattr(fil, attr)() == getattr(base, attr)()


def test_filleted_geometry_rounds_outer_but_keeps_midline():
    # geometry(): outer gains arc points; the midline skeleton (used by the
    # classical solvers) is copied straight from the base.
    from library.shapes.filleted import make_filleted
    base = make_section("C-Beam / Channel", [3, 6, 0.375, 0.25])
    fil = make_filleted(base, 0.125, 6)
    gb, gf = base.geometry(), fil.geometry()
    assert len(gf.outer) > len(gb.outer)               # corners tessellated
    assert gf.is_thin_walled == gb.is_thin_walled
    assert (gf.nodes is None) == (gb.nodes is None)
    if gb.nodes is not None:
        assert np.allclose(gf.nodes, gb.nodes)         # skeleton unchanged


def test_classical_stress_is_invariant_to_fillets():
    # The headline Option-A guarantee: the classical result does not move.
    from library.shapes.filleted import make_filleted
    from apps.beam_section.calculations import Loads, calc_stress_at_points
    base = make_section("C-Beam / Channel", [3, 6, 0.375, 0.25])
    fil = make_filleted(base, 0.125, 6)
    loads = Loads(P=13000, Vy=0, Vz=6500, My=44000, Mz=5500, T=2000)
    d0 = calc_stress_at_points(base, loads, solver="Classical")
    d1 = calc_stress_at_points(fil, loads, solver="Classical")
    assert np.allclose(d0["σ_vm"].to_numpy(), d1["σ_vm"].to_numpy(), atol=1e-9)
    assert np.allclose(d0["τ_total"].to_numpy(), d1["τ_total"].to_numpy(),
                       atol=1e-9)


def test_section_key_distinguishes_fillet_settings():
    # Two fillet radii must not collide in the FEM result cache.
    from library.shapes.filleted import make_filleted
    from apps.beam_section.app import _section_key
    base = make_section("C-Beam / Channel", [3, 6, 0.375, 0.25])
    k_sharp = _section_key(base)
    k_a = _section_key(make_filleted(base, 0.10, 6))
    k_b = _section_key(make_filleted(base, 0.20, 6))
    assert k_sharp != k_a and k_a != k_b
