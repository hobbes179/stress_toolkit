"""
tests/test_crippling.py

Crippling (local plate buckling) of thin-walled open sections and the Cozzone
plastic-bending unlock it gates (library/analysis/crippling.py). This is the
"risky math" of the crippling feature, locked independently of any UI:
element-method behaviour, per-shape decomposition, and the gate decision.

The empirical COEFFICIENTS (Ce, Gerard β/m/g) are documented defaults flagged
⚠️ VERIFY in the module; these tests assert method STRUCTURE and physically
required behaviour (monotonicity, edge-condition ordering, the Fcy cap, and the
lock/unlock gate), not specific handbook values.
"""
from __future__ import annotations

import pytest

from library.shapes import make_section
from library.materials import MATERIALS
from library.analysis.crippling import (
    element_fcc, crippling_summary,
    compression_bending_allowable, _elements_for,
)


# An aluminium with Fcy + Ec present.
_MAT = next(MATERIALS[k] for k in MATERIALS if "2024" in k)
_FCY = _MAT.Fcy
_EC = (_MAT.Ec or _MAT.E) * 1000.0


def test_element_fcc_decreases_with_slenderness():
    # Thinner (higher b/t) element crippling stress must be lower.
    coarse = element_fcc(2.0, 0.5, "OEF", _FCY, _EC)     # b/t = 4
    slender = element_fcc(8.0, 0.5, "OEF", _FCY, _EC)    # b/t = 16
    assert slender < coarse


def test_nef_stronger_than_oef():
    # A both-edges-supported element must crush at a higher stress than an
    # otherwise-identical one-edge-free element.
    b, t = 4.0, 0.25
    assert element_fcc(b, t, "NEF", _FCY, _EC) > element_fcc(b, t, "OEF", _FCY, _EC)


def test_fcc_capped_at_fcy():
    # A very stocky element cannot cripple above yield.
    assert element_fcc(0.5, 0.5, "OEF", _FCY, _EC) == pytest.approx(_FCY)


@pytest.mark.parametrize("name,dims,n_elem", [
    ("I-Beam / W-Shape", [4, 6, 0.375, 0.25], 5),
    ("C-Beam / Channel", [3, 6, 0.375, 0.25], 3),
    ("T-Beam",           [4, 0.375, 4, 0.25], 3),
    ("L-Beam / Angle",   [3, 3, 0.25, 0.25], 2),
    ("Z-Beam",           [3, 6, 0.375, 0.25], 3),
    ("Plus / Cross",     [3, 3, 0.25, 0.25], 4),
])
def test_decomposition_element_counts(name, dims, n_elem):
    sec = make_section(name, dims)
    els = _elements_for(sec)
    assert els is not None and len(els) == n_elem
    assert all(e.b > 0 and e.t > 0 for e in els)


def test_crippling_not_applicable_to_non_open_shapes():
    # Solids and closed tubes do not plate-cripple → no summary.
    for name, dims in [("Rectangle", [2, 3, None, None]),
                       ("Circle", [3, None, None, None]),
                       ("Circular Tube", [4, 0.25, None, None])]:
        assert crippling_summary(make_section(name, dims), _MAT) is None


def test_gerard_is_a_bounded_crosscheck():
    # Gerard is computed for display and must stay within its 0.80·Fcy plateau
    # (which is exactly why it cannot be used for the reach-Fcy gate).
    res = crippling_summary(make_section("C-Beam / Channel", [3, 6, 0.375, 0.25]),
                            _MAT)
    assert res.fcc_gerard is not None
    assert 0.0 < res.fcc_gerard <= 0.80 * _FCY + 1e-6


def test_thin_section_is_crippling_limited():
    # A typical thin channel cripples below yield → crippling-limited, and the
    # compression bending allowable is capped at the crippling stress. There is
    # no tension-side gate: the shape keeps its plastic factor for Fbu.
    sec = make_section("C-Beam / Channel", [3, 6, 0.375, 0.25])
    res = crippling_summary(sec, _MAT)
    assert res.crippling_limited
    assert res.fcc_element < _FCY
    assert compression_bending_allowable(_FCY, res) == pytest.approx(res.fcc_element)
    assert sec.effective_f_cozzone == sec.f_cozzone       # gate removed


def test_stocky_section_is_not_crippling_limited():
    # A chunky (low-b/t) angle reaches Fcy before crippling → not crippling-
    # limited, and the compression allowable is the full Fcy.
    sec = make_section("L-Beam / Angle", [1.5, 1.5, 0.45, 0.45])
    res = crippling_summary(sec, _MAT)
    assert not res.crippling_limited
    assert compression_bending_allowable(_FCY, res) == pytest.approx(_FCY)


def test_crippling_is_a_standalone_row_element_wise():
    # Crippling is its own margin row (σ_c vs Fcc). Element-wise (v2.2.1): the
    # row reports the WORST plate element — its own peak compression vs its own
    # Fcc_i — not the peak stress against the area-weighted section average.
    from apps.beam_section.calculations import (
        Loads, calc_stress_at_points, calc_margin_table,
    )
    from library.analysis.crippling import worst_element_crippling
    sec = make_section("C-Beam / Channel", [3, 6, 0.375, 0.25])
    res = crippling_summary(sec, _MAT)
    assert res.fcc_element < _MAT.Fcy               # crippling below yield
    loads = Loads(P=0, Vy=0, Vz=0, My=20000, Mz=0, T=0)
    df = calc_stress_at_points(sec, loads, solver="Classical")
    ms = calc_margin_table(df, _MAT, sec, 1.0, 1.5, loads)

    crow = ms[ms["Check"].str.startswith("σ_c vs")].iloc[0]
    assert "Fcc" in crow["Check"] and "crippling" in crow["Check"]

    # Recompute the expected governing element from the same affine normal-
    # stress field the margin table uses (pure My here, so σ_axial = 0).
    Iy, Iz, Iyz = sec.Iy(), sec.Iz(), sec.Iyz()
    D = Iy * Iz - Iyz**2
    cz = (loads.My * Iz - loads.Mz * Iyz) / D
    cy = (loads.Mz * Iy - loads.My * Iyz) / D
    applied, fcc, name, _pt = worst_element_crippling(
        res, lambda y, z: (cz * z + cy * y) / 1000.0)

    assert crow["Allow"] == pytest.approx(fcc, rel=1e-6)
    assert crow["Applied"] == pytest.approx(applied, rel=1e-6)
    # The governing element's own Fcc is at or below the area-weighted section
    # value — the compression flange, being the outstanding element, is weaker
    # than the web-inclusive average.
    assert fcc <= res.fcc_element + 1e-9
    # The STRENGTH interaction no longer carries Fcc — that is the crippling row.
    inter = ms[ms["Check"].str.contains("Combined")].iloc[0]["Allow"]
    assert "Fcc" not in inter


def test_element_wise_catches_slender_flange_masked_by_stocky_web():
    # Fable review finding #1 (the unconservatism the element-wise fix removes):
    # a slender compression flange (high b/t) paired with a stocky web (low b/t).
    # The area-weighted section Fcc is pulled UP by the strong web and masks the
    # flange — the v2.2.0 peak-vs-average check reported a POSITIVE crippling
    # margin while the flange was actually past its own crippling stress. The
    # element-wise check must catch it (MS < 0) and report the flange's Fcc.
    from apps.beam_section.calculations import (
        Loads, calc_stress_at_points, calc_margin_table,
    )
    sec = make_section("I-Beam / W-Shape", [6, 6, 0.08, 0.5])  # thin flange, thick web
    res = crippling_summary(sec, _MAT)
    fccs = [er.fcc for er in res.elements]
    # The slender flange is far weaker than the area-weighted section average
    # (the web inflates the average) — the exact masking condition.
    assert min(fccs) < 0.5 * res.fcc_element

    loads = Loads(My=60000)
    df = calc_stress_at_points(sec, loads, solver="Classical")
    ms = calc_margin_table(df, _MAT, sec, 1.0, 1.5, loads)
    crow = ms[ms["Check"].str.startswith("σ_c vs")].iloc[0]

    assert crow["MS"] < 0.0                          # element-wise catches it
    # The reported allowable is the weak flange's Fcc, not the inflated average.
    assert crow["Allow"] == pytest.approx(min(fccs), rel=1e-6)
    # Sanity: the old area-weighted check would have looked SAFE here.
    old_ms = res.fcc_element / (1.5 * crow["Applied"]) - 1
    assert old_ms > 0.0


def test_crippling_row_captures_pure_axial_compression():
    # The whole point of using σ_total: a compression MEMBER (pure axial, no
    # bending) must trigger crippling. A bending-only check would read +∞ here.
    from apps.beam_section.calculations import (
        Loads, calc_stress_at_points, calc_margin_table,
    )
    sec = make_section("C-Beam / Channel", [3, 6, 0.375, 0.25])
    res = crippling_summary(sec, _MAT)
    # axial compression at ~90% of the crippling stress (P in lb, stress in ksi)
    P = -0.9 * res.fcc_element * sec.area() * 1000.0
    loads = Loads(P=P, Vy=0, Vz=0, My=0, Mz=0, T=0)
    df = calc_stress_at_points(sec, loads, solver="Classical")
    ms = calc_margin_table(df, _MAT, sec, 1.0, 1.5, loads)

    crow = ms[ms["Check"].str.startswith("σ_c vs")].iloc[0]
    assert crow["Applied"] == pytest.approx(0.9 * res.fcc_element, rel=1e-3)
    # bending rows see ~zero applied stress; only crippling catches the member
    bt = ms[ms["Check"].str.contains("σ_bend,t")].iloc[0]
    assert bt["Applied"] == pytest.approx(0.0, abs=1e-6)
    assert crow["MS"] < 0.0                              # 1/(1.5·0.9) − 1 < 0


def test_imported_section_skips_crippling_without_crashing():
    # An imported polygon has no catalog dims / plate-element decomposition, so
    # crippling_summary must return None (not raise), and the compression
    # bending allowable falls back to Fcy.
    pytest.importorskip("sectionproperties")
    pytest.importorskip("shapely")
    from library.shapes.import_section import make_imported_section, parse_vertex_text
    loops = parse_vertex_text("0,0\n3,0\n3,0.25\n0.25,0.25\n0.25,6\n0,6")
    isec, _ = make_imported_section(loops)
    assert crippling_summary(isec, _MAT) is None
    assert compression_bending_allowable(_MAT.Fcy, None) == _MAT.Fcy


def test_solids_have_no_crippling_and_keep_their_factor():
    # Solids do not plate-cripple → no crippling summary, and effective_f_cozzone
    # is just the shape's plastic factor (the gate is gone for every shape).
    rect = make_section("Rectangle", [2, 3, None, None])
    assert crippling_summary(rect, _MAT) is None
    assert rect.effective_f_cozzone == rect.f_cozzone == pytest.approx(1.50)
