"""
Input editors for the tie-rod module.

Split deliberately in two:

* **Pure helpers** (`slider_specs`, `body_form_spec`, `apply_body_edits`,
  `region_choices`, `set_rod_end_region`) — no Streamlit, no session state, so
  they are unit-testable and the widget layer stays thin.
* **Widget renderers** (`*_editor`) — Streamlit only, no engineering logic.

The design-variable sliders GENERATE THEMSELVES from `region.bounds()` via
`Assembly.design_vector_layout()`. A `PlanarPatch` end gets two sliders, a
`CircleArc` end one, a `FixedPoint` end none — with no per-type UI code, so
adding a region primitive never touches this file.

The ground toggle GRAYS the inertial inputs. It must never clear them:
toggling ground to check something and losing a body's mass is a data-loss bug
of the kind nobody notices until the margins are wrong.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import streamlit as st

from library.tierod import allowables as al
from library.tierod.model import Assembly, Body

# ----------------------------------------------------------------------
# Pure helpers
# ----------------------------------------------------------------------


@dataclass
class SliderSpec:
    """One design variable, fully described by the model."""

    key: str
    label: str
    rod_id: str
    end: str            # 'a' or 'b'
    region_id: str
    axis: int           # which parameter of that region
    lo: float
    hi: float
    value: float
    step: float


def slider_specs(assembly: Assembly) -> list[SliderSpec]:
    """One spec per design variable, in design-vector order.

    Reads `ndim` and `bounds()` only — never a region type. That is what makes
    the UI generate itself.
    """
    specs: list[SliderSpec] = []
    for rod_id, tag, ndim in assembly.design_vector_layout():
        rod = assembly.rods[rod_id]
        end = rod.end_a if tag == "a" else rod.end_b
        region = assembly.regions[end.region_id]
        bounds = region.bounds()
        for axis in range(ndim):
            lo, hi = bounds[axis]
            specs.append(
                SliderSpec(
                    key=f"tierod::q::{rod_id}::{tag}::{axis}",
                    label=f"{rod_id} · end {tag} · q{axis}  ({region.id})",
                    rod_id=rod_id,
                    end=tag,
                    region_id=region.id,
                    axis=axis,
                    lo=float(lo),
                    hi=float(hi),
                    value=float(end.q[axis]),
                    step=float(hi - lo) / 200.0 or 1e-3,
                )
            )
    return specs


@dataclass
class BodyFormSpec:
    """Which inertial inputs are live for this body.

    `*_disabled` means grayed in the UI, NOT cleared in the model.
    """

    body_id: str
    is_ground: bool
    mass_disabled: bool
    cg_disabled: bool
    g_factor_disabled: bool
    note: str


def body_form_spec(body: Body) -> BodyFormSpec:
    grounded = bool(body.is_ground)
    return BodyFormSpec(
        body_id=body.id,
        is_ground=grounded,
        mass_disabled=grounded,
        cg_disabled=grounded,
        g_factor_disabled=grounded,
        note=(
            "Ground: contributes no DOF and no inertial load. Mass and CG are "
            "kept, just inactive."
            if grounded
            else "Free body: 6 DOF, inertial load m x G along the case direction."
        ),
    )


def apply_body_edits(body: Body, *, is_ground=None, mass=None, cg=None,
                     g_factor=None, origin=None) -> None:
    """Write only the fields actually supplied.

    Flipping `is_ground` never touches mass / cg / g_factor, so the toggle
    round-trips without data loss.
    """
    if is_ground is not None:
        body.is_ground = bool(is_ground)
    if mass is not None:
        body.mass = float(mass)
    if cg is not None:
        body.cg = np.asarray(cg, dtype=float).reshape(3)
    if g_factor is not None:
        body.g_factor = float(g_factor)
    if origin is not None:
        body.origin = np.asarray(origin, dtype=float).reshape(3)


def region_choices(assembly: Assembly) -> dict[str, list[str]]:
    """`{body_id: [region_id, ...]}` for the topology pickers."""
    out: dict[str, list[str]] = {b: [] for b in assembly.bodies}
    for region in assembly.regions.values():
        out.setdefault(region.body_id, []).append(region.id)
    return {k: sorted(v) for k, v in out.items()}


def rods_with_design_vars(assembly: Assembly) -> list[str]:
    """Rods that have at least one design variable, sorted.

    A rod pinned to fixed points at both ends has nothing to drag, so offering
    it in the picker would be a dead end.
    """
    return sorted({rod_id for rod_id, _, nd in assembly.design_vector_layout() if nd})


def apply_rod_q(assembly: Assembly, rod_id: str, values) -> bool:
    """Write one rod's design variables, leaving every other rod untouched.

    Returns True if any value had to be clipped into its region.

    Editing a single rod at a time is deliberate: the demo assembly has 48
    design variables, and rendering all of them at once is both a wall of
    scrolling and an easy way to drag the wrong rod by accident.

    **Every value is clipped into its region's bounds before it is stored.**
    Streamlit does NOT clamp a stored widget value that falls outside a
    slider's declared range — measured on 1.57: a slider bounded [0, 1] whose
    key holds 9.0 returns 9.0. So a slider key left over from before a region
    was narrowed writes an out-of-bounds `q` straight into the model, and the
    NEXT rerun fails `Assembly.validate()` and refuses the whole model. The
    page then shows "the model is inconsistent" about a rod the user never
    touched, and the only way out is Reset — which discards their work.
    Clipping here makes the invariant "an attachment is inside its region"
    hold at the one place the UI writes attachments.
    """
    values = np.asarray(values, dtype=float).reshape(-1)
    ends = [
        (tag, nd) for r_id, tag, nd in assembly.design_vector_layout() if r_id == rod_id
    ]
    expected = sum(nd for _, nd in ends)
    if values.size != expected:
        raise ValueError(
            f"rod {rod_id!r} has {expected} design variables, got {values.size}"
        )
    rod = assembly.rods[rod_id]
    clipped = False
    i = 0
    for tag, nd in ends:
        end = rod.end_a if tag == "a" else rod.end_b
        region = assembly.regions[end.region_id]
        wanted = values[i : i + nd]
        end.q = region.clip(wanted)
        clipped = clipped or not np.allclose(end.q, wanted)
        i += nd
    return clipped


CUSTOM = "custom"

_ROD_OVERRIDE_FIELDS = (
    ("E", "E (psi)", 1.0e5),
    ("A", "A (in²)", 0.005),
    ("I", "I (in⁴)", 1.0e-4),
    ("Fcy", "Fcy (psi)", 1.0e3),
    ("Ftu", "Ftu (psi)", 1.0e3),
    ("Fty", "Fty (psi)", 1.0e3),
    ("A_net", "A_net (in²)", 0.005),
    ("P_tension_allow", "Vendor rated tension (lb)", 100.0),
    ("end_fixity", "End fixity c", 0.25),
)


def spec_assignments(assembly: Assembly, specs=None) -> dict[str, str]:
    """`{rod_id: spec name}`, or `CUSTOM` where nothing matches.

    Reported rather than stored: the model's single source of truth is the
    Rod's own fields, so a spec assignment that drifted out of date could never
    contradict the numbers actually used in the margins.
    """
    specs = al.ROD_SPECS if specs is None else specs
    out = {}
    for rod_id, rod in assembly.rods.items():
        out[rod_id] = next(
            (name for name, spec in specs.items() if spec.matches(rod)), CUSTOM
        )
    return out


def assign_spec(assembly: Assembly, spec, rod_ids) -> None:
    """Write one section+material spec onto a group of rods.

    Grouping is the point. Twelve individually-sized rods is not something
    anyone manufactures or assembles, and a shared spec is also what makes a
    fail-safe layout reachable — a spec that survives the damaged case survives
    it for every rod carrying it.
    """
    rod_ids = list(rod_ids)
    unknown = [r for r in rod_ids if r not in assembly.rods]
    if unknown:
        raise KeyError(f"unknown rod ids: {unknown}")
    for rod_id in rod_ids:
        spec.apply_to(assembly.rods[rod_id])


def apply_rod_properties(rod, **fields) -> None:
    """Write only the fields actually supplied.

    Passing `None` explicitly CLEARS an optional allowable (a vendor rating, an
    Ftu) rather than being ignored — otherwise deleting a number in the UI
    would leave the old one silently driving the margin.
    """
    for name, value in fields.items():
        if name not in {f for f, _, _ in _ROD_OVERRIDE_FIELDS}:
            raise KeyError(f"{name!r} is not an editable rod property")
        setattr(rod, name, None if value is None else float(value))


def set_rod_end_region(assembly: Assembly, rod_id: str, tag: str,
                       region_id: str) -> None:
    """Point a rod end at a different region, reseeding `q`.

    Topology is a user input, not a design variable, so this is an explicit
    edit. `q` is reseeded to the new region's midpoint because a stale `q` of
    the wrong length would fail validation later, far from the cause.
    """
    if region_id not in assembly.regions:
        raise KeyError(f"unknown region {region_id!r}")
    rod = assembly.rods[rod_id]
    end = rod.end_a if tag == "a" else rod.end_b
    end.region_id = region_id
    end.q = assembly.regions[region_id].q0()


# ----------------------------------------------------------------------
# Widget renderers — Streamlit only
# ----------------------------------------------------------------------


def body_editor(assembly: Assembly) -> None:
    st.caption(
        "Ground is a flag, not a different kind of body. Toggling it grays the "
        "inertial inputs — it never clears them."
    )
    for body in assembly.bodies.values():
        spec = body_form_spec(body)
        with st.expander(f"{'⏚' if spec.is_ground else '◻'}  {body.id}", expanded=False):
            grounded = st.checkbox(
                "Ground", value=spec.is_ground, key=f"tierod::ground::{body.id}"
            )
            apply_body_edits(body, is_ground=grounded)
            spec = body_form_spec(body)
            st.caption(spec.note)

            c1, c2 = st.columns(2)
            with c1:
                mass = st.number_input(
                    "Mass (lb)", value=float(body.mass), min_value=0.0, step=1.0,
                    disabled=spec.mass_disabled, key=f"tierod::mass::{body.id}",
                )
            with c2:
                g_factor = st.number_input(
                    "Load factor G", value=float(body.g_factor), min_value=0.0,
                    step=0.5, disabled=spec.g_factor_disabled,
                    key=f"tierod::g::{body.id}",
                    help="Scalar. The load case supplies only a unit direction, "
                         "so every case has the same magnitude.",
                )
            cols = st.columns(3)
            cg = [
                cols[i].number_input(
                    f"cg {ax} (in)", value=float(body.cg[i]), step=0.5,
                    disabled=spec.cg_disabled, key=f"tierod::cg{ax}::{body.id}",
                )
                for i, ax in enumerate("XYZ")
            ]
            if not spec.mass_disabled:
                apply_body_edits(body, mass=mass, cg=cg, g_factor=g_factor)


def topology_editor(assembly: Assembly) -> None:
    st.caption(
        "Which pair of regions a rod spans is a user input — it carries "
        "manufacturing and access consequences. The optimizer places q inside "
        "the declared topology."
    )
    all_regions = sorted(assembly.regions)
    if not all_regions:
        st.caption("No regions yet — add some in the Build tab.")
        return
    for rod_id, rod in assembly.rods.items():
        with st.expander(rod_id, expanded=False):
            for tag in ("a", "b"):
                end = rod.end_a if tag == "a" else rod.end_b
                choice = st.selectbox(
                    f"end {tag} region",
                    all_regions,
                    index=all_regions.index(end.region_id),
                    key=f"tierod::topo::{rod_id}::{tag}",
                )
                if choice != end.region_id:
                    set_rod_end_region(assembly, rod_id, tag, choice)


def rod_editor(assembly: Assembly) -> None:
    """Rod strength data: a spec assigned to a group, plus per-rod overrides.

    Deliberately NOT twelve sets of loose fields. Rods come off a short list of
    sections in practice, and the whole point of the grouping is that changing
    one spec moves every rod carrying it — which is how a layout is actually
    resized once the sweep says the governing rod is short.
    """
    if not assembly.rods:
        st.caption("No rods yet — add some in the Build tab.")
        return

    assignments = spec_assignments(assembly)
    n_custom = sum(1 for v in assignments.values() if v == CUSTOM)
    st.caption(
        f"{len(assembly.rods) - n_custom} of {len(assembly.rods)} rods match a "
        f"listed spec. Section and material only — topology and end fixity are "
        f"separate inputs."
    )

    spec_name = st.selectbox(
        "Rod specification", list(al.ROD_SPECS), key="tierod::spec"
    )
    spec = al.ROD_SPECS[spec_name]
    st.caption(
        f"{spec.note} · A {spec.A:.4f} in² · I {spec.I:.2e} in⁴ · "
        f"Fcy {spec.Fcy / 1e3:.0f} ksi · Ftu {(spec.Ftu or 0) / 1e3:.0f} ksi"
    )
    targets = st.multiselect(
        "Assign to",
        list(assembly.rods),
        default=[r for r, name in assignments.items() if name == spec_name],
        key="tierod::spec_targets",
    )
    if st.button("Apply spec", width="stretch") and targets:
        assign_spec(assembly, spec, targets)
        st.rerun()

    with st.expander("Override one rod", expanded=False):
        rod_id = st.selectbox("Rod", list(assembly.rods), key="tierod::override_rod")
        rod = assembly.rods[rod_id]
        st.caption(f"Spec match: **{assignments[rod_id]}**")
        edits = {}
        for name, label, step in _ROD_OVERRIDE_FIELDS:
            current = getattr(rod, name)
            optional = current is None
            value = st.number_input(
                label,
                value=float(current) if current is not None else 0.0,
                step=step, format="%g",
                key=f"tierod::rodprop::{rod_id}::{name}",
                help="0 clears this optional value" if optional or name in
                     ("Ftu", "Fty", "A_net", "P_tension_allow") else None,
            )
            # 0 is not a physical value for any of these, so it is the clear
            # gesture for the optional ones and simply invalid for the rest.
            if name in ("Ftu", "Fty", "A_net", "P_tension_allow") and value == 0.0:
                edits[name] = None
            elif value > 0.0:
                edits[name] = value
        apply_rod_properties(rod, **edits)


def design_sliders(assembly: Assembly) -> bool:
    """Sliders for ONE rod at a time. Returns True if anything moved.

    The sliders still generate themselves from `region.bounds()` — a 2-D region
    contributes two, a 1-D region one, a fixed point none — but only the
    selected rod's are rendered. The demo assembly has 48 design variables, and
    putting all of them in the sidebar is a wall of scrolling that also makes
    it easy to drag the wrong rod. Once the optimizer exists these are a
    probing tool ("what if I nudge this one rod?"), which is a one-rod-at-a-
    time job anyway.
    """
    specs = slider_specs(assembly)
    if not specs:
        st.caption("No design variables — every rod end is a fixed point.")
        return False

    rod_ids = rods_with_design_vars(assembly)
    selected = st.selectbox(
        "Rod to adjust", rod_ids, key="tierod::qrod",
        help=f"{len(specs)} design variables across {len(rod_ids)} rods. "
             f"One rod is shown at a time.",
    )
    mine = [s for s in specs if s.rod_id == selected]

    st.caption(
        f"{selected}: {len(mine)} design variable"
        f"{'s' if len(mine) != 1 else ''} of {len(specs)} total."
    )
    values = [
        st.slider(
            f"end {spec.end} · q{spec.axis}  ({spec.region_id})",
            min_value=spec.lo, max_value=spec.hi,
            value=float(np.clip(spec.value, spec.lo, spec.hi)),
            step=spec.step, key=spec.key,
        )
        for spec in mine
    ]

    before = [spec.value for spec in mine]
    changed = not np.allclose(values, before)
    if changed:
        apply_rod_q(assembly, selected, values)
    return changed


__all__ = [
    "SliderSpec",
    "BodyFormSpec",
    "CUSTOM",
    "slider_specs",
    "body_form_spec",
    "apply_body_edits",
    "region_choices",
    "rods_with_design_vars",
    "apply_rod_q",
    "spec_assignments",
    "assign_spec",
    "apply_rod_properties",
    "set_rod_end_region",
    "body_editor",
    "topology_editor",
    "rod_editor",
    "design_sliders",
]
