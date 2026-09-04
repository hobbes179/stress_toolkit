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
)

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

PAGE = "pages/4_Bolt_Bending.py"
TIMEOUT = 60

SECTION = BoltSection(d_shank=0.375, d_section=0.315)
ALLOW = Allowables(Ftu=160.0, Fsu=95.0, k_bending=1.5, fitting_factor=1.0)


def _run(**session_state):
    at = AppTest.from_file(PAGE, default_timeout=TIMEOUT)
    for k, v in session_state.items():
        at.session_state[k] = v
    return at.run()


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


def test_nothing_is_hidden_behind_a_tab():
    """The original tool showed the stack, the diagrams, the margins and the
    checks at once. Losing that was the regression that prompted the rebuild:
    the point of the tool is watching the margin move as a load changes."""
    at = _run()
    assert not at.tabs, "bolt bending must stay a single page"

    body = _page_html(at)
    for fragment in ("<svg", "bb-res", "bb-checks", "bb-method"):
        assert fragment in body, f"{fragment} is not on the page"


def test_unbalanced_stack_warns_and_prints_no_margin_numbers():
    """Handoff §4.1 — the page must not show a margin an analyst could paste
    into a report when the loads do not close."""
    import pandas as pd

    unbalanced = pd.DataFrame(
        [
            {"Type": "Plate", "Thickness, in": 0.25, "Load, lbf": 1000.0},
            {"Type": "Plate", "Thickness, in": 0.25, "Load, lbf": -600.0},
        ]
    )
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
    assert "56.60 lbf" in svg                   # head and nut reactions
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
