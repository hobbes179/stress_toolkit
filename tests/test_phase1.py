"""
tests/test_phase1.py

Gate tests for v2 Phase 1 (PolygonProperties engine + unsymmetric bending)
— design handoff §9 (Phase 1) and §7.1.

Phase 1 gate: "analytic property goldens + tensor-reduction test pass; all
shapes' polygon A/Iy/Iz match their v1 closed forms ≤ 0.1%."
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from library.analysis.polygon_props import polygon_section_props
from library.shapes import SHAPE_REGISTRY, make_section
from apps.beam_section.calculations import (
    Loads, calc_stress_at_points, neutral_axis_angle_deg,
)
import tests.golden_values as gv


# ──────────────────────────────────────────────────────────────────────────
# Analytic property goldens (§7.1)
# ──────────────────────────────────────────────────────────────────────────
def test_rectangle_polygon_props():
    b, h = 4.0, 2.0
    p = polygon_section_props(gv.rectangle_polygon(b, h))
    g = gv.rectangle_props(b, h)
    assert p.A == pytest.approx(g["A"], rel=1e-12)
    assert p.Iy == pytest.approx(g["Iy"], rel=1e-12)
    assert p.Iz == pytest.approx(g["Iz"], rel=1e-12)
    assert p.Iyz == pytest.approx(0.0, abs=1e-12)
    assert p.y_bar == pytest.approx(0.0, abs=1e-12)
    assert p.z_bar == pytest.approx(0.0, abs=1e-12)


def test_offset_rectangle_iyz_about_origin():
    # Green's-theorem Iyz validation: a rectangle whose centroid sits at
    # (dy, dz) has ∫yz dA about the ORIGIN = A·dy·dz, while its centroidal
    # Iyz stays ~0. Recover the origin value via parallel axis.
    b, h, dy, dz = 3.0, 2.0, 1.5, 0.75
    p = polygon_section_props(gv.rectangle_polygon(b, h, cy=dy, cz=dz))
    assert p.Iyz == pytest.approx(0.0, abs=1e-10)
    iyz_origin = p.Iyz + p.A * p.y_bar * p.z_bar
    assert iyz_origin == pytest.approx(
        gv.offset_rectangle_iyz_about_origin(b, h, dy, dz), rel=1e-12)


def test_rotated_rectangle_principal_axes_recovered():
    # A 45°-rotated rectangle has nonzero centroidal Iyz, but its principal
    # moments must recover the unrotated bh³/12 and hb³/12.
    b, h = 4.0, 2.0
    poly = gv.rotate_polygon(gv.rectangle_polygon(b, h), math.radians(45.0))
    p = polygon_section_props(poly)
    g = gv.rectangle_props(b, h)
    I_major = max(g["Iy"], g["Iz"])
    I_minor = min(g["Iy"], g["Iz"])
    assert p.I1 == pytest.approx(I_major, rel=1e-10)
    assert p.I2 == pytest.approx(I_minor, rel=1e-10)
    assert abs(p.Iyz) > 1e-6                      # genuinely rotated
    assert abs(p.principal_angle_rad) == pytest.approx(math.radians(45.0), abs=1e-6)


# ──────────────────────────────────────────────────────────────────────────
# Tensor-bending reduction (§3.1): Iyz = 0 reproduces v1 formula
# ──────────────────────────────────────────────────────────────────────────
def test_tensor_bending_reduces_to_v1_for_symmetric_section():
    sec = make_section("I-Beam / W-Shape", [4, 6, 0.375, 0.25])
    assert abs(sec.Iyz()) < 1e-6                  # symmetric → ~0
    loads = Loads(My=1200, Mz=800)
    df = calc_stress_at_points(sec, loads)

    Iy, Iz = sec.Iy(), sec.Iz()
    for _, row in df.iterrows():
        v1 = (loads.My * row["z"] / Iy + loads.Mz * row["y"] / Iz) / 1000.0
        assert row["σ_bend"] == pytest.approx(v1, rel=1e-6, abs=1e-9)


# ──────────────────────────────────────────────────────────────────────────
# Unsymmetric bending is genuinely exercised for L (Iyz ≠ 0)
# ──────────────────────────────────────────────────────────────────────────
def test_l_beam_has_nonzero_iyz_and_rotated_neutral_axis():
    sec = make_section("L-Beam / Angle", [3.0, 3.0, 0.25, 0.25])
    assert abs(sec.Iyz()) > 1e-3                  # L-section: real product of inertia

    # Pure My: a symmetric section would give a horizontal (0°) neutral
    # axis; the L must show a rotated one.
    angle = neutral_axis_angle_deg(sec, Loads(My=1000.0))
    assert angle is not None
    assert abs(angle) > 1.0                       # clearly rotated off the Y axis


def test_symmetric_section_neutral_axis_horizontal_under_pure_my():
    sec = make_section("Rectangle", [4.0, 2.0, None, None])
    angle = neutral_axis_angle_deg(sec, Loads(My=1000.0))
    assert angle == pytest.approx(0.0, abs=1e-9)


# ──────────────────────────────────────────────────────────────────────────
# Polygon A/Iy/Iz vs v1 closed forms ≤ 0.1% for every registered shape
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("shape_name", list(SHAPE_REGISTRY.keys()))
def test_polygon_props_match_closed_forms(shape_name):
    cls = SHAPE_REGISTRY[shape_name]
    sec = make_section(shape_name, list(cls.dim_defaults))
    p = sec.section_props()

    assert p.A == pytest.approx(sec.area(), rel=1e-3), f"{shape_name} A"
    assert p.Iy == pytest.approx(sec.Iy(), rel=1e-3), f"{shape_name} Iy"
    assert p.Iz == pytest.approx(sec.Iz(), rel=1e-3), f"{shape_name} Iz"


# ──────────────────────────────────────────────────────────────────────────
# Every shape exposes a usable geometry()
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("shape_name", list(SHAPE_REGISTRY.keys()))
def test_geometry_outer_loop_present(shape_name):
    cls = SHAPE_REGISTRY[shape_name]
    sec = make_section(shape_name, list(cls.dim_defaults))
    g = sec.geometry()
    assert g.outer.shape[1] == 2
    assert len(g.outer) >= 3
    # Hollow shapes carry exactly one void; solids/open carry none.
    expected_voids = 1 if sec.category == "Hollow" else 0
    assert len(g.voids) == expected_voids
    assert g.is_thin_walled == (sec.category == "Open thin-walled")
