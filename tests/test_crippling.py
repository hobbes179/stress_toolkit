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
    element_fcc, crippling_summary, cozzone_factor,
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


def test_thin_section_stays_locked():
    # A typical thin channel cripples below yield → credit locked (f = 1.0),
    # and the compression bending allowable is capped at the crippling stress.
    sec = make_section("C-Beam / Channel", [3, 6, 0.375, 0.25])
    res = crippling_summary(sec, _MAT)
    assert not res.cozzone_unlocked
    f, _ = cozzone_factor(sec, _MAT)
    assert f == 1.0
    assert res.fcc_element < _FCY
    assert compression_bending_allowable(_FCY, res) == pytest.approx(res.fcc_element)


def test_stocky_section_unlocks_full_factor():
    # A chunky (low-b/t) angle reaches Fcy before crippling → the raw Cozzone
    # plastic factor is restored, and the compression allowable is full Fcy.
    sec = make_section("L-Beam / Angle", [1.5, 1.5, 0.45, 0.45])
    res = crippling_summary(sec, _MAT)
    assert res.cozzone_unlocked
    f, _ = cozzone_factor(sec, _MAT)
    assert f == pytest.approx(sec.f_cozzone) and f > 1.0
    assert compression_bending_allowable(_FCY, res) == pytest.approx(_FCY)


def test_non_thinwalled_factor_is_unchanged():
    # cozzone_factor must not disturb solids — they keep their geometric
    # effective_f_cozzone and get no crippling summary.
    rect = make_section("Rectangle", [2, 3, None, None])
    f, res = cozzone_factor(rect, _MAT)
    assert res is None
    assert f == rect.effective_f_cozzone == rect.f_cozzone   # solid keeps its f
