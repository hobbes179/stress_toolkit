"""
tests/tierod/test_ui_results.py — Session 5 gate, results-presentation half.

The results table is the deliverable of push 1, so what it *says* is gated,
not just that it renders:

  * the governing value in the table is the **closed form** `||t||`, and the
    enumerated case name next to it is a LABEL for the nearest sampled
    direction, not the source of the number. Presenting the enumerated maximum
    as the envelope is the specific error §7.2 warns about, and it is invisible
    once it is in a table.
  * the coverage angle to that nearest case is shown, so the sampling shortfall
    is on the page rather than in a docstring.
  * which allowable source is active per rod is shown (§6.1) — a margin
    computed off the `A_net * Ftu` fallback when the engineer meant to enter a
    vendor rating is a review-surviving error.
  * rods whose margin does not cover every limit state are named.

`ui_results` splits the same way `ui_inputs` does: pure frame builders here,
Streamlit only in the renderers.
"""
from __future__ import annotations

import numpy as np
import pytest

from apps.tierod import examples, ui_results
from library.tierod import allowables as al
from library.tierod import sweep as sw

from conftest import make_hexapod, make_two_body


def _steel(a):
    for rod in a.rods.values():
        rod.Ftu, rod.Fty, rod.A_net = 180.0e3, 160.0e3, 0.08
    return a


@pytest.fixture
def result():
    return sw.run_sweep(_steel(make_two_body()))


# ======================================================================
# The rod table
# ======================================================================


def test_one_row_per_rod_in_load_ratio_order(result):
    rows = ui_results.results_frame(result)
    assert len(rows) == len(result.rows)
    assert [r["rod"] for r in rows] == [r.rod_id for r in result.rows]


def test_the_reported_load_is_the_closed_form_envelope(result):
    """Not the enumerated maximum. This is the whole point of §7.2."""
    rows = ui_results.results_frame(result)
    by_id = {r.rod_id: r for r in result.rows}
    for row in rows:
        src = by_id[row["rod"]]
        assert row["P (lb)"] == pytest.approx(src.P_envelope, rel=1e-9)
        assert src.P_enumerated <= src.P_envelope * (1 + 1e-12)


def test_the_case_column_is_a_label_and_carries_its_angle(result):
    rows = ui_results.results_frame(result)
    by_id = {r.rod_id: r for r in result.rows}
    for row in rows:
        src = by_id[row["rod"]]
        assert src.nearest_case in row["worst direction"]
        assert f"{src.nearest_case_angle:.0f}" in row["worst direction"]


def test_the_active_allowable_source_is_shown(result):
    rows = ui_results.results_frame(result)
    for row in rows:
        assert row["source"]
        assert any(
            token in row["source"]
            for token in ("vendor", "Ftu", "Fty", "Fcy", "Euler", "Johnson")
        )


def test_the_sense_column_says_tension_or_compression(result):
    for row in ui_results.results_frame(result):
        assert row["sense"] in ("T", "C")


def test_margins_and_ratios_are_consistent_in_the_table(result):
    for row in ui_results.results_frame(result):
        assert row["MS"] == pytest.approx(al.margin_of_safety(row["LR"]), rel=1e-9)


def test_a_missing_number_renders_as_a_dash_not_a_zero():
    """A blank margin must never look like a computed one."""
    a = make_hexapod()
    a.rods["h0m"].Fcy = None
    rows = ui_results.results_frame(sw.run_sweep(_steel(a)))
    assert all(r["rod"] != "h0m" for r in rows)
    assert ui_results.fmt(None) == "—"
    assert ui_results.fmt(0.0) == "0.000"


def test_the_summary_names_the_governing_rod_and_the_worst_margin(result):
    s = ui_results.summary(result)
    assert s["governing_rod"] == result.rows[0].rod_id
    assert s["worst_margin"] == pytest.approx(result.rows[0].margin)
    assert s["n_negative"] == sum(
        1 for r in result.rows if r.margin is not None and r.margin < 0.0
    )


def test_the_summary_reports_the_sampling_shortfall(result):
    """How far the readable 26-case sample falls below the true envelope, at
    its worst — the number that justifies not reporting the sample."""
    s = ui_results.summary(result)
    expected = max(r.sample_shortfall for r in result.rows)
    assert s["worst_sample_shortfall"] == pytest.approx(expected)
    assert 0.0 <= s["worst_sample_shortfall"] < 1.0


def test_incomplete_rods_are_surfaced_in_the_summary():
    a = make_hexapod()          # no tension source at all
    s = ui_results.summary(sw.run_sweep(a))
    assert sorted(s["incomplete"]) == sorted(a.rods)


# ======================================================================
# The per-rod case table
# ======================================================================


def test_the_case_table_lists_every_enumerated_case_for_one_rod(result):
    rod_id = result.rows[0].rod_id
    rows = ui_results.case_frame(result, rod_id)
    assert len(rows) == len(result.cases)
    assert {r["case"] for r in rows} == {c.name for c in result.cases}
    # the rows are re-ordered by severity, so compare the multiset of loads
    i = result.rod_ids.index(rod_id)
    assert sorted(r["P (lb)"] for r in rows) == pytest.approx(
        sorted(result.P_cases[i])
    )


def test_the_case_table_is_sorted_by_severity(result):
    rows = ui_results.case_frame(result, result.rows[0].rod_id)
    mags = [abs(r["P (lb)"]) for r in rows]
    assert mags == sorted(mags, reverse=True)


def test_the_case_table_flags_how_far_each_case_is_from_the_envelope(result):
    rod_id = result.rows[0].rod_id
    rows = ui_results.case_frame(result, rod_id)
    row = result.row(rod_id)
    top = rows[0]
    assert top["% of envelope"] == pytest.approx(
        100.0 * abs(top["P (lb)"]) / row.P_envelope
    )
    assert top["% of envelope"] <= 100.0 + 1e-9


def test_asking_for_an_unknown_rod_raises(result):
    with pytest.raises(KeyError):
        ui_results.case_frame(result, "no_such_rod")


# ======================================================================
# Layer separation — the frame builders must stay Streamlit-free
# ======================================================================


def test_the_frame_builders_do_not_touch_session_state():
    import inspect

    for fn in (ui_results.results_frame, ui_results.case_frame,
               ui_results.summary, ui_results.fmt):
        assert "session_state" not in inspect.getsource(fn)


def test_the_scene_colouring_comes_straight_from_the_result(result):
    ratios = result.load_ratios()
    assert set(ratios) == set(result.rod_ids)
    assert ratios[result.rows[0].rod_id] == pytest.approx(result.rows[0].load_ratio)


# ======================================================================
# End to end on the shipped demo geometry
# ======================================================================


def test_the_demo_assembly_sweeps_and_reports_margins():
    """Push-1 definition of done: the saved demo loads, solves and reports
    margins end to end."""
    a = examples.demo_assembly()
    result = sw.run_sweep(a)
    assert len(result.rows) == 12
    assert result.incomplete_rods == []
    assert all(r.load_ratio is not None and r.load_ratio > 0.0 for r in result.rows)
    rows = ui_results.results_frame(result)
    assert len(rows) == 12
    assert ui_results.summary(result)["governing_rod"] in a.rods


def test_the_demo_is_buckling_driven_as_the_spec_predicts():
    """§7.2: a symmetric sweep reaches both senses, so the weaker allowable
    governs — for slender tie rods that is compression, every time."""
    result = sw.run_sweep(examples.demo_assembly())
    assert all(row.sense == "C" for row in result.rows)
    assert all("column" in row.allowable_source for row in result.rows)
