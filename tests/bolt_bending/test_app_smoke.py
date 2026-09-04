"""
tests/bolt_bending/test_app_smoke.py

Headless execution of the page, plus structural checks on the SVG figure and
the HTML blocks.

`streamlit run` starting without error only proves the module imports — the
script body does not execute until a browser connects. AppTest actually runs
`render()` in-process and surfaces any exception.

What still needs eyes: that the joint elevation reads correctly at real
container widths, and that the two-column Method section wraps sanely on a
narrow screen.
"""

from __future__ import annotations

import re
import xml.dom.minidom

import pytest

from apps.bolt_bending.app import (
    _bold,
    checks_html,
    header_html,
    peak_html,
    results_html,
)
from apps.bolt_bending.method import method_html
from apps.bolt_bending.plotting import joint_diagram_svg, svg_document
from library.bolt_bending.kernel import (
    Allowables,
    BoltSection,
    Layer,
    analyse,
    default_stack,
    margins,
    screening_checks,
    symmetric_double_shear,
)

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

PAGE = "pages/4_Bolt_Bending.py"
_REFINE = "boltbend::refine"
TIMEOUT = 60

SECTION = BoltSection(d_shank=0.375, d_section=0.315)
ALLOW = Allowables(Ftu=160.0, Fsu=95.0, k_bending=1.5, fitting_factor=1.0)


def _run(**session_state):
    at = AppTest.from_file(PAGE, default_timeout=TIMEOUT)
    for k, v in session_state.items():
        at.session_state[k] = v
    return at.run()


def _rows(*layers) -> list[dict]:
    """Build stack state in the page's row-dict format.

    Each tuple is (kind, thickness, load); a gap's load is ignored.
    """
    return [{"id": i, "kind": k, "t": t, "P": P, "mat": "2024-T3 Sheet"}
            for i, (k, t, P) in enumerate(layers)]


def _page_html(at) -> str:
    """Everything the page wrote as markdown, concatenated."""
    return " ".join(str(m.value) for m in at.markdown)


# ══════════════════════════════════════════════════════════════════════════
# Page
# ══════════════════════════════════════════════════════════════════════════
def test_the_page_renders_without_exceptions():
    at = _run()
    assert not at.exception, [e.value for e in at.exception]


def test_every_fastener_material_renders():
    """Selecting a material reseeds Ftu/Fsu; none of them may break the page."""
    from library.materials import list_by_category

    for mat in list_by_category()["Fastener"]:
        at = _run(**{"boltbend::material": mat.name})
        assert not at.exception, (mat.name, [e.value for e in at.exception])


def test_the_figure_actually_reaches_the_page():
    """Regression pin. `st.html()` sanitises with an HTML-only profile that
    strips SVG silently, which left the figure column blank with no error.
    The figure must go out through st.markdown(unsafe_allow_html=True)."""
    at = _run()
    body = _page_html(at)
    assert "<svg" in body, "the SVG never reached the page"
    assert "278.7" in body, "the peak-moment callout is missing from the figure"


def test_the_page_is_never_fragmented():
    """The original tool showed the stack, the diagrams, the margins and the
    checks at once. Losing that was the regression that prompted the rebuild:
    the point of the tool is watching the margin move as a load changes.

    The refinement used to be a second tab; it is now a sidebar toggle, so
    there must be NO tabs at all. Everything lives on one scroll.
    """
    at = _run()
    assert not at.tabs, [t.label for t in at.tabs]

    body = _page_html(at)
    for fragment in ("<svg", "bb-res", "bb-checks", "bb-method"):
        assert fragment in body, f"{fragment} left the page"


def test_the_bearing_model_is_stated_in_words_in_both_states():
    """A toggle that quietly moves the peak moment by 15% is a trap. The
    assumption in force must be on the page whichever way it is set."""
    off = _page_html(_run())
    assert 'class="bb-model"' in off
    assert "Uniform &mdash; baseline" in off
    assert "rigid across the thickness" in off

    on = _page_html(_run(**{_REFINE: True}))
    assert 'class="bb-model bb-model-refined"' in on
    assert "beam on an elastic foundation" in on
    assert "less-conservative" in on


def test_the_toggle_off_gives_exactly_the_baseline():
    """The refinement is a correction to the model in service, not a rival to
    it. With the toggle off the page must show the uniform-bearing numbers."""
    body = _page_html(_run())
    assert "278.7" in body                    # baseline peak moment
    assert "Tate & Rosenfeld" not in body     # refinement blocks stay away
    # the class name also appears in the stylesheet, so match the tag
    assert 'class="bb-model bb-model-refined"' not in body


def test_the_toggle_on_replaces_the_numbers_and_states_its_basis():
    """One analysis drives the page. When the refinement is on it must be the
    one shown — and it must never appear without its justification."""
    at = _run(**{_REFINE: True})
    assert not at.exception, [e.value for e in at.exception]
    body = _page_html(at)

    assert "235.2" in body                    # refined peak moment, 2024-T3
    assert "Tate & Rosenfeld" in body         # documented basis travels
    assert "NACA TN 1051" in body
    assert "Huth" in body                     # independent cross-check
    assert "VERIFY" in body                   # unverified constants flagged
    assert "<svg" in body                     # refined distribution drawn
    assert "load split is still your input" in body

    # The refined analysis is 24 strips per plate. Stations must still be
    # named by the PHYSICAL layer — an earlier draft reported "in plate 36".
    assert "in plate 36" not in body
    assert "in plate 2" in body


def test_the_refinement_degrades_to_the_baseline_and_says_so():
    """A single-plate stack has nothing to redistribute. The page must fall
    back to the baseline AND say it did — a toggle that reads as on while
    baseline numbers are displayed is the worst outcome available."""
    single = _rows(("plate", 0.25, 0.0))
    at = _run(**{_REFINE: True, "boltbend::stack": single})
    assert not at.exception, [e.value for e in at.exception]
    assert any("baseline" in str(w.value).lower() for w in at.warning),         [str(w.value) for w in at.warning]


def test_every_layer_is_drawn_to_its_full_width():
    """A plate exists on both sides of its hole. Drawing only the bearing side
    made the stack read as a set of half-plates, so both sides are drawn and
    distinguished by WEIGHT: the bearing side solid, the unloaded side pale."""
    import re

    from apps.bolt_bending.plotting import BW, CX, PL

    svg = joint_diagram_svg(analyse(default_stack()))
    rects = re.findall(r"<rect [^>]*?/>", svg)

    def at(x, w):
        return [r for r in rects
                if f'x="{x}"' in r and f'width="{w}"' in r]

    left, right = min(CX - BW / 2, CX - (BW / 2 + PL)), CX + BW / 2
    assert at(left, PL), "no plate body on the left of the bolt"
    assert at(right, PL), "no plate body on the right of the bolt"

    # Both weights must be present: solid bearing sides and pale quiet sides.
    solid = [r for r in at(left, PL) + at(right, PL)
             if 'fill-opacity="1.0"' in r]
    pale = [r for r in at(left, PL) + at(right, PL)
            if 'fill-opacity="0.38"' in r]
    assert solid and pale, (len(solid), len(pale))
    # the shipped stack has three plates, so three of each
    assert len(solid) == len(pale) == 3


def test_the_labels_and_direction_arrow_sit_on_the_unloaded_side():
    """They used to share the bearing side with the block and its arrows. The
    label anchors flip with the sign of P, so a single-sign check is enough to
    catch them being drawn on the wrong side."""
    import re

    pos = joint_diagram_svg(analyse([Layer("plate", 0.25, 1000.0),
                                     Layer("plate", 0.25, -1000.0)]))
    # plate 1 carries +P, so it bears from the left and is labelled on the
    # right — anchored "end" so the text grows back toward the bolt.
    label = re.search(r'<text [^>]*text-anchor="end"[^>]*>plate 1</text>', pos)
    assert label, "plate 1 was not labelled on its unloaded (right) side"

    # and the entered load, not the intensity, so the figure checks data entry
    assert ">1,000 lbf<" in pos
    assert "lbf/in" not in pos


def test_the_end_pair_is_not_drawn_as_solid_sideways_bearing():
    """The R0/RL arrows are a statically equivalent couple, not a contact
    force — nothing at the underside of a head can push sideways. They are
    drawn dashed and captioned as a couple so the figure does not assert the
    very thing the Method section spends a paragraph correcting."""
    svg = joint_diagram_svg(analyse(default_stack()))
    assert "stroke-dasharray" in svg, "the end pair is drawn as a solid force"
    assert "R₀" in svg and "Rₗ" in svg, "the arrows are unlabelled"
    # The arrows are forces; their MOMENT closes the residual. The caption
    # must not label the pair itself in lb·in — that conflates a force pair
    # with its moment and puts two units on one object.
    assert "equal and opposite forces" in svg
    assert "lbf, L apart" in svg
    assert "their moment, R·L" in svg
    assert "not sideways bearing on the head" in svg


def test_the_couple_note_is_dropped_when_there_is_no_residual():
    """A symmetric stack closes on its own; annotating a zero couple would be
    noise."""
    sym = symmetric_double_shear()
    svg = joint_diagram_svg(analyse(sym))
    assert "equal and opposite forces" not in svg


def test_a_loaded_layer_with_no_thickness_suppresses_the_margins():
    """Regression pin. The loads sum to zero, so the old ΣP-only gate passed
    the stack — while V(L) = 1000 lbf and M(L) = 250 lb·in, i.e. the diagrams
    never closed. The page showed confident, meaningless margins."""
    starved = _rows(("plate", 0.25, 1000.0), ("plate", 0.0, -1000.0),
                    ("plate", 0.25, 0.0))
    at = _run(**{"boltbend::stack": starved})
    assert not at.exception, [e.value for e in at.exception]

    body = _page_html(at)
    assert "no thickness" in body, "the diagnosis never reached the page"

    # Every computed cell in the results grid must be an em dash. Counted
    # rather than string-scanned for a value: the Method section carries a
    # static worked example whose numbers legitimately appear on the page.
    assert body.count("bb-void") >= 5, "margins were not suppressed"
    assert "90.83" not in body, "a computed stress was shown for a broken stack"

    # The banner must describe THIS failure, not recite the sum-of-loads one.
    # It read "Plate loads sum to 0.0 lbf, not zero" before this was branched.
    assert "bb-banner" in body
    assert "sum to 0.0 lbf, not zero" not in body


def test_both_bearing_models_agree_on_whether_a_stack_is_valid():
    """The refined path used to drop a zero-thickness plate's load, so the
    same stack was gated differently depending on the toggle."""
    starved = _rows(("plate", 0.25, 1000.0), ("plate", 0.0, -1000.0),
                    ("plate", 0.25, 0.0))
    for refine in (False, True):
        at = _run(**{_REFINE: refine, "boltbend::stack": starved})
        assert not at.exception, (refine, [e.value for e in at.exception])
        assert "bb-void" in _page_html(at), refine


def test_a_non_fastener_bolt_material_says_shear_is_checked_on_the_peak():
    """Fsu for plate stock is a material shear strength, not a fastener
    allowable, so V/A is the wrong basis — worth 33%. It must be stated."""
    at = _run(**{"boltbend::material": "4340 HT180"})
    assert not at.exception, [e.value for e in at.exception]
    caps = " ".join(str(c.value) for c in at.caption)
    assert "not a fastener grade" in caps
    body = _page_html(at)
    assert "1.333" in body                    # the factor, on the Strength card
    assert "Peak shear" in body               # and the label follows the basis
    assert "Average shear" not in body

    fastener = _run(**{"boltbend::material": "Alloy Steel Bolt 160 ksi"})
    assert "not a fastener grade" not in " ".join(
        str(c.value) for c in fastener.caption)


def test_the_custom_material_option_explains_itself():
    """It was silently inert: no caption, no hint that the fields above are
    the only source and that E is assumed for the refined solve."""
    at = _run(**{"boltbend::material": "Custom — enter allowables"})
    assert not at.exception, [e.value for e in at.exception]
    caps = " ".join(str(c.value) for c in at.caption)
    assert "nothing is read from the library" in caps
    assert "29.0 Msi" in caps


def test_the_bearing_model_is_the_first_decision_in_the_sidebar():
    """It changes the peak moment by ~15% AND changes what the stack editor
    asks for, so it must sit above the thing it reconfigures."""
    at = _run()
    assert at.sidebar.toggle[0].key == _REFINE,         [t.key for t in at.sidebar.toggle]
    # and it must precede the stack's own widgets
    keys = [w.key for w in at.sidebar.number_input if w.key]
    assert any(k.startswith("bb::t::") for k in keys), keys


def test_the_method_never_claims_no_solver_while_one_is_running():
    """The lead paragraph promised 'calls no solver'. That is true of the
    baseline and false of the refined pass, which assembles and solves a
    linear system — a false statement about the numbers on the same page."""
    base = _page_html(_run())
    assert "calls no solver" in base

    ref = _page_html(_run(**{_REFINE: True}))
    assert "calls no solver" not in ref
    assert "one linear system" in ref
    assert "beam on an elastic foundation" in ref


def test_the_method_documents_the_closure_gate_that_is_actually_used():
    """§4 documented ΣP alone long after the gate also began testing V(L) and
    M(L). A Method section that describes a superseded gate is worse than
    none — it tells the reader the tool checks something it does not."""
    body = _page_html(_run())
    assert "necessary but not sufficient" in body
    for token in ("|<i>V</i>(<i>L</i>)|", "|<i>M</i>(<i>L</i>)|"):
        assert token in body, token


def test_the_method_does_not_deny_a_feature_the_tool_ships():
    """§11 said 'No bearing peaking' for as long as the refined pass existed."""
    body = _page_html(_run())
    assert "No bearing peaking" not in body
    assert "Bearing peaking is available" in body


def test_the_stack_is_edited_with_native_number_inputs():
    """The stepper buttons and the scroll-wheel nudge come from
    `st.number_input`. A `data_editor` NumberColumn has neither, which is why
    the editor was rebuilt from real widgets on 2026-09-04. If this ever goes
    back to a data_editor, both are silently lost."""
    at = _run()
    assert not at.dataframe, "the stack went back to a data_editor"
    keys = [w.key for w in at.number_input if w.key]
    assert any(k.startswith("bb::t::") for k in keys), keys
    assert any(k.startswith("bb::P::") for k in keys), keys


def test_a_gap_gets_no_load_field_at_all():
    """Not a disabled or zeroed one — a spacer carries no bearing, so a load
    box beside it invites a number the model will silently discard."""
    stack = _rows(("plate", 0.25, 1000.0), ("gap", 0.06, 0.0),
                  ("plate", 0.25, -1000.0))
    at = _run(**{"boltbend::stack": stack})
    assert not at.exception, [e.value for e in at.exception]

    load_keys = {w.key for w in at.number_input if w.key
                 and w.key.startswith("bb::P::")}
    # rows 0 and 2 are plates; row 1 is the gap and must have no load widget
    assert load_keys == {"bb::P::0", "bb::P::2"}, load_keys


def test_stale_session_state_from_an_older_deploy_does_not_crash():
    """Streamlit Cloud redeploys under live sessions. A browser still holding
    the pre-2026-09-04 DataFrame must be reseeded, not crash on rerun."""
    import pandas as pd

    old = pd.DataFrame([{"Type": "Plate", "Thickness, in": 0.25,
                         "Load, lbf": 1000.0}])
    at = _run(**{"boltbend::stack": old})
    assert not at.exception, [e.value for e in at.exception]
    assert "278.7" in _page_html(at)          # reseeded to the default stack


def test_each_plate_can_take_its_own_material_when_refining():
    """A mixed stack is the point of per-layer materials: the per-plate table
    must show two different beds, not one averaged number."""
    stack = _rows(("plate", 0.25, 1000.0), ("gap", 0.06, 0.0),
                  ("plate", 0.50, -2000.0), ("plate", 0.25, 1000.0))
    from apps.bolt_bending.app import _plate_options

    # a plate material with a genuinely different E from the 2024-T3 default
    steel = next(n for n in _plate_options() if n.startswith("4340"))
    stack[2]["mat"] = steel
    at = _run(**{_REFINE: True, "boltbend::stack": stack})
    assert not at.exception, [e.value for e in at.exception]

    keys = {w.key for w in at.selectbox if w.key}
    assert {"bb::mat::0", "bb::mat::2", "bb::mat::3"} <= keys, keys
    assert "bb::mat::1" not in keys, "the gap was offered a plate material"

    # the mixed bed must reach the per-plate table, not be averaged away
    body = _page_html(at)
    assert steel in body, "the plate's own material never reached the page"


def test_unbalanced_stack_warns_and_prints_no_margin_numbers():
    """Handoff §4.1 — the page must not show a margin an analyst could paste
    into a report when the loads do not close."""
    unbalanced = _rows(("plate", 0.25, 1000.0), ("plate", 0.25, -600.0))
    at = _run(**{"boltbend::stack": unbalanced})
    assert not at.exception, [e.value for e in at.exception]

    body = _page_html(at)
    assert "not zero" in body and "suppressed" in body

    # No signed margin value anywhere in the results grid. Anchor on the <dl>
    # itself — matching the bare class name finds the CSS rule first and the
    # slice then swallows the whole page.
    start = body.index('<dl class="bb-res">')
    grid = body[start:body.index("</dl>", start)]
    assert not re.search(r"[+-]\d+\.\d\d", grid), grid


# ══════════════════════════════════════════════════════════════════════════
# HTML blocks
# ══════════════════════════════════════════════════════════════════════════
def test_results_grid_has_six_cells_and_shows_margins():
    m = margins(analyse(default_stack()), SECTION, ALLOW)
    html = results_html(m)
    assert html.count("<dt>") == 6
    assert "+1.64" in html                       # MS bending and MS combined
    assert "90.8" in html                        # bending stress
    assert "240" in html                         # allowable


def test_results_grid_voids_every_computed_value_when_unbalanced():
    a = analyse([Layer("plate", 0.25, 1000.0), Layer("plate", 0.25, -600.0)])
    m = margins(a, SECTION, ALLOW)
    assert not m.valid

    html = results_html(m)
    assert html.count("&mdash;") == 5            # all but the allowable
    assert "bb-void" in html
    assert not re.search(r"[+-]\d+\.\d\d", html)


def test_negative_margins_are_flagged():
    weak = Allowables(Ftu=10.0, Fsu=5.0, k_bending=1.0, fitting_factor=1.0)
    m = margins(analyse(default_stack()), SECTION, weak)
    assert m.MS_bending < 0
    assert "bb-neg" in results_html(m)


def test_check_bold_spans_become_real_html():
    """Regression pin: a mangled backreference once replaced every bold value
    with a literal control character, so each number rendered as a tofu box."""
    assert _bold("Grip/D = **2.83**.") == "Grip/D = <b>2.83</b>."

    a = analyse(default_stack())
    html = checks_html(screening_checks(a, SECTION))
    assert "**" not in html
    assert "\x01" not in html
    assert "<b>-60.0 lb·in</b>" in html
    assert "&#10003;" in html                    # the pass tick


def test_peak_and_header_blocks():
    a = analyse(default_stack())
    assert "278.7" in peak_html(a) and "in plate 2" in peak_html(a)
    assert "No bending moment" in peak_html(analyse([]))
    assert "<h1>" in header_html()


def test_method_section_is_two_columns_and_documents_the_mechanics():
    html = method_html()
    assert html.count("bb-mgrid") == 1
    assert html.count("<h3>") == 11              # sections 1-11
    assert "bb-eq" in html
    assert "278.7" in html                       # worked example table
    assert "constant along the bolt" in html     # the §4.2 assumption


# ══════════════════════════════════════════════════════════════════════════
# Figure
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "layers",
    [
        pytest.param(default_stack(), id="verification-case"),
        pytest.param([], id="empty-stack"),
        pytest.param([Layer("plate", 0.0, 100.0)], id="zero-thickness"),
        pytest.param([Layer("plate", 0.25, 0.0), Layer("plate", 0.25, 0.0)],
                     id="no-load"),
        pytest.param([Layer("gap", 0.25, 0.0)], id="gap-only"),
        pytest.param([Layer("plate", 0.25, 1000.0),
                      Layer("plate", 0.25, -600.0)], id="unbalanced"),
        pytest.param([Layer("plate", 0.002, 50.0), Layer("gap", 2.0, 0.0),
                      Layer("plate", 0.002, -50.0)], id="extreme-aspect"),
    ],
)
def test_svg_is_well_formed(layers):
    """A malformed figure fails silently in a browser, so parse it here."""
    svg = joint_diagram_svg(analyse(layers))
    xml.dom.minidom.parseString(svg)
    assert svg.startswith("<svg") and svg.endswith("</svg>")


def test_svg_carries_the_expected_annotations():
    svg = joint_diagram_svg(analyse(default_stack()))
    assert "278.7" in svg                       # peak moment callout
    # whole lbf: decimals on a ~57 lbf idealisation imply precision it
    # does not have (the closure choice itself is worth ~12%)
    assert "57 lbf" in svg                      # head and nut reactions
    assert "56.60" not in svg
    assert "1.060" in svg                       # nut station tick
    assert svg.count("plate ") == 3             # three plate labels
    assert "spacer" in svg


@pytest.mark.parametrize(
    "layers",
    [
        pytest.param(default_stack(), id="verification-case"),
        pytest.param([Layer("plate", 0.25, 500.0), Layer("plate", 0.25, -500.0)],
                     id="single-shear"),
        pytest.param([Layer("plate", 0.002, 50.0), Layer("gap", 2.0, 0.0),
                      Layer("plate", 0.002, -50.0)], id="extreme-aspect"),
    ],
)
def test_axis_tick_labels_never_overprint(layers):
    """Ticks sit at the two data extremes plus zero, but a diagram that barely
    crosses zero puts two of those on the same pixel — the default stack dips
    to M = -0.4 against a 278.7 peak, which printed '-0.400' on top of '0'."""
    from apps.bolt_bending.plotting import BOT, TICK_MIN_SEP

    svg = joint_diagram_svg(analyse(layers))
    ticks = re.findall(
        rf'<text x="([-\d.]+)" y="{BOT + 17}"[^>]*>([^<]+)</text>', svg
    )
    assert ticks, "no axis tick labels found — has the layout moved?"

    # group by panel: V occupies x < 570, M above it
    for lo_x, hi_x in ((0, 570), (570, 900)):
        xs = sorted(float(x) for x, _ in ticks if lo_x <= float(x) < hi_x)
        for a_x, b_x in zip(xs, xs[1:]):
            assert b_x - a_x >= TICK_MIN_SEP, (layers, xs)


def test_spacer_hatch_is_self_contained():
    """The hatch is explicit line segments, not a `<pattern>` fill. A pattern
    would depend on `<defs>`, a `url(#id)` reference surviving sanitisation,
    and that id being unique on the page — none of which the figure should
    need. Every hatch stroke must also stay inside its band."""
    from apps.bolt_bending.plotting import _hatch_band

    svg = joint_diagram_svg(analyse(default_stack()))
    assert "<defs" not in svg and "url(#" not in svg and "<pattern" not in svg

    x, y, w, h = 100.0, 50.0, 60.0, 30.0
    band = _hatch_band(x, y, w, h)
    assert band.count("<line") > 1
    for x1, y1, x2, y2 in re.findall(
        r'<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)"', band
    ):
        for px, py in ((float(x1), float(y1)), (float(x2), float(y2))):
            assert x - 0.02 <= px <= x + w + 0.02, (px, py)
            assert y - 0.02 <= py <= y + h + 0.02, (px, py)


def test_svg_uses_only_theme_palette_colours():
    """The toolkit rule: no hardcoded hex outside ui/theme.py."""
    from ui.theme import BOLT_PALETTE

    svg = joint_diagram_svg(analyse(default_stack()))
    used = {c.lower() for c in re.findall(r"#[0-9a-fA-F]{6}", svg)}
    allowed = {c.lower() for c in BOLT_PALETTE.values() if c.startswith("#")}
    assert used <= allowed, used - allowed


def test_page_css_uses_only_theme_palette_colours():
    """Same rule for the stylesheet: every colour traces back to ui/theme.py."""
    from dataclasses import asdict

    from apps.bolt_bending.styles import bolt_css
    from ui.theme import BOLT_PALETTE, THEME

    used = {c.lower() for c in re.findall(r"#[0-9a-fA-F]{6}", bolt_css())}
    allowed = {c.lower() for c in BOLT_PALETTE.values() if c.startswith("#")}
    allowed |= {
        v.lower() for v in asdict(THEME).values()
        if isinstance(v, str) and v.startswith("#")
    }
    assert used <= allowed, used - allowed


def test_svg_document_wraps_as_a_standalone_page():
    doc = svg_document(joint_diagram_svg(analyse(default_stack())))
    assert doc.startswith("<!doctype html>")
    assert "<svg" in doc and doc.rstrip().endswith("</html>")
