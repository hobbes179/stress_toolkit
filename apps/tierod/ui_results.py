"""
Results presentation for the tie-rod module — Phase 1.

Split the same way `ui_inputs` is:

* **Pure frame builders** (`results_frame`, `case_frame`, `summary`, `fmt`) —
  no Streamlit, no session state, so what the table SAYS is unit-testable.
* **Widget renderers** (`safety_factor_inputs`, `results_tab`) — Streamlit only.

What the table has to get right, and what the tests gate:

* The governing load is the **closed form** `||t_i||_2`, never the maximum over
  the enumerated cases. The case name beside it is a label for the nearest
  sampled direction, with the angle to it, so the sampling shortfall is on the
  page instead of buried in a docstring. Reporting the sample as the envelope
  under-predicts by up to 11% with `cube26`, and nothing about the table would
  look wrong.
* **Which allowable is active** per rod (§6.1). A margin computed off the
  `A_net * Ftu` fallback when a vendor rating was intended survives review.
* Rods whose margin does not cover every limit state are named, not quietly
  reported as if complete.
"""

from __future__ import annotations

import numpy as np
import streamlit as st

from apps.tierod import ui_scene
from library.tierod import allowables as al
from library.tierod import sweep as sw

__all__ = [
    "fmt",
    "results_frame",
    "case_frame",
    "summary",
    "safety_factor_inputs",
    "results_tab",
]

DASH = "—"


# ----------------------------------------------------------------------
# Pure frame builders
# ----------------------------------------------------------------------


def fmt(x, nd: int = 3) -> str:
    """A missing number must never render as a computed one."""
    if x is None:
        return DASH
    x = float(x)
    if not np.isfinite(x):
        return "∞" if x > 0 else DASH
    return f"{x:.{nd}f}"


def results_frame(result: sw.SweepResult) -> list[dict]:
    """One row per rod, already in governing order (worst load ratio first)."""
    rows = []
    for r in result.rows:
        rows.append(
            {
                "rod": r.rod_id,
                "sense": r.sense,
                "P (lb)": r.P_envelope,
                "worst direction": (
                    f"{r.nearest_case}  ({r.nearest_case_angle:.0f}° off)"
                ),
                "allowable (lb)": r.allowable,
                "source": r.allowable_source,
                "LR": r.load_ratio,
                "MS": r.margin,
                "L (in)": r.L,
                "λ": r.column.lam,
                "sample (lb)": r.P_enumerated,
                "sample case": r.governing_case,
            }
        )
    return rows


def case_frame(result: sw.SweepResult, rod_id: str) -> list[dict]:
    """Every enumerated case for one rod, worst first.

    The `% of envelope` column is the honest one: it shows how close the
    readable sample gets to the closed form for THIS rod.
    """
    if rod_id not in result.rod_ids:
        raise KeyError(f"no result for rod {rod_id!r}")
    i = result.rod_ids.index(rod_id)
    envelope = float(result.env.magnitudes[i])
    rows = []
    for j, case in enumerate(result.cases):
        P = float(result.P_cases[i, j])
        rows.append(
            {
                "case": case.name,
                "direction": np.array2string(case.direction, precision=3),
                "P (lb)": P,
                "sense": "T" if P > 0 else ("C" if P < 0 else DASH),
                "% of envelope": (
                    100.0 * abs(P) / envelope if envelope > 0.0 else 0.0
                ),
            }
        )
    rows.sort(key=lambda r: -abs(r["P (lb)"]))
    return rows


def summary(result: sw.SweepResult) -> dict:
    """The headline numbers, computed once so the metrics and the prose agree."""
    rows = result.rows
    margins = [r.margin for r in rows if r.margin is not None]
    return {
        "governing_rod": rows[0].rod_id if rows else None,
        "governing_lr": rows[0].load_ratio if rows else None,
        "worst_margin": min(margins) if margins else None,
        "n_negative": sum(1 for m in margins if m < 0.0),
        "n_rods": len(rows),
        "worst_sample_shortfall": (
            max(r.sample_shortfall for r in rows) if rows else 0.0
        ),
        "incomplete": list(result.incomplete_rods),
    }


# ----------------------------------------------------------------------
# Widget renderers
# ----------------------------------------------------------------------


def safety_factor_inputs() -> al.SafetyFactors:
    """The two factors, as editable cells with defaults.

    They are inputs, not constants: the library defaults them to 1.0 / 1.5 and
    nothing else in the code hardcodes either number.
    """
    c1, c2 = st.columns(2)
    yield_ = c1.number_input(
        "SF yield", min_value=0.01, value=1.0, step=0.05, key="tierod::sf_yield",
        help="Applied to the load against the yield allowables (A·Fty, A·Fcy).",
    )
    ultimate = c2.number_input(
        "SF ultimate", min_value=0.01, value=1.5, step=0.05, key="tierod::sf_ult",
        help="Applied to the load against the ultimate allowables (vendor "
             "rating or A_net·Ftu, and the Euler/Johnson column allowable).",
    )
    return al.SafetyFactors(ultimate=float(ultimate), yield_=float(yield_))


def _metric_row(s: dict) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Governing rod", s["governing_rod"] or DASH)
    c2.metric("Worst MS", fmt(s["worst_margin"]))
    c3.metric("Rods with MS < 0", s["n_negative"])
    c4.metric("Sample shortfall", f"{100.0 * s['worst_sample_shortfall']:.1f}%")


def results_tab(assembly, result: sw.SweepResult, static=None) -> None:
    """The Phase-1 results page: margins, the scene coloured by load ratio, and
    the per-rod case breakdown."""
    import pandas as pd

    s = summary(result)
    _metric_row(s)

    if s["n_negative"]:
        st.error(
            f"{s['n_negative']} rod(s) have no margin under the full "
            f"orientation sweep. Governing: **{s['governing_rod']}**."
        )
    elif s["governing_rod"]:
        st.success(
            f"Every rod has positive margin. Governing: "
            f"**{s['governing_rod']}** at MS {fmt(result.rows[0].margin)}."
        )

    if s["incomplete"]:
        st.warning(
            "No tension allowable for: **" + ", ".join(s["incomplete"]) + "**. "
            "Their margins come off the compression side alone — enter a vendor "
            "rating, or A_net and Ftu, in the rod editor. A compression-only "
            "margin looks exactly like a complete one in this table."
        )

    st.caption(
        f"`P` is the **closed-form envelope** ‖t‖₂ over ALL load orientations, "
        f"not the worst of the {len(result.cases)} enumerated cases — the "
        f"enumerated set is a readable sample of the sphere and can only "
        f"under-predict (here by up to "
        f"{100.0 * s['worst_sample_shortfall']:.1f}%). The direction column "
        f"names the nearest enumerated case and how far off it is. Because "
        f"n̂* and −n̂* are both load directions, every rod is checked against "
        f"the weaker of its tension and compression allowables."
    )

    df = pd.DataFrame(results_frame(result))
    st.dataframe(
        df.style.format(
            {
                "P (lb)": "{:,.0f}",
                "allowable (lb)": "{:,.0f}",
                "LR": "{:.3f}",
                "MS": "{:+.3f}",
                "L (in)": "{:.2f}",
                "λ": "{:.0f}",
                "sample (lb)": "{:,.0f}",
            }
        ),
        width="stretch",
        hide_index=True,
    )

    st.markdown("#### Scene coloured by load ratio")
    selected = st.selectbox(
        "Rod to inspect",
        [r.rod_id for r in result.rows],
        key="tierod::inspect",
        help="Its worst load direction n̂* is drawn as a cone at the rod "
             "midpoint, and its case table is below.",
    )
    row = result.row(selected)
    st.plotly_chart(
        ui_scene.build_figure(
            assembly,
            load_ratios=result.load_ratios(),
            selected=selected,
            static=static,
            worst_direction=(selected, row.worst_direction),
        ),
        width="stretch",
        key="tierod-results-scene",
    )

    st.markdown(f"#### {selected} — enumerated cases")
    st.caption(
        f"Envelope {row.P_envelope:,.0f} lb at n̂* = "
        f"[{row.worst_direction[0]:.3f}, {row.worst_direction[1]:.3f}, "
        f"{row.worst_direction[2]:.3f}] — nearest enumerated case "
        f"**{row.nearest_case}**, {row.nearest_case_angle:.1f}° away. "
        f"Column: {row.column.branch}, λ = {row.column.lam:.0f} against "
        f"λ_crit = {row.column.lam_crit:.0f}, L = {row.L:.2f} in."
    )
    st.dataframe(
        pd.DataFrame(case_frame(result, selected)).style.format(
            {"P (lb)": "{:,.0f}", "% of envelope": "{:.1f}"}
        ),
        width="stretch",
        hide_index=True,
        height=320,
    )
