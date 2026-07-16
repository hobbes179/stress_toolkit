"""
tests/test_phase6.py

Phase 6 (UX/plotting overhaul) gate tests. Focus so far: the interactive
FEM stress field is correct — the shear field actually varies (the old
contour was degenerate) and von Mises is consistent with σ, τ.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

pytest.importorskip("sectionproperties")
pytest.importorskip("plotly")

from library.shapes import make_section
from apps.beam_section.calculations import Loads, calc_stress_at_points
from apps.beam_section.plotting_interactive import (
    interactive_stress_contour, compute_stress_field, FIELD_LABELS,
)
from library.materials import MATERIALS

_MAT = MATERIALS[next(iter(MATERIALS))]


def test_von_mises_identity_holds():
    # σ_vm from principal stresses == √(σ² + 3τ²) (plane-stress uniaxial+shear).
    for s, tau in [(12.0, 5.0), (-8.0, 3.0), (0.0, 4.0), (10.0, 0.0)]:
        half = s / 2
        r = math.hypot(half, tau)
        s1, s2 = half + r, half - r
        vm_principal = math.sqrt(s1**2 - s1 * s2 + s2**2)
        assert vm_principal == pytest.approx(math.sqrt(s**2 + 3 * tau**2), rel=1e-12)


def test_fem_table_von_mises_matches_sigma_tau():
    # The FEM results-table σ_vm must equal √(σ_total² + 3·τ_total²) row-by-row.
    sec = make_section("C-Beam / Channel", [3, 6, 0.375, 0.25])
    df = calc_stress_at_points(sec, Loads(Vz=1000, My=4000, T=200), solver="FEM")
    for _, r in df.iterrows():
        expect = math.sqrt(r["σ_total"]**2 + 3 * r["τ_total"]**2)
        assert r["σ_vm"] == pytest.approx(expect, rel=1e-6, abs=1e-6)


def test_interactive_shear_field_is_not_degenerate():
    # The whole point of the overhaul: the shear field must vary across the
    # section (the legacy contour returned a single uniform value).
    sec = make_section("I-Beam / W-Shape", [4, 6, 0.375, 0.25])
    fig = interactive_stress_contour(sec, Loads(Vz=1000, My=1000), _MAT,
                                     1.0, 1.5, "τ (shear)")
    heat = fig.data[0]
    z = np.asarray(heat.z, dtype=float)
    finite = z[np.isfinite(z)]
    assert finite.size > 100
    assert finite.max() - finite.min() > 0.05      # genuinely varies


@pytest.mark.parametrize("field", list(FIELD_LABELS.keys()))
def test_interactive_contour_builds_all_fields(field):
    sec = make_section("T-Beam", [4, 0.375, 4, 0.25])
    fig = interactive_stress_contour(sec, Loads(Vz=500, My=2000), _MAT,
                                     1.0, 1.5, field)
    assert len(fig.data) >= 2                       # heatmap + outline(s)


# ──────────────────────────────────────────────────────────────────────────
# Regression: closed/curved sections (duplicate closing vertex broke warping)
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name,dims", [
    ("Circular Tube", [4, 0.25, None, None]),
    ("Circle", [3, None, None, None]),
    ("Ellipse", [2, 1, None, None]),
])
def test_fem_warping_finite_for_curved_sections(name, dims):
    # The circle/ellipse/tube polygons close with a duplicate vertex; that
    # used to make the sectionproperties warping solve return NaN J.
    from library.analysis.fem_solver import fem_properties, default_mesh_size
    sec = make_section(name, dims)
    g = sec.geometry()
    p = fem_properties(g.outer, g.voids, default_mesh_size(g.outer, g.voids, None))
    assert math.isfinite(p["J"]) and p["J"] > 0
    assert p["J"] == pytest.approx(sec.J_torsion(), rel=0.02)


def test_hollow_tube_interactive_contour_not_empty():
    sec = make_section("Circular Tube", [4, 0.25, None, None])
    fig = interactive_stress_contour(sec, Loads(Vz=1000, My=2000, T=300),
                                     _MAT, 1.0, 1.5, "σ_vm (von Mises)")
    z = np.asarray(fig.data[0].z, dtype=float)
    assert np.isfinite(z).sum() > 500               # the ring is populated


# ──────────────────────────────────────────────────────────────────────────
# Mesh quality: ≥2 elements through wall thickness (no element bridges a wall)
# ──────────────────────────────────────────────────────────────────────────
def test_default_mesh_gives_two_elements_through_thickness():
    # A thin strip 2.0 × t: at the default mesh size, no single element may
    # span more than ~0.9·t through the thickness (i.e. it can't touch both
    # walls). The old t²/2 sizing let ~half the elements bridge the wall.
    from library.analysis.fem_solver import fem_mesh, default_mesh_size
    t = 0.1
    outer = np.array([[0, 0], [2.0, 0], [2.0, t], [0, t]], dtype=float)
    ms = default_mesh_size(outer, [], min_wall=t)
    verts, tris = fem_mesh(outer, [], ms)
    span = verts[tris, 1]                       # (n_el, 3) z of the corners
    through = span.max(axis=1) - span.min(axis=1)
    assert through.max() < 0.9 * t              # nothing bridges both walls
    assert tris.shape[0] > 100                  # genuinely refined


def test_contour_overlays_toggle_and_shear_point_and_mesh():
    sec = make_section("C-Beam / Channel", [3, 6, 0.375, 0.25])
    loads = Loads(Vz=1000, My=2000)
    # Only the centroid overlay + the shear-application point, plus mesh lines.
    fig = interactive_stress_contour(
        sec, loads, _MAT, 1.0, 1.5, "τ (shear)",
        shear_app=(0.5, 0.0), overlays={"centroid", "shear_point"},
        show_mesh=True)
    names = {tr.name for tr in fig.data if tr.name}
    assert "shear applied" in names             # the yellow diamond is drawn
    assert "mesh" in names                       # mesh-line overlay present
    assert "neutral axis" not in names           # excluded overlay stays off

    # Empty overlay set ⇒ no marker/line overlays (heatmap + outline only).
    fig2 = interactive_stress_contour(
        sec, loads, _MAT, 1.0, 1.5, "τ (shear)", overlays=set())
    names2 = {tr.name for tr in fig2.data if tr.name}
    assert "centroid" not in names2 and "shear applied" not in names2


# ──────────────────────────────────────────────────────────────────────────
# Phase 6B caching: a reused (cached) field must match a fresh compute exactly
# ──────────────────────────────────────────────────────────────────────────
def test_precomputed_field_matches_fresh_solve():
    sec = make_section("I-Beam / W-Shape", [4, 6, 0.375, 0.25])
    loads = Loads(Vz=1000, My=1000, T=100)
    field = compute_stress_field(sec, loads, 1.0, 100)
    ys, zs, sig, tau = field
    assert np.isfinite(sig).sum() > 100           # interior actually populated

    fresh = interactive_stress_contour(sec, loads, _MAT, 1.0, 1.5,
                                       "σ_vm (von Mises)", n_grid=100)
    reuse = interactive_stress_contour(sec, loads, _MAT, 1.0, 1.5,
                                       "σ_vm (von Mises)", field=field)
    a = np.asarray(fresh.data[0].z, dtype=float)
    b = np.asarray(reuse.data[0].z, dtype=float)
    # NaN pattern identical, finite values identical.
    assert np.array_equal(np.isnan(a), np.isnan(b))
    np.testing.assert_allclose(np.nan_to_num(a), np.nan_to_num(b), rtol=1e-9)
