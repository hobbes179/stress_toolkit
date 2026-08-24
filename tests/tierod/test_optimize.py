"""
tests/tierod/test_optimize.py — Session 8 gate: the layout search.

This is the part that answers the product question. Everything before it either
scored a layout somebody else wrote or moved one rod at a time; this proposes
layouts.

    seed  ->  refine  ->  score  ->  rank

Findings pinned here, each of which cost a debugging round:

  * **A symmetric seed with no twist is a mechanism.** Both ends land at the
    same angle, every rod lies in a plane through the body axis, and nothing
    reacts rotation about it — sigma_min exactly 0, at every rod count. Twist
    0.5 is degenerate for the same reason. The family must sweep strictly
    between.
  * **Spread fraction 0.5 collapses the alternation**, putting every attachment
    at one height: the coplanar trap, rank 6 of 12 on this geometry.
  * **The penalty must be additive**, in units of `lambda_crit`. Multiplying it
    by the slenderness made the objective 1e3x larger than the thing being
    optimized and stalled L-BFGS-B after one iteration with zero improvement.
  * **Topology raises the counting floor.** `6 n_free + 1 = 13` is global, but
    with only tank->plate pairs offered each tank needs 7 of its own, so 14 is
    the real floor. Allow tank-to-tank rods and 13 becomes reachable.
"""
from __future__ import annotations

import numpy as np
import pytest

from apps.tierod import examples
from library.tierod import failsafe as fs
from library.tierod import optimize as opt
from library.tierod.model import Assembly

CRIT = fs.Criteria(sigma_floor=0.05)
PAIRWISE = [("band_a", "foot_a"), ("band_b", "foot_b")]


@pytest.fixture(scope="module")
def space() -> opt.LayoutSpace:
    """The demo's bodies and regions with no rods — the declared design space,
    which is exactly what a user hands the tool."""
    return opt.space_from(examples.demo_assembly())


@pytest.fixture(scope="module")
def pairwise(space) -> opt.LayoutSpace:
    """Narrowed to tank->plate only: no tank-to-tank rods."""
    return space.restrict(PAIRWISE)


@pytest.fixture(scope="module")
def found(pairwise) -> opt.SearchResult:
    """One real search, shared across the assertions that need it."""
    return opt.search(pairwise, CRIT, n_range=range(13, 15), n_symmetric=3,
                      n_random=1, max_iter=25, rng=np.random.default_rng(0))


# ======================================================================
# The declared design space
# ======================================================================


def test_the_space_keeps_the_bodies_and_regions_but_drops_the_rods(space):
    assert set(space.template.bodies) == {"plate", "tank_a", "tank_b"}
    assert set(space.template.regions) == {"band_a", "band_b", "foot_a", "foot_b"}
    assert space.template.rods == {}


def test_topology_options_are_cross_body_pairs_only(space):
    """A rod between two regions on the SAME body contributes a column of
    exactly zero — the two blocks cancel and `(a-b) x u` vanishes because a-b
    is parallel to u. Not a weak constraint: no constraint."""
    assert ("band_a", "foot_a") in space.topologies
    assert ("band_a", "band_b") in space.topologies, "tank-to-tank is legitimate"
    for ra, rb in space.topologies:
        assert space.template.regions[ra].body_id != space.template.regions[rb].body_id


def test_a_same_body_rod_really_does_nothing():
    """The justification for that exclusion, measured rather than argued."""
    from library.tierod.kernel import assemble
    from library.tierod.model import new_rod

    a = examples.demo_assembly()
    before = assemble(a).rank
    a.add_rod(new_rod(a, id="useless", region_a="band_a", region_b="band_a",
                      q_a=[0.3, 10.0], q_b=[2.0, 20.0]))
    asm = assemble(a)
    assert asm.rank == before
    assert np.allclose(asm.G_hat[:, asm.rod_ids.index("useless")], 0.0)


def test_the_space_can_be_narrowed_by_hand(space):
    """Topology stays a user decision — the search picks within what is
    offered, it does not invent access that does not exist."""
    narrowed = space.restrict([("band_a", "foot_a")])
    assert narrowed.topologies == [("band_a", "foot_a")]
    layout = opt.seed_symmetric(narrowed, 8)
    assert {(r.end_a.region_id, r.end_b.region_id) for r in layout.rods.values()} == {
        ("band_a", "foot_a")
    }


def test_narrowing_to_something_never_offered_is_refused(space):
    with pytest.raises(ValueError):
        space.restrict([("band_a", "band_a")])


# ======================================================================
# Seeding
# ======================================================================


@pytest.mark.parametrize("n", [6, 8, 13])
def test_every_seed_is_a_valid_assembly(space, n):
    rng = np.random.default_rng(0)
    for layout in (opt.seed_symmetric(space, n), opt.seed_random(space, n, rng)):
        layout.validate()
        assert len(layout.rods) == n
        for rod in layout.rods.values():
            for end in (rod.end_a, rod.end_b):
                assert layout.regions[end.region_id].in_bounds(end.q)


def test_seeds_spread_rods_evenly_over_the_offered_topologies(space, pairwise):
    for sp, n in ((pairwise, 14), (space, 14)):
        counts: dict = {}
        for rod in opt.seed_symmetric(sp, n).rods.values():
            key = (rod.end_a.region_id, rod.end_b.region_id)
            counts[key] = counts.get(key, 0) + 1
        assert len(counts) == len(sp.topologies)
        assert max(counts.values()) - min(counts.values()) <= 1
        assert sum(counts.values()) == n


def test_the_symmetric_seed_spreads_along_the_regions_longest_direction(pairwise):
    """Which parameter is 'around' differs by primitive — an Annulus indexes
    (r, theta) and a CylindricalBand indexes (theta, z). The seeder picks the
    axis of greatest ARC LENGTH rather than branching on the type, so a new
    primitive needs no code here. Straight-line lo-to-hi distance would also
    fail: a full revolution returns to where it started."""
    assert opt.spread_axis(pairwise.template.regions["band_a"]) == 0     # theta
    assert opt.spread_axis(pairwise.template.regions["foot_a"]) == 1     # theta

    layout = opt.seed_symmetric(pairwise, 12)
    thetas = sorted(
        r.end_a.q[0] for r in layout.rods.values() if r.end_a.region_id == "band_a"
    )
    gaps = np.diff(thetas)
    assert np.allclose(gaps, gaps[0], rtol=1e-6)


def test_the_symmetric_seed_alternates_the_other_parameter(pairwise):
    """Attachments all at one height is the coplanar trap — rank 6 of 12 on
    this very geometry. The seeder must not walk into it by construction."""
    layout = opt.seed_symmetric(pairwise, 12)
    z = {r.end_a.q[1] for r in layout.rods.values() if r.end_a.region_id == "band_a"}
    assert len(z) == 2, "two heights, not one"


@pytest.mark.parametrize("twist", [0.0, 0.5])
def test_a_symmetric_seed_without_twist_is_a_mechanism(pairwise, twist):
    """The failure that made every symmetric seed useless until it was found.
    With no twist both ends of each rod sit at the same angle, so every rod
    lies in a plane through the tank axis and nothing reacts rotation about
    it. Half a turn is degenerate for the same reason."""
    m = fs.layout_metrics(opt.seed_symmetric(pairwise, 12, twist=twist))
    assert m.is_mechanism
    assert m.sigma_min == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("twist", [0.1, 0.25, 0.4])
def test_a_twisted_symmetric_seed_is_not(pairwise, twist):
    assert not fs.layout_metrics(opt.seed_symmetric(pairwise, 12, twist=twist)).is_mechanism


def test_the_search_family_never_uses_a_degenerate_knob():
    for frac, twist in opt._symmetric_family(99):
        assert 0.0 < twist < 0.5, twist
        assert frac != 0.5


def test_the_spread_pair_cannot_collapse(pairwise):
    """frac 0.5 would put both alternating values at the same height."""
    lo, hi = opt._spread_pair(pairwise, 0.5)
    assert lo != hi


def test_seeding_is_deterministic_given_a_generator(space):
    a = opt.seed_random(space, 10, np.random.default_rng(3))
    b = opt.seed_random(space, 10, np.random.default_rng(3))
    assert np.allclose(a.design_vector(), b.design_vector())


# ======================================================================
# The smooth surrogate
# ======================================================================


def test_the_surrogate_tracks_the_true_maximum_lambda(pairwise):
    """The refiner minimizes a p-norm because `max` has no gradient. It has to
    bound and track the real thing, or it optimizes something else."""
    for n in (8, 14):
        m = fs.layout_metrics(opt.seed_symmetric(pairwise, n))
        soft = opt.softmax_lambda(m.lambdas, p=opt.SOFTMAX_P)
        assert m.max_lambda <= soft <= 1.35 * m.max_lambda


def test_the_surrogate_stays_finite_on_a_mechanism(pairwise):
    """An `inf` mid-line-search kills the optimizer. A mechanism has
    sigma_min = 0, which already saturates the conditioning penalty, so the
    continuous form covers it and stays differentiable on the way in."""
    m = fs.layout_metrics(opt.seed_symmetric(pairwise, 12, twist=0.0))
    assert m.is_mechanism
    assert np.isfinite(opt.surrogate(m, CRIT))


def test_the_conditioning_penalty_actually_bites(pairwise):
    """Isolated: one layout, two floors. Comparing two DIFFERENT layouts would
    conflate the penalty with their slenderness."""
    m = fs.layout_metrics(opt.seed_symmetric(pairwise, 14))
    relaxed = opt.surrogate(m, fs.Criteria(sigma_floor=1e-3))
    demanding = opt.surrogate(m, fs.Criteria(sigma_floor=0.5))
    assert m.sigma_min > 1e-3
    assert demanding > relaxed


def test_the_penalty_is_additive_not_multiplicative(pairwise):
    """A multiplicative penalty made the objective ~1e3x the quantity being
    optimized and stalled the optimizer after one iteration. The surrogate must
    stay within a small multiple of the slenderness it is minimizing."""
    m = fs.layout_metrics(opt.seed_symmetric(pairwise, 14))
    assert opt.surrogate(m, CRIT) < 50.0 * m.max_lambda


# ======================================================================
# Local refinement
# ======================================================================


def test_refinement_never_makes_a_layout_worse(pairwise):
    start = opt.seed_symmetric(pairwise, 14)
    before = fs.objective(fs.layout_metrics(start), CRIT)
    after = fs.objective(fs.layout_metrics(opt.refine(start, CRIT, max_iter=25)), CRIT)
    assert after <= before


def test_refinement_stays_inside_the_declared_regions(pairwise):
    refined = opt.refine(opt.seed_random(pairwise, 14, np.random.default_rng(1)),
                         CRIT, max_iter=25)
    refined.validate()
    for rod in refined.rods.values():
        for end in (rod.end_a, rod.end_b):
            assert refined.regions[end.region_id].in_bounds(end.q)


def test_refinement_pulls_in_a_deliberately_stretched_layout(pairwise):
    """The whole point: shorten the rods without falling off the conditioning
    cliff. Measured on this seed, max lambda goes 287 -> ~72."""
    start = opt.seed_symmetric(pairwise, 12, spread=(24.0, 22.0), twist=0.25)
    before = fs.layout_metrics(start)
    after = fs.layout_metrics(opt.refine(start, CRIT, max_iter=60))

    assert after.max_lambda < 0.5 * before.max_lambda
    assert after.total_length < before.total_length
    assert after.sigma_min > before.sigma_min, "shorter AND better conditioned"


def test_refinement_refuses_a_result_the_true_objective_dislikes(pairwise, monkeypatch):
    """The accept-guard, tested directly.

    The real surrogate happens to agree with the true objective on every
    fixture here, so a disagreement cannot be provoked by luck — inject one. A
    surrogate that REWARDS long rods sends the optimizer the wrong way, and
    `refine` must still hand back the layout it was given. Without the guard
    this returns the lengthened layout and the caller never knows.
    """
    nominal = fs.Criteria(sigma_floor=0.05, require_single_failure=False)
    start = opt.seed_symmetric(pairwise, 14)
    assert fs.feasible(fs.layout_metrics(start), nominal).ok, "start must be feasible"

    monkeypatch.setattr(opt, "surrogate", lambda m, c: -m.max_lambda)
    out = opt.refine(start, nominal, max_iter=30)
    assert np.allclose(out.design_vector(), start.design_vector())


def test_refinement_of_a_rodless_layout_is_a_no_op(pairwise):
    blank = pairwise.blank()
    assert opt.refine(blank, CRIT).rods == {}


# ======================================================================
# The search
# ======================================================================


def test_the_search_finds_nothing_below_the_counting_bound(pairwise):
    result = opt.search(pairwise, CRIT, n_range=range(12, 13), n_symmetric=2,
                        n_random=1, max_iter=15, rng=np.random.default_rng(0))
    assert result.best is None
    assert not result.feasible_candidates
    assert result.n_evaluated > 0, "it looked, and found nothing"


def test_the_topology_can_raise_the_floor_above_the_global_bound(found):
    """The global bound is 6*n_free+1 = 13. With only tank->plate pairs
    offered, each tank needs 7 of its own, so 14 is the real floor. A search
    that trusted the global count would report 13 as reachable."""
    assert fs.min_rods_for_single_failure(2) == 13
    assert found.best_for(13) is None
    assert found.best_for(14) is not None


def test_allowing_body_to_body_rods_lowers_that_floor_back(space):
    """And the converse: offer tank-to-tank pairing and 13 becomes reachable.
    Topology is a real design lever, not bookkeeping."""
    result = opt.search(space, CRIT, n_range=range(13, 14), n_symmetric=0,
                        n_random=4, max_iter=20, rng=np.random.default_rng(0))
    assert result.best is not None
    assert result.best.n_rods == 13


def test_the_search_finds_a_fail_safe_layout_on_the_demo_geometry(found):
    best = found.best
    assert best is not None
    assert best.metrics.survives_single_loss
    assert best.metrics.sigma_min >= CRIT.sigma_floor
    assert fs.feasible(best.metrics, CRIT).ok
    best.assembly.validate()


def test_what_it_finds_beats_the_hand_built_demo(found):
    """A CATEGORICAL win, which is the robust one: the shipped 12-rod layout is
    determinate and therefore never fail-safe at any load; what the search
    returns survives any single rod loss.

    Deliberately no threshold on max lambda here. The search is a stochastic
    local method — see `test_the_search_is_a_local_method_and_says_so` — and
    its achieved slenderness at a small seed budget is not stable enough to
    assert against. Quality is gated relative to its own seeds instead.
    """
    shipped = fs.layout_metrics(examples.demo_assembly())
    best = found.best.metrics
    assert not shipped.survives_single_loss
    assert best.survives_single_loss
    assert best.max_lambda <= shipped.max_lambda


def test_the_search_improves_on_the_seeds_it_started_from(pairwise, found):
    """Budget-independent quality claim: refinement plus selection must beat
    the raw seeds, whatever the seeds happened to be."""
    raw = []
    for frac, twist in opt._symmetric_family(3):
        seed = opt.seed_symmetric(pairwise, 14,
                                  spread=opt._spread_pair(pairwise, frac), twist=twist)
        raw.append(fs.objective(fs.layout_metrics(seed), CRIT))
    assert found.best.objective < min(raw)


def test_the_search_is_a_local_method_and_says_so(pairwise):
    """Two searches from DIFFERENT seeds reach different local optima. This is
    a property to be honest about, not a bug: the answer is a good layout, not
    a proven optimum, and the tool must never imply otherwise."""
    kw = dict(n_range=range(14, 15), n_symmetric=0, n_random=2, max_iter=15)
    a = opt.search(pairwise, CRIT, rng=np.random.default_rng(1), **kw)
    b = opt.search(pairwise, CRIT, rng=np.random.default_rng(2), **kw)
    assert [c.objective for c in a.candidates] != [c.objective for c in b.candidates]


def test_the_search_reports_a_trade_curve_of_count_against_slenderness(found):
    curve = found.trade_curve()
    assert [row["n_rods"] for row in curve] == [13, 14]
    assert not curve[0]["feasible"] and curve[0]["reason"]
    assert curve[1]["feasible"]
    assert curve[1]["max_lambda"] > 0.0 and curve[1]["total_length"] > 0.0
    assert curve[1]["n_euler"] <= curve[1]["n_rods"]


def test_candidates_come_back_ranked(found):
    objectives = [c.objective for c in found.candidates]
    assert objectives == sorted(objectives)
    assert found.best is found.candidates[0]


def test_symmetric_only_seeding_can_find_a_feasible_layout(pairwise):
    """Both strategies are kept because neither dominates. Which one WINS on a
    given run is not stable enough to assert — it flips with the seed budget
    and even with the LAPACK driver — so each is only required to be capable on
    its own. The case where random succeeds and the symmetric family cannot is
    covered by `test_allowing_body_to_body_rods_lowers_that_floor_back`, which
    runs with `n_symmetric=0`."""
    result = opt.search(pairwise, CRIT, n_range=range(14, 15), n_symmetric=3,
                        n_random=0, max_iter=25, rng=np.random.default_rng(0))
    assert result.best is not None
    assert result.best.seed_kind == "symmetric"


def test_the_search_survives_a_space_where_nothing_works(pairwise):
    """Impossible criteria must return an empty answer, not raise — a user will
    set a slenderness cap nothing can meet."""
    result = opt.search(
        pairwise, fs.Criteria(sigma_floor=0.05, max_lambda=1.0),
        n_range=range(14, 15), n_symmetric=1, n_random=1, max_iter=10,
        rng=np.random.default_rng(0),
    )
    assert result.best is None
    assert result.candidates, "candidates were still generated and scored"


def test_the_search_is_reproducible(pairwise):
    kw = dict(n_range=range(14, 15), n_symmetric=1, n_random=1, max_iter=8)
    a = opt.search(pairwise, CRIT, rng=np.random.default_rng(7), **kw)
    b = opt.search(pairwise, CRIT, rng=np.random.default_rng(7), **kw)
    assert [c.objective for c in a.candidates] == [c.objective for c in b.candidates]


def test_a_found_layout_is_a_real_assembly_that_round_trips(found):
    """Not a report — the user has to be able to save what the search found and
    keep working on it."""
    from library.tierod import serialize as ser

    layout = found.best.assembly
    back = ser.loads(ser.dumps(layout))
    assert isinstance(back, Assembly)
    assert np.allclose(back.design_vector(), layout.design_vector())
    assert fs.layout_metrics(back).max_lambda == pytest.approx(
        found.best.metrics.max_lambda
    )
