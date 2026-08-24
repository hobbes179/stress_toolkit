"""
tests/tierod/test_ui_search.py — Session 10 gate: the layout-search UI.

One real search runs here, module-scoped, on a deliberately small space (two
arcs, one topology, three rod counts, two seeds each). It takes a few seconds
and every test that needs a `SearchResult` shares it. Faking one would not
exercise the couplings that actually break — the cost estimate against the
search's own skip rule, and adoption against a real refined layout.
"""
from __future__ import annotations

import time

import numpy as np
import pytest

from apps.tierod import ui_search as us
from library.tierod import failsafe as fs
from library.tierod import optimize as opt
from library.tierod.model import Assembly, Body, new_region, new_rod

# The small-search knobs, in one place so a test can reuse the exact numbers
# the fixture searched with.
N_RANGE = range(7, 10)
N_SEEDS = 2
MAX_ITER = 25


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


def _two_disc() -> Assembly:
    """Ground disc + free disc 12 in above it. One cross-body pair."""
    asm = Assembly({}, {}, {})
    asm.add_body(Body("base", is_ground=True))
    asm.add_body(Body("top", mass=200.0, origin=np.array([0.0, 0.0, 12.0])))
    asm.add_region(new_region("CircleArc", "base_r", "base", axis="Z", radius=10.0))
    asm.add_region(new_region("CircleArc", "top_r", "top", axis="Z", radius=7.0))
    return asm


@pytest.fixture
def two_disc() -> Assembly:
    return _two_disc()


@pytest.fixture(scope="module")
def result():
    """One real search, shared. See the module docstring."""
    space = opt.space_from(_two_disc())
    return opt.search(
        space, fs.Criteria(), n_range=N_RANGE,
        n_symmetric=N_SEEDS, n_random=N_SEEDS, max_iter=MAX_ITER,
        rng=np.random.default_rng(7),
    )


# ----------------------------------------------------------------------
# searchable — what is missing, by name
# ----------------------------------------------------------------------


def test_a_complete_model_is_searchable(two_disc):
    assert us.searchable(two_disc) == []


def test_a_model_with_no_ground_says_so():
    asm = _two_disc()
    asm.bodies["base"].is_ground = False
    assert any("ground" in p for p in us.searchable(asm))


def test_a_model_with_no_free_body_says_so():
    asm = _two_disc()
    asm.bodies["top"].is_ground = True
    assert any("free body" in p for p in us.searchable(asm))


def test_a_model_whose_regions_share_one_body_says_so():
    """A rod between two regions on the same body contributes nothing."""
    asm = _two_disc()
    asm.regions["top_r"].body_id = "base"
    assert any("cross-body" in p for p in us.searchable(asm))


def test_each_missing_piece_is_reported_separately():
    asm = Assembly({}, {}, {})
    asm.add_body(Body("lonely"))
    assert len(us.searchable(asm)) >= 2


# ----------------------------------------------------------------------
# n_range_floor
# ----------------------------------------------------------------------


def test_the_floor_is_the_single_failure_counting_bound(two_disc):
    assert us.n_range_floor(two_disc) == 7          # 6*1 + 1


def test_the_floor_scales_with_the_number_of_free_bodies(two_disc):
    two_disc.add_body(Body("second", mass=50.0))
    assert us.n_range_floor(two_disc) == 13         # 6*2 + 1


# ----------------------------------------------------------------------
# budget — the estimate must mirror the search, not guess at it
# ----------------------------------------------------------------------


def test_the_estimate_matches_what_the_search_actually_evaluates(result, two_disc):
    """The coupling that matters. If `search` changes which counts it skips,
    the quoted cost is wrong and this fails instead of the user waiting."""
    space = opt.space_from(two_disc)
    est = us.budget(space, N_RANGE, N_SEEDS, N_SEEDS)
    assert est.n_candidates == result.n_evaluated


def test_the_estimate_skips_counts_the_search_would_skip(two_disc):
    """`search` skips any count below the number of offered topologies."""
    space = opt.space_from(two_disc)
    wide = opt.LayoutSpace(space.template, space.topologies * 9, space.rod_props)
    assert us.budget(wide, range(1, 4), 2, 2).n_candidates == 0


def test_the_estimate_reports_seconds_and_a_readable_message(two_disc):
    est = us.budget(opt.space_from(two_disc), N_RANGE, 2, 2)
    assert est.seconds > 0
    assert "7–9" in est.message()


def test_an_empty_budget_says_there_is_nothing_to_search(two_disc):
    est = us.budget(opt.space_from(two_disc), range(0, 0), 2, 2)
    assert est.n_candidates == 0
    assert "nothing to search" in est.message().lower()


def test_more_seeds_cost_more(two_disc):
    space = opt.space_from(two_disc)
    assert (us.budget(space, N_RANGE, 6, 6).n_candidates
            > us.budget(space, N_RANGE, 2, 2).n_candidates)


# ----------------------------------------------------------------------
# geometry_fingerprint — staleness
# ----------------------------------------------------------------------


def test_the_fingerprint_is_stable_across_repeated_reads(two_disc):
    assert us.geometry_fingerprint(two_disc) == us.geometry_fingerprint(two_disc)


def test_editing_a_region_changes_the_fingerprint(two_disc):
    before = us.geometry_fingerprint(two_disc)
    two_disc.regions["top_r"].radius = 5.0
    assert us.geometry_fingerprint(two_disc) != before


def test_moving_a_body_changes_the_fingerprint(two_disc):
    before = us.geometry_fingerprint(two_disc)
    two_disc.bodies["top"].origin = np.array([0.0, 0.0, 20.0])
    assert us.geometry_fingerprint(two_disc) != before


def test_changing_the_rods_does_NOT_change_the_fingerprint(two_disc):
    """The search replaces rods, so adopting a layout must not mark its own
    result stale — the warning would fire the instant it was acted on."""
    before = us.geometry_fingerprint(two_disc)
    two_disc.add_rod(new_rod(two_disc, "r1", "base_r", "top_r"))
    assert us.geometry_fingerprint(two_disc) == before


# ----------------------------------------------------------------------
# Presentation
# ----------------------------------------------------------------------


def test_the_trade_table_has_one_row_per_rod_count(result):
    rows = us.trade_rows(result)
    assert [r["rods"] for r in rows] == list(N_RANGE)


def test_an_infeasible_count_shows_a_dash_not_a_zero():
    """A zero in the slenderness column would read as the best row in the
    table. There is no slenderness for a layout that does not exist."""
    empty = opt.SearchResult(
        candidates=[
            opt.Candidate(assembly=Assembly({}, {}, {}),
                          metrics=fs.layout_metrics(Assembly({}, {}, {})),
                          objective=(float("inf"), float("inf"), 7),
                          n_rods=7, seed_kind="symmetric")
        ],
        n_evaluated=1, criteria=fs.Criteria(),
    )
    row = us.trade_rows(empty)[0]
    assert row["feasible"] == "no"
    assert row["max λ"] == "—" and row["Σ length (in)"] == "—"


def test_an_infeasible_count_carries_the_reason(result):
    """Formatting must not drop `why not` — it is the actionable half."""
    rows = us.trade_rows(result)
    assert all("why not" in r for r in rows)


def test_the_candidate_label_leads_with_count_and_slenderness(result):
    label = us.candidate_label(result.best)
    assert "rods" in label and "λ" in label


def test_the_gallery_is_ranked_best_first(result):
    rows = us.candidate_rows(result)
    assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))


def test_the_gallery_is_capped_so_a_big_run_does_not_flood_the_page(result):
    assert len(us.candidate_rows(result, limit=3)) <= 3


def test_the_summary_always_shows_the_knee_next_to_the_slenderness(result):
    """A λ with no λ_crit to compare against is not interpretable."""
    summary = us.metrics_summary(result.best.metrics, result.criteria)
    assert "knee" in summary["max λ"]


def test_the_summary_states_the_verdict_in_words(result):
    summary = us.metrics_summary(result.best.metrics, result.criteria)
    assert summary["verdict"] == "feasible"


def test_the_summary_explains_an_infeasible_layout_rather_than_saying_no():
    metrics = fs.layout_metrics(_two_disc())          # no rods: a mechanism
    summary = us.metrics_summary(metrics, fs.Criteria())
    assert "mechanism" in summary["verdict"]


# ----------------------------------------------------------------------
# trade_figure
# ----------------------------------------------------------------------


def test_the_trade_figure_plots_both_costs_of_complexity(result):
    fig = us.trade_figure(result)
    names = {t.name for t in fig.data}
    assert "max λ" in names and "Σ length (in)" in names


def test_the_trade_figure_marks_the_buckling_knee(result):
    fig = us.trade_figure(result)
    assert any("λ_crit" in str(a.text) for a in fig.layout.annotations)
    assert fig.layout.shapes, "the knee needs a line, not only a label"


def test_infeasible_counts_are_drawn_not_dropped():
    """A gap in the curve leaves the reader to infer the floor. A red x with
    the reason on hover states it."""
    metrics = fs.layout_metrics(_two_disc())
    empty = opt.SearchResult(
        candidates=[opt.Candidate(assembly=_two_disc(), metrics=metrics,
                                  objective=(float("inf"), float("inf"), 7),
                                  n_rods=7, seed_kind="symmetric")],
        n_evaluated=1, criteria=fs.Criteria(),
    )
    fig = us.trade_figure(empty)
    infeasible = [t for t in fig.data if t.name == "infeasible"]
    assert infeasible and infeasible[0].hovertext
    assert "mechanism" in infeasible[0].hovertext[0]


def test_the_trade_figure_survives_a_result_with_nothing_in_it():
    fig = us.trade_figure(
        opt.SearchResult(candidates=[], n_evaluated=0, criteria=fs.Criteria())
    )
    assert fig is not None


# ----------------------------------------------------------------------
# adoptable / adopt — the destructive step
# ----------------------------------------------------------------------


def test_a_fresh_result_adopts_onto_the_model_it_came_from(result, two_disc):
    assert us.adoptable(two_disc, result.best) == []


def test_adopting_installs_the_candidate_s_rods(result, two_disc):
    report = us.adopt(two_disc, result.best)
    assert len(two_disc.rods) == result.best.n_rods
    assert set(report.added) == set(two_disc.rods)
    two_disc.validate()


def test_adopting_replaces_rather_than_appends(result, two_disc):
    two_disc.add_rod(new_rod(two_disc, "old", "base_r", "top_r"))
    report = us.adopt(two_disc, result.best)
    assert "old" in report.removed
    assert "old" not in two_disc.rods


def test_adopting_leaves_bodies_and_regions_alone(result, two_disc):
    before = us.geometry_fingerprint(two_disc)
    us.adopt(two_disc, result.best)
    assert us.geometry_fingerprint(two_disc) == before


def test_an_adopted_layout_reproduces_the_metrics_it_was_ranked_on(result, two_disc):
    """Adoption must be lossless. A layout that scores differently once it is
    in the model would make the whole trade curve meaningless."""
    us.adopt(two_disc, result.best)
    after = fs.layout_metrics(two_disc)
    assert after.max_lambda == pytest.approx(result.best.metrics.max_lambda)
    assert after.sigma_min == pytest.approx(result.best.metrics.sigma_min)


def test_adopting_deep_copies_so_the_candidate_is_not_aliased(result, two_disc):
    """Dragging a slider after adopting must not silently rewrite the search
    result the user is still comparing against."""
    us.adopt(two_disc, result.best)
    rod_id = sorted(two_disc.rods)[0]
    before = float(result.best.assembly.rods[rod_id].end_a.q[0])
    two_disc.rods[rod_id].end_a.q[0] += 0.1
    assert float(result.best.assembly.rods[rod_id].end_a.q[0]) == before


def test_a_deleted_region_blocks_adoption(result, two_disc):
    two_disc.remove_region("top_r")
    blockers = us.adoptable(two_disc, result.best)
    assert blockers and "top_r" in blockers[0]


def test_a_retyped_region_blocks_adoption(result, two_disc):
    from apps.tierod import ui_build

    ui_build.replace_region(two_disc, "top_r", type_name="PlanarPatch")
    assert us.adoptable(two_disc, result.best)


def test_the_parameter_count_check_is_reachable_on_its_own(two_disc):
    """A `q` that happens to land inside the new region's bounds would slip
    past the bounds check, so the dimension check has to stand alone.

    Built by hand rather than taken from the shared search: the values must be
    chosen so that only one of the two checks can fire.
    """
    from apps.tierod import ui_build

    layout = _two_disc()
    layout.add_rod(new_rod(layout, "r1", "base_r", "top_r",
                           q_a=[0.5], q_b=[0.5]))
    hand = opt.Candidate(
        assembly=layout, metrics=fs.layout_metrics(layout),
        objective=(1.0, 1.0, 1), n_rods=1, seed_kind="hand",
    )
    # CircleArc(ndim 1) -> PlanarPatch(ndim 2), and q = 0.5 is inside the
    # patch's [0, 1] domain, so `in_bounds` cannot be what catches this.
    ui_build.replace_region(two_disc, "top_r", type_name="PlanarPatch")
    blockers = us.adoptable(two_disc, hand)
    assert blockers and "parameter" in blockers[0]


def test_a_shrunken_region_blocks_adoption(result, two_disc):
    from apps.tierod import ui_build

    ui_build.replace_region(two_disc, "base_r", params={"theta_max": 20.0})
    blockers = us.adoptable(two_disc, result.best)
    assert blockers and "resized" in blockers[0]


def test_a_blocked_adoption_refuses_without_deleting_anything(result, two_disc):
    """Atomicity. A model left with no rods because the install failed halfway
    is worse than a refusal — there is no undo."""
    two_disc.add_rod(new_rod(two_disc, "old", "base_r", "top_r"))
    two_disc.remove_region("top_r")
    before = sorted(two_disc.rods)
    with pytest.raises(ValueError, match="cannot adopt"):
        us.adopt(two_disc, result.best)
    assert sorted(two_disc.rods) == before


def test_the_refusal_says_which_layout_problem_it_hit(result, two_disc):
    two_disc.remove_region("top_r")
    with pytest.raises(ValueError, match="no longer has"):
        us.adopt(two_disc, result.best)


# ----------------------------------------------------------------------
# The running page
# ----------------------------------------------------------------------

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

PAGE = "pages/3_Tie_Rod_Layout.py"
TIMEOUT = 120


def _run(**session_state):
    at = AppTest.from_file(PAGE, default_timeout=TIMEOUT)
    for key, value in session_state.items():
        at.session_state[key] = value
    return at.run()


def _with_model(assembly):
    from apps.tierod import examples

    return {
        "tierod::assembly": assembly,
        "tierod::loaded": examples.DEFAULT_EXAMPLE,
        "tierod::example": examples.DEFAULT_EXAMPLE,
    }


def test_the_search_tab_renders_on_the_default_example():
    at = _run()
    assert not at.exception, [e.value for e in at.exception]


def test_the_page_does_not_run_a_search_on_load():
    """The single most important behaviour in this file.

    A search is minutes. If it ever ran on a rerun the app would be unusable,
    and the failure would look like a hang rather than an error. "No search
    has been run yet" is only reachable when nothing was searched.
    """
    started = time.perf_counter()
    at = _run()
    assert not at.exception
    assert any("no search has been run" in str(c.value).lower()
               for c in at.caption)
    assert time.perf_counter() - started < 60.0


def test_a_model_that_cannot_be_searched_says_what_is_missing():
    asm = Assembly({"only": Body("only")}, {}, {})
    at = _run(**_with_model(asm))
    assert not at.exception, [e.value for e in at.exception]
    text = " ".join(str(e.value).lower() for e in at.error)
    assert "ground" in text


def test_the_rodless_message_points_at_the_search_as_well_as_the_builder():
    at = _run(**_with_model(_two_disc()))
    assert not at.exception, [e.value for e in at.exception]
    assert any("find a layout" in str(i.value).lower() for i in at.info)


# ----------------------------------------------------------------------
# The floor follows the fail-safe setting (added after the owner found it
# frozen: `n_range_floor` quoted the single-failure bound unconditionally,
# so with fail-safe off the tool hid the rod count that would have worked)
# ----------------------------------------------------------------------


def test_the_floor_is_the_single_failure_bound_when_fail_safe_is_on(two_disc):
    criteria = fs.Criteria(require_single_failure=True)
    assert us.n_range_floor(two_disc, criteria) == 7        # 6*1 + 1


def test_the_floor_drops_to_the_mechanism_bound_when_fail_safe_is_off(two_disc):
    """One whole rod count. Quoting 7 with fail-safe off hides that 6 works."""
    criteria = fs.Criteria(require_single_failure=False)
    assert us.n_range_floor(two_disc, criteria) == 6        # 6*1


def test_omitting_the_criteria_assumes_the_stricter_bound(two_disc):
    assert us.n_range_floor(two_disc) == us.n_range_floor(
        two_disc, fs.Criteria(require_single_failure=True)
    )


def test_the_floor_still_scales_with_free_bodies_under_either_setting(two_disc):
    two_disc.add_body(Body("second", mass=50.0))
    assert us.n_range_floor(two_disc, fs.Criteria(require_single_failure=True)) == 13
    assert us.n_range_floor(two_disc, fs.Criteria(require_single_failure=False)) == 12


def test_the_hint_warns_when_the_count_is_below_the_bound():
    text = us.floor_hint(5, 7, True)
    assert "below the counting bound" in text.lower() and "7" in text


def test_the_hint_says_what_a_high_count_skips():
    text = us.floor_hint(10, 7, True)
    assert "skips 3" in text


def test_the_hint_confirms_a_count_sitting_on_the_bound():
    assert "counting bound" in us.floor_hint(7, 7, True)


def test_the_hint_explains_which_bound_it_is_quoting():
    """The two bounds mean different things and the wording has to say which."""
    assert "losing any one rod" in us.floor_hint(7, 7, True)
    assert "restrain every degree" in us.floor_hint(6, 6, False)


def test_the_hint_never_returns_a_replacement_value():
    """Option B: advisory only. It is a string, not a number to write back."""
    assert isinstance(us.floor_hint(5, 7, True), str)


# ----------------------------------------------------------------------
# The plan is shared with the search rather than reimplemented
# ----------------------------------------------------------------------


def test_the_budget_reads_the_search_s_own_plan(two_disc):
    space = opt.space_from(two_disc)
    assert us.budget(space, N_RANGE, 3, 3).n_candidates == opt.plan_size(
        space, N_RANGE, 3, 3
    )


def test_the_plan_skips_counts_below_the_number_of_paths(two_disc):
    space = opt.space_from(two_disc)
    wide = opt.LayoutSpace(space.template, space.topologies * 9, space.rod_props)
    assert opt.plan_counts(wide, range(1, 4)) == []


# ----------------------------------------------------------------------
# Progress reporting
# ----------------------------------------------------------------------


def test_the_search_reports_every_candidate_it_scores(two_disc):
    seen = []
    space = opt.space_from(two_disc)
    result = opt.search(
        space, fs.Criteria(), n_range=range(7, 9), n_symmetric=1, n_random=1,
        max_iter=5, rng=np.random.default_rng(3),
        on_candidate=lambda c, done, total: seen.append((done, total)),
    )
    assert len(seen) == result.n_evaluated
    assert [d for d, _ in seen] == list(range(1, result.n_evaluated + 1))
    assert {t for _, t in seen} == {opt.plan_size(space, range(7, 9), 1, 1)}


def test_a_progress_callback_that_raises_does_not_lose_the_search():
    """A run is minutes. Losing all of it because a progress bar failed would
    be a bad trade — the callback reports, it must never steer."""
    def boom(candidate, done, total):
        raise RuntimeError("the progress bar fell over")

    result = opt.search(
        opt.space_from(_two_disc()), fs.Criteria(), n_range=range(7, 8),
        n_symmetric=1, n_random=1, max_iter=5,
        rng=np.random.default_rng(3), on_candidate=boom,
    )
    assert result.n_evaluated > 0
    assert result.candidates


def test_a_search_with_no_callback_still_runs(two_disc):
    result = opt.search(
        opt.space_from(two_disc), fs.Criteria(), n_range=range(7, 8),
        n_symmetric=1, n_random=1, max_iter=5, rng=np.random.default_rng(3),
    )
    assert result.n_evaluated > 0


def test_the_quoted_range_names_only_the_counts_that_will_run(two_disc):
    """`Budget.counts` drives the "rod counts 9–11" line. Quoting the range
    the user typed rather than the one the search will visit over-promises."""
    space = opt.space_from(two_disc)
    wide = opt.LayoutSpace(space.template, space.topologies * 9, space.rod_props)
    est = us.budget(wide, range(7, 12), 2, 2)
    assert est.counts == (9, 10, 11)
    assert "9–11" in est.message()
