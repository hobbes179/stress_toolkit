"""
tests/test_phase3.py

Gate tests for Phase 3: closed cells, solids, induced torsion, warping
screen (design handoff §9 Phase 3, §3.2–3.5, §7.1).

Sub-steps append here as they land:
  3A — corrected transverse-shear axis pairing on the solid/tube VQ/It path
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from library.shapes import make_section
from apps.beam_section.calculations import (
    Loads, calc_stress_at_points, induced_torsion, warping_characteristic_length,
    shear_center,
)
import tests.golden_values as gv


def _tau_vz_at(section, Vz):
    """Max |τ_Vz| over the evaluation set for a pure vertical shear."""
    df = calc_stress_at_points(section, Loads(Vz=Vz))
    return df["τ_Vz"].abs().max()


# ──────────────────────────────────────────────────────────────────────────
# 3A — solid transverse-shear factors (locks the classic closed forms)
# ──────────────────────────────────────────────────────────────────────────
def test_rectangle_max_transverse_shear_factor():
    sec = make_section("Rectangle", [4.0, 2.0, None, None])
    Vz = 1000.0
    tau = _tau_vz_at(sec, Vz)
    assert tau == pytest.approx(1.5 * Vz / sec.area() / 1000.0, rel=1e-9)


def test_circle_max_transverse_shear_factor():
    sec = make_section("Circle", [3.0, None, None, None])
    Vz = 1000.0
    tau = _tau_vz_at(sec, Vz)
    assert tau == pytest.approx(4.0 / 3.0 * Vz / sec.area() / 1000.0, rel=1e-9)


# ──────────────────────────────────────────────────────────────────────────
# 3A — corrected axis pairing (matters for an asymmetric closed tube)
# ──────────────────────────────────────────────────────────────────────────
def test_tall_rect_tube_vertical_shear_uses_strong_axis():
    # A tall 2×10 tube under vertical shear must resolve on the STRONG axis
    # Iy (large), giving a modest stress — not the weak-axis Iz value the v1
    # pairing would have used (3× too high here).
    sec = make_section("Rect Tube (HSS)", [2.0, 10.0, 0.2, 0.2])
    Vz = 1000.0
    tau = _tau_vz_at(sec, Vz)

    strong = Vz * sec.Qy() / (sec.Iy() * sec.tw_y()) / 1000.0   # correct
    weak   = Vz * sec.Qz() / (sec.Iz() * sec.tw_z()) / 1000.0   # v1 (wrong)
    assert tau == pytest.approx(strong, rel=1e-9)
    assert tau < 0.5 * weak            # strong-axis value is far below the v1 one


# ──────────────────────────────────────────────────────────────────────────
# 3B — closed tube: thin-ring goldens + Vz+T combination = 2τ (not RSS)
# ──────────────────────────────────────────────────────────────────────────
def test_thin_ring_section_property_goldens():
    r, t = 2.0, 0.05
    sec = make_section("Circular Tube", [2 * r + t, t, None, None])  # midline radius r
    g = gv.thin_ring_props(r, t)
    assert sec.area() == pytest.approx(g["A"], rel=1e-3)
    assert sec.Iy() == pytest.approx(g["I"], rel=2e-3)
    assert sec.J_torsion() == pytest.approx(g["J"], rel=2e-3)


def test_circular_tube_shear_torsion_combination_is_algebraic():
    # §7.1 golden: size Vz and T so the transverse and torsional shear are
    # equal at the horizontal diameter → combined = 2τ (algebraic), NOT the
    # RSS value 1.414τ. Guards against any RSS regression on the tube path.
    r, t = 2.0, 0.05
    sec = make_section("Circular Tube", [2 * r + t, t, None, None])
    Vz = 1000.0
    tau_v = calc_stress_at_points(sec, Loads(Vz=Vz))["τ_Vz"].abs().max()

    Am = math.pi * r**2
    T = tau_v * 1000 * 2 * Am * t                     # Bredt: τ_T = T/(2·Am·t)
    combined = calc_stress_at_points(sec, Loads(Vz=Vz, T=T))["τ_total"].abs().max()

    tau_t = sec.tau_T(T)
    assert combined == pytest.approx(tau_v + tau_t, rel=1e-6)     # algebraic
    assert combined > 1.2 * math.hypot(tau_v, tau_t)             # not RSS


# ──────────────────────────────────────────────────────────────────────────
# 3C — induced torsion (§3.4): channel sign test (acceptance criterion #3)
# ──────────────────────────────────────────────────────────────────────────
def test_channel_induced_torsion_sign_and_zero_at_shear_center():
    sec = make_section("C-Beam / Channel", [3, 6, 0.375, 0.25])
    y_sc, z_sc = shear_center(sec)
    Vz = 1000.0

    # Applied at the centroid (0,0): nonzero induced torsion, sign = sign of
    # Vz·(0 − y_sc). The channel's shear center is on −y, so this is > 0.
    T_centroid = induced_torsion(0.0, Vz, 0.0, 0.0, y_sc, z_sc)
    assert T_centroid != 0.0
    assert math.copysign(1, T_centroid) == math.copysign(1, Vz * (0.0 - y_sc))
    assert T_centroid == pytest.approx(Vz * (0.0 - y_sc), rel=1e-9)

    # Applied at the shear center: exactly zero induced torsion.
    T_sc = induced_torsion(0.0, Vz, y_sc, z_sc, y_sc, z_sc)
    assert T_sc == pytest.approx(0.0, abs=1e-9)


def test_symmetric_section_no_induced_torsion_at_centroid():
    # Doubly-symmetric I: shear center = centroid, so centroid-applied shear
    # induces no torsion.
    sec = make_section("I-Beam / W-Shape", [4, 6, 0.375, 0.25])
    y_sc, z_sc = shear_center(sec)
    T = induced_torsion(0.0, 1000.0, 0.0, 0.0, y_sc, z_sc)
    assert T == pytest.approx(0.0, abs=1e-6)


# ──────────────────────────────────────────────────────────────────────────
# 3D — warping screen (§3.5): Cw and λ
# ──────────────────────────────────────────────────────────────────────────
def test_ibeam_warping_constant_closed_form():
    sec = make_section("I-Beam / W-Shape", [4, 6, 0.375, 0.25])
    bf, d, tf = 4.0, 6.0, 0.375
    h = d - tf
    expected = tf * bf**3 * h**2 / 24.0
    assert sec.Cw() == pytest.approx(expected, rel=1e-12)


def test_warping_free_sections_have_zero_cw():
    for name, dims in [("T-Beam", [4, 0.375, 4, 0.25]),
                       ("L-Beam / Angle", [3, 3, 0.25, 0.25]),
                       ("Plus / Cross", [4, 4, 0.5, 0.5])]:
        assert make_section(name, dims).Cw() == 0.0


def test_warping_characteristic_length_and_screen():
    sec = make_section("I-Beam / W-Shape", [4, 6, 0.375, 0.25])
    E, G = 10.3, 3.9   # Msi (aluminium-ish)
    lam = warping_characteristic_length(E, G, sec.Cw(), sec.J_torsion())
    assert lam is not None and lam > 0.0

    # Warping-free section → λ = 0; unavailable Cw → None.
    lfree = warping_characteristic_length(E, G, 0.0, 1.0)
    assert lfree == 0.0
    assert warping_characteristic_length(E, G, None, 1.0) is None
