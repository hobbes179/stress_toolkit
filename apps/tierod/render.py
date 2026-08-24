"""
Streamlit entry point for the tie-rod layout module.

Six tabs, in the order the work is actually done:

    Build           bodies, mountable regions, rods; JSON save and load
    Find a layout   generate layouts from scratch, rank them, adopt one
    Layout          the scene, rods coloured by load ratio
    Results         margins under the closed-form orientation envelope
    Mechanism check rank, nullity, and every mechanism mode animated
    Assembly props  section properties and a hand-checkable trial wrench

What this page does NOT do: rod sizing from a pool (section and material are
fixed per rod — Session 11), warping or rotational-inertia terms, and any
report export.

All engineering lives in `library/tierod`; all figure building in `ui_scene`
and `ui_search` (neither imports Streamlit for the figure builders). This file
is glue: it owns the session-state model and the tab layout, nothing else.
"""

from __future__ import annotations

import numpy as np
import streamlit as st

from apps.tierod import examples, ui_build, ui_inputs, ui_results, ui_scene, ui_search
from library.tierod import mechanisms as mech
from library.tierod import sweep
from library.tierod.kernel import (
    SingularAssemblyError,
    assemble,
    rod_loads,
    solve,
)
from ui.components import section_header
from ui.styles import inject_css
from ui.theme import THEME

_STATE_KEY = "tierod::assembly"
_EXAMPLE_KEY = "tierod::example"


def _assembly():
    """The live model. Held in session state so slider edits persist."""
    chosen = st.session_state.get(_EXAMPLE_KEY, examples.DEFAULT_EXAMPLE)
    if st.session_state.get("tierod::loaded") != chosen:
        st.session_state[_STATE_KEY] = examples.EXAMPLES[chosen]()
        st.session_state["tierod::loaded"] = chosen
    return st.session_state[_STATE_KEY]


def render() -> None:
    inject_css()
    t = THEME

    section_header(
        "Tie-Rod Layout",
        "Rigid bodies on two-force members with spherical bearings both ends. "
        "Where can we tie this down so it holds and stays fail-safe? "
        "Build the geometry, search for a layout, check the margins.",
    )

    # ── sidebar ───────────────────────────────────────────────────────
    with st.sidebar:
        st.selectbox(
            "Example assembly",
            list(examples.EXAMPLES),
            key=_EXAMPLE_KEY,
            help="Starting geometry. Edits are kept until you switch examples.",
        )
        if st.button("Reset to the example geometry", width="stretch"):
            st.session_state.pop("tierod::loaded", None)
            st.rerun()

    assembly = _assembly()

    try:
        assembly.validate()
    except ValueError as exc:
        st.error(f"The model is inconsistent: {exc}")
        return

    with st.sidebar:
        st.divider()
        st.subheader("Bodies")
        ui_inputs.body_editor(assembly)
        st.divider()
        st.subheader("Rods")
        ui_inputs.rod_editor(assembly)
        st.divider()
        st.subheader("Safety factors")
        factors = ui_results.safety_factor_inputs()
        st.divider()
        st.subheader("Topology")
        ui_inputs.topology_editor(assembly)
        st.divider()
        st.subheader("Attachment positions")
        ui_inputs.design_sliders(assembly)

    (tab_build, tab_search, tab_scene, tab_results, tab_mech,
     tab_props) = st.tabs(
        ["Build", "Find a layout", "Layout", "Results", "Mechanism check",
         "Assembly properties"]
    )

    # The builder renders FIRST so that a structural edit reruns the page
    # before anything downstream reads a half-edited model. Every mutating
    # button in it ends in `st.rerun()`.
    with tab_build:
        ui_build.builder_tab(assembly, _STATE_KEY)

    # The search reads the geometry and writes only rods, so it sits with the
    # builder ahead of the analysis tabs. Adopting reruns the page.
    with tab_search:
        ui_search.search_tab(assembly, _STATE_KEY)

    # ── analysis ──────────────────────────────────────────────────────
    #
    # An empty or rodless model is a legitimate intermediate state while
    # building, not an error. The analysis tabs say what is missing instead of
    # raising: a traceback halfway through adding the first body would take the
    # builder tab down with it.
    if not assembly.rods:
        for tab in (tab_scene, tab_results, tab_mech, tab_props):
            with tab:
                st.info(
                    "No rods yet — nothing to analyse. Use the **Build** tab "
                    "(bodies, then a mountable region on each, then rods "
                    "between them), or let **Find a layout** generate a set."
                )
        return

    asm = assemble(assembly)
    report = mech.check(assembly, assembled=asm)

    # The sweep needs an invertible K. Gate on the RANK, not on `report.ok`:
    # a model with no ground body at all is a legitimate free-free diagnostic
    # (V12) and reports ok, but it still has six null modes and no influence
    # matrix. Un-grounding the last body in the sidebar goes straight there.
    result = None
    if not asm.is_singular:
        result = sweep.run_sweep(assembly, factors=factors, asm=asm)

    with tab_scene:
        _layout_tab(assembly, asm, report, result)

    with tab_results:
        _results_tab(assembly, result, report)

    with tab_mech:
        _mechanism_tab(assembly, asm, report)

    with tab_props:
        _properties_tab(assembly, asm, report)


# ----------------------------------------------------------------------


def _layout_tab(assembly, asm, report, result=None) -> None:
    if report.ok:
        st.success(report.messages[0])
    else:
        st.error(report.messages[0])
        for extra in report.messages[1:]:
            st.warning(extra)

    load_ratios = None if result is None else result.load_ratios()
    st.plotly_chart(
        ui_scene.build_figure(assembly, load_ratios=load_ratios),
        width="stretch",
        key="tierod-scene",
    )
    st.caption(
        "Bodies are drawn from their clearance primitives, regions from "
        "`region.point(q)` — the same function the optimizer differentiates. "
        + (
            "Rods are coloured by load ratio under the full orientation "
            "envelope: green through amber to red at LR = 1."
            if load_ratios
            else "Rods are grey: a mechanism has no load path to colour."
        )
    )


def _results_tab(assembly, result, report) -> None:
    if result is None:
        st.error(
            f"No margins: the layout permits {report.nullity} rigid-body "
            f"motion(s), so there is no load path and no honest number to "
            f"report. See the Mechanism check tab for which motions those are."
        )
        if not assembly.free_bodies() or len(assembly.free_bodies()) == len(
            assembly.bodies
        ):
            st.info(
                "Every body is free — nothing is grounded. That is a valid "
                "free-free model for checking the internal load path, but it "
                "has six null modes by definition and cannot be solved for "
                "margins. Ground a body in the sidebar."
            )
        return
    ui_results.results_tab(assembly, result)


def _mechanism_tab(assembly, asm, report) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Free-body DOF", report.n_dof)
    c2.metric("Rank", report.rank)
    c3.metric("Nullity", report.nullity, delta=None)
    c4.metric("σ_min (non-dim)", f"{report.sigma_min:.4f}")

    st.caption(
        "σ_min is taken on the NON-dimensionalized screw matrix. A condition "
        "number on the raw K would be meaningless — it mixes force/length with "
        "force·length."
    )

    if not report.graph.ok:
        st.error(report.graph.message)

    if report.ok:
        st.success("No mechanism. Every free body is fully restrained.")
        return

    for finding in report.findings:
        st.warning(f"**{finding.kind.replace('_', ' ').title()}** — {finding.message}")
    if not report.findings:
        st.info(
            "No named geometric cause fits this layout — the four interpretable "
            "checks (parallel, concurrent, collinear ground attachments, common "
            "line) are not a complete classifier. The animated modes below are "
            "the diagnosis."
        )

    if not report.modes:
        return

    st.markdown("#### Mechanism modes")
    st.caption(
        "Each mode is an independent motion the layout permits with no rod "
        "changing length. Modes are normalized so the amplitude below is "
        "roughly a real displacement."
    )
    labels = [f"Mode {i + 1} of {len(report.modes)}" for i in range(len(report.modes))]
    idx = labels.index(st.radio("Mode", labels, horizontal=True, key="tierod::mode"))
    mode = report.modes[idx]

    axis = mode.common_axis()
    if axis is not None:
        point, direction = axis
        st.info(
            f"This mode is a **rigid rotation** about the line through "
            f"[{point[0]:.3f}, {point[1]:.3f}, {point[2]:.3f}] along "
            f"[{direction[0]:.3f}, {direction[1]:.3f}, {direction[2]:.3f}] "
            f"(drawn dashed red)."
        )
    else:
        kinds = []
        for body_id, motion in mode.per_body.items():
            if motion.is_pure_translation(1e-7):
                kinds.append(f"{body_id}: translation")
            elif motion.axis_line(mode.datums[body_id]) is None:
                kinds.append(f"{body_id}: screw (rotation with axial advance)")
            else:
                kinds.append(f"{body_id}: rotation")
        st.info(
            "No single stationary axis for this mode — " + "; ".join(kinds) + "."
        )

    amp = st.slider(
        "Animation amplitude (in)",
        0.0,
        float(0.4 * ui_scene._model_extent(assembly)),
        float(0.12 * ui_scene._model_extent(assembly)),
        key="tierod::amp",
    )
    st.plotly_chart(
        ui_scene.mechanism_figure(assembly, mode, n_frames=24, amplitude=amp),
        width="stretch",
        key=f"tierod-mech-{idx}",
    )


def _properties_tab(assembly, asm, report) -> None:
    import pandas as pd

    st.markdown("#### Bodies")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "body": b.id,
                    "ground": "yes" if b.is_ground else "",
                    "mass (lb)": b.mass,
                    "G": b.g_factor,
                    "cg (body-local)": np.array2string(b.cg, precision=2),
                    "datum": np.array2string(b.origin, precision=2),
                }
                for b in assembly.bodies.values()
            ]
        ),
        width="stretch",
        hide_index=True,
    )

    st.markdown("#### Rods")
    st.caption(
        "The sidebar edits one rod at a time to keep the slider stack short; "
        "every attachment parameter is listed here read-only."
    )
    specs = ui_inputs.spec_assignments(assembly)
    rows = []
    for j, rod_id in enumerate(asm.rod_ids):
        rod = assembly.rods[rod_id]
        rows.append(
            {
                "rod": rod_id,
                "spec": specs.get(rod_id, ""),
                "from": asm.rod_body_a[j],
                "to": asm.rod_body_b[j],
                "q (end a)": np.array2string(rod.end_a.q, precision=3),
                "q (end b)": np.array2string(rod.end_b.q, precision=3),
                "L (in)": round(float(asm.lengths[j]), 3),
                "k = AE/L (lb/in)": f"{asm.k_d[j]:,.0f}",
                "û": np.array2string(asm.units[:, j], precision=3),
            }
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    st.markdown("#### Rod loads under a trial wrench")
    st.caption(
        "A single hand-entered wrench on one free body — the kernel end to "
        "end, with no sweep and no allowables in the way. The Results tab is "
        "the design answer; this is the one you can check by hand."
    )
    free = asm.body_order
    if not free:
        st.info("No free bodies.")
        return
    target = st.selectbox("Apply to body", free, key="tierod::loadbody")
    cols = st.columns(3)
    F_body = [
        cols[i].number_input(f"F{ax} (lb)", value=0.0 if ax != "Z" else -1000.0,
                             step=100.0, key=f"tierod::F{ax}")
        for i, ax in enumerate("XYZ")
    ]

    F = np.zeros(asm.n_dof)
    slot = free.index(target)
    F[6 * slot : 6 * slot + 3] = F_body

    try:
        P = rod_loads(asm, solve(asm.K, F))
    except SingularAssemblyError as exc:
        st.error(f"Cannot solve: {exc}")
        return

    resid = float(np.max(np.abs(asm.G_hat @ P + F)))
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "rod": rod_id,
                    "P (lb)": round(float(P[j]), 2),
                    "sense": "tension" if P[j] > 0 else ("compression" if P[j] < 0 else "—"),
                }
                for j, rod_id in enumerate(asm.rod_ids)
            ]
        ).sort_values("P (lb)"),
        width="stretch",
        hide_index=True,
    )
    st.caption(f"Equilibrium residual  max|Ĝ P + F| = {resid:.3e} lb")
