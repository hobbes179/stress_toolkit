"""
tests/bolt_bending/test_refined.py

Gates for the refined bearing distribution (`library/bolt_bending/refined.py`).

The governing gate is the **rigid-bolt limit**: as the foundation goes soft
relative to the bolt, the refined model must reproduce the uniform-bearing
baseline exactly. That is what makes the refinement trustworthy — it provably
degenerates to the model already in service, so it can only ever be a
correction to it, never a different answer.

The standing arithmetic check from the baseline still applies: refined
diagrams must close at the nut.
"""

from __future__ import annotations

import math

import pytest

from library.bolt_bending.kernel import (
    Allowables,
    BoltSection,
    Layer,
    default_stack,
    margins,
    symmetric_double_shear,
)
from library.bolt_bending.refined import (
    LOAD_ERROR_WARN,
    RESIDUAL_WARN,
    STRIPS_PER_PLATE,
    huth_compliance,
    refined_analysis,
    tate_rosenfeld_k,
)

SECTION = BoltSection(d_shank=0.375, d_section=0.315)
ALLOW = Allowables(Ftu=160.0, Fsu=95.0, k_bending=1.5, fitting_factor=1.0)

BOLT = dict(d_bolt=0.375, E_bolt_msi=29.0)


def run(layers=None, E_plate_msi=10.7, **kw):
    return refined_analysis(
        layers if layers is not None else default_stack(),
        E_plate_msi=E_plate_msi, **BOLT, **kw)


# ══════════════════════════════════════════════════════════════════════════
# The governing gate
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("E_plate_msi", [1e-3, 1e-2])
def test_rigid_bolt_limit_reproduces_the_uniform_baseline(E_plate_msi):
    """Pinned at both ends and straight => w == 0 => q = k*d_i, uniform over
    each plate. Deep in the soft-foundation limit the refined answer must
    collapse onto the baseline."""
    r = run(E_plate_msi=E_plate_msi)
    assert r.moment_ratio == pytest.approx(1.0, abs=1e-3)
    assert not r.refinement_is_material
    assert r.refined.M_max.M == pytest.approx(r.baseline.M_max.M, rel=1e-3)


def test_the_baseline_is_approached_smoothly_not_just_hit_at_one_point():
    """The limit is a limit: the departure from uniform bearing must shrink
    monotonically as the foundation softens, with no step or sign change.

    Testing a single soft-k point would be too weak — at E_plate = 0.1 Msi
    the departure is already 0.2%, which is correct physics (beta*t ~ 0.5,
    real bending) and not a limit at all.
    """
    departures = [abs(1.0 - run(E_plate_msi=E).moment_ratio)
                  for E in (1e-3, 1e-2, 1e-1, 1.0, 10.7)]
    assert departures == sorted(departures), departures
    assert departures[0] < 1e-4          # deep in the limit
    assert departures[-1] > 0.1          # and materially different in service


def test_refined_diagrams_close_at_the_nut():
    """The baseline's standing arithmetic check, applied to the strip model."""
    for E_p in (10.7, 16.0, 29.0):
        r = run(E_plate_msi=E_p)
        nut = r.refined.stations[-1]
        assert nut.V == pytest.approx(0.0, abs=1e-6), E_p
        assert nut.M == pytest.approx(0.0, abs=1e-6), E_p
        assert r.refined.balanced


def test_strips_reproduce_the_entered_load_split():
    """The load split stays an INPUT. Each plate's strips must sum to exactly
    the load the engineer entered — the refinement only moves it around."""
    layers = default_stack()
    r = run(layers)

    entered = [ly.load for ly in layers if ly.kind == "plate"]

    # Each plate becomes STRIPS_PER_PLATE contiguous strips; a gap stays one
    # layer. Walk the strip list in step with the original layers and total
    # each plate's run.
    got, i = [], 0
    for ly in layers:
        if ly.kind != "plate" or ly.thickness <= 0:
            i += 1
            continue
        got.append(sum(s.load for s in r.strips[i:i + STRIPS_PER_PLATE]))
        i += STRIPS_PER_PLATE

    assert len(got) == len(entered)
    for want, have in zip(entered, got):
        assert have == pytest.approx(want, rel=1e-9), (entered, got)

    assert r.refined.sum_P == pytest.approx(r.baseline.sum_P, abs=1e-9)


def test_total_thickness_is_preserved():
    layers = default_stack()
    r = run(layers)
    assert sum(s.thickness for s in r.strips) == pytest.approx(
        sum(ly.thickness for ly in layers))
    assert r.refined.L == pytest.approx(r.baseline.L)


# ══════════════════════════════════════════════════════════════════════════
# Direction and magnitude
# ══════════════════════════════════════════════════════════════════════════
def test_refinement_is_never_more_conservative_than_the_baseline():
    """Letting the bolt bend shortens the effective arm, so the refined peak
    moment must not exceed the uniform-bearing one. If it ever does, the
    formulation is wrong — uniform bearing is the conservative bound."""
    for E_p in (1.0, 5.0, 10.7, 16.0, 29.0):
        r = run(E_plate_msi=E_p)
        assert abs(r.refined.M_max.M) <= abs(r.baseline.M_max.M) * 1.001, E_p


def test_stiffer_plates_recover_more_conservatism():
    """Monotonic: a stiffer foundation makes the bolt tilt more within the
    hole, concentrating bearing and shortening the arm further."""
    recovered = [run(E_plate_msi=E).conservatism_recovered
                 for E in (1.0, 5.0, 10.7, 16.0, 29.0)]
    assert recovered == sorted(recovered), recovered
    assert recovered[-1] > recovered[0]


def test_the_margin_improves_and_stays_finite():
    r = run(E_plate_msi=10.7)
    mb = margins(r.baseline, SECTION, ALLOW)
    mr = margins(r.refined, SECTION, ALLOW)
    assert mr.MS_bending > mb.MS_bending
    assert math.isfinite(mr.MS_bending)
    assert mr.valid


def test_beta_t_is_the_screening_number():
    """beta*t below ~1 means bearing is already near-uniform. It must scale
    as k^(1/4) and with plate thickness."""
    r = run(E_plate_msi=10.7)
    thick = {p.t: p for p in r.plates}
    assert thick[0.500].beta_t == pytest.approx(2 * thick[0.250].beta_t)

    soft, stiff = run(E_plate_msi=1.0), run(E_plate_msi=16.0)
    assert stiff.max_beta_t > soft.max_beta_t
    # beta ~ k^(1/4): a 16x stiffness ratio is a 2x beta ratio
    assert stiff.max_beta_t / soft.max_beta_t == pytest.approx(2.0, rel=0.02)


# ══════════════════════════════════════════════════════════════════════════
# Per-plate foundation modulus — a mixed stack
# ══════════════════════════════════════════════════════════════════════════
def test_a_uniform_sequence_matches_the_scalar_exactly():
    """The per-layer path must be the same computation as the scalar one when
    every plate names the same material. If these ever diverge, one of the two
    assembly paths is wrong."""
    layers = default_stack()
    scalar = run(layers, E_plate_msi=10.7)
    seq = run(layers, E_plate_msi=[10.7] * len(layers))
    assert seq.refined.M_max.M == pytest.approx(scalar.refined.M_max.M, rel=1e-12)
    assert not seq.mixed_stack


def test_each_plate_gets_its_own_k_and_its_own_beta():
    """A steel doubler and an aluminium skin are not one averaged bed."""
    layers = default_stack()
    # plate, gap, plate, plate — steel in the middle
    r = run(layers, E_plate_msi=[10.7, None, 29.0, 10.7])
    assert r.mixed_stack
    ks = [p.k for p in r.plates]
    assert ks[0] == pytest.approx(10.7e6)
    assert ks[1] == pytest.approx(29.0e6)
    assert ks[2] == pytest.approx(10.7e6)
    # beta ~ k^(1/4): the steel plate is stiffer, so it peaks harder per inch
    assert r.plates[1].beta > r.plates[0].beta
    assert r.plates[0].beta == pytest.approx(r.plates[2].beta)


def test_a_mixed_stack_lands_between_its_two_uniform_bounds():
    """Sanity: mixing 2024-T3 and steel must give a peak moment between the
    all-aluminium and all-steel answers. A per-plate assembly bug would
    typically push it outside that bracket."""
    layers = default_stack()
    soft = run(layers, E_plate_msi=10.7).refined.M_max.M
    stiff = run(layers, E_plate_msi=29.0).refined.M_max.M
    mixed = run(layers, E_plate_msi=[10.7, None, 29.0, 10.7]).refined.M_max.M
    lo, hi = sorted((abs(soft), abs(stiff)))
    assert lo <= abs(mixed) <= hi, (soft, mixed, stiff)


def test_the_headline_basis_is_the_governing_plate_not_an_average():
    """A mixed stack must never advertise a modulus no plate actually has."""
    r = run(default_stack(), E_plate_msi=[10.7, None, 29.0, 10.7])
    assert r.basis.k_msi in (10.7, 29.0)
    governing = max(r.plates, key=lambda p: p.beta_t)
    assert r.basis.k == pytest.approx(governing.k)


def test_a_short_or_gappy_material_list_degrades_instead_of_zeroing():
    """A half-filled list must fall back to the first stated modulus, not
    leave a plate on a zero-stiffness bed (which would be a singular solve)."""
    layers = default_stack()
    r = run(layers, E_plate_msi=[16.0])          # only the first named
    assert all(p.k == pytest.approx(16.0e6) for p in r.plates)
    assert not r.mixed_stack

    r2 = run(layers, E_plate_msi=[None, None, None, None])
    assert all(p.k > 0 for p in r2.plates)
    assert math.isfinite(r2.refined.M_max.M)


def test_plate_material_names_travel_into_the_result():
    """A less-conservative k must never appear without saying what it came
    from — the name is part of the justification, not decoration."""
    r = refined_analysis(
        default_stack(), E_plate_msi=[10.7, None, 29.0, 10.7],
        plate_materials=["2024-T3", "", "4340 Steel", "2024-T3"], **BOLT)
    assert [p.material for p in r.plates] == ["2024-T3", "4340 Steel", "2024-T3"]


# ══════════════════════════════════════════════════════════════════════════
# Numerics
# ══════════════════════════════════════════════════════════════════════════
# The fine-mesh references are the expensive part of this file; compute each
# once for the whole module rather than per parametrised case.
@pytest.fixture(scope="module")
def strip_reference():
    return run(strips_per_plate=96).refined.M_max.M


@pytest.fixture(scope="module")
def mesh_reference():
    return run(elements_per_inch=1600).refined.M_max.M


@pytest.mark.parametrize("strips", [12, 24, 48])
def test_converged_in_strips(strips, strip_reference):
    got = run(strips_per_plate=strips).refined.M_max.M
    assert got == pytest.approx(strip_reference, rel=0.01), strips


@pytest.mark.parametrize("epi", [100, 200, 400, 800])
def test_converged_and_stable_in_mesh(epi, mesh_reference):
    """An earlier draft left the system singular and used a least-squares
    minimum-norm solve; it drifted with mesh (239.4 at coarse, 235.1 at fine)
    while looking perfectly plausible. Pinning the end deflections made it
    well posed. This gate is what would have caught that."""
    got = run(elements_per_inch=epi).refined.M_max.M
    assert got == pytest.approx(mesh_reference, rel=1e-3), epi


def test_the_solve_actually_satisfies_what_it_was_given():
    """Quality is measured on the solve, not on the matrix.

    A `np.linalg.cond` gate used to sit here. It was insensitive to k (E swept
    over 10^6 did not move it) and scaled as h^-4 and d^4 instead, so it called
    an ordinary 1 in bolt untrustworthy and got *worse* as the mesh improved,
    while the answers agreed to six figures. These two measure the solve.
    """
    r = run()
    assert r.residual < RESIDUAL_WARN
    assert r.load_error < LOAD_ERROR_WARN
    assert r.trustworthy


@pytest.mark.parametrize("epi", [100, 200, 800, 1600])
def test_quality_does_not_degrade_as_the_mesh_improves(epi):
    """The regression the old condition-number gate had exactly backwards."""
    r = run(elements_per_inch=epi)
    assert r.trustworthy, (epi, r.residual, r.load_error)


@pytest.mark.parametrize("d_bolt", [0.164, 0.375, 1.0])
def test_quality_holds_across_ordinary_bolt_diameters(d_bolt):
    """The old gate failed a 1 in bolt at the default mesh."""
    r = refined_analysis(default_stack(), d_bolt=d_bolt, E_bolt_msi=29.0,
                         E_plate_msi=10.7)
    assert r.trustworthy, (d_bolt, r.residual, r.load_error)


def test_load_error_is_a_strip_resolution_measure():
    """It must fall as the strips are refined — that is what identifies it as
    quadrature error rather than a bad solve, and it is why the threshold sits
    where it does. If this ever stops scaling, the gate is measuring something
    else and needs re-deriving."""
    errs = [run(strips_per_plate=n).load_error for n in (12, 24, 48, 96)]
    assert errs == sorted(errs, reverse=True), errs
    assert errs[0] / errs[-1] > 10          # genuinely converging, not noise
    assert all(e < LOAD_ERROR_WARN for e in errs)


# ══════════════════════════════════════════════════════════════════════════
# The documented basis and its cross-check
# ══════════════════════════════════════════════════════════════════════════
def test_tate_rosenfeld_gives_k_equal_to_the_plate_modulus():
    """k = E_plate falls out of the bearing compliance d = P/(E*t) combined
    with the Winkler bed P = k*d*t. Derived, not fitted."""
    basis = tate_rosenfeld_k(10.7)
    assert basis.k == pytest.approx(10.7e6)
    assert "Tate & Rosenfeld" in basis.citation
    assert "NACA TN 1051" in basis.citation


def test_the_basis_travels_with_the_result():
    """A less-conservative option must never appear without its justification."""
    r = run()
    assert r.basis.citation
    assert r.basis.note
    assert "double-count" in r.basis.note


def test_huth_cross_check_is_independent_and_in_the_right_ballpark():
    """Huth is a lumped empirical compliance from a different source; it is a
    sanity check on the derived k, never an input to it. The two routinely
    disagree by up to ~2x in the literature, so the gate is loose on purpose —
    it is there to catch an order-of-magnitude blunder, not to force
    agreement."""
    for E_p in (10.7, 16.0, 29.0):
        r = run(E_plate_msi=E_p)
        assert r.cross_check_ratio is not None
        assert 0.3 < r.cross_check_ratio < 3.0, (E_p, r.cross_check_ratio)


def test_huth_compliance_scales_sensibly():
    base = huth_compliance(0.375, 0.25, 0.5, 10.7, 10.7, 29.0)
    assert base > 0 and math.isfinite(base)
    # thinner plates are more compliant
    assert huth_compliance(0.375, 0.10, 0.5, 10.7, 10.7, 29.0) > base
    # single shear is more compliant than double
    assert huth_compliance(0.375, 0.25, 0.5, 10.7, 10.7, 29.0,
                           n_shear_planes=1) > base
    assert huth_compliance(0.0, 0.25, 0.5, 10.7, 10.7, 29.0) == math.inf


# ══════════════════════════════════════════════════════════════════════════
# Degenerate input — the UI calls this on every rerun
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "layers",
    [
        pytest.param([], id="empty"),
        pytest.param([Layer("gap", 0.25, 0.0)], id="gap-only"),
        pytest.param([Layer("plate", 0.0, 100.0)], id="zero-thickness"),
        pytest.param([Layer("plate", 0.25, 0.0), Layer("plate", 0.25, 0.0)],
                     id="no-load"),
        pytest.param([Layer("plate", 0.25, 1000.0),
                      Layer("plate", 0.25, -600.0)], id="unbalanced"),
        pytest.param(symmetric_double_shear(), id="symmetric-double-shear"),
    ],
)
def test_degenerate_stacks_do_not_raise(layers):
    r = run(layers)
    assert r.refined is not None
    assert math.isfinite(r.moment_ratio)
    margins(r.refined, SECTION, ALLOW)


def test_unbalanced_stack_stays_unbalanced_after_refinement():
    """The refinement must not paper over a force-closure failure — the strips
    preserve the entered loads, so the gate still fires."""
    r = run([Layer("plate", 0.25, 1000.0), Layer("plate", 0.25, -600.0)])
    assert not r.baseline.balanced
    assert not r.refined.balanced
    assert not margins(r.refined, SECTION, ALLOW).valid
