"""
tests/test_phase5.py

Gate tests for Phase 5: custom-section import (design handoff §5, §7.3).

  • Pasted-vertex path builds a valid ImportedSection whose properties match
    the equivalent catalog shape.
  • Hostile inputs (self-intersection, void outside the boundary, degenerate)
    raise GeometryImportError — never a traceback.
  • DXF round-trip (guarded by ezdxf): an I-beam written to DXF, re-imported,
    matches the catalog I-beam.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from library.shapes import make_section
from library.shapes.import_section import (
    parse_vertex_text, validate_loops, make_imported_section,
    ImportedSection, GeometryImportError,
)
from apps.beam_section.calculations import Loads, calc_stress_at_points, shear_center


# ──────────────────────────────────────────────────────────────────────────
# Pasted-vertex parsing + build
# ──────────────────────────────────────────────────────────────────────────
def test_parse_vertex_text_two_loops():
    text = "0,0\n4,0\n4,2\n0,2\n\n1,0.5\n3,0.5\n3,1.5\n1,1.5\n"
    loops = parse_vertex_text(text)
    assert len(loops) == 2
    assert loops[0].shape == (4, 2)


def test_imported_rectangle_properties():
    sec, res = make_imported_section([np.array([(-2, -1), (2, -1), (2, 1), (-2, 1)])])
    assert isinstance(sec, ImportedSection)
    assert sec.area() == pytest.approx(8.0, rel=1e-9)
    assert sec.Iy() == pytest.approx(4 * 2**3 / 12, rel=1e-9)     # b·h³/12
    assert sec.Iz() == pytest.approx(2 * 4**3 / 12, rel=1e-9)     # h·b³/12
    assert res.bbox == pytest.approx((4.0, 2.0))
    assert res.area == pytest.approx(8.0)


def test_imported_section_with_void_subtracts_area():
    outer = np.array([(-2, -2), (2, -2), (2, 2), (-2, 2)])       # 4×4 = 16
    void = np.array([(-1, -1), (1, -1), (1, 1), (-1, 1)])        # 2×2 = 4
    sec, _ = make_imported_section([outer, void])
    assert sec.area() == pytest.approx(16.0 - 4.0, rel=1e-9)
    assert len(sec.geometry().voids) == 1


def test_imported_ibeam_roundtrip_matches_catalog():
    cat = make_section("I-Beam / W-Shape", [4, 6, 0.375, 0.25])
    outer = cat.polygon_vertices()[0]
    sec, _ = make_imported_section([outer])
    assert sec.area() == pytest.approx(cat.area(), rel=1e-9)
    assert sec.Iy() == pytest.approx(cat.Iy(), rel=1e-9)
    assert sec.Iz() == pytest.approx(cat.Iz(), rel=1e-9)


def test_imported_section_routes_through_fem_and_reports_shear_center():
    sp = pytest.importorskip("sectionproperties")   # FEM path needs the backend
    cat = make_section("C-Beam / Channel", [3, 6, 0.375, 0.25])
    sec, _ = make_imported_section([cat.polygon_vertices()[0]])
    df = calc_stress_at_points(sec, Loads(Vz=1000, My=4000))
    assert len(df) > 0 and np.isfinite(df["σ_vm"]).all()
    # FEM shear centre should land near the classical channel value.
    y_sc, _ = shear_center(sec)
    y_sc_cat, _ = shear_center(cat)
    assert y_sc == pytest.approx(y_sc_cat, rel=0.05, abs=0.05)


# ──────────────────────────────────────────────────────────────────────────
# Hostile inputs → clean GeometryImportError (§7.3 gate)
# ──────────────────────────────────────────────────────────────────────────
def test_self_intersecting_outer_rejected():
    bowtie = [np.array([(0, 0), (2, 2), (2, 0), (0, 2)])]        # crossing edges
    with pytest.raises(GeometryImportError):
        validate_loops(bowtie)


def test_void_outside_boundary_rejected():
    outer = np.array([(-2, -2), (2, -2), (2, 2), (-2, 2)])
    stray = np.array([(5, 5), (6, 5), (6, 6), (5, 6)])           # fully outside
    with pytest.raises(GeometryImportError):
        validate_loops([outer, stray])


def test_void_crossing_boundary_rejected():
    outer = np.array([(-2, -2), (2, -2), (2, 2), (-2, 2)])
    crossing = np.array([(1, 1), (3, 1), (3, 3), (1, 3)])        # straddles edge
    with pytest.raises(GeometryImportError):
        validate_loops([outer, crossing])


def test_degenerate_input_rejected():
    with pytest.raises(GeometryImportError):
        validate_loops([np.array([(0, 0), (1, 1)])])            # < 3 vertices


def test_unparseable_text_rejected():
    with pytest.raises(GeometryImportError):
        parse_vertex_text("this is not coordinates\n")


# ──────────────────────────────────────────────────────────────────────────
# DXF path (guarded by ezdxf)
# ──────────────────────────────────────────────────────────────────────────
def _dxf_bytes(build) -> bytes:
    import io
    import ezdxf
    doc = ezdxf.new()
    build(doc.modelspace())
    text = io.StringIO()
    doc.write(text)
    return text.getvalue().encode("utf-8")


def test_dxf_roundtrip_ibeam_matches_catalog():
    pytest.importorskip("ezdxf")
    from library.shapes.import_section import parse_dxf

    cat = make_section("I-Beam / W-Shape", [4, 6, 0.375, 0.25])
    outer = cat.polygon_vertices()[0]

    data = _dxf_bytes(lambda msp: msp.add_lwpolyline(
        [(float(y), float(z)) for y, z in outer], close=True))
    loops, skipped = parse_dxf(data)
    sec, _ = make_imported_section(loops)

    assert sec.area() == pytest.approx(cat.area(), rel=1e-2)
    assert sec.Iy() == pytest.approx(cat.Iy(), rel=1e-2)
    assert sec.Iz() == pytest.approx(cat.Iz(), rel=1e-2)


def test_dxf_circle_entity_imports_as_loop():
    pytest.importorskip("ezdxf")
    from library.shapes.import_section import parse_dxf

    data = _dxf_bytes(lambda msp: msp.add_circle((0, 0), radius=1.5))
    loops, _ = parse_dxf(data)
    sec, _ = make_imported_section(loops)
    # Discretised circle area ≈ πr²  (slightly low; within a fraction of a %).
    assert sec.area() == pytest.approx(math.pi * 1.5**2, rel=2e-3)


def test_dxf_with_only_open_polyline_rejected():
    pytest.importorskip("ezdxf")
    from library.shapes.import_section import parse_dxf

    data = _dxf_bytes(lambda msp: msp.add_lwpolyline(
        [(0, 0), (1, 0), (1, 1)], close=False))
    with pytest.raises(GeometryImportError):
        parse_dxf(data)
