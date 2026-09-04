"""
apps/bolt_bending/app.py

Streamlit UI for the Bolt Bending module.

Shear and moment diagrams along a bolt in a multi-layer joint, with strength
margins. All mechanics live in `library/bolt_bending/kernel.py`; the figure is
built by `plotting.py`, the derivation text by `method.py`, and the page CSS by
`styles.py`. This file is glue: session state, widgets, and layout.

Layout follows the original standalone tool (archived at
`docs/bolt_bending/index.html`) rather than the toolkit's tabbed page
furniture: **one page, nothing behind a tab.** The stack, the diagrams, the
margins and the screening checks are all visible at once, because the point of
the tool is changing a load and watching the moment peak and the margin move
together. Bolt properties — set once, rarely touched — go in the sidebar,
which lands at roughly the width of the original's left column.

⚠️ Rendering note: the figure is emitted with
`st.markdown(svg, unsafe_allow_html=True)`. Do NOT switch it to `st.html()`,
which sanitises with an HTML-only profile and silently drops SVG entirely,
leaving a blank column. There is a test pinning this.
"""

from __future__ import annotations

import math
import re

import pandas as pd
import streamlit as st

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
from library.materials import MATERIALS, list_by_category
from ui.styles import inject_css
from ui.theme import THEME

# ── session-state keys ────────────────────────────────────────────────────
_STACK_KEY = "boltbend::stack"
_REV_KEY = "boltbend::rev"
_MAT_KEY = "boltbend::material"
_FTU_KEY = "boltbend::Ftu"
_FSU_KEY = "boltbend::Fsu"

_DEFAULT_MATERIAL = "Alloy Steel Bolt 160 ksi"
_CUSTOM = "Custom — enter allowables"

_TYPE_LABELS = {"plate": "Plate", "gap": "Gap"}
_TYPE_KINDS = {v: k for k, v in _TYPE_LABELS.items()}


# ══════════════════════════════════════════════════════════════════════════
# State
# ══════════════════════════════════════════════════════════════════════════
def _stack_df() -> pd.DataFrame:
    """The live stack as a DataFrame, seeded with the verification case."""
    if _STACK_KEY not in st.session_state:
        st.session_state[_STACK_KEY] = pd.DataFrame(
            [
                {
                    "Type": _TYPE_LABELS[ly.kind],
                    "Thickness, in": ly.t,
                    "Load, lbf": ly.P,
                }
                for ly in default_stack()
            ]
        )
    return st.session_state[_STACK_KEY]


def _layers_from_df(df: pd.DataFrame) -> list[Layer]:
    """Convert the editor frame to kernel Layers.

    A gap's load is forced to zero by `Layer.load`, so a stale number left in
    the row after switching a plate to a gap cannot leak into the statics.
    """
    out: list[Layer] = []
    for _, row in df.iterrows():
        kind = _TYPE_KINDS.get(str(row.get("Type", "Plate")), "plate")
        t = row.get("Thickness, in")
        P = row.get("Load, lbf")
        t = 0.0 if t is None or (isinstance(t, float) and math.isnan(t)) else float(t)
        P = 0.0 if P is None or (isinstance(P, float) and math.isnan(P)) else float(P)
        out.append(Layer(kind=kind, t=t, P=P))
    return out


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

    The editor revision is bumped so `st.data_editor` gets a fresh widget key.
    Without that its stored edit delta would be replayed on top of the
    restored default and the reset would appear to do nothing.
    """
    for key in (_STACK_KEY, _MAT_KEY, _FTU_KEY, _FSU_KEY):
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
    if not m.valid:
        cells = [
            ("Bending stress", "&mdash;", "bb-void", ""),
            allowable,
            ("MS bending", "&mdash;", "bb-void", ""),
            ("Average shear", "&mdash;", "bb-void", ""),
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
            ("Average shear", sig(m.f_s), "", " <small>ksi</small>"),
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


def peak_html(a: BoltAnalysis) -> str:
    if abs(a.M_max.M) <= 1e-9:
        return '<p class="bb-peak">No bending moment with the loads entered.</p>'
    return (
        f'<p class="bb-peak">Peak moment <b>{sig(a.M_max.M)} lb&middot;in</b> '
        f"at x = {fmt(a.M_max.x, 3)} in, {a.layer_name_at(a.M_max.x)}.</p>"
    )


def figure_html(a: BoltAnalysis) -> str:
    """The joint elevation and both diagrams, plus the peak callout."""
    return (
        '<div class="bb-card">'
        f'<div class="bb-fig">{joint_diagram_svg(a)}</div>'
        f"{peak_html(a)}</div>"
    )


def strength_html(m: Margins, a: BoltAnalysis, section: BoltSection) -> str:
    """The Strength card: the six-cell grid plus the governing-station note."""
    if m.valid:
        note = (
            f"Combined interaction governs at x = {fmt(m.critical.x, 3)} in "
            f"({a.layer_name_at(m.critical.x)}), where M = {sig(m.critical.M)} "
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
    return (
        '<div class="bb-card">'
        '<div class="bb-h2">Strength</div>'
        f"{results_html(m)}"
        f'<p class="bb-note">{note}</p></div>'
    )


def banner_html(a: BoltAnalysis) -> str:
    return (
        '<div class="bb-banner">'
        f"<b>Plate loads sum to {a.sum_P:,.1f} lbf, not zero</b> "
        f"(tolerance &plusmn;{a.imbalance_tol:,.1f} lbf). The shear diagram "
        "does not return to zero at the nut and M(L)&nbsp;&ne;&nbsp;0, so every "
        "stress and margin below is suppressed. Check for a missing layer or a "
        "sign flip &mdash; a real joint reacts the difference through clamp-up "
        "friction or head and nut bearing, neither of which is modelled."
        "</div>"
    )


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


def _sidebar() -> tuple[BoltSection, Allowables, bool]:
    with st.sidebar:
        _html('<div class="bb-h2">Bolt</div>')
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

    return (
        BoltSection(d_shank=d_shank, d_section=d_section),
        Allowables(Ftu=Ftu, Fsu=Fsu, k_bending=k, fitting_factor=FF),
        close_moment,
    )


# ══════════════════════════════════════════════════════════════════════════
# Page
# ══════════════════════════════════════════════════════════════════════════
def render() -> None:
    inject_css()
    _html(bolt_css())
    _html(header_html())

    section, allow, close_moment = _sidebar()

    # The stack editor must run before the analysis, but the banner sits above
    # it. Reserve the slot now and fill it in afterwards — steadier than
    # writing session state and forcing a rerun, which would replay the
    # editor's stored delta onto the restored frame.
    banner_slot = st.container()

    left, right = st.columns([0.34, 0.66], gap="medium")

    # The stack editor is the one block that cannot be raw HTML — it is a live
    # widget — so it gets Streamlit's bordered container, restyled in
    # styles.py to match .bb-card.
    with left, st.container(border=True):
        _html('<div class="bb-h2">Stack, head to nut</div>')
        edited = st.data_editor(
            _stack_df(),
            # revision in the key so Reset drops the stored edit delta
            key=f"boltbend::editor::{st.session_state.get(_REV_KEY, 0)}",
            num_rows="dynamic",
            width="stretch",
            hide_index=True,
            column_config={
                "Type": st.column_config.SelectboxColumn(
                    "Type", options=list(_TYPE_LABELS.values()),
                    required=True, width="small",
                ),
                "Thickness, in": st.column_config.NumberColumn(
                    "Thickness", min_value=0.0, step=0.005, format="%.3f",
                ),
                "Load, lbf": st.column_config.NumberColumn(
                    "Load, lbf", step=50.0, format="%.0f",
                ),
            },
        )
        _html(
            '<p class="bb-note">Opposing sides of the load path take opposite '
            "signs, so the loads must sum to zero. A gap carries no bearing "
            "&mdash; its load is ignored.</p>"
        )

    a = analyse(_layers_from_df(edited), close_moment=close_moment)
    m = margins(a, section, allow)

    with left:
        _html(checks_html(screening_checks(a, section)))

    with right:
        _html(figure_html(a))

    with banner_slot:
        if not m.valid:
            _html(banner_html(a))

    _html(strength_html(m, a, section))
    _html(f'<div class="bb-card">{method_html()}</div>')

    from version import version_string

    st.divider()
    _html(
        f"<p style='font-size:11px;color:{THEME.muted};text-align:center;'>"
        f"Stress Toolkit {version_string()} · Bolt Bending</p>"
    )
