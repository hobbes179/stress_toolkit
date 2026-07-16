"""
tests/test_phase7.py

Phase 7 gate: the in-app Validation page's evidence must hold up in CI too.
These exercise the SAME shared helpers the page uses (single source of truth =
tests/golden_values.py), so a regression in either the classical closed forms
or the FEM property solve fails the build, not just the page.
"""
from __future__ import annotations

import pytest

pytest.importorskip("sectionproperties")
pytest.importorskip("shapely")

from apps.beam_section.calculations import (
    validate_catalog_properties, validate_anchor_goldens,
)
import tests.golden_values as gv


def test_catalog_classical_vs_fem_geometric_agree():
    # Every catalog shape: closed-form A/Iy/Iz vs the FEM geometric solve.
    # These are geometry-only properties and must agree tightly (<1%); the
    # only spread is polygon faceting of the curved shapes.
    rows = validate_catalog_properties(1.0)
    assert len(rows) == 3 * len(gv.VALIDATION_SWEEP)
    worst = max(rows, key=lambda r: r["Δ%"])
    assert worst["Δ%"] < 1.0, (
        f"{worst['Shape']} {worst['Property']} disagrees by {worst['Δ%']:.3f}%")


def test_import_seed_caps_curved_shapes_and_reimports():
    # Curved catalog shapes must seed the custom-import box with a manageable
    # polygon (not ~180 points), and the seed must round-trip back into a valid
    # imported section.
    from library.shapes import make_section
    from library.shapes.import_section import (
        parse_vertex_text, make_imported_section,
    )
    from apps.beam_section.app import (
        _poly_to_vertex_text, _IMPORT_SEED_MAX_PTS,
    )
    for name, dims in [("Circle", [3, None, None, None]),
                       ("Ellipse", [2, 1, None, None]),
                       ("Circular Tube", [4, 0.25, None, None])]:
        sec = make_section(name, dims)
        txt = _poly_to_vertex_text(sec)
        for loop in txt.split("\n\n"):
            assert 0 < len(loop.splitlines()) <= _IMPORT_SEED_MAX_PTS
        make_imported_section(parse_vertex_text(txt))   # must not raise


def test_anchor_goldens_match_reference():
    # Textbook reference (rectangle b·h³/12, circle πd⁴/64) must match BOTH the
    # classical closed form and the FEM solve.
    for r in validate_anchor_goldens(1.0):
        ref = r["Reference"]
        assert r["Closed-form"] == pytest.approx(ref, rel=1e-6), r
        assert r["FEM"] == pytest.approx(ref, rel=2e-3), r      # faceting margin
