"""
tests/test_phase0.py

Gate tests for v2 Phase 0 (safety patch) — see
_TrainingData/v2_handoff/V2_DESIGN_HANDOFF.md §9 (Phase 0) and §7.1.

Phase 0 gate: "interaction and shear-combination unit tests from §7.1
pass; smoke test passes."
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
import pytest

from apps.beam_section.calculations import (
    Loads, calc_stress_at_points, calc_margin_table, interaction_ms,
)
from library.materials import MATERIALS
from library.shapes import SHAPE_REGISTRY, make_section, CircularTube, Ellipse, RectTube


REPO_ROOT = Path(__file__).resolve().parent.parent
_MATERIAL = MATERIALS[next(iter(MATERIALS))]


# ──────────────────────────────────────────────────────────────────────────
# §7.1 — Interaction: Ra=Rb=0.5, Rs=0 -> MS=0.0; Ra=Rb=0, Rs=1 -> MS=0.0
# ──────────────────────────────────────────────────────────────────────────
def test_interaction_zero_margin_axial_bending():
    ms = interaction_ms(Ra=0.5, Rb=0.5, Rs=0.0)
    assert ms == pytest.approx(0.0, abs=1e-9)


def test_interaction_zero_margin_shear():
    ms = interaction_ms(Ra=0.0, Rb=0.0, Rs=1.0)
    assert ms == pytest.approx(0.0, abs=1e-9)


def test_interaction_old_rss_form_was_optimistic_here():
    # The v1 RSS-style form gave MS=+0.41 at this exact state — documenting
    # the contrast so a future accidental revert is easy to catch.
    old_rss_ms = 1 / math.sqrt(0.5**2 + 0.5**2) - 1
    assert old_rss_ms == pytest.approx(0.4142, abs=1e-3)
    assert interaction_ms(0.5, 0.5, 0.0) < old_rss_ms


def test_interaction_ms_responds_to_sf_ult():
    # CHANGELOG.md v1.1.0 "Interaction SF" — Ra/Rb/Rs must be factored by
    # SF_ult inside calc_margin_table so raising SF_ult tightens (lowers)
    # the interaction MS, same as every other check.
    sec = make_section("Rectangle", [4.0, 2.0, None, None])
    loads = Loads(P=0, Vy=0, Vz=0, My=3000, Mz=0, T=0)
    df_stress = calc_stress_at_points(sec, loads)

    df_low  = calc_margin_table(df_stress, _MATERIAL, sec, 1.0, 1.0, loads)
    df_high = calc_margin_table(df_stress, _MATERIAL, sec, 1.0, 2.0, loads)

    ms_low  = df_low[df_low["Check"].str.contains("Combined interaction")]["MS"].iloc[0]
    ms_high = df_high[df_high["Check"].str.contains("Combined interaction")]["MS"].iloc[0]
    assert ms_high < ms_low


# ──────────────────────────────────────────────────────────────────────────
# §7.1 — Shear combination: circular tube, Vz + T with τ_V = τ_T at the
# horizontal diameter -> combined = 2τ, NOT the RSS value 1.414τ.
# ──────────────────────────────────────────────────────────────────────────
def test_shear_combination_circular_tube_not_rss():
    sec = CircularTube([4.0, 0.25, None, None])

    # Pick Vz arbitrarily, read back the resulting transverse shear stress,
    # then back-solve T so tau_T matches it exactly.
    Vz = 1000.0
    probe = calc_stress_at_points(sec, Loads(Vz=Vz))
    tau_v = probe["τ_Vz"].iloc[0]
    assert tau_v > 0

    J = sec.J_torsion()
    ro = sec.d1 / 2
    T = tau_v * 1000 * J / ro  # inverts sec.tau_T(T) = |T|*ro/J/1000

    df = calc_stress_at_points(sec, Loads(Vz=Vz, T=T))
    tau_t = df["τ_T"].iloc[0]
    assert tau_t == pytest.approx(tau_v, rel=1e-6)

    combined = df["τ_total"].iloc[0]
    algebraic_sum = tau_v + tau_t
    rss = math.sqrt(tau_v**2 + tau_t**2)

    assert combined == pytest.approx(algebraic_sum, rel=1e-9)
    # RSS under-predicts by ~29% when the two components are equal.
    assert combined > rss * 1.2


# ──────────────────────────────────────────────────────────────────────────
# Grep-guard: the RSS shear combination must not survive anywhere in
# apps/ or library/ source.
# ──────────────────────────────────────────────────────────────────────────
def test_no_rss_shear_combination_in_source():
    rss_pattern = re.compile(r"tvy\s*\*\*\s*2\s*\+\s*tvz\s*\*\*\s*2\s*\+\s*tau_T\s*\*\*\s*2")
    offenders = []
    for base in ("apps", "library"):
        for path in (REPO_ROOT / base).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if rss_pattern.search(text):
                offenders.append(str(path))
    assert not offenders, f"RSS shear combination found in: {offenders}"


# ──────────────────────────────────────────────────────────────────────────
# Cozzone gate (§3.7)
# ──────────────────────────────────────────────────────────────────────────
def test_cozzone_gate_thin_walled_open_sections():
    ibeam = make_section("I-Beam / W-Shape", [4, 6, 0.375, 0.25])
    assert ibeam.f_cozzone == pytest.approx(1.07)
    assert ibeam.effective_f_cozzone == pytest.approx(1.0)

    plus = make_section("Plus / Cross", [4, 4, 0.5, 0.5])
    assert plus.f_cozzone == pytest.approx(1.30)
    assert plus.effective_f_cozzone == pytest.approx(1.0)


def test_cozzone_gate_does_not_affect_solids_or_closed_sections():
    rect = make_section("Rectangle", [4, 2, None, None])
    assert rect.effective_f_cozzone == pytest.approx(rect.f_cozzone) == pytest.approx(1.50)

    tube = make_section("Rect Tube (HSS)", [4, 6, 0.375, 0.25])
    assert tube.effective_f_cozzone == pytest.approx(tube.f_cozzone) == pytest.approx(1.30)


# ──────────────────────────────────────────────────────────────────────────
# Ellipse a >= b guard
# ──────────────────────────────────────────────────────────────────────────
def test_ellipse_rejects_b_greater_than_a():
    tall = Ellipse([1.0, 2.0, None, None])
    assert tall.validate_dims() is not None


def test_ellipse_accepts_a_greater_or_equal_b():
    wide = Ellipse([2.0, 1.0, None, None])
    assert wide.validate_dims() is None
    square = Ellipse([1.0, 1.0, None, None])
    assert square.validate_dims() is None


# ──────────────────────────────────────────────────────────────────────────
# Rect Tube Bredt min-thickness guard
# ──────────────────────────────────────────────────────────────────────────
def test_rect_tube_rejects_wall_exceeding_section():
    degenerate = RectTube([2.0, 2.0, 1.5, 1.5])  # 2*1.5 >= 2.0
    assert degenerate.validate_dims() is not None


def test_rect_tube_accepts_reasonable_walls():
    normal = RectTube([4.0, 6.0, 0.375, 0.25])
    assert normal.validate_dims() is None


# ──────────────────────────────────────────────────────────────────────────
# Smoke test — full pipeline for every registered shape, combined loads.
# Ports the CLAUDE.md smoke test into pytest and extends it to all shapes.
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("shape_name", list(SHAPE_REGISTRY.keys()))
def test_smoke_all_shapes(shape_name):
    cls = SHAPE_REGISTRY[shape_name]
    dims = [d for d in cls.dim_defaults]
    sec = make_section(shape_name, dims)

    assert sec.validate_dims() is None, (
        f"{shape_name} default dims failed validation"
    )

    loads = Loads(P=500, Vy=200, Vz=500, My=1000, Mz=300, T=0)
    df_stress = calc_stress_at_points(sec, loads)
    assert len(df_stress) > 0
    numeric = df_stress.drop(columns=["KP", "Description"]).to_numpy(dtype=float)
    assert np.isfinite(numeric).all()

    df_ms = calc_margin_table(df_stress, _MATERIAL, sec, 1.0, 1.5, loads)
    assert len(df_ms) == 5
    numeric_ms = [v for v in df_ms["MS"] if isinstance(v, (int, float))]
    assert len(numeric_ms) == len(df_ms)
    assert all(math.isfinite(v) for v in numeric_ms)
