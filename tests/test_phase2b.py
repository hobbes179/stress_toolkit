"""
tests/test_phase2b.py

Gate tests for Phase 2 sub-step B: the ClassicalMidlineSolver for open
thin-walled sections (design handoff §9 Phase 2, §7.1–7.2).

Phase 2 gate: "channel shear-center golden passes; I-beam τ profile matches
VQ/It hand values at web NA and flange points."
"""
from __future__ import annotations

import numpy as np
import pytest

from library.shapes import make_section
from library.analysis.solvers import (
    classical_shear_center, classical_shear_flow_at, classical_J_open,
    ClassicalMidlineSolver,
)
import tests.golden_values as gv


# ──────────────────────────────────────────────────────────────────────────
# Shear-center goldens (§7.1)
# ──────────────────────────────────────────────────────────────────────────
def test_ibeam_shear_center_at_centroid():
    sec = make_section("I-Beam / W-Shape", [4, 6, 0.375, 0.25])
    y_sc, z_sc = classical_shear_center(sec.geometry(), sec.section_props())
    assert y_sc == pytest.approx(0.0, abs=1e-6)
    assert z_sc == pytest.approx(0.0, abs=1e-6)


def test_plus_cross_shear_center_at_centroid():
    sec = make_section("Plus / Cross", [4, 4, 0.5, 0.5])
    y_sc, z_sc = classical_shear_center(sec.geometry(), sec.section_props())
    assert y_sc == pytest.approx(0.0, abs=1e-6)
    assert z_sc == pytest.approx(0.0, abs=1e-6)


def test_zbeam_shear_center_at_centroid():
    # Z is point-symmetric about its centroid → shear center at the centroid.
    sec = make_section("Z-Beam", [3, 6, 0.375, 0.25])
    y_sc, z_sc = classical_shear_center(sec.geometry(), sec.section_props())
    assert y_sc == pytest.approx(0.0, abs=1e-6)
    assert z_sc == pytest.approx(0.0, abs=1e-6)


def test_tbeam_shear_center_on_symmetry_axis():
    # T is symmetric about the vertical (z) axis → y_sc = 0.
    sec = make_section("T-Beam", [4, 0.375, 4, 0.25])
    y_sc, _ = classical_shear_center(sec.geometry(), sec.section_props())
    assert y_sc == pytest.approx(0.0, abs=1e-6)


def test_uniform_channel_shear_center_golden():
    # §7.1 golden: uniform-thickness channel, e = 3b²/(h + 6b) from the web
    # midline (b, h = midline flange width / web height). Solver uses exact
    # Iy, so use a genuinely uniform channel where the thin-wall golden holds.
    t = 0.10
    bf, d = 3.0, 6.0
    sec = make_section("C-Beam / Channel", [bf, d, t, t])
    yb, _ = sec.centroid()
    web_y = t / 2 - yb
    b_mid = bf - t / 2
    h_mid = d - t
    e_golden = gv.uniform_channel_shear_center_offset(b_mid, h_mid)

    y_sc, z_sc = classical_shear_center(sec.geometry(), sec.section_props())
    # Channel is symmetric about the horizontal (y) axis → z_sc = 0 (residual
    # here is trapezoid-integration noise, ~1e-4 in on a 6-in section).
    assert z_sc == pytest.approx(0.0, abs=2e-3)
    # Shear center sits on the far (−y) side of the web from the flanges.
    assert abs(y_sc - web_y) == pytest.approx(e_golden, rel=0.03)
    assert y_sc < web_y


# ──────────────────────────────────────────────────────────────────────────
# I-beam transverse-shear τ profile vs VQ/It (§7.1)
# ──────────────────────────────────────────────────────────────────────────
def test_ibeam_tau_profile_web_na_and_flange_tip():
    sec = make_section("I-Beam / W-Shape", [4, 6, 0.375, 0.25])
    g, p = sec.geometry(), sec.section_props()
    Vz = 1000.0

    # Web neutral axis (0,0): |τ| ≈ Vz·Qy/(Iy·tw) (VQ/It, strong axis).
    q, t = classical_shear_flow_at(g, p, 0.0, Vz, np.array([[0.0, 0.0]]))
    tau_na = abs(q[0] / t[0] / 1000.0)
    vqit = Vz * sec.Qy() / (sec.Iy() * sec.d4) / 1000.0
    # ≤7% — thin-wall midline vs the shape's exact-Q closed form legitimately
    # differ slightly (web idealized to the flange midline).
    assert tau_na == pytest.approx(vqit, rel=0.07)

    # Flange outer tip is a free edge → τ ≈ 0.
    qf, tf = classical_shear_flow_at(g, p, 0.0, Vz,
                                     np.array([[2.0, 6/2 - 0.375/2]]))
    assert abs(qf[0] / tf[0] / 1000.0) == pytest.approx(0.0, abs=1e-6)


def test_ibeam_vertical_shear_beats_v1_axis_mixup():
    # Regression guard on the CHANGELOG finding: the correct vertical-shear
    # stress uses the strong axis Iy, giving a markedly higher web stress
    # than v1's Iz-based value. Assert the solver is on the strong-axis side.
    sec = make_section("I-Beam / W-Shape", [4, 6, 0.375, 0.25])
    g, p = sec.geometry(), sec.section_props()
    q, t = classical_shear_flow_at(g, p, 0.0, 1000.0, np.array([[0.0, 0.0]]))
    tau_correct = abs(q[0] / t[0] / 1000.0)
    v1_wrong = 1000.0 * sec.Qz() / (sec.Iz() * sec.tw_z()) / 1000.0
    assert tau_correct > 1.25 * v1_wrong          # ~34% higher on the default I-beam


# ──────────────────────────────────────────────────────────────────────────
# Open torsion J and the solver wrapper
# ──────────────────────────────────────────────────────────────────────────
def test_classical_J_matches_shape_open_torsion():
    for name, dims in [("I-Beam / W-Shape", [4, 6, 0.375, 0.25]),
                       ("C-Beam / Channel", [3, 6, 0.375, 0.25])]:
        sec = make_section(name, dims)
        J_solver = classical_J_open(sec.geometry())
        # Midline ΣLt³/3 vs the shape's J (same theory, slight length idealization).
        assert J_solver == pytest.approx(sec.J_torsion(), rel=0.10)


def test_solver_wrapper_result_shape():
    sec = make_section("C-Beam / Channel", [3, 6, 0.375, 0.25])
    solver = ClassicalMidlineSolver()
    pts = np.array([[0.0, 0.0], [2.0, 2.8]])
    res = solver.solve(sec.geometry(), sec.section_props(),
                       Vy=0.0, Vz=1000.0, T=500.0, points=pts)
    assert res["J"] > 0
    assert res["Cw"] is None
    assert res["tau_v"].shape == (2,)
    assert res["tau_t"].shape == (2,)
    assert np.all(np.isfinite(res["tau_v"]))
