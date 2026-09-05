"""
tests/beam_line/test_app_smoke.py

Headless execution of the page, plus structural checks on the SVG figure, the
HTML blocks and the module's UI conventions.

`streamlit run` starting without error only proves the module imports -- the
script body does not execute until a browser connects. AppTest actually runs
`render()` in-process and surfaces any exception.

What still needs eyes, and got them during the build: that the panel titles
and the peak labels do not overprint at real container widths, and that the
reaction callouts clear the support symbols. Neither is visible to a green
suite. Two label collisions were found by screenshot after these tests passed.
"""

from __future__ import annotations

import inspect
import re
import xml.dom.minidom

import pytest

from apps.beam_line import app as bl_app
from apps.beam_line import plotting
from apps.beam_line import styles as bl_styles
from apps.beam_line.method import method_html
from apps.beam_line.plotting import figure_svg
from library.beam_line import (
    Beam,
    DistributedLoad,
    Hinge,
    PointLoad,
    Support,
    analyse,
)

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

PAGE = "pages/5_Beam_Diagrams.py"
TIMEOUT = 90


def _run(**session_state):
    at = AppTest.from_file(PAGE, default_timeout=TIMEOUT)
    for k, v in session_state.items():
        at.session_state[k] = v
    return at.run()


def _page_html(at) -> str:
    return " ".join(str(m.value) for m in at.markdown)


def _demo() -> Beam:
    return Beam(120.0, 1.0e8,
                (Support(0.0, uy="rigid", rz="rigid"), Support(70.0),
                 Support(120.0)),
                point_loads=(PointLoad(95.0, -800.0),),
                distributed=(DistributedLoad(0.0, 70.0, -12.0, -4.0),))


# ==========================================================================
# Page
# ==========================================================================
def test_the_page_renders_without_exceptions():
    at = _run()
    assert not at.exception, [e.value for e in at.exception]


def test_the_figure_actually_reaches_the_page():
    """`st.html` sanitises with an HTML-only profile that strips <svg>
    silently -- the figure column just comes out blank, with no error and no
    log line. This is the gate on using st.markdown(unsafe_allow_html=True)
    instead."""
    at = _run()
    assert "<svg" in _page_html(at)


def test_the_page_is_never_fragmented():
    """Model, figure, peaks and reactions must all be visible at once. The
    point of the tool is moving a support and watching the moment peak move
    with it, and that feedback loop dies the moment a result goes behind a
    tab. Only the Method section may be collapsed."""
    at = _run()
    assert len(at.tabs) == 0, "the results must not be split across tabs"
    html = _page_html(at)
    assert "Peak values" in html
    assert "Reactions" in html


def test_the_default_beam_reproduces_a_hand_calculation():
    """L = 120, w = -8 lb/in over the full span, 600 lb down at x = 40, on
    two pin/rollers. R_A = 480 + 400 = 880 lb and M(40) = 880(40) - 8(40)(20)
    = 28,800 lb-in."""
    at = _run()
    html = _page_html(at)
    assert "880.0" in html
    assert "28,800" in html


def test_the_method_section_is_present_and_states_the_conventions():
    html = method_html()
    for fragment in ("positive <b>up</b>", "counterclockwise",
                     "sagging-positive"):
        assert fragment in html, fragment


# ==========================================================================
# Conventions this project has already paid for
# ==========================================================================
def test_the_stack_is_edited_with_native_number_inputs():
    """`st.number_input`, never `st.data_editor`: the stepper buttons and the
    scroll-wheel nudge come from the native input and a NumberColumn has
    neither."""
    src = inspect.getsource(bl_app)
    assert not re.search(r"\bst\.data_editor\(", src)
    assert re.search(r"\.number_input\(", src)


def test_no_row_carries_more_than_two_number_inputs():
    """Streamlit drops the steppers when a column gets narrow, and three
    number inputs to a row in this sidebar is under that threshold while
    still looking fine in a test. Measured in a browser, not guessed.

    The constraint is on the count of number inputs, not of columns: a row of
    three columns holding one number input, a selectbox and a delete button is
    fine, because only the number input needs the width.
    """
    src = inspect.getsource(bl_app)
    segments = re.split(r"st\.columns\(", src)[1:]
    assert segments, "no column rows found"
    for seg in segments:
        n = len(re.findall(r"\.number_input\(", seg))
        assert n <= 2, f"a row carries {n} number inputs; the steppers go"


def test_row_widget_keys_are_built_from_a_stable_row_id():
    """Never the list position: deleting row 1 would otherwise shift every key
    below it and Streamlit would replay row 2's stored value into row 1."""
    src = inspect.getsource(bl_app)
    keys = re.findall(r'key=f"(bl::[a-z]+)::\{(\w+)\}"', src)
    assert keys, "no per-row widget keys found"
    for _, var in keys:
        assert var == "rid", f"row key interpolates {var!r}, not the row id"


def test_reset_drops_every_per_row_widget_key():
    """A surviving `bl::sx::3` would be replayed into the rebuilt row and the
    reset would appear to do nothing for that field."""
    src = inspect.getsource(bl_app._reset)
    assert 'startswith("bl::")' in src


def test_stale_session_state_from_an_older_deploy_does_not_crash():
    """Streamlit Cloud redeploys under live sessions, so a browser holding the
    previous payload format must be reseeded rather than crash the page on its
    next rerun. Presence-checking would not catch any of these."""
    for payload in ("not a list", [], [{"id": 1}], [{"nope": 2}], 17,
                    [{"id": 1, "x": 0.0}]):
        at = _run(**{"bl::supports": payload})
        assert not at.exception, (payload, [e.value for e in at.exception])


def test_a_stale_section_handoff_is_ignored_rather_than_trusted():
    """The handoff payload is shape-checked for the same reason. A snapshot
    written by an older schema must be dropped, not partially believed."""
    for payload in ({"schema": 0, "shape": "x"}, {"nope": 1}, "text",
                    {"schema": 1, "shape": "I", "material": "m", "E": 0.0,
                     "Iy": 1.0, "Iz": 1.0, "area": 1.0}):
        at = _run(**{"handoff::section": payload})
        assert not at.exception, payload
        assert "entered directly" in _page_html(at), (
            "an unusable snapshot must fall back to the manual E and I")


def test_the_beam_section_page_publishes_a_usable_section_snapshot():
    """The producing half of the handoff. Widget state does not survive page
    navigation, so the section has to be mirrored into a plain session key --
    this asserts that mirror is written and holds library units (E in psi,
    not Msi)."""
    at = AppTest.from_file("pages/1_Beam_Section_Stress.py",
                           default_timeout=180).run()
    snap = at.session_state["handoff::section"]
    assert snap["schema"] == 1
    assert snap["E"] > 1.0e6, "E must be published in psi, not Msi"
    assert snap["Iy"] > 0 and snap["Iz"] > 0
    assert snap["shape"] and snap["material"]


def test_an_inherited_section_is_stated_on_screen_and_never_silent():
    """A toggle that moves EI by 10x without saying so is a trap. The strip
    must name the shape, the material and the modulus actually in force."""
    snap = {"schema": 1, "shape": "I-Beam / W-Shape", "material": "7075-T6",
            "E": 10.3e6, "Iy": 42.5, "Iz": 7.25, "area": 4.0}
    at = _run(**{"handoff::section": snap, "bl::use_section": True})
    assert not at.exception, [e.value for e in at.exception]
    html = _page_html(at)
    assert "I-Beam / W-Shape" in html
    assert "7075-T6" in html
    assert "42.5" in html
    assert "snapshot" in html.lower(), (
        "the page must say the handoff is a snapshot, not a live link")


def test_without_a_snapshot_the_page_does_not_offer_the_toggle():
    """A toggle that is inert most of the time is worse than no toggle."""
    at = _run()
    assert not at.exception
    labels = [t.label for t in at.toggle]
    assert not any("Beam Section Stress" in str(l) for l in labels)
    assert "entered directly" in _page_html(at)


def _loads(*rows) -> list[dict]:
    """Load rows in the page's format. Each tuple is (kind, x, value, on)."""
    out = []
    for i, (kind, x, val, on) in enumerate(rows):
        out.append({"id": 100 + i, "kind": kind, "x": x, "x2": 120.0,
                    "P": val if kind == "Point force" else 0.0,
                    "M": val if kind == "Moment" else 0.0,
                    "w1": val if kind == "Distributed" else 0.0,
                    "w2": val if kind == "Distributed" else 0.0,
                    "on": on})
    return out


def _excluded_notice(html: str) -> bool:
    """True when the excluded-items banner is present.

    Matched on "item(s) switched off", which only the banner emits. A looser
    "switched off" also matches the Method section's prose about the feature,
    and a negative assertion on that quietly tests nothing.
    """
    return bool(re.search(r"\d+ items? switched off", html))


def test_switching_a_load_off_actually_removes_it_from_the_solve():
    """The point of the switch. A 600 lb load at midspan of a 120 in span on
    two pin/rollers gives M = 18,000 lb·in; switched off it gives nothing."""
    on = _run(**{"bl::loads": _loads(("Point force", 60.0, -600.0, True))})
    off = _run(**{"bl::loads": _loads(("Point force", 60.0, -600.0, False))})
    assert "18,000" in _page_html(on)
    assert "18,000" not in _page_html(off)


def test_toggling_a_load_does_not_move_the_figure():
    """The interaction the switch exists for is flipping a load on and off and
    watching the diagrams change IN PLACE. Anything above the figure that
    appears or disappears makes the whole plot stack jump by its height and
    destroys that.

    The excluded-items notice used to sit above the figure and did exactly
    this. The gate is exact: everything rendered before the figure must be
    byte-identical in both states.
    """
    on = _run(**{"bl::loads": _loads(("Distributed", 0.0, -8.0, True),
                                     ("Point force", 40.0, -600.0, True))})
    off = _run(**{"bl::loads": _loads(("Distributed", 0.0, -8.0, True),
                                      ("Point force", 40.0, -600.0, False))})
    a, b = _page_html(on), _page_html(off)
    assert "<svg" in a and "<svg" in b
    assert a[:a.index("<svg")] == b[:b.index("<svg")], (
        "content above the figure changed when a load was toggled")


def test_the_excluded_notice_is_rendered_after_the_figure():
    at = _run(**{"bl::loads": _loads(("Distributed", 0.0, -8.0, True),
                                     ("Point force", 40.0, -600.0, False))})
    html = _page_html(at)
    m = re.search(r"\d+ items? switched off", html)
    assert m, "the notice must still be shown"
    assert html.index("<svg") < m.start(), (
        "the notice must come after the figure, or it pushes the plots down")


def test_a_switched_off_item_is_named_in_the_results():
    """It must never be silently absent. This page gets screenshotted into
    stress reports, and a load that simply is not in the picture is one nobody
    notices is missing."""
    at = _run(**{"bl::loads": _loads(
        ("Point force", 60.0, -600.0, False),
        ("Distributed", 0.0, -8.0, True))})
    html = _page_html(at)
    assert _excluded_notice(html)
    assert "excluded from these results" in html
    assert "-600" in html, "the excluded item must be identified, not counted"


def test_nothing_is_said_when_everything_is_switched_on():
    """The notice is a warning, so it must not appear on an ordinary run."""
    assert not _excluded_notice(_page_html(_run()))


def test_a_switched_off_item_is_ghosted_on_the_elevation_not_omitted():
    from library.beam_line import PointMoment
    beam = Beam(120.0, 1e8, (Support(0.0), Support(120.0)),
                point_loads=(PointLoad(30.0, -500.0),))
    ghost = Beam(120.0, 1e8, (Support(60.0, uy="rigid", rz="rigid"),),
                 point_loads=(PointLoad(90.0, -900.0),),
                 moments=(PointMoment(45.0, 3000.0),),
                 hinges=(Hinge(75.0),))
    _, sol, dg = analyse(beam)
    plain = figure_svg(beam, sol, dg)
    withg = figure_svg(beam, sol, dg, ghost)
    xml.dom.minidom.parseString(withg)
    # On the label text, not the bare number -- "900" also matches an SVG
    # coordinate like "900.0,135.5".
    assert "900.0 lb" in withg, "the ghosted load must be drawn and labelled"
    assert "900.0 lb" not in plain
    assert "Fixed" in withg, "a switched-off support keeps its symbol"
    assert 'stroke-dasharray="4 3"' in withg
    assert "opacity=\"0.3\"" in withg


def test_the_ghost_layer_shares_the_load_scale_with_the_active_one():
    """Otherwise a ghosted 100 lb/in patch is drawn the same height as an
    active 1 lb/in one and reads as comparable."""
    from apps.beam_line.plotting import _load_scale
    active = Beam(120.0, 1e8, (Support(0.0), Support(120.0)),
                  distributed=(DistributedLoad(0.0, 120.0, -1.0, -1.0),))
    ghost = Beam(120.0, 1e8, (),
                 distributed=(DistributedLoad(0.0, 120.0, -100.0, -100.0),))
    assert _load_scale(active, ghost) == _load_scale(ghost, active)
    assert _load_scale(active, ghost) < _load_scale(active)


def test_switching_supports_off_composes_with_the_mechanism_gate():
    """Disabling a support can leave a mechanism, and that has to be caught by
    the existing gate rather than produce a plausible diagram."""
    at = _run(**{"bl::supports": [
        {"id": 1, "x": 0.0, "kind": "Pin / roller", "ky": 1.0, "krz": 0.0,
         "dy": 0.0, "drz": 0.0, "on": True},
        {"id": 2, "x": 120.0, "kind": "Pin / roller", "ky": 1.0, "krz": 0.0,
         "dy": 0.0, "drz": 0.0, "on": False}]})
    assert not at.exception, [e.value for e in at.exception]
    html = _page_html(at)
    assert "mechanism" in html.lower()
    assert "Peak values" not in html
    assert _excluded_notice(html), (
        "the excluded support must still be named, especially here")


def test_rows_from_before_the_switch_existed_are_reseeded():
    """`on` is part of the shape check on purpose. Defaulting it in instead
    would leave a stored row in a state the widget cannot represent."""
    at = _run(**{"bl::loads": [
        {"id": 1, "kind": "Point force", "x": 60.0, "x2": 60.0, "P": -600.0,
         "M": 0.0, "w1": 0.0, "w2": 0.0}]})
    assert not at.exception
    assert not _excluded_notice(_page_html(at))


def test_the_diagram_scale_is_locked_by_default():
    at = _run()
    labels = [str(c.label) for c in at.checkbox]
    assert any("Lock diagram scale" in l for l in labels), labels
    lock = next(c for c in at.checkbox if "Lock diagram scale" in str(c.label))
    assert lock.value is True


def test_locking_holds_the_scale_still_while_loads_are_toggled():
    """The whole point. The same value must map to the same pixel whether a
    load is on or off, or two screenshots cannot be compared by eye."""
    from library.beam_line import load_envelope

    full = Beam(120.0, 1e8, (Support(0.0), Support(120.0)),
                point_loads=(PointLoad(40.0, -600.0),),
                distributed=(DistributedLoad(0.0, 120.0, -8.0, -8.0),))
    env = load_envelope(full)
    assert env is not None

    only_udl = Beam(120.0, 1e8, (Support(0.0), Support(120.0)),
                    distributed=(DistributedLoad(0.0, 120.0, -8.0, -8.0),))
    ghost = Beam(120.0, 1e8, (), point_loads=(PointLoad(40.0, -600.0),))

    def zero_lines(svg: str) -> list[str]:
        # The panel zero rules; their y is fixed, but the CURVE geometry is
        # what moves with the scale, so compare the plotted polyline instead.
        return re.findall(r'<polyline points="([^"]+)"', svg)

    _, s1, d1 = analyse(full)
    _, s2, d2 = analyse(only_udl)

    unlocked = zero_lines(figure_svg(only_udl, s2, d2, ghost))
    locked = zero_lines(figure_svg(only_udl, s2, d2, ghost, env))
    assert unlocked != locked, "locking must actually change the drawn scale"

    # Locked, the UDL-only curve must sit strictly inside the full model's.
    full_locked = zero_lines(figure_svg(full, s1, d1, None, env))

    def span(pts: str) -> float:
        ys = [float(p.split(",")[1]) for p in pts.split()]
        return max(ys) - min(ys)

    for a, b in zip(locked, full_locked):
        assert span(a) <= span(b) + 1e-6, (
            "a subset drawn on the locked scale must not exceed the full "
            "model it is a subset of")


def test_the_envelope_reference_is_drawn_only_when_there_is_headroom():
    from library.beam_line import load_envelope
    full = Beam(120.0, 1e8, (Support(0.0), Support(120.0)),
                point_loads=(PointLoad(40.0, -600.0),),
                distributed=(DistributedLoad(0.0, 120.0, -8.0, -8.0),))
    env = load_envelope(full)
    _, sol, dg = analyse(full)
    # Everything on and same-signed: the model IS the envelope, so no rules.
    assert "load envelope" not in figure_svg(full, sol, dg, None, env)

    only_udl = Beam(120.0, 1e8, (Support(0.0), Support(120.0)),
                    distributed=(DistributedLoad(0.0, 120.0, -8.0, -8.0),))
    ghost = Beam(120.0, 1e8, (), point_loads=(PointLoad(40.0, -600.0),))
    _, s2, d2 = analyse(only_udl)
    assert "load envelope" in figure_svg(only_udl, s2, d2, ghost, env)


def test_the_envelope_covers_switched_off_loads_not_just_active_ones():
    """It is computed on the FULL model. If it only saw the active loads the
    scale would move on every toggle, which is the bug this feature exists to
    avoid."""
    src = inspect.getsource(bl_app._full_model)
    assert "ghost.point_loads" in src
    assert "ghost.moments" in src
    assert "ghost.distributed" in src
    assert "supports" not in src.split('"""')[2], (
        "supports must not be merged in — the response is not linear in the "
        "structure")


def test_the_envelope_is_cached_so_toggling_is_free():
    """Streamlit reruns the whole script on every widget change. The envelope
    depends on the full model, not on which items are on, so it must be a
    cache hit when a switch flips."""
    src = inspect.getsource(bl_app)
    assert "@st.cache_data" in src
    assert "_cached_envelope" in src


def test_colours_come_only_from_the_theme():
    """No page or plotting module hardcodes a hex value."""
    for mod in (plotting, bl_styles, bl_app):
        src = inspect.getsource(mod)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", src), mod.__name__


# ==========================================================================
# The figure
# ==========================================================================
def test_the_figure_is_well_formed_svg():
    beam = _demo()
    _, sol, dg = analyse(beam)
    xml.dom.minidom.parseString(figure_svg(beam, sol, dg))


def test_the_figure_uses_no_defs_or_url_references():
    """Arrowheads are explicit polygons and hatching explicit segments.
    `<pattern>` and `<marker>` need a <defs> block plus id references that
    have to survive the page's sanitiser and stay unique against everything
    else on the page."""
    beam = _demo()
    _, sol, dg = analyse(beam)
    svg = figure_svg(beam, sol, dg)
    assert "<defs" not in svg
    assert "url(#" not in svg


def test_an_unstable_beam_still_draws_its_elevation_but_no_diagrams():
    """The elevation is the user's own input, so hiding it leaves them nothing
    to correct. The diagrams go, because one drawn for a mechanism looks
    plausible and means nothing."""
    beam = Beam(100.0, 1e7, (Support(50.0),),
                point_loads=(PointLoad(0.0, -100.0),))
    _, sol, dg = analyse(beam)
    svg = figure_svg(beam, sol, dg)
    assert "Elevation" in svg
    assert "Shear" not in svg
    assert "Moment" not in svg


def test_a_mechanism_suppresses_every_result_on_the_page():
    at = _run(**{"bl::supports": [
        {"id": 1, "x": 50.0, "kind": "Pin / roller", "ky": 1.0, "krz": 0.0,
         "dy": 0.0, "drz": 0.0, "on": True}]})
    assert not at.exception, [e.value for e in at.exception]
    html = _page_html(at)
    assert "mechanism" in html.lower()
    assert "Peak values" not in html
    assert "Span / deflection" not in html


def test_a_zero_diagram_says_so_instead_of_drawing_a_flat_full_scale_line():
    """The degenerate case the beam-section module had to fix for its stress
    contour: a quantity that is identically zero must be labelled, not
    rendered against a meaningless scale."""
    beam = Beam(100.0, 1e7, (Support(0.0), Support(100.0)))
    _, sol, dg = analyse(beam)
    svg = figure_svg(beam, sol, dg)
    assert "zero throughout" in svg


def test_a_rounding_floor_diagram_counts_as_zero_too():
    """Two self-cancelling couples give a shear of ~1e-13. Scaling that panel
    to its own peak magnifies pure rounding to full scale -- the most
    misleading thing the figure could do. It shipped that way during the
    build."""
    from library.beam_line import PointMoment
    beam = Beam(240.0, 3.0e8, (Support(0.0), Support(240.0)),
                moments=(PointMoment(80.0, 9000.0),
                         PointMoment(160.0, -9000.0)))
    _, sol, dg = analyse(beam)
    assert dg.valid, dg.message
    svg = figure_svg(beam, sol, dg)
    assert "zero throughout" in svg
    assert "e-13" not in svg, "a rounding-floor value reached the figure"


def test_a_rounding_floor_value_never_reaches_the_peak_summary():
    at = _run(**{
        "bl::loads": [
            {"id": 1, "kind": "Moment", "x": 40.0, "x2": 60.0, "P": 0.0,
             "M": 9000.0, "w1": 0.0, "w2": 0.0, "on": True},
            {"id": 2, "kind": "Moment", "x": 80.0, "x2": 60.0, "P": 0.0,
             "M": -9000.0, "w1": 0.0, "w2": 0.0, "on": True},
        ]})
    assert not at.exception, [e.value for e in at.exception]
    html = _page_html(at)
    assert "Peak values" in html, "this beam solves; results must show"

    # Only the reported quantities are cleaned. The Residual row and the
    # Solve-quality note must keep showing the true closure residue -- that
    # evidence is the whole point of them, so the assertion is scoped rather
    # than applied to the page as a whole.
    reported = html.split("Peak values", 1)[1].split("Residual", 1)[0]
    assert "e-13" not in reported, reported[:400]
    assert "Solve quality" in html
    assert "e-1" in html.split("Solve quality", 1)[1][:300], (
        "the solve-quality note must still report the real residue")


def test_every_load_type_and_support_kind_draws():
    beam = Beam(120.0, 1e8,
                (Support(0.0, uy="rigid", rz="rigid"),
                 Support(60.0, uy="spring", ky=5000.0, krz=1000.0),
                 Support(120.0, uy="rigid", dy=-0.05)),
                point_loads=(PointLoad(30.0, -500.0), PointLoad(90.0, 250.0)),
                moments=(bl_moment(45.0, 4000.0), bl_moment(100.0, -4000.0)),
                distributed=(DistributedLoad(0.0, 60.0, -10.0, -2.0),
                             DistributedLoad(60.0, 120.0, 3.0, 3.0)))
    _, sol, dg = analyse(beam)
    svg = figure_svg(beam, sol, dg)
    xml.dom.minidom.parseString(svg)
    for fragment in ("Fixed", "Spring", "Pin/roller", "lb/in", "lb·in"):
        assert fragment in svg, fragment


def test_a_hinge_is_drawn_on_the_beam():
    beam = Beam(200.0, 1e8,
                (Support(0.0, uy="rigid", rz="rigid"), Support(200.0)),
                point_loads=(PointLoad(150.0, -1000.0),),
                hinges=(Hinge(100.0),))
    _, sol, dg = analyse(beam)
    assert "hinge" in figure_svg(beam, sol, dg)


def test_a_sign_changing_distributed_patch_is_split_at_its_zero_crossing():
    """Otherwise the arrows on one half point the wrong way."""
    beam = Beam(100.0, 1e8, (Support(0.0), Support(100.0)),
                distributed=(DistributedLoad(0.0, 100.0, -10.0, 10.0),))
    _, sol, dg = analyse(beam)
    svg = figure_svg(beam, sol, dg)
    xml.dom.minidom.parseString(svg)
    assert "→" in svg, "a varying patch should print both end intensities"


def bl_moment(x, m):
    from library.beam_line import PointMoment
    return PointMoment(x, m)
