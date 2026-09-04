"""
apps/bolt_bending/app.py

Streamlit UI for the Bolt Bending module.

Shear and moment diagrams along a bolt in a multi-layer joint, with strength
margins. All mechanics live in `library/bolt_bending/kernel.py`; the figure is
built by `plotting.py`, the derivation text by `method.py`, and the page CSS by
`styles.py`. This file is glue: session state, widgets, and layout.

Layout follows the original standalone tool (archived at
`docs/bolt_bending/index.html`) rather than the toolkit's default page
furniture. **The page is never fragmented:** the stack, the diagrams, the
margins and the screening checks all stay on one scroll, because the point of
the tool is changing a load and watching the moment peak and the margin move
together. Bolt properties — set once, rarely touched — go in the sidebar,
which lands at roughly the width of the original's left column.

The optional refined bearing pass (`library/bolt_bending/refined.py`) is a
**sidebar toggle, not a second tab.** It reads the same layer and bolt data and
adds one input (plate material), and when it is on it replaces the analysis
driving the figure, the checks and the margins — there is one set of numbers on
the page at a time, never two competing ones. It is off by default, so uniform
bearing remains the default answer.

A toggle that quietly moves the peak moment by 15% would be a trap, so the
assumption in force is stated in words directly above the results in **both**
states (`refined_view.model_strip_html`), and switching it off restores the
baseline exactly — the refinement provably degenerates to it.

⚠️ Rendering note: the figure is emitted with
`st.markdown(svg, unsafe_allow_html=True)`. Do NOT switch it to `st.html()`,
which sanitises with an HTML-only profile and silently drops SVG entirely,
leaving a blank column. There is a test pinning this.
"""

from __future__ import annotations

import math
import re

import streamlit as st

from apps.bolt_bending import refined_view
from apps.bolt_bending.method import method_html
from apps.bolt_bending.plotting import fmt, joint_diagram_svg, sig
from apps.bolt_bending.styles import bolt_css
from library.bolt_bending.kernel import (
    Allowables,
    BoltAnalysis,
    BoltSection,
    Check,
    Layer,
    Margins,
    analyse,
    default_stack,
    margins,
    screening_checks,
)
from library.bolt_bending.refined import refined_analysis
from library.materials import MATERIALS, list_by_category
from ui.styles import inject_css
from ui.theme import THEME

# ── session-state keys ────────────────────────────────────────────────────
_STACK_KEY = "boltbend::stack"
_REV_KEY = "boltbend::rev"
_MAT_KEY = "boltbend::material"
_PLATE_KEY = "boltbend::plate_material"
_REFINE_KEY = "boltbend::refine"
_NEXT_ID_KEY = "boltbend::next_id"

_FTU_KEY = "boltbend::Ftu"
_FSU_KEY = "boltbend::Fsu"

_DEFAULT_MATERIAL = "Alloy Steel Bolt 160 ksi"
_DEFAULT_PLATE = "2024-T3 Sheet"
_CUSTOM = "Custom — enter allowables"

# On a solid round the parabolic shear distribution peaks at 4/3 of the
# average. It applies when Fsu is a MATERIAL shear strength; an MMPDS fastener
# allowable is already stated on the shank area, so it does not.
_ROUND_SHEAR_PEAK = 4.0 / 3.0

_TYPE_LABELS = {"plate": "Plate", "gap": "Gap"}
_TYPE_KINDS = {v: k for k, v in _TYPE_LABELS.items()}


# ══════════════════════════════════════════════════════════════════════════
# State
# ══════════════════════════════════════════════════════════════════════════
def _stack() -> list[dict]:
    """The live stack, seeded with the verification case.

    A list of plain dicts rather than a DataFrame: each row is rendered as
    real `st.number_input` widgets, which is what gives the stepper buttons
    and the scroll-wheel nudge that `st.data_editor`'s NumberColumn does not.

    Every row carries a stable `id`. Widget keys are built from that id, never
    from the list position — deleting row 1 would otherwise shift every key
    below it and Streamlit would replay row 2's stored value into row 1.
    """
    rows = st.session_state.get(_STACK_KEY)
    # Shape-checked, not just presence-checked. Streamlit Cloud redeploys under
    # live sessions, so a browser holding the pre-2026-09-04 DataFrame would
    # otherwise crash the page on the first rerun after a deploy.
    if not _is_stack(rows):
        rows = [
            {"id": i, "kind": ly.kind, "t": ly.t, "P": ly.P,
             "mat": _DEFAULT_PLATE}
            for i, ly in enumerate(default_stack())
        ]
        st.session_state[_STACK_KEY] = rows
        st.session_state[_NEXT_ID_KEY] = len(rows)
    return rows


def _is_stack(value) -> bool:
    """True when `value` is a stack in the current row-dict format."""
    return (
        isinstance(value, list) and bool(value)
        and all(isinstance(r, dict) and {"id", "kind", "t", "P"} <= r.keys()
                for r in value)
    )


def _add_layer() -> None:
    rows = _stack()
    new_id = st.session_state.get(_NEXT_ID_KEY, len(rows))
    st.session_state[_NEXT_ID_KEY] = new_id + 1
    rows.append({"id": new_id, "kind": "plate", "t": 0.250, "P": 0.0,
                 "mat": _DEFAULT_PLATE})


def _remove_layer(row_id: int) -> None:
    """Drop a row and its widget keys.

    Dropping the keys matters: ids are never reused, so a stale key is
    harmless to correctness, but leaving them accumulates session state for
    the life of the tab.
    """
    st.session_state[_STACK_KEY] = [r for r in _stack() if r["id"] != row_id]
    for prefix in ("bb::kind::", "bb::t::", "bb::P::", "bb::mat::"):
        st.session_state.pop(f"{prefix}{row_id}", None)


def _layers_from_stack(rows: list[dict]) -> list[Layer]:
    """Convert the stack rows to kernel Layers.

    A gap's load is forced to zero by `Layer.load`, so a number left behind
    after switching a plate to a gap cannot leak into the statics.
    """
    return [Layer(kind=r["kind"], t=float(r["t"]), P=float(r["P"]))
            for r in rows]


def _plate_moduli(rows: list[dict]) -> tuple[list[float | None], list[str]]:
    """Per-layer (modulus in Msi, material name) for the refined solve.

    Positional over `rows`, `None` for gaps — `refined_analysis` resolves the
    fallbacks. A material with no E in the library also yields None rather
    than a guess.
    """
    Es: list[float | None] = []
    names: list[str] = []
    for r in rows:
        mat = MATERIALS.get(r.get("mat", "")) if r["kind"] == "plate" else None
        Es.append(float(mat.E) if mat and mat.E else None)
        names.append(r.get("mat", "") if r["kind"] == "plate" else "")
    return Es, names


def _sync_allowables() -> None:
    """Reseed Ftu/Fsu from the library when the material changes.

    Runs as the selectbox's on_change so the number inputs show the new
    material's values immediately, while staying editable afterwards.
    """
    mat = MATERIALS.get(st.session_state.get(_MAT_KEY, ""))
    if mat and mat.Ftu and mat.Fsu:
        st.session_state[_FTU_KEY] = float(mat.Ftu)
        st.session_state[_FSU_KEY] = float(mat.Fsu)


def _reset() -> None:
    """Back to the shipped verification case.

    Every per-row widget key must go too. A surviving `bb::t::3` would be
    replayed into the rebuilt row 3 and the reset would appear to do nothing
    for that field — the same trap the old data_editor revision counter
    existed to dodge.
    """
    for key in (_STACK_KEY, _MAT_KEY, _PLATE_KEY, _FTU_KEY, _FSU_KEY,
                _REFINE_KEY, _NEXT_ID_KEY):
        st.session_state.pop(key, None)
    for key in [k for k in st.session_state if k.startswith("bb::")]:
        st.session_state.pop(key, None)
    st.session_state[_REV_KEY] = st.session_state.get(_REV_KEY, 0) + 1


# ══════════════════════════════════════════════════════════════════════════
# HTML blocks — the original tool's markup, styled by styles.py
# ══════════════════════════════════════════════════════════════════════════
def _html(markup: str) -> None:
    """Render raw HTML.

    `st.markdown(..., unsafe_allow_html=True)`, never `st.html()` — the latter
    sanitises with an HTML-only profile that strips SVG completely, which
    leaves the figure column blank with no error.
    """
    st.markdown(markup, unsafe_allow_html=True)


def _bold(text: str) -> str:
    """Convert markdown **bold** spans to <b>. Check text is authored in the
    kernel as markdown and rendered as HTML here."""
    return re.sub(r"\*\*(.+?)\*\*", lambda mo: f"<b>{mo.group(1)}</b>", text)


def header_html() -> str:
    return (
        '<div class="bb-header">'
        "<h1>Bolt bending &mdash; shear and moment along the grip</h1>"
        "<p>Bearing from each plate is spread over its own thickness. Gaps and "
        "spacers carry no bearing, so they pass moment straight through.</p>"
        "</div>"
    )


def _ms_cell(value: float) -> tuple[str, str]:
    """(display text, css class) for one margin value."""
    if not math.isfinite(value):
        return "high", ""
    if value > 9:
        return "&gt; 9", ""
    return f"{value:+.2f}", ("bb-neg" if value < 0 else "")


def results_html(m: Margins) -> str:
    """The original's six-cell `.res` grid.

    When force closure fails every computed value becomes an em dash: the
    handoff §4.1 rule is that no number here may look trustworthy. The
    allowable is still shown — it is an input, not a result.
    """
    allowable = ("Allowable, k&middot;F<sub>tu</sub>", sig(m.F_b),
                 "", " <small>ksi</small>")
    # The label must follow the basis. Calling a 4/3-factored value "average"
    # would misreport the very number the factor exists to correct.
    shear_label = ("Average shear"
                   if abs(m.allowables.shear_peak_factor - 1.0) < 1e-9
                   else "Peak shear")
    if not m.valid:
        cells = [
            ("Bending stress", "&mdash;", "bb-void", ""),
            allowable,
            ("MS bending", "&mdash;", "bb-void", ""),
            (shear_label, "&mdash;", "bb-void", ""),
            ("MS shear", "&mdash;", "bb-void", ""),
            ("MS combined", "&mdash;", "bb-void", ""),
        ]
    else:
        msb, cb = _ms_cell(m.MS_bending)
        mss, cs = _ms_cell(m.MS_shear)
        msc, cc = _ms_cell(m.MS_combined)
        cells = [
            ("Bending stress", sig(m.f_b), "", " <small>ksi</small>"),
            allowable,
            ("MS bending", msb, cb, ""),
            (shear_label, sig(m.f_s), "", " <small>ksi</small>"),
            ("MS shear", mss, cs, ""),
            ("MS combined", msc, cc, ""),
        ]

    body = "".join(
        f"<div><dt>{label}</dt><dd class='{cls}'>{value}{unit}</dd></div>"
        for label, value, cls, unit in cells
    )
    return f'<dl class="bb-res">{body}</dl>'


def checks_html(checks: list[Check]) -> str:
    rows = "".join(
        f'<li class="{"bb-ok" if c.ok else "bb-warn"}">'
        f'<span class="bb-mark">{"&#10003;" if c.ok else "!"}</span>'
        f"<span>{_bold(c.text)}</span></li>"
        for c in checks
    )
    return (
        '<div class="bb-card">'
        '<div class="bb-h2">Equilibrium and screening</div>'
        f'<ul class="bb-checks">{rows}</ul></div>'
    )


def peak_html(a: BoltAnalysis, names: BoltAnalysis | None = None) -> str:
    """Peak-moment callout.

    Args:
        a:     The analysis in force.
        names: Analysis to name the station from. The refined pass subdivides
               each plate into 24 strips, so `a` would call the peak "plate 36";
               pass the baseline, whose segments are the physical layers.
    """
    if abs(a.M_max.M) <= 1e-9:
        return '<p class="bb-peak">No bending moment with the loads entered.</p>'
    return (
        f'<p class="bb-peak">Peak moment <b>{sig(a.M_max.M)} lb&middot;in</b> '
        f"at x = {fmt(a.M_max.x, 3)} in, "
        f"{(names or a).layer_name_at(a.M_max.x)}.</p>"
    )


def figure_html(a: BoltAnalysis, groups=None, note: str = "",
                names: BoltAnalysis | None = None) -> str:
    """The joint elevation and both diagrams, plus the peak callout.

    Args:
        a:      The analysis actually in force — baseline or refined.
        groups: Physical layers, when `a`'s segments are subdivisions of them.
                Without this a refined analysis annotates every strip and the
                elevation grows 24 station ticks per plate.
        note:   Optional caption below the peak callout.
        names:  Analysis to name stations from — see `peak_html`.
    """
    return (
        '<div class="bb-card">'
        f'<div class="bb-fig">{joint_diagram_svg(a, groups)}</div>'
        f"{peak_html(a, names)}{note}</div>"
    )


def strength_html(m: Margins, a: BoltAnalysis, section: BoltSection,
                  names: BoltAnalysis | None = None) -> str:
    """The Strength card: the six-cell grid plus the governing-station note."""
    if m.valid:
        note = (
            f"Combined interaction governs at x = {fmt(m.critical.x, 3)} in "
            f"({(names or a).layer_name_at(m.critical.x)}), where "
            f"M = {sig(m.critical.M)} "
            f"lb&middot;in and V = {sig(m.critical.V)} lbf &mdash; scanned at "
            f"every station, not M<sub>max</sub> paired with V<sub>max</sub>."
        )
    else:
        note = (
            "Suppressed: the plate loads do not sum to zero, so the diagrams "
            "do not close and none of these numbers means anything."
        )
    note += (
        f" Section constant at d = {section.d_section:g} in: "
        f"Z = {section.Z:.6f} in&sup3;, A = {section.A:.5f} in&sup2;."
    )
    # Never leave a 33% factor implicit — say it is on and why, at the point
    # where the number it changed is displayed.
    kappa = m.allowables.shear_peak_factor
    if abs(kappa - 1.0) > 1e-9:
        note += (
            f" Shear is <b>{kappa:.3f} &times; V/A</b>: the chosen material's "
            f"F<sub>su</sub> is a material shear strength, so the check is "
            f"against the peak on a solid round, not the average. A fastener "
            f"allowable would use V/A directly."
        )
    return (
        '<div class="bb-card">'
        '<div class="bb-h2">Strength</div>'
        f"{results_html(m)}"
        f'<p class="bb-note">{note}</p></div>'
    )


def banner_html(a: BoltAnalysis) -> str:
    """The top-of-page suppression banner.

    Branches the same way `screening_checks` does. It used to state the ΣP
    message unconditionally, which read as "Plate loads sum to 0.0 lbf, not
    zero" on a stack that failed closure for a different reason.
    """
    if a.starved:
        which = ", ".join(str(i) for i in a.starved)
        plural = "s" if len(a.starved) > 1 else ""
        body = (
            f"<b>Layer{plural} {which} carr{'y' if plural else 'ies'} load but "
            f"ha{'ve' if plural else 's'} no thickness.</b> A layer with zero "
            "thickness applies no bearing, so its load never reaches the "
            "diagrams: they do not close and every stress and margin below is "
            "suppressed. Give it a thickness, or move the load to a layer that "
            "has one."
        )
    elif abs(a.sum_P) > a.imbalance_tol:
        body = (
            f"<b>Plate loads sum to {a.sum_P:,.1f} lbf, not zero</b> "
            f"(tolerance &plusmn;{a.imbalance_tol:,.1f} lbf). The shear diagram "
            "does not return to zero at the nut and M(L)&nbsp;&ne;&nbsp;0, so "
            "every stress and margin below is suppressed. Check for a missing "
            "layer or a sign flip &mdash; a real joint reacts the difference "
            "through faying-surface friction or restraint outside the grip, "
            "neither of which is modelled."
        )
    else:
        body = (
            f"<b>The diagrams do not close.</b> The loads sum to zero, but "
            f"V(L)&nbsp;=&nbsp;{a.closure_V:,.1f} lbf and "
            f"M(L)&nbsp;=&nbsp;{a.closure_M:,.1f} lb&middot;in, so some load is "
            "not reaching the bolt. Every stress and margin below is suppressed."
        )
    return f'<div class="bb-banner">{body}</div>'


# ══════════════════════════════════════════════════════════════════════════
# Refined bearing — the optional pass behind the sidebar toggle
# ══════════════════════════════════════════════════════════════════════════
def _refine(rows: list[dict], layers: list[Layer], section: BoltSection,
            close_moment: bool, E_bolt: float):
    """Run the refinement, or explain in one line why it was not run.

    Returns `(result, reason)` with exactly one of them set. Never raises and
    never silently falls back: if the refinement cannot run, the page shows
    the baseline AND says so, because a toggle that appears to be on while
    baseline numbers are displayed is the worst outcome available here.
    """
    plates = [ly for ly in layers if ly.kind == "plate" and ly.thickness > 0]
    if len(plates) < 2 or all(ly.load == 0 for ly in plates):
        return None, ("Needs at least two loaded plates — there is nothing to "
                      "redistribute. Showing the baseline.")
    Es, names = _plate_moduli(rows)
    try:
        return refined_analysis(
            layers, d_bolt=section.d_shank, E_bolt_msi=E_bolt,
            E_plate_msi=Es, plate_materials=names,
            close_moment=close_moment,
        ), ""
    except Exception as exc:                       # noqa: BLE001 — surface it
        return None, (f"The refined solve failed ({exc}). Showing the "
                      "baseline, which is unaffected and remains valid.")


# ══════════════════════════════════════════════════════════════════════════
# Stack editor — native widgets, in the sidebar
# ══════════════════════════════════════════════════════════════════════════
def _stack_editor(refine: bool) -> list[dict]:
    """Render one block of real widgets per layer and return the edited stack.

    `st.number_input` rather than `st.data_editor`: the stepper buttons and the
    scroll-wheel nudge come from the native number input, and a data-editor
    NumberColumn has neither.

    **Two lines per layer, two number inputs to a line.** Streamlit drops the
    steppers when an input's column gets narrow, and three-to-a-row in this
    sidebar was under that threshold — the whole reason for the rebuild was
    lost while the page still looked fine. Measured, not guessed; if this is
    ever re-compacted, re-check the steppers in a browser.

    A **gap gets no load field at all**, rather than a disabled or zeroed one.
    A spacer carries no bearing, so a load box next to it is an invitation to
    enter a number that the model will silently discard.
    """
    rows = _stack()

    for n, r in enumerate(rows):
        rid = r["id"]
        if n:
            _html('<div class="bb-layer-rule"></div>')

        # line 1 — what this layer is, and (when refining) what it is made of
        widths = (0.34, 0.52, 0.14) if refine else (0.86, 0.14)
        cols = st.columns(widths, vertical_alignment="center")

        r["kind"] = _TYPE_KINDS[cols[0].selectbox(
            "Type", list(_TYPE_LABELS.values()),
            index=list(_TYPE_KINDS).index(_TYPE_LABELS[r["kind"]]),
            key=f"bb::kind::{rid}", label_visibility="collapsed")]

        if refine:
            if r["kind"] == "plate":
                r["mat"] = cols[1].selectbox(
                    "Plate material", _plate_options(),
                    index=_plate_index(r.get("mat", _DEFAULT_PLATE)),
                    key=f"bb::mat::{rid}", label_visibility="collapsed",
                    help="Sets this plate's foundation modulus k = E. Each "
                         "plate gets its own bed — a steel doubler and an "
                         "aluminium skin do not share a bearing stiffness.")
            else:
                with cols[1]:
                    _html('<div class="bb-nogap">no bearing &mdash; '
                          "no bed</div>")

        cols[-1].button("✕", key=f"bb::rm::{rid}", help="Remove this layer",
                        on_click=_remove_layer, args=(rid,),
                        disabled=len(rows) <= 1)

        # line 2 — the numbers, two to a row so the steppers survive
        if r["kind"] == "plate":
            c_t, c_P = st.columns(2)
            r["t"] = c_t.number_input(
                "Thickness, in", min_value=0.0, step=0.005, format="%.3f",
                value=float(r["t"]), key=f"bb::t::{rid}")
            r["P"] = c_P.number_input(
                "Load, lbf", step=50.0, format="%.0f", value=float(r["P"]),
                key=f"bb::P::{rid}")
        else:
            # A gap has no load: no widget, no key, no label, no placeholder
            # holding an empty column. The thickness takes the whole row, and
            # there is simply nothing there to type a load into.
            r["P"] = 0.0
            r["t"] = st.number_input(
                "Thickness, in — a gap carries no bearing", min_value=0.0,
                step=0.005, format="%.3f", value=float(r["t"]),
                key=f"bb::t::{rid}")

    st.button("Add layer", on_click=_add_layer, width="stretch")
    return rows


# ══════════════════════════════════════════════════════════════════════════
# Sidebar — the original's "Bolt" card
# ══════════════════════════════════════════════════════════════════════════
def _material_options() -> list[str]:
    """Fasteners first — this is a bolt tool — then everything else."""
    grouped = list_by_category()
    fasteners = [m.name for m in grouped.get("Fastener", [])]
    others = [m.name for cat, mats in grouped.items() if cat != "Fastener"
              for m in mats]
    return fasteners + others + [_CUSTOM]


def _plate_options() -> list[str]:
    """Structural stock for the plates — fastener grades are not plate stock,
    so they are excluded rather than offered misleadingly."""
    grouped = list_by_category()
    return [m.name for cat, mats in grouped.items() if cat != "Fastener"
            for m in mats if m.E]


def _plate_index(name: str) -> int:
    """Index of a plate material, tolerating one that has left the library."""
    opts = _plate_options()
    return opts.index(name) if name in opts else 0


def _sidebar():
    """Every input, in decision order.

    Returns `(rows, section, allowables, close_moment, refine, E_bolt)`.

    **Bearing model leads.** It is the first decision — it changes the peak
    moment by ~15% and it changes what the stack editor below asks for (a
    per-plate material appears only when it is on), so it belongs above the
    thing it reconfigures rather than after it.

    The stack comes second: it moved here from the main column on 2026-09-04
    because it is a set-up input, typed once and then left alone while the
    diagrams are read, and moving it gave the figure the full page width.
    """
    with st.sidebar:
        _html('<div class="bb-h2">Bearing model</div>')
        refine = st.toggle(
            "Refine bearing distribution", value=False, key=_REFINE_KEY,
            help="Off: each plate's load spreads uniformly over its thickness "
                 "(conservative). On: a beam-on-elastic-foundation solve lets "
                 "the bolt bend in the hole, so bearing concentrates toward "
                 "the shear planes, and each plate below gets its own "
                 "material. The load split stays your input either way, and "
                 "the assumption in force is stated above the results.",
        )

        # Rendered before the stack, so the editor can just read the toggle's
        # return value. It previously had to peek at session state ahead of
        # the widget, because the toggle sat further down the sidebar.
        _html('<div class="bb-h2" style="margin-top:16px">Stack, head to nut</div>')
        rows = _stack_editor(refine)
        _html(
            '<p class="bb-note" style="margin:8px 0 2px;">Opposing sides of '
            "the load path take opposite signs, so the loads must sum to "
            "zero. A gap carries no bearing and takes no load.</p>"
        )

        _html('<div class="bb-h2" style="margin-top:16px">Bolt</div>')
        c1, c2 = st.columns(2)
        with c1:
            d_shank = st.number_input(
                "Shank dia, in", min_value=0.001, value=0.375, step=0.001,
                format="%.4f",
                help="Used for the grip/D screen. Stress uses the section "
                     "diameter.",
            )
        with c2:
            d_section = st.number_input(
                "Section dia, in", min_value=0.001, value=0.315, step=0.001,
                format="%.4f",
                help="Thread minor diameter, if threads or a runout fall near "
                     "the peak moment.",
            )
        use_section = st.checkbox(
            "Use section diameter for stress", value=True,
            help="Off: stress is taken on the full shank diameter.",
        )
        if not use_section:
            d_section = d_shank

        _html('<div class="bb-h2" style="margin-top:14px">Material</div>')
        if _MAT_KEY not in st.session_state:
            st.session_state[_MAT_KEY] = _DEFAULT_MATERIAL
        name = st.selectbox(
            "Bolt material", _material_options(), key=_MAT_KEY,
            on_change=_sync_allowables, label_visibility="collapsed",
            help="Fastener grades are strength LEVELS for preliminary sizing. "
                 "Confirm the actual part number and diameter against "
                 "MMPDS-01 Table 8.1.4 or the procurement spec before "
                 "releasing a stress report.",
        )
        mat = MATERIALS.get(name)
        if _FTU_KEY not in st.session_state:
            st.session_state[_FTU_KEY] = float(mat.Ftu) if mat and mat.Ftu else 160.0
            st.session_state[_FSU_KEY] = float(mat.Fsu) if mat and mat.Fsu else 95.0

        c3, c4 = st.columns(2)
        with c3:
            Ftu = st.number_input("Ftu, ksi", min_value=1.0, step=1.0,
                                  key=_FTU_KEY)
        with c4:
            Fsu = st.number_input("Fsu, ksi", min_value=1.0, step=1.0,
                                  key=_FSU_KEY)

        # What Fsu means depends on where it came from, and the difference is
        # worth 33% on the shear margin. A fastener grade is tabulated as
        # ultimate load over the shank area — already an average, so V/A is
        # the matching basis. Any other entry is a material shear strength and
        # must be compared against the peak.
        is_fastener = bool(mat and mat.category == "Fastener")
        kappa = 1.0 if (is_fastener or mat is None) else _ROUND_SHEAR_PEAK

        if mat is None:
            st.caption(
                "Custom — allowables come from the fields above, nothing is "
                "read from the library. Shear is checked as average V/A; if "
                "your Fsu is a material property rather than a fastener "
                "allowable, divide it by 1.333 first. E = 29.0 Msi is assumed "
                "for the refined solve."
            )
        elif not is_fastener:
            st.caption(
                f"⚠️ {name} is {mat.category.lower()} stock, not a fastener "
                f"grade — its Fsu is a material shear strength, so shear is "
                f"checked against the peak on a round section "
                f"(4/3 × V/A), not the average."
            )

        if mat and mat.Ftu is not None and mat.Fsu is not None:
            if abs(Ftu - mat.Ftu) > 1e-9 or abs(Fsu - mat.Fsu) > 1e-9:
                st.caption(
                    f"⚠️ Overridden — library values are Ftu {mat.Ftu:g}, "
                    f"Fsu {mat.Fsu:g} ksi."
                )
            elif mat.source:
                st.caption(mat.source)

        _html('<div class="bb-h2" style="margin-top:14px">Factors</div>')
        c5, c6 = st.columns(2)
        with c5:
            k = st.number_input(
                "Shape factor k", min_value=1.0, max_value=1.7, value=1.5,
                step=0.05,
                help="F_b = k · Ftu. A solid round is 1.7 fully plastic; 1.5 "
                     "is the usual defensible working value.",
            )
        with c6:
            FF = st.number_input(
                "Fitting factor", min_value=1.0, value=1.0, step=0.05,
                help="Applied to the applied stress, not to the allowable.",
            )

        close_moment = st.checkbox(
            "React leftover moment at head and nut", value=True,
            help="Applies the R0 / RL couple that closes the moment diagram. "
                 "Turn off to see the raw imbalance.",
        )

        st.button("Reset to the verification case", on_click=_reset,
                  width="stretch")

        # Bolt E comes from the chosen fastener material; fall back to steel.
        E_bolt = float(mat.E) if mat and mat.E else 29.0

    return (
        rows,
        BoltSection(d_shank=d_shank, d_section=d_section),
        Allowables(Ftu=Ftu, Fsu=Fsu, k_bending=k, fitting_factor=FF,
                   shear_peak_factor=kappa),
        close_moment,
        refine,
        E_bolt,
    )


# ══════════════════════════════════════════════════════════════════════════
# Page
# ══════════════════════════════════════════════════════════════════════════
def render() -> None:
    inject_css()
    _html(bolt_css())
    _html(header_html())

    rows, section, allow, close_moment, refine, E_bolt = _sidebar()

    layers = _layers_from_stack(rows)
    baseline = analyse(layers, close_moment=close_moment)

    # One analysis drives the whole page. The toggle chooses WHICH — it does
    # not add a parallel set of results, because two peak moments on one
    # screen is how the wrong one ends up in a report.
    result, reason = (None, "")
    if refine:
        result, reason = _refine(rows, layers, section, close_moment, E_bolt)

    a = result.refined if result else baseline
    m = margins(a, section, allow)

    if not m.valid:
        _html(banner_html(a))
    _html(refined_view.model_strip_html(result))
    if reason:
        st.warning(reason)

    # The stack moved to the sidebar, so the figure gets the width it wanted.
    _html(figure_html(
        a,
        groups=refined_view.groups(result) if result else None,
        note=refined_view.figure_note_html() if result else "",
        names=baseline,
    ))

    left, right = st.columns([0.38, 0.62], gap="medium")
    with left:
        _html(checks_html(screening_checks(a, section)))
    with right:
        _html(strength_html(m, a, section, names=baseline))

    # Basis, per-plate table and limits sit BELOW the numbers they qualify —
    # a less-conservative result must never appear without its justification.
    if result:
        for block in refined_view.supplement(result, section, allow):
            _html(block)

    _html(f'<div class="bb-card">{method_html(bool(result))}</div>')

    from version import version_string

    st.divider()
    _html(
        f"<p style='font-size:11px;color:{THEME.muted};text-align:center;'>"
        f"Stress Toolkit {version_string()} · Bolt Bending</p>"
    )
