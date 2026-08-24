"""
tests/tierod/test_app_smoke.py — Session 4 gate, headless execution.

`streamlit run` starting without error only proves the module imports: the
script body does not execute until a browser connects. AppTest actually runs
`render()` in-process and surfaces any exception, so this is the part of the
manual checklist that can be automated.

What still needs eyes: that the camera survives a slider move (a client-side
Plotly behaviour, covered structurally by the `uirevision` test) and that the
animation looks like the motion it claims to show.
"""
from __future__ import annotations

import numpy as np
import pytest

from apps.tierod import examples

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

PAGE = "pages/3_Tie_Rod_Layout.py"
TIMEOUT = 90


def _run(**session_state):
    at = AppTest.from_file(PAGE, default_timeout=TIMEOUT)
    for k, v in session_state.items():
        at.session_state[k] = v
    return at.run()


def test_the_page_renders_without_exceptions():
    at = _run()
    assert not at.exception, [e.value for e in at.exception]


@pytest.mark.parametrize("example", list(examples.EXAMPLES))
def test_every_example_renders(example):
    at = _run(**{"tierod::example": example})
    assert not at.exception, f"{example}: {[e.value for e in at.exception]}"


def test_the_mechanism_case_reports_an_error_not_a_crash():
    """A mechanism must produce a diagnosis, never a traceback."""
    at = _run(**{"tierod::example": "Mechanism — baseplate idealized as a line"})
    assert not at.exception
    text = " ".join(str(e.value) for e in at.error) + " ".join(
        str(w.value) for w in at.warning
    )
    assert "collinear" in text.lower() or "mechanism" in text.lower()


def test_a_healthy_layout_reports_success():
    at = _run(**{"tierod::example": examples.DEFAULT_EXAMPLE})
    assert not at.exception
    assert any("no mechanism" in str(s.value).lower() for s in at.success)


def test_ground_toggle_does_not_clear_mass_in_the_running_app():
    """The data-loss bug, exercised through the real widget layer."""
    at = AppTest.from_file(PAGE, default_timeout=TIMEOUT)
    at.session_state["tierod::example"] = examples.DEFAULT_EXAMPLE
    at.run()
    assert not at.exception

    assembly = at.session_state["tierod::assembly"]
    assert assembly.bodies["plate"].mass == 400.0

    box = next(c for c in at.checkbox if c.key == "tierod::ground::plate")
    box.set_value(False).run()          # un-ground it
    assert not at.exception
    at.session_state["tierod::assembly"].bodies["plate"].mass == 400.0

    box = next(c for c in at.checkbox if c.key == "tierod::ground::plate")
    box.set_value(True).run()           # and back
    assert not at.exception
    assert at.session_state["tierod::assembly"].bodies["plate"].mass == 400.0
    assert at.session_state["tierod::assembly"].bodies["plate"].g_factor == 6.0


def test_only_the_selected_rod_gets_sliders():
    """48 sliders in one sidebar is clutter and invites dragging the wrong rod.
    One rod is selected at a time, so only its 2-4 parameters are live."""
    at = AppTest.from_file(PAGE, default_timeout=TIMEOUT)
    at.session_state["tierod::example"] = examples.DEFAULT_EXAMPLE
    at.run()
    assert not at.exception

    a = at.session_state["tierod::assembly"]
    assert a.n_design_vars() == 48, "the model still has all 48 variables"

    q_sliders = [s for s in at.slider if s.key and s.key.startswith("tierod::q::")]
    assert len(q_sliders) == 4, f"expected one rod's worth, got {len(q_sliders)}"
    assert all("rod_a0" in s.key for s in q_sliders)


def test_switching_the_selected_rod_switches_the_sliders():
    at = AppTest.from_file(PAGE, default_timeout=TIMEOUT)
    at.session_state["tierod::example"] = examples.DEFAULT_EXAMPLE
    at.run()
    picker = next(s for s in at.selectbox if s.key == "tierod::qrod")
    picker.set_value("rod_b3").run()
    assert not at.exception
    q_sliders = [s for s in at.slider if s.key and s.key.startswith("tierod::q::")]
    assert len(q_sliders) == 4
    assert all("rod_b3" in s.key for s in q_sliders)


def test_moving_a_slider_moves_only_that_rod():
    at = AppTest.from_file(PAGE, default_timeout=TIMEOUT)
    at.session_state["tierod::example"] = examples.DEFAULT_EXAMPLE
    at.run()
    before = at.session_state["tierod::assembly"].design_vector().copy()

    s = next(x for x in at.slider if x.key and x.key.startswith("tierod::q::"))
    s.set_value(float(s.value) + 0.4).run()
    assert not at.exception

    after = at.session_state["tierod::assembly"].design_vector()
    moved = np.flatnonzero(~np.isclose(after, before))
    assert moved.size == 1 and moved[0] < 4, "only one variable, on the selected rod"


# ======================================================================
# Session 5 — results, safety factors, rod specs
# ======================================================================


def test_the_results_tab_reports_margins_for_the_demo():
    at = _run(**{"tierod::example": examples.DEFAULT_EXAMPLE})
    assert not at.exception
    text = " ".join(str(m.value) for m in at.markdown) + " ".join(
        str(c.value) for c in at.caption
    )
    assert "closed-form envelope" in text
    assert any("Governing rod" in str(m.label) for m in at.metric)


def test_the_safety_factors_are_editable_cells_with_the_expected_defaults():
    at = _run(**{"tierod::example": examples.DEFAULT_EXAMPLE})
    cells = {n.key: n for n in at.number_input if n.key in
             ("tierod::sf_yield", "tierod::sf_ult")}
    assert cells["tierod::sf_yield"].value == 1.0
    assert cells["tierod::sf_ult"].value == 1.5

    cells["tierod::sf_ult"].set_value(2.0).run()
    assert not at.exception


def test_tightening_the_ultimate_factor_worsens_every_margin():
    """The factors are inputs, not decoration — moving one has to move the
    numbers on the page."""
    at = AppTest.from_file(PAGE, default_timeout=TIMEOUT)
    at.session_state["tierod::example"] = examples.DEFAULT_EXAMPLE
    at.run()

    def worst():
        m = next(x for x in at.metric if "Worst MS" in str(x.label))
        return float(str(m.value))

    loose = worst()
    next(n for n in at.number_input if n.key == "tierod::sf_ult").set_value(3.0).run()
    assert not at.exception
    assert worst() < loose


def test_ungrounding_every_body_reports_a_diagnosis_not_a_traceback():
    """Zero ground bodies is a legitimate free-free model (V12) and the
    mechanism report calls it ok — but K is still singular, so the sweep must
    be gated on the rank, not on that report."""
    at = AppTest.from_file(PAGE, default_timeout=TIMEOUT)
    at.session_state["tierod::example"] = examples.DEFAULT_EXAMPLE
    at.run()
    next(c for c in at.checkbox if c.key == "tierod::ground::plate").set_value(
        False
    ).run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("no load path" in str(e.value).lower() for e in at.error)


def test_the_rod_spec_editor_assigns_a_section_to_every_rod():
    at = AppTest.from_file(PAGE, default_timeout=TIMEOUT)
    at.session_state["tierod::example"] = examples.DEFAULT_EXAMPLE
    at.run()

    picker = next(s for s in at.selectbox if s.key == "tierod::spec")
    picker.set_value('5/8" alloy steel').run()
    targets = next(m for m in at.multiselect if m.key == "tierod::spec_targets")
    a = at.session_state["tierod::assembly"]
    targets.set_value(list(a.rods)).run()
    next(b for b in at.button if "Apply spec" in str(b.label)).click().run()
    assert not at.exception

    a = at.session_state["tierod::assembly"]
    assert all(r.A == 0.3068 for r in a.rods.values())


def _figure_spec(at, key: str) -> dict:
    """The Plotly figure the page actually emitted, as data."""
    import json

    el = next(e for e in at.get("plotly_chart") if key in e.proto.id)
    return json.loads(el.proto.spec)


def test_the_layout_scene_is_coloured_by_load_ratio():
    """Grey rods were the Phase-0 placeholder. Once the sweep runs they carry
    the answer, and the caption on that tab claims they do."""
    from apps.tierod import ui_scene

    at = _run(**{"tierod::example": examples.DEFAULT_EXAMPLE})
    rods = [
        t for t in _figure_spec(at, "tierod-scene")["data"]
        if str(t.get("name", "")).startswith("rod_")
    ]
    assert len(rods) == 12
    assert ui_scene.ROD_NEUTRAL not in {t["line"]["color"] for t in rods}
    assert all("LR" in t.get("hovertext", "") for t in rods)


def test_the_results_scene_draws_the_worst_direction_cone():
    at = _run(**{"tierod::example": examples.DEFAULT_EXAMPLE})
    spec = _figure_spec(at, "tierod-results-scene")
    cones = [t for t in spec["data"] if t.get("type") == "cone"]
    assert len(cones) == 1
    assert cones[0]["name"].startswith("worst::")
