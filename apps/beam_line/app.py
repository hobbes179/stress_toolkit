"""
apps/beam_line/app.py

Streamlit UI for the Beam Diagrams module. The ONLY file in this module that
imports Streamlit; the mechanics live in `library/beam_line/`, the figure in
`plotting.py`, the Method text in `method.py` and the CSS in `styles.py`.

Conventions carried over from the bolt module, for the reasons recorded in
`apps/bolt_bending/CLAUDE.md`:

  * The page is never fragmented. Model, figure, peaks and reactions are all
    visible at once -- the point of the tool is moving a support and watching
    the moment peak move with it.
  * `st.number_input`, never `st.data_editor`: the stepper buttons and the
    scroll-wheel nudge come from the native input, and a NumberColumn has
    neither. Two number inputs to a row, maximum, or Streamlit drops the
    steppers when the column gets narrow.
  * Row widget keys are built from a stable row id, never the list position,
    or deleting row 1 replays row 2's stored value into it.
  * Session state is shape-checked, not presence-checked, so a browser holding
    a payload from a previous deploy is reseeded rather than crashing.
  * Render HTML with `st.markdown(..., unsafe_allow_html=True)`, never
    `st.html()` -- the latter strips `<svg>` silently and the figure column
    just comes out blank.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from apps.beam_line.method import method_html
from apps.beam_line.plotting import figure_svg, sig, station
from apps.beam_line.styles import beam_css
from library.beam_line import (
    MAX_ENVELOPE_LOADS,
    Beam,
    DistributedLoad,
    Hinge,
    PointLoad,
    PointMoment,
    Support,
    analyse,
    load_envelope,
)
from ui.handoff import read_section
from ui.styles import inject_css

# ---- session keys. Everything under `bl::` is this module's. --------------
_SUP_KEY = "bl::supports"
_LOAD_KEY = "bl::loads"
_HINGE_KEY = "bl::hinges"
_NEXT_ID = "bl::next_id"

SUPPORT_KINDS = ("Pin / roller", "Fixed", "Guided", "Spring")
LOAD_KINDS = ("Point force", "Moment", "Distributed")


# ==========================================================================
# Defaults and state
# ==========================================================================
def _default_span() -> float:
    return 120.0


def _default_supports() -> list[dict]:
    return [
        {"id": 1, "x": 0.0, "kind": "Pin / roller", "ky": 10000.0,
         "krz": 0.0, "dy": 0.0, "drz": 0.0, "on": True},
        {"id": 2, "x": 120.0, "kind": "Pin / roller", "ky": 10000.0,
         "krz": 0.0, "dy": 0.0, "drz": 0.0, "on": True},
    ]


def _default_loads() -> list[dict]:
    return [
        {"id": 11, "kind": "Distributed", "x": 0.0, "x2": 120.0,
         "P": -500.0, "M": 0.0, "w1": -8.0, "w2": -8.0, "on": True},
        {"id": 12, "kind": "Point force", "x": 40.0, "x2": 60.0,
         "P": -600.0, "M": 0.0, "w1": -10.0, "w2": -10.0, "on": True},
    ]


# Every row carries `on`. Adding it to the shape check is deliberate: a
# browser holding pre-toggle rows fails the check and is reseeded, which is
# right. Defaulting the field in instead would silently leave those rows in a
# state the widget cannot represent.
_SUP_FIELDS = {"id", "x", "kind", "ky", "krz", "dy", "drz", "on"}
_LOAD_FIELDS = {"id", "kind", "x", "x2", "P", "M", "w1", "w2", "on"}
_HINGE_FIELDS = {"id", "x", "on"}


def _rows(key: str, default, fields: set[str]) -> list[dict]:
    """Shape-checked row list. A payload written by an older deploy is
    replaced rather than allowed to crash the page on its next rerun."""
    raw: Any = st.session_state.get(key)
    ok = (isinstance(raw, list)
          and all(isinstance(r, dict) and fields <= set(r) for r in raw))
    if not ok:
        st.session_state[key] = default()
    return st.session_state[key]


def _new_id() -> int:
    n = st.session_state.get(_NEXT_ID)
    if not isinstance(n, int):
        n = 100
    st.session_state[_NEXT_ID] = n + 1
    return n


def _reset() -> None:
    """Back to the shipped default beam.

    Every per-row widget key has to go too. A surviving `bl::sx::3` would be
    replayed into the rebuilt row and the reset would appear to do nothing for
    that field.
    """
    for k in [k for k in st.session_state if str(k).startswith("bl::")]:
        st.session_state.pop(k, None)


def _html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


@st.cache_data(show_spinner=False, max_entries=32)
def _cached_envelope(key: str, _beam: Beam):
    """Envelope over every load combination, for the model as built.

    Cached on the FULL model, which is exactly what makes the locked scale
    free to use: the envelope does not depend on which loads are currently
    switched on, so flipping a switch is a cache hit and costs nothing. It is
    recomputed only when the beam itself changes.

    `_beam` is underscore-prefixed so Streamlit does not try to hash it; `key`
    is the cache identity.
    """
    return load_envelope(_beam)


def _full_model(beam: Beam, ghost: Beam) -> Beam:
    """Active model plus the switched-off loads, on the ACTIVE supports.

    Supports are deliberately not merged in: the response is linear in the
    loads but not in the structure, so a different support arrangement gets
    its own envelope. Switching a support is allowed to move the scale;
    switching a load is not.
    """
    from dataclasses import replace
    return replace(
        beam,
        point_loads=beam.point_loads + ghost.point_loads,
        moments=beam.moments + ghost.moments,
        distributed=beam.distributed + ghost.distributed,
    )


def _on_switch(col, r: dict, key: str, first: bool, what: str) -> bool:
    """The per-row include/exclude switch.

    A checkbox rather than `st.toggle`: it is narrower, and this sits in a row
    that already holds a number input whose stepper buttons need the width.

    The row's inputs stay EDITABLE while it is off, so a load can be dialled in
    before being switched back on. Switching off is not a soft delete -- the
    row keeps its place and its values, and the item is drawn ghosted in the
    elevation so it cannot be forgotten.
    """
    if first:
        col.markdown("<div style='height:28px'></div>",
                     unsafe_allow_html=True)
    r["on"] = col.checkbox(
        "on", value=bool(r.get("on", True)), key=key,
        label_visibility="collapsed",
        help=f"Include this {what} in the analysis",
    )
    return bool(r["on"])


# ==========================================================================
# Sidebar
# ==========================================================================
def _stiffness_inputs() -> tuple[float, str, bool]:
    """Return (EI in lb-in^2, a description of where it came from, inherited).

    Manual E and I are the default and always available. The section handoff
    is offered only when the Beam Section Stress page has actually published
    one in this browser session, because a toggle that is usually inert is
    worse than no toggle.
    """
    snap = read_section()
    use_section = False
    if snap is not None:
        use_section = st.toggle(
            "Use the section from Beam Section Stress",
            value=st.session_state.get("bl::use_section", False),
            key="bl::use_section",
            help="Snapshot of the section that page last built in this "
                 "browser session — not a live link.",
        )

    if snap is not None and use_section:
        axis = st.radio(
            "Bending axis", ["Iy (loads in the vertical plane)",
                             "Iz (loads in the horizontal plane)"],
            key="bl::axis", label_visibility="collapsed",
        )
        I = snap.Iy if axis.startswith("Iy") else snap.Iz
        Iname = "Iy" if axis.startswith("Iy") else "Iz"
        EI = snap.E * I
        st.caption(f"{snap.label} · E = {snap.E / 1e6:,.2f} Msi · "
                   f"{Iname} = {I:,.4f} in⁴")
        return EI, (f"{snap.shape}, {snap.material} — E = "
                    f"{snap.E / 1e6:,.2f} Msi, {Iname} = {I:,.4f} in⁴"), True

    c1, c2 = st.columns(2)
    E = c1.number_input("E (Msi)", value=10.0, min_value=0.001, step=0.5,
                        format="%.3f", key="bl::E")
    I = c2.number_input("I (in⁴)", value=10.0, min_value=1e-9, step=1.0,
                        format="%.4f", key="bl::I")
    if snap is not None:
        st.caption(f"Available from Beam Section Stress: {snap.label}")
    return (E * 1.0e6 * I,
            f"E = {E:,.3f} Msi, I = {I:,.4f} in⁴ (entered directly)", False)


def _support_editor(L: float, show_move: bool
                    ) -> tuple[list[Support], list[Support]]:
    """Returns (active, switched-off)."""
    rows = _rows(_SUP_KEY, _default_supports, _SUP_FIELDS)
    out: list[Support] = []
    off: list[Support] = []
    drop: int | None = None

    for i, r in enumerate(rows):
        rid = r["id"]
        if i:
            _html('<div class="bl-row-rule"></div>')
        # Widths measured in a browser: the switch and the delete
        # button are trimmed to whatever they actually need so the x
        # input keeps room for "120.0000" AND its stepper buttons.
        c0, c1, c2, c3 = st.columns([0.26, 1.30, 1.20, 0.32])
        on = _on_switch(c0, r, f"bl::son::{rid}", not i, "support")
        r["x"] = c1.number_input(
            "x (in)", value=float(r["x"]), step=1.0, format="%.4f",
            key=f"bl::sx::{rid}", label_visibility="visible" if not i else "collapsed",
        )
        r["kind"] = c2.selectbox(
            "Restraint", SUPPORT_KINDS,
            index=SUPPORT_KINDS.index(r["kind"]) if r["kind"] in SUPPORT_KINDS else 0,
            key=f"bl::sk::{rid}",
            label_visibility="visible" if not i else "collapsed",
        )
        if not i:
            c3.markdown("<div style='height:28px'></div>",
                        unsafe_allow_html=True)
        if c3.button("✕", key=f"bl::sd::{rid}", help="Remove this support"):
            drop = i

        if r["kind"] == "Spring":
            k1, k2 = st.columns(2)
            r["ky"] = k1.number_input(
                "kᵥ (lb/in)", value=float(r["ky"]), min_value=0.0, step=1000.0,
                format="%.1f", key=f"bl::sky::{rid}")
            r["krz"] = k2.number_input(
                "k𝜃 (lb·in/rad)", value=float(r["krz"]), min_value=0.0,
                step=10000.0, format="%.1f", key=f"bl::skr::{rid}")
        if show_move:
            m1, m2 = st.columns(2)
            r["dy"] = m1.number_input(
                "Δ settlement (in)", value=float(r["dy"]), step=0.01,
                format="%.5f", key=f"bl::sdy::{rid}")
            r["drz"] = m2.number_input(
                "φ rotation (rad)", value=float(r["drz"]), step=0.001,
                format="%.6f", key=f"bl::sdr::{rid}")

        kind = r["kind"]
        if kind == "Fixed":
            uy, rz = "rigid", "rigid"
        elif kind == "Guided":
            uy, rz = "none", "rigid"
        elif kind == "Spring":
            uy = "spring"
            rz = "spring" if float(r["krz"]) > 0 else "none"
        else:
            uy, rz = "rigid", "none"
        (out if on else off).append(
            Support(float(r["x"]), uy, rz, float(r["ky"]), float(r["krz"]),
                    float(r["dy"]), float(r["drz"])))

    if drop is not None:
        rows.pop(drop)
        st.rerun()

    if st.button("＋ Add support", key="bl::sadd", width="stretch"):
        rows.append({"id": _new_id(), "x": round(L / 2, 4),
                     "kind": "Pin / roller", "ky": 10000.0, "krz": 0.0,
                     "dy": 0.0, "drz": 0.0, "on": True})
        st.rerun()
    return out, off


def _load_editor(L: float):
    """Returns (point loads, moments, patches, switched-off counterparts)."""
    rows = _rows(_LOAD_KEY, _default_loads, _LOAD_FIELDS)
    pts: list[PointLoad] = []
    mts: list[PointMoment] = []
    dst: list[DistributedLoad] = []
    off_p: list[PointLoad] = []
    off_m: list[PointMoment] = []
    off_d: list[DistributedLoad] = []
    drop: int | None = None

    for i, r in enumerate(rows):
        rid = r["id"]
        if i:
            _html('<div class="bl-row-rule"></div>')
        c0, c1, c2 = st.columns([0.32, 2.0, 0.4])
        on = _on_switch(c0, r, f"bl::lon::{rid}", not i, "load")
        r["kind"] = c1.selectbox(
            "Load type", LOAD_KINDS,
            index=LOAD_KINDS.index(r["kind"]) if r["kind"] in LOAD_KINDS else 0,
            key=f"bl::lk::{rid}",
            label_visibility="visible" if not i else "collapsed",
        )
        if not i:
            c2.markdown("<div style='height:28px'></div>",
                        unsafe_allow_html=True)
        if c2.button("✕", key=f"bl::ld::{rid}", help="Remove this load"):
            drop = i

        kind = r["kind"]
        if kind == "Point force":
            a, b = st.columns(2)
            r["x"] = a.number_input("x (in)", value=float(r["x"]), step=1.0,
                                    format="%.4f", key=f"bl::lx::{rid}")
            r["P"] = b.number_input("P (lb, + up)", value=float(r["P"]),
                                    step=50.0, format="%.2f",
                                    key=f"bl::lp::{rid}")
            (pts if on else off_p).append(
                PointLoad(float(r["x"]), float(r["P"])))
        elif kind == "Moment":
            a, b = st.columns(2)
            r["x"] = a.number_input("x (in)", value=float(r["x"]), step=1.0,
                                    format="%.4f", key=f"bl::mx::{rid}")
            r["M"] = b.number_input("M (lb·in, + CCW)", value=float(r["M"]),
                                    step=500.0, format="%.2f",
                                    key=f"bl::mm::{rid}")
            (mts if on else off_m).append(
                PointMoment(float(r["x"]), float(r["M"])))
        else:
            a, b = st.columns(2)
            r["x"] = a.number_input("x₁ (in)", value=float(r["x"]), step=1.0,
                                    format="%.4f", key=f"bl::dx1::{rid}")
            r["x2"] = b.number_input("x₂ (in)", value=float(r["x2"]), step=1.0,
                                     format="%.4f", key=f"bl::dx2::{rid}")
            c, d = st.columns(2)
            r["w1"] = c.number_input("w₁ (lb/in, + up)", value=float(r["w1"]),
                                     step=1.0, format="%.4f",
                                     key=f"bl::dw1::{rid}")
            r["w2"] = d.number_input("w₂ (lb/in, + up)", value=float(r["w2"]),
                                     step=1.0, format="%.4f",
                                     key=f"bl::dw2::{rid}")
            (dst if on else off_d).append(
                DistributedLoad(float(r["x"]), float(r["x2"]),
                                float(r["w1"]), float(r["w2"])))

    if drop is not None:
        rows.pop(drop)
        st.rerun()

    a, b, c = st.columns(3)
    if a.button("＋ Point", key="bl::ladd_p", width="stretch"):
        rows.append({"id": _new_id(), "kind": "Point force",
                     "x": round(L / 2, 4), "x2": round(L, 4), "P": -500.0,
                     "M": 0.0, "w1": -10.0, "w2": -10.0, "on": True})
        st.rerun()
    if b.button("＋ Moment", key="bl::ladd_m", width="stretch"):
        rows.append({"id": _new_id(), "kind": "Moment",
                     "x": round(L / 2, 4), "x2": round(L, 4), "P": 0.0,
                     "M": 5000.0, "w1": -10.0, "w2": -10.0, "on": True})
        st.rerun()
    if c.button("＋ Dist.", key="bl::ladd_d", width="stretch"):
        rows.append({"id": _new_id(), "kind": "Distributed", "x": 0.0,
                     "x2": round(L, 4), "P": 0.0, "M": 0.0,
                     "w1": -10.0, "w2": -10.0, "on": True})
        st.rerun()
    return (tuple(pts), tuple(mts), tuple(dst),
            tuple(off_p), tuple(off_m), tuple(off_d))


def _hinge_editor(L: float) -> tuple[tuple[Hinge, ...], tuple[Hinge, ...]]:
    """Returns (active, switched-off)."""
    rows = _rows(_HINGE_KEY, list, _HINGE_FIELDS)
    out: list[Hinge] = []
    drop: int | None = None
    off: list[Hinge] = []
    for i, r in enumerate(rows):
        rid = r["id"]
        c0, c1, c2 = st.columns([0.32, 2.0, 0.4])
        on = _on_switch(c0, r, f"bl::hon::{rid}", not i, "hinge")
        r["x"] = c1.number_input("x (in)", value=float(r["x"]), step=1.0,
                                 format="%.4f", key=f"bl::hx::{rid}",
                                 label_visibility="visible" if not i
                                 else "collapsed")
        if not i:
            c2.markdown("<div style='height:28px'></div>",
                        unsafe_allow_html=True)
        if c2.button("✕", key=f"bl::hd::{rid}", help="Remove this hinge"):
            drop = i
        (out if on else off).append(Hinge(float(r["x"])))
    if drop is not None:
        rows.pop(drop)
        st.rerun()
    if st.button("＋ Add hinge", key="bl::hadd", width="stretch"):
        rows.append({"id": _new_id(), "x": round(L / 2, 4), "on": True})
        st.rerun()
    return tuple(out), tuple(off)


# ==========================================================================
# Main-column HTML blocks
# ==========================================================================
def model_strip_html(desc: str, inherited: bool) -> str:
    tag = "SECTION" if inherited else "STIFFNESS"
    cls = "bl-model bl-inherited" if inherited else "bl-model"
    extra = ("  This is a snapshot of what that page last built in this "
             "browser session, not a live link — change the section there and "
             "it updates on this page's next run."
             if inherited else
             "  Enter the section on the Beam Section Stress page and switch "
             "the toggle above to pull E and I from it instead.")
    return (f'<div class="{cls}"><span class="bl-tag">{tag}</span>'
            f'<b>{desc}</b>.{extra}</div>')


def excluded_html(ghost: Beam) -> str:
    """Name every switched-off item, directly beneath the figure.

    Not optional furniture. This figure and these numbers get screenshotted
    into stress reports, and a load that is simply absent from the picture is
    one nobody notices is missing. Switching an item off has to be visible in
    the output, not only in the sidebar that produced it.

    It sits BELOW the figure rather than above it because it appears and
    disappears as items are switched, and anything above the figure that
    changes height makes the plots jump on every toggle.
    """
    items: list[str] = []
    for sup in ghost.supports:
        items.append(f"{sup.kind.lower()} support at x = {station(sup.x)}")
    for pl in ghost.point_loads:
        items.append(f"{sig(pl.P)} lb at x = {station(pl.x)}")
    for mm in ghost.moments:
        items.append(f"{sig(mm.M)} lb·in at x = {station(mm.x)}")
    for d in ghost.distributed:
        items.append(f"{d.shape} load, x = {station(d.x1)} to "
                     f"{station(d.x2)}")
    for h in ghost.hinges:
        items.append(f"hinge at x = {station(h.x)}")
    if not items:
        return ""
    n = len(items)
    return ('<div class="bl-banner bl-warn bl-excl"><b>'
            f'{n} item{"s" if n > 1 else ""} switched off</b> and excluded '
            "from these results: " + "; ".join(items)
            + ". They are drawn ghosted on the elevation above.</div>")


def banner_html(errors: list[str], sol, dg) -> str:
    if errors:
        items = "".join(f"<li>{e}</li>" for e in errors)
        return ('<div class="bl-banner"><b>The model is not well formed.</b>'
                f'<ul style="margin:6px 0 0;padding-left:18px">{items}</ul>'
                "</div>")
    if sol is not None and not sol.stable:
        return ('<div class="bl-banner"><b>Unstable — no results.</b> '
                f'{sol.message} '
                "<br><span style='font-size:12px'>The elevation below is your "
                "input; the diagrams are suppressed because a diagram drawn "
                "for a mechanism would look plausible and be meaningless."
                "</span></div>")
    if dg is not None and not dg.valid:
        return f'<div class="bl-banner"><b>Solve failed.</b> {dg.message}</div>'
    return ""


def _clean(v: float, ref: float) -> float:
    """Snap a rounding-floor value to exactly zero.

    A beam under self-cancelling couples carries a shear of 1e-13, and
    "-1.14e-13 lb" reads as a real measurement with an odd exponent rather
    than as nothing. Judged against the applied loading, never against the
    value itself -- the self-relative test is what fails here, because the
    value IS the rounding floor.

    Deliberately NOT applied to the Residual row or the Solve-quality note:
    showing the true size of the closure residue is the entire point of
    those, and cleaning them would hide the evidence the gate rests on.
    """
    return 0.0 if abs(v) <= 1.0e-9 * ref else v


def peaks_html(beam: Beam, dg) -> str:
    """Peak summary.

    Shear and moment carry both signed extremes, because the positive and
    negative envelopes are separately meaningful -- a hogging moment over a
    support is checked against a different fibre than the sagging peak.

    Deflection does not: on almost every beam one of its two extremes is the
    trivial zero at a support, so a signed pair wastes a cell on "0 at x = 0".
    It reports the largest magnitude and the span-to-deflection ratio instead,
    which is the form a deflection limit is actually written in.
    """
    ref_F, ref_M = beam.load_scale()
    cells = []
    for field, label, unit, cls, ref in (
        ("V", "Shear", "lb", "bl-shear", ref_F),
        ("M", "Moment", "lb·in", "bl-moment", ref_M),
    ):
        hi, lo, _ = dg.extremes(field)
        for ex, name in ((hi, "max"), (lo, "min")):
            val = _clean(ex.value, ref)
            cells.append(
                f"<div><dt>{label} {name}</dt>"
                f"<dd class='{cls}'>{sig(val)} <small>{unit}</small><br>"
                f"<small>at x = {station(ex.x)} in</small></dd></div>"
            )

    _, _, mag = dg.extremes("d")
    cells.append(
        "<div><dt>Deflection peak</dt>"
        f"<dd class='bl-deflect'>{mag.value:,.5f} <small>in</small><br>"
        f"<small>at x = {station(mag.x)} in</small></dd></div>"
    )
    if abs(mag.value) > 0:
        ratio = f"L / {beam.L / abs(mag.value):,.0f}"
        sub = f"span {station(beam.L)} in"
    else:
        ratio = "—"
        sub = "no deflection"
    cells.append(
        "<div><dt>Span / deflection</dt>"
        f"<dd class='bl-deflect'>{ratio}<br><small>{sub}</small></dd></div>"
    )
    return f'<dl class="bl-res">{"".join(cells)}</dl>'


def reactions_html(beam: Beam, sol) -> str:
    rows = []
    sum_F = 0.0
    sum_M = 0.0
    ref_F, ref_M = beam.load_scale()
    dash = "<span class='bl-dim'>—</span>"
    for r in sol.reactions:
        # The sums use the RAW values; only the display is cleaned, so the
        # Residual row still reports the true closure.
        sum_F += r.Fy
        sum_M += r.Mz + r.Fy * r.x
        cf, cm = _clean(r.Fy, ref_F), _clean(r.Mz, ref_M)
        fy = sig(cf) if cf else dash
        mz = sig(cm) if cm else dash
        rows.append(f"<tr><td>{station(r.x)}</td><td>{r.kind}</td>"
                    f"<td>{fy}</td><td>{mz}</td></tr>")
    net_F = beam.total_applied_force + sum_F
    net_M = beam.total_applied_moment_about(0.0) + sum_M
    return (
        '<table class="bl-tbl"><thead><tr>'
        "<th>x (in)</th><th>Restraint</th><th>Fᵧ (lb)</th>"
        "<th>Mz (lb·in)</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "<tfoot><tr><td>Residual</td><td>loads + reactions</td>"
        f"<td>{net_F:,.3g}</td><td>{net_M:,.3g}</td></tr></tfoot></table>"
    )


def quality_html(dg) -> str:
    return (
        '<p class="bl-note"><b>Solve quality.</b> '
        f"Shear closes to {dg.closure_V:.2e} lb and moment to "
        f"{dg.closure_M:.2e} lb·in past the last support; integrating the "
        f"curvature forward reproduces every solved node to "
        f"{dg.residual:.2e} relative. Results are suppressed above "
        "10⁻⁶ on any of the three — see Method §8.</p>"
    )


# ==========================================================================
# Page
# ==========================================================================
def render() -> None:
    inject_css()
    _html(beam_css())

    with st.sidebar:
        st.markdown("### Beam")
        L = st.number_input("Span L (in)", value=_default_span(),
                            min_value=1e-6, step=6.0, format="%.4f",
                            key="bl::L")
        EI, ei_desc, inherited = _stiffness_inputs()

        st.markdown("### Supports")
        show_move = st.checkbox(
            "Prescribed support movement", value=False, key="bl::showmove",
            help="Settlement or imposed rotation. Induces no internal load "
                 "on a determinate beam; induces real moments on an "
                 "indeterminate one.")
        supports, off_sup = _support_editor(L, show_move)

        st.markdown("### Loads")
        pts, mts, dst, off_p, off_m, off_d = _load_editor(L)

        st.markdown("### Releases")
        hinges, off_h = _hinge_editor(L)

        st.markdown("---")
        lock_scale = st.checkbox(
            "Lock diagram scale", value=True, key="bl::lockscale",
            help="Scale each diagram to the envelope of every load "
                 "combination, so switching a load off shrinks the curve "
                 "instead of rescaling the axis under it. Costs one solve "
                 f"per load (up to {MAX_ENVELOPE_LOADS}), cached.")
        if st.button("Reset to default beam", key="bl::reset",
                     width="stretch"):
            _reset()
            st.rerun()

    beam = Beam(L, EI, tuple(supports), pts, mts, dst, hinges)
    # The switched-off items, assembled only so the figure can ghost them and
    # the page can name them. This is never solved.
    ghost = Beam(L, EI, tuple(off_sup), off_p, off_m, off_d, off_h)
    errors, sol, dg = analyse(beam)

    env = None
    if lock_scale and not errors:
        full = _full_model(beam, ghost)
        env = _cached_envelope(repr(full), full)

    _html(
        '<div class="bl-header"><h1>Beam Diagrams</h1>'
        "<p>Shear, moment and deflection along a line beam — arbitrary "
        "supports, releases and loads, determinate or indeterminate.</p></div>"
    )
    _html(model_strip_html(ei_desc, inherited))

    banner = banner_html(errors, sol, dg)
    if banner:
        _html(banner)

    # The excluded-items notice goes BELOW the figure, inside its card.
    #
    # Above it, the notice appears and disappears as loads are switched, and
    # the whole plot stack jumps down and back by its height -- which destroys
    # the one interaction this feature exists for: flipping a load on and off
    # and watching the diagrams change in place. Nothing rendered above the
    # figure may change height on a load toggle.
    _html('<div class="bl-card">'
          f'<div class="bl-fig">{figure_svg(beam, sol, dg, ghost, env)}</div>'
          f"{excluded_html(ghost)}</div>")

    if not errors and sol is not None and sol.stable and dg is not None \
            and dg.valid:
        left, right = st.columns([1.15, 1.0])
        with left:
            _html('<div class="bl-card"><div class="bl-h2">Peak values</div>'
                  f"{peaks_html(beam, dg)}</div>")
        with right:
            _html('<div class="bl-card"><div class="bl-h2">Reactions</div>'
                  f"{reactions_html(beam, sol)}{quality_html(dg)}</div>")

    with st.expander("Method, assumptions and limits", expanded=False):
        _html(method_html())

    from version import version_string
    _html(
        "<p style='text-align:center;font-size:11px;opacity:.55;"
        f"margin-top:22px'>Stress Toolkit {version_string()} · "
        "Beam Diagrams</p>"
    )
