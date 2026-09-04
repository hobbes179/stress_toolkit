"""
tests/bolt_bending/test_kernel.py

Gate tests for the bolt-bending kernel.

The primary gate is the §6 verification case from `docs/bolt_bending/HANDOFF.md`,
station by station. Any refactor of `library/bolt_bending/kernel.py` must still
reproduce those numbers.

The standing arithmetic check — **both diagrams close at the nut** — is
asserted for every balanced case here, not just the golden one. If V(L) or
M(L) is non-zero, the load split or the residual moment has been mishandled.
"""

from __future__ import annotations

import math

import pytest

from library.bolt_bending.kernel import (
    IMBALANCE_TOL,
    Allowables,
    BoltSection,
    Layer,
    analyse,
    default_stack,
    margins,
    screening_checks,
    symmetric_double_shear,
)

# ══════════════════════════════════════════════════════════════════════════
# Handoff §6 — the shipped default
# ══════════════════════════════════════════════════════════════════════════
# (x, station name, V lbf, M lb·in) — the published table
GOLDEN_STATIONS = [
    (0.000, "head",           -56.6,    0.0),
    (0.250, "end plate 1",    943.4,  110.8),
    (0.310, "end spacer",     943.4,  167.5),
    (0.546, "V = 0, plate 2",   0.0,  278.7),
    (0.810, "end plate 2",  -1056.6,  139.2),
    (1.060, "nut, after R_L",   0.0,    0.0),
]

GOLDEN_SECTION = BoltSection(d_shank=0.375, d_section=0.315)
GOLDEN_ALLOWABLES = Allowables(Ftu=160.0, Fsu=95.0, k_bending=1.5,
                               fitting_factor=1.0)


@pytest.fixture
def golden():
    return analyse(default_stack())


def _at(a, x: float):
    """The sampled station nearest x. Exact for segment boundaries, which the
    sampling grid always lands on."""
    return min(a.stations, key=lambda p: abs(p.x - x))


def test_grip_and_equilibrium(golden):
    assert golden.L == pytest.approx(1.060)
    assert golden.sum_P == pytest.approx(0.0)
    assert golden.balanced
    assert golden.moment_residual == pytest.approx(-60.0)
    assert golden.RL == pytest.approx(56.60, abs=0.01)
    assert golden.R0 == pytest.approx(-56.60, abs=0.01)
    # the closing pair adds no net force
    assert golden.R0 + golden.RL == pytest.approx(0.0)


@pytest.mark.parametrize("x,name,V,M", GOLDEN_STATIONS)
def test_golden_station_table(golden, x, name, V, M):
    """Every row of the handoff §6 table, to its published precision."""
    if name == "nut, after R_L":
        p = golden.stations[-1]        # the post-R_L station is appended last
    elif name.startswith("V = 0"):
        # The interior peak is inserted at the EXACT stationary point, which
        # sits between two grid samples — a nearest-x lookup would find a
        # neighbouring sample instead.
        p = golden.M_max
    else:
        p = _at(golden, x)
    assert p.x == pytest.approx(x, abs=5e-4), name
    assert p.V == pytest.approx(V, abs=0.05), name
    assert p.M == pytest.approx(M, abs=0.05), name


def test_golden_peak_moment(golden):
    assert golden.M_max.M == pytest.approx(278.7, abs=0.05)
    assert golden.M_max.x == pytest.approx(0.546, abs=5e-4)
    assert golden.layer_name_at(golden.M_max.x) == "in plate 2"
    # shear is exactly zero at the peak-moment station
    assert golden.M_max.V == pytest.approx(0.0, abs=1e-9)


def test_golden_peak_shear(golden):
    assert abs(golden.V_max) == pytest.approx(1056.6, abs=0.05)


def test_golden_margins(golden):
    s, al = GOLDEN_SECTION, GOLDEN_ALLOWABLES
    assert s.Z == pytest.approx(0.003069, abs=5e-7)
    assert s.A == pytest.approx(0.07793, abs=5e-6)

    m = margins(golden, s, al)
    assert m.valid
    assert m.f_b == pytest.approx(90.8, abs=0.05)
    assert m.F_b == pytest.approx(240.0)
    assert m.MS_bending == pytest.approx(1.64, abs=0.005)
    # shear is zero at the peak-moment station, so the combined margin lands
    # on the same value as bending
    assert m.MS_combined == pytest.approx(1.64, abs=0.005)
    assert m.critical.x == pytest.approx(0.546, abs=5e-4)


# ══════════════════════════════════════════════════════════════════════════
# The standing arithmetic check
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "layers",
    [
        pytest.param(default_stack(), id="verification-case"),
        pytest.param(symmetric_double_shear(), id="symmetric-double-shear"),
        pytest.param(
            [Layer("plate", 0.19, 750.0), Layer("gap", 0.25, 0.0),
             Layer("plate", 0.40, -1750.0), Layer("gap", 0.03, 0.0),
             Layer("plate", 0.31, 1000.0)],
            id="asymmetric-two-spacer",
        ),
        pytest.param(
            [Layer("plate", 0.5, 4000.0), Layer("plate", 0.125, -4000.0)],
            id="single-shear",
        ),
    ],
)
def test_diagrams_close_at_the_nut(layers):
    """V(L) = 0 and M(L) = 0 for any balanced stack. This is THE check."""
    a = analyse(layers)
    assert a.balanced
    nut = a.stations[-1]
    assert nut.x == pytest.approx(a.L)
    assert nut.V == pytest.approx(0.0, abs=1e-9)
    assert nut.M == pytest.approx(0.0, abs=1e-9)


def test_symmetric_double_shear_closed_form():
    """M_res = 0 by symmetry, so R_0 = R_L = 0 and the peak has a closed form:
    M_max = P·(2·t_outer + t_inner)/8 at mid-grip."""
    t_o, t_i, P = 0.250, 0.500, 2000.0
    a = analyse(symmetric_double_shear(t_o, t_i, P))

    assert a.moment_residual == pytest.approx(0.0)
    assert a.R0 == pytest.approx(0.0)
    assert a.RL == pytest.approx(0.0)
    assert a.M_max.M == pytest.approx(P * (2 * t_o + t_i) / 8.0)
    assert a.M_max.x == pytest.approx(a.L / 2.0)


# ══════════════════════════════════════════════════════════════════════════
# Handoff §4.1 — force closure gates the margins
# ══════════════════════════════════════════════════════════════════════════
def test_imbalance_is_detected_and_suppresses_margins():
    layers = [Layer("plate", 0.25, 1000.0), Layer("plate", 0.25, -900.0)]
    a = analyse(layers)

    assert not a.balanced
    assert a.sum_P == pytest.approx(100.0)
    # the diagram genuinely does not close — that is why margins are void
    assert abs(a.stations[-1].V) > 1.0

    m = margins(a, GOLDEN_SECTION, GOLDEN_ALLOWABLES)
    assert not m.valid


def test_imbalance_tolerance_is_a_pure_ratio():
    """|ΣP| > IMBALANCE_TOL · max|P_i| is unbalanced; scaling the whole
    problem must not change the verdict (the old JS test mixed an absolute
    0.5 lbf floor with a scaled term and flipped under scaling)."""
    for scale in (1.0, 1e-3, 1e4):
        P = 1000.0 * scale
        just_inside = P * IMBALANCE_TOL * 0.9
        just_outside = P * IMBALANCE_TOL * 1.1

        ok = analyse([Layer("plate", 0.25, P),
                      Layer("plate", 0.25, -(P - just_inside))])
        bad = analyse([Layer("plate", 0.25, P),
                       Layer("plate", 0.25, -(P - just_outside))])
        assert ok.balanced, scale
        assert not bad.balanced, scale


def test_all_zero_loads_counts_as_balanced():
    """No load at all is trivially in equilibrium — it must not trip the gate
    (max|P_i| = 0 makes the tolerance zero)."""
    a = analyse([Layer("plate", 0.25, 0.0), Layer("plate", 0.25, 0.0)])
    assert a.balanced
    assert margins(a, GOLDEN_SECTION, GOLDEN_ALLOWABLES).valid


# ══════════════════════════════════════════════════════════════════════════
# Combined interaction — scanned, not paired
# ══════════════════════════════════════════════════════════════════════════
def test_combined_scans_stations_rather_than_pairing_maxima():
    """Pairing M_max with V_max would be strictly more conservative. The
    scanned result must be no worse than the paired one, and on the golden
    case strictly better, since the two maxima are at different stations."""
    a = analyse(default_stack())
    s, al = GOLDEN_SECTION, GOLDEN_ALLOWABLES
    m = margins(a, s, al)

    R_b_paired = abs(a.M_max.M) / (s.Z * al.Fb * 1000.0)
    R_s_paired = abs(a.V_max) / (s.A * al.Fsu * 1000.0)
    ms_paired = 1.0 / math.sqrt(R_b_paired**2 + R_s_paired**2) - 1.0

    assert m.MS_combined > ms_paired
    # and it is never optimistic relative to the pure bending margin
    assert m.MS_combined <= m.MS_bending + 1e-9


def test_fitting_factor_scales_the_applied_stress():
    a = analyse(default_stack())
    base = margins(a, GOLDEN_SECTION, GOLDEN_ALLOWABLES)
    ff = margins(a, GOLDEN_SECTION,
                 Allowables(Ftu=160.0, Fsu=95.0, k_bending=1.5,
                            fitting_factor=1.5))
    assert (1 + ff.MS_bending) == pytest.approx((1 + base.MS_bending) / 1.5)
    assert (1 + ff.MS_combined) == pytest.approx((1 + base.MS_combined) / 1.5)


# ══════════════════════════════════════════════════════════════════════════
# Model behaviour
# ══════════════════════════════════════════════════════════════════════════
def test_gap_carries_shear_but_no_bearing():
    """A spacer adds moment arm at no benefit: shear is flat across it and the
    peak moment rises when it is inserted."""
    without = analyse(symmetric_double_shear())
    with_gap = analyse([
        Layer("plate", 0.250, 1000.0),
        Layer("gap", 0.060, 0.0),
        Layer("plate", 0.500, -2000.0),
        Layer("plate", 0.250, 1000.0),
    ])
    assert abs(with_gap.M_max.M) > abs(without.M_max.M)

    gap_seg = next(s for s in with_gap.segments if s.kind == "gap")
    assert gap_seg.w == 0.0
    inside = [p.V for p in with_gap.stations if gap_seg.x0 < p.x < gap_seg.x1]
    assert max(inside) - min(inside) == pytest.approx(0.0, abs=1e-9)


def test_gap_load_is_ignored():
    """A stale number left on a row switched from plate to gap must not leak
    into the statics."""
    clean = analyse([Layer("plate", 0.25, 500.0), Layer("gap", 0.1, 0.0),
                     Layer("plate", 0.25, -500.0)])
    dirty = analyse([Layer("plate", 0.25, 500.0), Layer("gap", 0.1, 9999.0),
                     Layer("plate", 0.25, -500.0)])
    assert dirty.sum_P == clean.sum_P
    assert dirty.M_max.M == pytest.approx(clean.M_max.M)


def test_close_moment_option_off_leaves_the_diagram_open():
    a = analyse(default_stack(), close_moment=False)
    assert a.R0 == 0.0 and a.RL == 0.0
    assert abs(a.stations[-1].M) > 1.0        # M(L) = -M_res, unreacted


def test_negative_thickness_clamps_rather_than_reversing_the_axis():
    a = analyse([Layer("plate", 0.25, 500.0), Layer("plate", -0.4, 0.0),
                 Layer("plate", 0.25, -500.0)])
    assert a.L == pytest.approx(0.50)
    assert all(s.x1 >= s.x0 for s in a.segments)


def test_empty_and_zero_length_stacks_do_not_raise():
    for layers in ([], [Layer("plate", 0.0, 100.0)]):
        a = analyse(layers)
        assert a.L == pytest.approx(0.0)
        assert a.M_max.M == pytest.approx(0.0)
        # margins must still be constructible — the UI calls this every rerun
        margins(a, GOLDEN_SECTION, GOLDEN_ALLOWABLES)


# ══════════════════════════════════════════════════════════════════════════
# Screening checks
# ══════════════════════════════════════════════════════════════════════════
def test_screening_flags_imbalance_gap_and_section_diameter():
    a = analyse([Layer("plate", 0.25, 1000.0), Layer("gap", 0.5, 0.0),
                 Layer("plate", 0.25, -800.0)])
    # section diameter deliberately not reduced below the shank
    checks = screening_checks(a, BoltSection(d_shank=0.25, d_section=0.25))
    text = " ".join(c.text for c in checks)

    assert not checks[0].ok and "sum to" in checks[0].text
    assert "gap adds arm" in text
    assert "not smaller than the shank" in text
    assert "Grip/D" in text


def test_screening_passes_a_clean_case():
    a = analyse(default_stack())
    checks = screening_checks(a, GOLDEN_SECTION)
    assert checks[0].ok                      # force closure
    assert "end pair" in checks[1].text      # residual moment closed
    # the couple is a bookkeeping device; the check must not claim the
    # head bears sideways, which it cannot (see kernel module docstring)
    assert "clamp pressure" in checks[1].text


# ══════════════════════════════════════════════════════════════════════════
# Shear basis — what Fsu is stated on
# ══════════════════════════════════════════════════════════════════════════
def test_shear_peak_factor_defaults_to_the_fastener_basis():
    """1.0 by default: this is a bolt tool, and MMPDS Table 8.1.4 tabulates
    fastener shear on the shank area, so V/A is already the matching basis."""
    assert Allowables(Ftu=160.0, Fsu=95.0).shear_peak_factor == 1.0


def test_the_peak_factor_scales_the_shear_stress_and_the_margin():
    a = analyse(default_stack())
    base = margins(a, GOLDEN_SECTION, Allowables(Ftu=160.0, Fsu=95.0))
    peak = margins(a, GOLDEN_SECTION,
                   Allowables(Ftu=160.0, Fsu=95.0, shear_peak_factor=4 / 3))
    assert peak.f_s == pytest.approx(base.f_s * 4 / 3)
    assert peak.MS_shear < base.MS_shear
    assert peak.MS_bending == pytest.approx(base.MS_bending)   # bending untouched


def test_the_peak_factor_reaches_the_interaction_scan_too():
    """A factor applied to the standalone shear check but not to the scan
    would let the two disagree about the same station."""
    short = [Layer("plate", 0.06, 4000.0), Layer("plate", 0.06, -4000.0)]
    a = analyse(short)
    base = margins(a, GOLDEN_SECTION, Allowables(Ftu=160.0, Fsu=95.0))
    peak = margins(a, GOLDEN_SECTION,
                   Allowables(Ftu=160.0, Fsu=95.0, shear_peak_factor=4 / 3))
    assert peak.R_s > base.R_s
    assert peak.MS_combined < base.MS_combined
