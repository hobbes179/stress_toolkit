"""
tests/tierod/test_failsafe.py — Session 7 gate: feasibility and scoring.

The product question is not "are the margins positive". It is *"here is what we
need to hold down and here is where we have room — where do we tie it, with the
fewest members, to work and be fail-safe?"* This module is the scoring half of
that: everything needed to judge one candidate layout, so a search can rank
thousands of them.

Four measures, cheapest first:

  * **rank / sigma_min** — is it a mechanism, and how much room is there before
    it becomes one. Non-dimensionalized, always.
  * **rho_j^2** — rod j's share of the self-stress space. `rho_j^2 > 0` is
    EXACTLY the condition that rod j can be lost without creating a mechanism
    (verified against brute-force removal below, on every fixture). One SVD
    replaces N re-solves for the structural half of fail-safe.
  * **lambda** — slenderness, not length. `lambda_crit` is a knee, not a slope:
    below it a rod is on the Johnson branch and essentially not buckling
    limited; above it the allowable dies as 1/lambda^2.
  * **damaged margins** — the strength half, which does need the N re-solves.

The counting bounds are hard and worth stating: `N >= 6*n_free` to avoid a
mechanism, `N >= 6*n_free + 1` to survive any single loss. A statically
determinate layout has `rho^2 = 0` everywhere and no fail-safe path at all,
whatever its margins.
"""
from __future__ import annotations

import numpy as np
import pytest

from apps.tierod import examples
from library.tierod import allowables as al
from library.tierod import failsafe as fs
from library.tierod import sweep as sw
from library.tierod.kernel import assemble

from conftest import (
    make_hexapod,
    make_line_supported,
    make_symmetric8,
    make_two_body,
    make_unit_cage,
)


def _steel(a):
    for rod in a.rods.values():
        rod.Ftu, rod.Fty, rod.A_net = 180.0e3, 160.0e3, 0.08
    return a


# ======================================================================
# rho^2 — the self-stress redundancy, and what it predicts
# ======================================================================


@pytest.mark.parametrize(
    "build", [make_hexapod, make_symmetric8, make_two_body, make_unit_cage]
)
def test_rho2_sums_to_the_degree_of_redundancy(build):
    asm = assemble(build())
    red = fs.self_stress(asm)
    assert red.rho2.shape == (asm.n_rods,)
    assert red.total == pytest.approx(asm.n_rods - asm.rank)
    assert np.all(red.rho2 >= -1e-12) and np.all(red.rho2 <= 1.0 + 1e-12)


@pytest.mark.parametrize(
    "build", [make_hexapod, make_symmetric8, make_two_body, make_unit_cage]
)
def test_rho2_predicts_exactly_which_rods_can_be_lost(build):
    """The claim the whole fail-safe screen rests on, checked against
    brute-force removal: `rho_j^2 > 0` iff losing rod j keeps the rank."""
    a = build()
    asm = assemble(a)
    red = fs.self_stress(asm)
    for j, rod_id in enumerate(asm.rod_ids):
        survivors = [r for r in asm.rod_ids if r != rod_id]
        kept_rank = sw.mask_assembled(asm, survivors).rank == asm.rank
        assert (red.rho2[j] > fs.RHO_TOL) == kept_rank, rod_id


def test_rho2_is_unchanged_by_the_non_dimensionalization():
    """rho^2 lives in the null space of Ghat on the ROD-index side, and row
    scaling cannot move that. If it could, the number would depend on the
    characteristic length, which is a bookkeeping choice."""
    asm = assemble(make_symmetric8())
    raw = fs.self_stress(asm, nondimensional=False)
    scaled = fs.self_stress(asm, nondimensional=True)
    assert np.allclose(raw.rho2, scaled.rho2)


def test_a_determinate_layout_has_no_fail_safe_path():
    asm = assemble(make_hexapod())
    red = fs.self_stress(asm)
    assert np.allclose(red.rho2, 0.0)
    assert red.critical == list(asm.rod_ids), "every rod is critical"
    assert not red.any_redundancy


def test_a_symmetric_redundant_layout_spreads_redundancy_evenly():
    """Even rho^2 is a design target in itself: it means no single rod is
    quietly carrying all the redundant duty."""
    red = fs.self_stress(assemble(make_symmetric8()))
    assert np.allclose(red.rho2, 0.25)
    assert red.critical == []
    assert red.spread == pytest.approx(0.0)


def test_the_demo_is_determinate_and_therefore_never_fail_safe():
    """12 rods against 12 DOF. No load case and no rod section can fix that —
    it is a counting result, and the tool should say so before anyone sizes
    anything."""
    a = examples.demo_assembly()
    asm = assemble(a)
    assert asm.n_rods == asm.n_dof == 12
    assert fs.min_rods_for_single_failure(asm.n_free) == 13
    assert fs.self_stress(asm).critical == list(asm.rod_ids)


def test_the_counting_bounds():
    assert fs.min_rods_for_mechanism_free(1) == 6
    assert fs.min_rods_for_single_failure(1) == 7
    assert fs.min_rods_for_mechanism_free(2) == 12
    assert fs.min_rods_for_single_failure(2) == 13


# ======================================================================
# Layout metrics — the cheap score, no load sweep
# ======================================================================


def test_layout_metrics_report_slenderness_not_just_length():
    a = examples.demo_assembly()
    m = fs.layout_metrics(a)
    assert m.n_rods == 12
    assert m.total_length == pytest.approx(float(assemble(a).lengths.sum()))

    rod = a.rods["rod_a0"]
    rho = np.sqrt(rod.I / rod.A)
    assert m.max_lambda == pytest.approx(m.max_length / rho, rel=1e-6)
    assert m.max_lambda == pytest.approx(240.1, rel=1e-3)
    assert m.lambda_crit == pytest.approx(al.lambda_crit(rod.E, rod.Fcy))


def test_layout_metrics_count_the_rods_past_the_buckling_knee():
    """Below lambda_crit a rod is on the Johnson branch and barely buckling
    limited; above it the allowable falls as 1/lambda^2. The count of Euler
    rods is the headline the objective is trying to drive to zero."""
    a = examples.demo_assembly()
    m = fs.layout_metrics(a)
    assert m.n_euler == 12, "every demo rod is past the knee"
    assert m.euler_fraction == pytest.approx(1.0)


def test_layout_metrics_carry_the_conditioning_and_the_redundancy():
    m = fs.layout_metrics(make_symmetric8())
    assert m.rank == 6 and m.n_dof == 6
    assert not m.is_mechanism
    assert m.sigma_min > 0.0
    assert m.rho2_min == pytest.approx(0.25)
    assert m.survives_single_loss


def test_an_under_constrained_layout_reports_sigma_min_zero():
    """With fewer rods than DOF the screw matrix has only N singular values, so
    `s[-1]` is the smallest of the ones that EXIST — a healthy-looking nonzero
    number for a layout that cannot possibly be restrained. sigma_min has to be
    read at the n_dof-th slot, which does not exist here, hence zero."""
    from conftest import make_five_rod

    a = make_five_rod()
    asm = assemble(a)
    assert asm.n_rods == 5 < asm.n_dof == 6

    s = asm.screw_singular_values()
    assert s.size == 5 and float(s[-1]) > 0.05, "the trap: s[-1] looks fine"
    assert fs.layout_metrics(a).sigma_min == 0.0


def test_a_mechanism_is_reported_not_raised():
    """Scoring a candidate must never throw — a search will generate mechanisms
    constantly and needs them ranked last, not fatal."""
    m = fs.layout_metrics(make_line_supported())
    assert m.is_mechanism
    assert m.sigma_min == pytest.approx(0.0, abs=1e-9)
    assert not m.survives_single_loss


def test_shortening_the_demo_improves_slenderness_and_conditioning_together():
    """The finding that motivated this whole reframing: the shipped layout is
    DOMINATED. Moving the same rods within the same declared regions cuts max
    lambda roughly in half and doubles sigma_min at the same time."""
    shipped = fs.layout_metrics(examples.demo_assembly())
    short = fs.layout_metrics(_reposition(examples.demo_assembly(), 10.0, 5.0, 9.0))

    assert short.max_lambda < 0.6 * shipped.max_lambda
    assert short.sigma_min > 1.9 * shipped.sigma_min
    assert not short.is_mechanism


def test_pushing_every_attachment_to_one_height_collapses_the_layout():
    """The cliff on the other side. Short is good until the moment arms vanish
    — which is why sigma_floor has to be a hard constraint, not a diagnostic."""
    flat = fs.layout_metrics(_reposition(examples.demo_assembly(), 4.5, 4.5, 7.0))
    assert flat.max_lambda < 70.0, "it is indeed short"
    assert flat.is_mechanism and flat.rank == 6


def _reposition(a, z_hi, z_lo, r_foot):
    for tag in ("a", "b"):
        for k in range(6):
            rod = a.rods[f"rod_{tag}{k}"]
            th = 2.0 * np.pi * k / 6.0
            rod.end_a.q = np.array([th, z_hi if k % 2 == 0 else z_lo])
            rod.end_b.q = np.array([r_foot, th + 0.5])
    return a


# ======================================================================
# Failure states — the strength half
# ======================================================================


def test_one_failure_state_per_rod_by_default():
    a = _steel(make_symmetric8())
    report = fs.check_failsafe(a)
    assert [s.removed for s in report.states] == list(a.rods)
    assert all(s.ok for s in report.states)


def test_removing_a_critical_rod_is_reported_as_a_mechanism_not_a_margin():
    a = _steel(make_hexapod())
    report = fs.check_failsafe(a)
    assert all(not s.ok for s in report.states)
    assert all(s.worst_margin is None for s in report.states)
    assert not report.ok
    assert "determinate" in report.summary.lower() or report.n_critical == 6


def test_losing_a_rod_makes_the_survivors_work_harder():
    """Like for like: same factors both sides, so the only thing moving is the
    load redistributing onto fewer rods."""
    a = _steel(make_symmetric8())
    same = al.SafetyFactors(ultimate=1.5, yield_=1.0)
    report = fs.check_failsafe(
        a, fs.Criteria(intact_factors=same, damaged_factors=same)
    )
    intact = report.intact_worst_margin
    assert all(s.worst_margin <= intact + 1e-9 for s in report.states)
    assert report.damaged_worst_margin == min(s.worst_margin for s in report.states)


def test_the_default_damaged_check_is_deliberately_the_more_lenient_one():
    """Fail-safe is usually stated as 'survive LIMIT load with any one member
    gone', so the damaged case drops the 1.5.

    Note what this does NOT let us assert: whether the damaged margin comes out
    above or below the intact one. Two effects fight — load redistributing onto
    fewer rods (worse) against the relaxed factor (better) — and which wins is
    a property of the layout, not a rule. Asserting a direction here would be
    encoding one fixture's arithmetic as physics.
    """
    a = _steel(make_symmetric8())
    report = fs.check_failsafe(a)
    assert report.criteria.intact_factors.ultimate == 1.5
    assert report.criteria.damaged_factors.ultimate == 1.0

    strict = fs.check_failsafe(
        a, fs.Criteria(damaged_factors=al.SafetyFactors(ultimate=1.5))
    )
    assert strict.damaged_worst_margin < report.damaged_worst_margin


def test_the_damaged_case_uses_its_own_load_factor_and_safety_factor():
    """'Survive at 1x if a rod is lost' is a different check from the intact
    ultimate case, and both numbers are user inputs."""
    a = _steel(make_symmetric8())
    gentle = fs.check_failsafe(a, fs.Criteria(damaged_load_factor=1.0))
    harsh = fs.check_failsafe(a, fs.Criteria(damaged_load_factor=2.0))
    assert harsh.damaged_worst_margin < gentle.damaged_worst_margin


def test_criteria_defaults_are_inputs_not_constants():
    c = fs.Criteria()
    assert c.ms_required == 0.0
    assert c.ms_required_damaged == 0.0
    assert c.damaged_load_factor == 1.0
    assert c.intact_factors.ultimate == 1.5
    assert c.damaged_factors.ultimate == 1.0, "damaged case is a limit-load check"
    assert fs.Criteria(sigma_floor=0.2).sigma_floor == 0.2


def test_a_named_subset_can_be_checked_instead_of_every_singleton():
    """Phase 3 wants two-rod losses and named groups; the machinery must not
    assume singletons."""
    a = _steel(make_symmetric8())
    report = fs.check_failsafe(a, subsets=[("leg0",), ("leg0", "brace0")])
    assert [s.removed for s in report.states] == ["leg0", "leg0+brace0"]
    assert len(report.states) == 2


# ======================================================================
# Feasibility — the gate a layout search filters on
# ======================================================================


def test_a_mechanism_is_infeasible_whatever_its_margins():
    verdict = fs.feasible(fs.layout_metrics(make_line_supported()), fs.Criteria())
    assert not verdict.ok
    # matched on the prefix, not a substring: the conditioning reason used to
    # contain the word "mechanism" too, which made this assertion pass even
    # with the rank check deleted
    assert any(r.startswith("mechanism:") for r in verdict.reasons)


def test_the_rank_and_conditioning_reasons_are_distinguishable():
    """Two different failures that a length-hungry search hits constantly, so
    the messages must not be confusable with each other."""
    rank_fail = fs.feasible(fs.layout_metrics(make_line_supported()), fs.Criteria())
    fragile = fs.feasible(
        fs.layout_metrics(_reposition(examples.demo_assembly(), 5.0, 4.5, 7.0)),
        fs.Criteria(sigma_floor=0.10, require_single_failure=False),
    )
    assert any(r.startswith("mechanism:") for r in rank_fail.reasons)
    assert not any(r.startswith("mechanism:") for r in fragile.reasons)
    assert any(r.startswith("conditioning:") for r in fragile.reasons)


def test_a_determinate_layout_fails_the_fail_safe_requirement():
    verdict = fs.feasible(fs.layout_metrics(make_hexapod()), fs.Criteria())
    assert not verdict.ok
    assert any("single" in r.lower() or "critical" in r.lower() for r in verdict.reasons)


def test_the_sigma_floor_rejects_a_barely_stable_layout():
    """The all-short-but-not-quite-flat variant is technically full rank and
    genuinely fragile — sigma_min 0.04. A floor is what keeps a length-hungry
    search off that cliff."""
    m = fs.layout_metrics(_reposition(examples.demo_assembly(), 5.0, 4.5, 7.0))
    assert not m.is_mechanism
    assert fs.feasible(m, fs.Criteria(sigma_floor=0.10)).ok is False
    assert any(
        "conditioning" in r.lower() or "sigma" in r.lower()
        for r in fs.feasible(m, fs.Criteria(sigma_floor=0.10)).reasons
    )


def test_a_redundant_well_conditioned_layout_passes_the_cheap_screen():
    verdict = fs.feasible(
        fs.layout_metrics(make_symmetric8()),
        fs.Criteria(sigma_floor=0.01, require_single_failure=True),
    )
    assert verdict.ok, verdict.reasons


def test_a_damaged_margin_below_the_requirement_fails_the_report():
    """The strength half of fail-safe, not just the structural half: surviving
    as a structure is not the same as surviving with margin."""
    a = _steel(make_symmetric8())
    lenient = fs.check_failsafe(a, fs.Criteria(sigma_floor=0.01))
    assert lenient.ok
    worst = lenient.damaged_worst_margin

    strict = fs.check_failsafe(
        a, fs.Criteria(sigma_floor=0.01, ms_required_damaged=worst + 1.0)
    )
    assert not strict.ok
    assert strict.damaged_worst_margin == pytest.approx(worst)


def test_an_intact_margin_below_the_requirement_also_fails_the_report():
    a = _steel(make_symmetric8())
    report = fs.check_failsafe(a, fs.Criteria(sigma_floor=0.01))
    tight = fs.check_failsafe(
        a,
        fs.Criteria(sigma_floor=0.01,
                    ms_required=report.intact_worst_margin + 1.0),
    )
    assert not tight.ok


def test_the_screen_can_be_relaxed_for_a_nominal_only_study():
    m = fs.layout_metrics(make_hexapod())
    assert fs.feasible(m, fs.Criteria(require_single_failure=False)).ok


def test_reasons_are_specific_enough_to_act_on():
    verdict = fs.feasible(fs.layout_metrics(make_hexapod()), fs.Criteria())
    joined = " ".join(verdict.reasons)
    assert "6" in joined and "7" in joined, "say how many rods are needed"


# ======================================================================
# The objective the search minimizes
# ======================================================================


def test_the_objective_ranks_slenderness_first_then_length_then_count():
    """The demo is determinate, so a fail-safe screen rejects both variants
    before slenderness is even consulted — this is a nominal-only comparison."""
    nominal = fs.Criteria(require_single_failure=False)
    a = examples.demo_assembly()
    shipped = fs.objective(fs.layout_metrics(a), nominal)
    short = fs.objective(fs.layout_metrics(_reposition(a, 10.0, 5.0, 9.0)), nominal)

    assert short < shipped, "a shorter, better-conditioned layout must score better"
    assert short[0] < 0.6 * shipped[0], "max lambda leads the ranking"


def test_the_objective_refuses_to_rank_a_layout_it_would_reject():
    """The demo scores `inf` under the default (fail-safe) criteria however
    short its rods are — feasibility is a gate, not a term."""
    a = examples.demo_assembly()
    assert fs.objective(fs.layout_metrics(a))[0] == float("inf")
    assert fs.objective(fs.layout_metrics(_reposition(a, 10.0, 5.0, 9.0)))[0] == float(
        "inf"
    )


def test_the_objective_is_a_tuple_so_ties_break_deterministically():
    m = fs.layout_metrics(make_symmetric8())
    obj = fs.objective(m)
    assert isinstance(obj, tuple) and len(obj) == 3
    assert obj[0] == pytest.approx(m.max_lambda)
    assert obj[1] == pytest.approx(m.total_length)
    assert obj[2] == m.n_rods


def test_an_infeasible_layout_never_outranks_a_feasible_one():
    good = fs.layout_metrics(make_symmetric8())
    bad = fs.layout_metrics(make_line_supported())
    assert fs.objective(bad) > fs.objective(good)


def test_an_unsolvable_failure_state_fails_the_report():
    """Reachable only for multi-rod losses: if the cheap screen passes with
    single-failure required, no SINGLETON removal can be singular by
    construction (that is what rho^2 > 0 means). symmetric8 has redundancy 2,
    and 12 of its 28 two-rod losses do go singular — that is the case where a
    state is unsolvable while the intact layout screens clean."""
    a = _steel(make_symmetric8())
    criteria = fs.Criteria(sigma_floor=0.01)

    survivable = fs.check_failsafe(a, criteria, subsets=[("leg0", "brace1")])
    assert all(s.ok for s in survivable.states)
    assert survivable.ok

    collapses = fs.check_failsafe(a, criteria, subsets=[("leg0", "leg1")])
    assert [s.ok for s in collapses.states] == [False]
    assert collapses.states[0].worst_margin is None
    assert not collapses.ok, "an unsolvable damage state cannot be a pass"

    # And it must not be MASKED by the healthy states around it: a collapsed
    # state contributes no margin at all, so the worst-margin summary is taken
    # over the survivors and reads perfectly fine on its own.
    mixed = fs.check_failsafe(
        a, criteria, subsets=[("leg0", "brace1"), ("leg0", "leg1")]
    )
    assert [s.ok for s in mixed.states] == [True, False]
    assert mixed.damaged_worst_margin > 0.0, "the survivor's margin looks healthy"
    assert not mixed.ok, "one collapsed state condemns the layout"


def test_two_rod_damage_sets_are_the_same_machinery_as_singletons():
    """Widening the damage set is a caller change, not a rewrite — the Phase-3
    hook the module was shaped around."""
    import itertools

    a = _steel(make_symmetric8())
    pairs = list(itertools.combinations(list(a.rods), 2))
    report = fs.check_failsafe(a, fs.Criteria(sigma_floor=0.01), subsets=pairs)
    assert len(report.states) == 28
    assert sum(1 for s in report.states if not s.ok) == 12
