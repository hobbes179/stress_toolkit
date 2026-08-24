"""
Assembly construction UI — bodies, mountable regions, rods, save and load.

Until this file existed the only way to get geometry into the module was to
write a Python function in `examples.py`. This is the answer to "how does a
user define their geometry?".

Split the same way as `ui_inputs`: **pure helpers** carry every rule, the
`*_editor` functions are Streamlit and nothing else.

Three rules the helpers exist to enforce, each of which is a data-loss bug if
it is left to the widget layer:

1. **A parameter edit can invalidate the rods already on that region.** Shrink
   a patch from 10 in to 2 in and every attachment on it is out of bounds;
   `Assembly.validate()` then refuses the whole model and the page dies with a
   message pointing at a rod nobody touched. `replace_region` clips the
   attachments into the new domain and *reports which ones moved* — silently
   relocating an attachment would be worse than the crash.

2. **Changing a region's TYPE changes its `ndim`**, so every `q` on it is the
   wrong length. Those ends are reseeded to the new midpoint and reported.

3. **Widget state outlives the model, and Streamlit does not police it.**
   Measured on 1.57, not assumed: a slider bounded [0, 1] whose stored key
   holds 9.0 returns **9.0**, and a selectbox whose stored key names a deleted
   option silently **reverts to the first one**. Neither raises. So a leftover
   key does not fail loudly — it writes a wrong number into the model (an
   attachment outside its region, which fails `validate()` on the *next*
   rerun) or silently re-points a rod end at a different region. Structural
   edits therefore purge the transient keys (`stale_keys`), and
   `ui_inputs.apply_rod_q` clips on the way in as the backstop. The model is
   the truth; the widget cache is not.

**Units convention for this module:** anything called `params` in a public
signature is in DISPLAY units — degrees for `kind == "angle"`. The model stores
radians. The conversion happens here, once, in `display_to_stored`, so the
widget layer never touches it. An undeclared angle would present 6.28 where the
engineer expects 360.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import streamlit as st

from library.tierod import serialize
from library.tierod.clearance import CLEARANCE_TYPES
from library.tierod.model import (
    REGION_TYPES,
    Assembly,
    Body,
    Removed,
    frame_from_axis,
    new_rod,
)

CUSTOM_AXIS = "custom"
AXES = ("X", "Y", "Z")

#: Widget keys that describe a *selection* rather than model data. Any
#: structural edit invalidates them — see rule 3 in the module docstring.
TRANSIENT_PREFIXES = ("tierod::q::", "tierod::topo::", "tierod::rodprop::")
TRANSIENT_KEYS = (
    "tierod::qrod",
    "tierod::spec_targets",
    "tierod::override_rod",
    "tierod::loadbody",
)


# ----------------------------------------------------------------------
# Pure helpers — units
# ----------------------------------------------------------------------


def display_to_stored(kind: str, value):
    """Display units -> model units. Degrees become radians."""
    if kind == "angle":
        return float(np.radians(float(value)))
    if kind == "vec3":
        return tuple(float(v) for v in np.asarray(value, dtype=float).reshape(-1))
    return float(value)


def stored_to_display(kind: str, value):
    """Model units -> display units. Radians become degrees."""
    if kind == "angle":
        return float(np.degrees(float(value)))
    if kind == "vec3":
        return tuple(float(v) for v in np.asarray(value, dtype=float).reshape(-1))
    return float(value)


@dataclass(frozen=True)
class ParamField:
    """One editable parameter, ready to render. `value` is in DISPLAY units."""

    attr: str
    label: str
    kind: str
    step: float
    value: object


def param_fields(obj) -> list[ParamField]:
    """Editable parameters of a region/clearance instance *or* class.

    Reads `PARAMS` and nothing else — the same self-generating contract as
    `ui_inputs.slider_specs`. Passing the class yields the declared defaults,
    which is what the "add" form needs before an instance exists.
    """
    is_class = isinstance(obj, type)
    cls = obj if is_class else type(obj)
    return [
        ParamField(
            attr=p.attr,
            label=p.label,
            kind=p.kind,
            step=float(p.step),
            value=stored_to_display(
                p.kind, p.default if is_class else getattr(obj, p.attr)
            ),
        )
        for p in cls.PARAMS
    ]


def apply_params(obj, params: dict) -> None:
    """Write display-unit parameters onto a clearance primitive, in place.

    Regions must NOT go through here — a region's parameters bound the
    attachments living on it, so they change through `replace_region`, which
    repairs those attachments. Clearance shells carry no attachments.
    """
    kinds = {p.attr: p.kind for p in type(obj).PARAMS}
    for attr, value in params.items():
        if attr not in kinds:
            raise KeyError(
                f"{type(obj).__name__} has no parameter {attr!r}; "
                f"it accepts {sorted(kinds)}"
            )
        setattr(obj, attr, display_to_stored(kinds[attr], value))
    if hasattr(obj, "__post_init__"):
        obj.__post_init__()


# ----------------------------------------------------------------------
# Pure helpers — identity and frames
# ----------------------------------------------------------------------


def axis_name(obj) -> str:
    """Which axis dropdown produced this triad, or `CUSTOM_AXIS`.

    A triad loaded from JSON need not be any of the three; the dropdown must
    then report `custom` rather than silently claiming Z, because re-selecting
    Z would quietly rotate real geometry.
    """
    have = np.column_stack([obj.e1, obj.e2, obj.e3])
    for name in AXES:
        if np.allclose(np.column_stack(frame_from_axis(name)), have, atol=1e-9):
            return name
    return CUSTOM_AXIS


def unique_id(existing, stem: str) -> str:
    """`stem`, or `stem_2`, `stem_3`, ... — the first name not already taken."""
    taken = set(existing)
    if stem not in taken:
        return stem
    i = 2
    while f"{stem}_{i}" in taken:
        i += 1
    return f"{stem}_{i}"


def stale_keys(keys) -> list[str]:
    """Transient widget keys to drop after a structural edit.

    Deliberately blunt: one rule, no per-edit branch to get wrong. A structural
    edit is a button click, so re-defaulting a selectbox is a cheap price for
    never leaving a key pointed at geometry that no longer exists.
    """
    return sorted(
        k
        for k in keys
        if k in TRANSIENT_KEYS or any(k.startswith(p) for p in TRANSIENT_PREFIXES)
    )


def removal_message(removed: Removed) -> str:
    """Plain English for what a cascade actually took.

    `Assembly.remove_*` returns the cascade instead of logging it precisely so
    this can be said out loud. A silent cascade is how a user loses work.
    """
    parts = [
        f"{len(items)} {noun}{'' if len(items) == 1 else 's'} ({', '.join(items)})"
        for noun, items in (
            ("body", removed.bodies),
            ("region", removed.regions),
            ("rod", removed.rods),
        )
        if items
    ]
    return "Removed nothing." if not parts else "Removed " + "; ".join(parts) + "."


# ----------------------------------------------------------------------
# Pure helpers — region replacement
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ReplaceReport:
    """What a region edit did to the attachments already on it."""

    region_id: str
    reseeded: tuple = ()   # 'rod.end' whose q was the wrong length after a retype
    clipped: tuple = ()    # 'rod.end' dragged back inside a shrunken domain

    def __bool__(self) -> bool:
        return bool(self.reseeded or self.clipped)

    def message(self) -> str:
        bits = []
        if self.reseeded:
            bits.append(
                f"reseeded {len(self.reseeded)} attachment(s) to the new "
                f"midpoint ({', '.join(self.reseeded)}) — the region's "
                f"parameter count changed"
            )
        if self.clipped:
            bits.append(
                f"moved {len(self.clipped)} attachment(s) back inside the new "
                f"bounds ({', '.join(self.clipped)})"
            )
        if not bits:
            return f"{self.region_id}: updated; no attachment moved."
        return f"{self.region_id}: " + "; ".join(bits) + "."


def region_changed(region, *, type_name=None, axis=None, origin=None,
                   params=None, tol: float = 1e-12) -> bool:
    """Would `replace_region` with these arguments actually change anything?

    The widget layer reruns on every interaction, so without this a region
    would be rebuilt — and its slider keys purged — on every keystroke
    elsewhere on the page, making the design sliders unusable.
    """
    if type_name is not None and type_name != type(region).__name__:
        return True
    if axis is not None and axis != axis_name(region):
        return True
    if origin is not None and not np.allclose(
        np.asarray(origin, dtype=float).reshape(3), region.origin, atol=tol
    ):
        return True
    for p in type(region).PARAMS:
        if params is None or p.attr not in params:
            continue
        want = display_to_stored(p.kind, params[p.attr])
        if not np.allclose(np.asarray(want, dtype=float),
                           np.asarray(getattr(region, p.attr), dtype=float),
                           atol=tol):
            return True
    return False


def replace_region(assembly: Assembly, region_id: str, *, type_name=None,
                   axis=None, origin=None, params=None) -> ReplaceReport:
    """Rebuild one region in place and repair the attachments on it.

    One code path for all three kinds of edit — parameter, axis, type — so
    there is only one place where the attachment repair can be forgotten.

    `axis=None` keeps the EXISTING TRIAD rather than re-deriving one from an
    axis name. A region loaded from JSON may sit on an arbitrary frame that no
    dropdown value describes; rebuilding it "on Z" because the caller did not
    say otherwise would rotate real geometry on an unrelated edit.

    Parameters the new type also declares are carried across BY NAME, so
    switching CircleArc -> Annulus keeps the theta range. Names that do not
    line up (CircleArc's `radius` has no counterpart in Annulus's
    `r_inner`/`r_outer`) fall back to the new type's declared default rather
    than being guessed at.
    """
    if region_id not in assembly.regions:
        raise KeyError(f"unknown region {region_id!r}")
    old = assembly.regions[region_id]
    cls_name = type(old).__name__ if type_name is None else type_name
    try:
        cls = REGION_TYPES[cls_name]
    except KeyError:
        raise ValueError(
            f"unknown region type {cls_name!r}; have {sorted(REGION_TYPES)}"
        ) from None

    stored = {p.attr: p.default for p in cls.PARAMS}
    stored.update(
        {p.attr: getattr(old, p.attr) for p in type(old).PARAMS if p.attr in stored}
    )
    if params:
        kinds = {p.attr: p.kind for p in cls.PARAMS}
        for attr, value in params.items():
            if attr not in kinds:
                raise KeyError(
                    f"{cls_name} has no parameter {attr!r}; "
                    f"it accepts {sorted(kinds)}"
                )
            stored[attr] = display_to_stored(kinds[attr], value)

    e1, e2, e3 = (old.e1, old.e2, old.e3) if axis is None else frame_from_axis(axis)
    new = cls(
        id=region_id,
        body_id=old.body_id,
        origin=old.origin if origin is None else origin,
        e1=e1, e2=e2, e3=e3,
        **stored,
    )
    new.keepouts = list(old.keepouts)
    assembly.regions[region_id] = new

    reseeded, clipped = [], []
    for rod_id in assembly.rods_on_regions([region_id]):
        rod = assembly.rods[rod_id]
        for tag in ("a", "b"):
            end = rod.end_a if tag == "a" else rod.end_b
            if end.region_id != region_id:
                continue
            if end.q.size != new.ndim:
                end.q = new.q0()
                reseeded.append(f"{rod_id}.{tag}")
            elif not new.in_bounds(end.q):
                end.q = new.clip(end.q)
                clipped.append(f"{rod_id}.{tag}")
    return ReplaceReport(region_id, tuple(reseeded), tuple(clipped))


# ----------------------------------------------------------------------
# Widget renderers — Streamlit only
# ----------------------------------------------------------------------


def scene_caption(assembly: Assembly) -> str:
    """What the live builder scene is showing, counted.

    Says the counts out loud because the commonest build mistake is a region
    that was never created or a rod that silently cascaded away, and both look
    identical to "the view has not refreshed yet".
    """
    if not assembly.bodies:
        return "Nothing to draw yet — add a body."
    grounded = sum(1 for b in assembly.bodies.values() if b.is_ground)
    return (
        f"{len(assembly.bodies)} bod{'y' if len(assembly.bodies) == 1 else 'ies'} "
        f"({grounded} ground) · {len(assembly.regions)} region(s) · "
        f"{len(assembly.rods)} rod(s). Bodies are drawn from their clearance "
        f"shells, regions from `region.point(q)`."
    )


def _build_scene(assembly: Assembly) -> None:
    from apps.tierod import ui_scene

    if not assembly.bodies:
        st.info(scene_caption(assembly))
        return
    st.plotly_chart(
        ui_scene.build_figure(assembly), width="stretch",
        key="tierod-build-scene",
    )
    st.caption(scene_caption(assembly))


def _purge() -> None:
    for key in stale_keys(list(st.session_state.keys())):
        st.session_state.pop(key, None)


def _vec3_inputs(label: str, value, key: str, step: float = 0.5,
                 disabled: bool = False) -> list[float]:
    st.caption(label)
    cols = st.columns(3)
    return [
        cols[i].number_input(
            ax, value=float(np.asarray(value, dtype=float).reshape(-1)[i]),
            step=step, format="%g", key=f"{key}::{i}", disabled=disabled,
            label_visibility="visible",
        )
        for i, ax in enumerate("XYZ")
    ]


def _param_inputs(obj, key: str) -> dict:
    """Render `PARAMS` and return the values in DISPLAY units."""
    out = {}
    for f in param_fields(obj):
        if f.kind == "vec3":
            out[f.attr] = _vec3_inputs(f.label, f.value, f"{key}::{f.attr}", f.step)
        else:
            out[f.attr] = st.number_input(
                f.label, value=float(f.value), step=f.step, format="%g",
                key=f"{key}::{f.attr}",
            )
    return out


def _axis_select(label: str, current: str, key: str) -> str:
    options = list(AXES) if current != CUSTOM_AXIS else [CUSTOM_AXIS, *AXES]
    return st.selectbox(
        label, options, index=options.index(current), key=key,
        help="Populates the local frame triad. `custom` means the stored "
             "triad is not one of the three — leave it alone to keep it.",
    )


def body_builder(assembly: Assembly) -> None:
    """Add and delete bodies, and edit each body's clearance shell.

    Mass / CG / ground live in `ui_inputs.body_editor` in the sidebar; this is
    the structural half — what exists, and what shape it occupies.
    """
    with st.expander("Add a body", expanded=not assembly.bodies):
        c1, c2 = st.columns([2, 1])
        new_name = c1.text_input(
            "Body name", value=unique_id(assembly.bodies, "body"),
            key="tierod::b::newbody",
        )
        grounded = c2.checkbox("Ground", key="tierod::b::newbody_ground")
        origin = _vec3_inputs("Datum (global, in)", np.zeros(3),
                              "tierod::b::newbody_origin")
        shell = st.selectbox(
            "Clearance shell", ["(none)", *CLEARANCE_TYPES],
            key="tierod::b::newbody_shell",
            help="The volume the body occupies. Drawn in the Layout tab and "
                 "used for keep-out checks; it does not carry load.",
        )
        if st.button("Add body", key="tierod::b::addbody", width="stretch"):
            name = new_name.strip()
            if not name:
                st.error("A body needs a name.")
            elif name in assembly.bodies:
                st.error(f"There is already a body called {name!r}.")
            else:
                clearance = None
                if shell != "(none)":
                    cls = CLEARANCE_TYPES[shell]
                    clearance = cls(
                        origin=np.zeros(3), e1=np.eye(3)[0], e2=np.eye(3)[1],
                        e3=np.eye(3)[2],
                        **{p.attr: p.default for p in cls.PARAMS},
                    )
                assembly.add_body(
                    Body(id=name, is_ground=grounded, origin=origin,
                         clearance=clearance)
                )
                _purge()
                st.rerun()

    if not assembly.bodies:
        st.info("No bodies yet. Add one above, then give it a mountable region.")
        return

    for body in list(assembly.bodies.values()):
        owned = sorted(r.id for r in assembly.regions.values()
                       if r.body_id == body.id)
        with st.expander(
            f"{'⏚' if body.is_ground else '◻'}  {body.id}  "
            f"· {len(owned)} region(s)"
        ):
            origin = _vec3_inputs("Datum (global, in)", body.origin,
                                  f"tierod::b::org::{body.id}")
            if not np.allclose(origin, body.origin):
                body.origin = np.asarray(origin, dtype=float)

            names = list(CLEARANCE_TYPES)
            current = (
                type(body.clearance).__name__ if body.clearance is not None
                else "(none)"
            )
            options = ["(none)", *names]
            choice = st.selectbox(
                "Clearance shell", options, index=options.index(current),
                key=f"tierod::b::shell::{body.id}",
            )
            if choice != current:
                if choice == "(none)":
                    body.clearance = None
                else:
                    cls = CLEARANCE_TYPES[choice]
                    body.clearance = cls(
                        origin=np.zeros(3), e1=np.eye(3)[0], e2=np.eye(3)[1],
                        e3=np.eye(3)[2],
                        **{p.attr: p.default for p in cls.PARAMS},
                    )
                st.rerun()

            if body.clearance is not None:
                prim = body.clearance
                axis = _axis_select(
                    "Shell axis", axis_name(prim), f"tierod::b::shellax::{body.id}"
                )
                if axis != CUSTOM_AXIS and axis != axis_name(prim):
                    prim.e1, prim.e2, prim.e3 = frame_from_axis(axis)
                shell_origin = _vec3_inputs(
                    "Shell centre (body-local, in)", prim.origin,
                    f"tierod::b::shellorg::{body.id}",
                )
                if not np.allclose(shell_origin, prim.origin):
                    prim.origin = np.asarray(shell_origin, dtype=float)
                apply_params(prim, _param_inputs(prim, f"tierod::b::shp::{body.id}"))

            st.caption(
                f"Deleting this body also deletes its {len(owned)} region(s) "
                f"and every rod on them."
            )
            if st.button("Delete body", key=f"tierod::b::delbody::{body.id}",
                         width="stretch"):
                st.session_state["tierod::b::note"] = removal_message(
                    assembly.remove_body(body.id)
                )
                _purge()
                st.rerun()


def region_builder(assembly: Assembly) -> None:
    """Add, retype, reshape and delete the mountable regions on each body.

    A region is *where a rod is allowed to attach* — the answer to the owner's
    "here are some places where we have room to mount some rods". Its
    dimension is the number of design variables the optimizer gets for that
    end: a fixed point none, a rail one, a patch or a band two.
    """
    if not assembly.bodies:
        st.info("Add a body first — a region belongs to one.")
        return

    with st.expander("Add a region", expanded=not assembly.regions):
        c1, c2 = st.columns(2)
        body_id = c1.selectbox("On body", list(assembly.bodies),
                               key="tierod::b::newreg_body")
        type_name = c2.selectbox("Type", list(REGION_TYPES),
                                 key="tierod::b::newreg_type")
        cls = REGION_TYPES[type_name]
        st.caption(
            f"`{type_name}` · ndim {cls.ndim} — "
            f"{['a fixed point, no design freedom', 'a curve: one design variable per attachment', 'a surface: two design variables per attachment'][cls.ndim]}."
        )
        c3, c4 = st.columns([2, 1])
        name = c3.text_input(
            "Region name", value=unique_id(assembly.regions, f"{body_id}_r"),
            key="tierod::b::newreg_name",
        )
        axis = c4.selectbox("Axis", AXES, index=2, key="tierod::b::newreg_axis")
        origin = _vec3_inputs("Origin (body-local, in)", np.zeros(3),
                              "tierod::b::newreg_origin")
        params = _param_inputs(cls, "tierod::b::newreg")

        if st.button("Add region", key="tierod::b::addreg", width="stretch"):
            rid = name.strip()
            if not rid:
                st.error("A region needs a name.")
            elif rid in assembly.regions:
                st.error(f"There is already a region called {rid!r}.")
            else:
                e1, e2, e3 = frame_from_axis(axis)
                try:
                    region = cls(
                        id=rid, body_id=body_id, origin=origin,
                        e1=e1, e2=e2, e3=e3,
                        **{k: display_to_stored(
                            {p.attr: p.kind for p in cls.PARAMS}[k], v)
                           for k, v in params.items()},
                    )
                    assembly.add_region(region)
                except (ValueError, TypeError) as exc:
                    st.error(f"Cannot build that region: {exc}")
                else:
                    _purge()
                    st.rerun()

    if not assembly.regions:
        return

    for region in list(assembly.regions.values()):
        attached = assembly.rods_on_regions([region.id])
        with st.expander(
            f"{region.id}  ·  {type(region).__name__}  ·  on {region.body_id}  "
            f"·  {len(attached)} rod(s)"
        ):
            c1, c2 = st.columns(2)
            type_name = c1.selectbox(
                "Type", list(REGION_TYPES),
                index=list(REGION_TYPES).index(type(region).__name__),
                key=f"tierod::b::rt::{region.id}",
            )
            axis = _axis_select("Axis", axis_name(region),
                                f"tierod::b::ra::{region.id}")
            with c2:
                st.caption(f"ndim {REGION_TYPES[type_name].ndim}")
            origin = _vec3_inputs("Origin (body-local, in)", region.origin,
                                  f"tierod::b::ro::{region.id}")
            # Render the params of the SELECTED type, seeded from the current
            # region where the names line up — so switching type shows the
            # right inputs immediately, not after an extra rerun.
            proto = region
            if type_name != type(region).__name__:
                proto = REGION_TYPES[type_name]
            params = _param_inputs(proto, f"tierod::b::rp::{region.id}")

            want_axis = None if axis == CUSTOM_AXIS else axis
            if region_changed(region, type_name=type_name, axis=want_axis,
                              origin=origin, params=params):
                try:
                    report = replace_region(
                        assembly, region.id, type_name=type_name,
                        axis=want_axis, origin=origin, params=params,
                    )
                except (ValueError, TypeError) as exc:
                    st.error(f"Cannot apply that edit: {exc}")
                else:
                    if report:
                        st.warning(report.message())
                        _purge()
                        st.rerun()

            if attached:
                st.caption(f"Deleting this region also deletes {', '.join(attached)}.")
            if st.button("Delete region", key=f"tierod::b::delreg::{region.id}",
                         width="stretch"):
                st.session_state["tierod::b::note"] = removal_message(
                    assembly.remove_region(region.id)
                )
                _purge()
                st.rerun()


def rod_builder(assembly: Assembly) -> None:
    """Add and delete rods. Section and material are `ui_inputs.rod_editor`.

    Only the topology and the group are set here: which two regions the rod
    spans, and which sizing group it belongs to. `q` is seeded at each
    region's midpoint — a zero `q` is outside the domain of several primitives
    (an annulus starts at its inner radius), so a rod created at zero would
    fail validation immediately, far from the click that made it.
    """
    if len(assembly.regions) < 2:
        st.info("A rod spans two regions — add at least two.")
        return

    options = sorted(assembly.regions)
    labels = {
        r: f"{r}  ({assembly.regions[r].body_id})" for r in options
    }
    with st.expander("Add a rod", expanded=not assembly.rods):
        c1, c2 = st.columns(2)
        region_a = c1.selectbox("End A region", options,
                                format_func=labels.get, key="tierod::b::newrod_a")
        region_b = c2.selectbox(
            "End B region", options, format_func=labels.get,
            index=min(1, len(options) - 1), key="tierod::b::newrod_b",
        )
        c3, c4, c5 = st.columns(3)
        name = c3.text_input("Rod name", value=unique_id(assembly.rods, "rod"),
                             key="tierod::b::newrod_name")
        groups = sorted(assembly.rod_groups()) or ["main"]
        group = c4.selectbox(
            "Group", [*groups, "(new)"], key="tierod::b::newrod_group",
            help="Rods in one group are sized as a unit. A dozen "
                 "individually-sized rods is not something anyone builds.",
        )
        if group == "(new)":
            group = c5.text_input("New group name", value="main",
                                  key="tierod::b::newrod_newgroup").strip() or "main"
        c6, c7 = st.columns(2)
        h_a = c6.number_input("End A standoff h (in)", value=0.0, step=0.25,
                              format="%g", key="tierod::b::newrod_ha")
        h_b = c7.number_input("End B standoff h (in)", value=0.0, step=0.25,
                              format="%g", key="tierod::b::newrod_hb")

        same_body = (assembly.regions[region_a].body_id
                     == assembly.regions[region_b].body_id)
        if same_body:
            st.warning(
                "Both ends land on the same body. Such a rod contributes a "
                "column of exactly zero to the screw matrix — the two blocks "
                "cancel — so it is not a weak constraint, it is no constraint."
            )
        if st.button("Add rod", key="tierod::b::addrod", width="stretch"):
            rid = name.strip()
            if not rid:
                st.error("A rod needs a name.")
            elif rid in assembly.rods:
                st.error(f"There is already a rod called {rid!r}.")
            else:
                assembly.add_rod(
                    new_rod(assembly, rid, region_a, region_b,
                            h_a=h_a, h_b=h_b, group=group)
                )
                _purge()
                st.rerun()

    if not assembly.rods:
        return

    st.caption(
        f"{len(assembly.rods)} rod(s) in {len(assembly.rod_groups())} group(s). "
        "Attachment positions are the sidebar sliders; section and material "
        "are the sidebar rod editor."
    )
    for rod_id in list(assembly.rods):
        rod = assembly.rods[rod_id]
        c1, c2 = st.columns([4, 1])
        c1.markdown(
            f"**{rod_id}** · {rod.end_a.region_id} → {rod.end_b.region_id} "
            f"· group `{rod.group}`"
        )
        if c2.button("Delete", key=f"tierod::b::delrod::{rod_id}",
                     width="stretch"):
            st.session_state["tierod::b::note"] = removal_message(
                assembly.remove_rod(rod_id)
            )
            _purge()
            st.rerun()


def save_load(assembly: Assembly, state_key: str) -> None:
    """Download the model as JSON; upload one back.

    A failed load must leave the live model untouched — `serialize.loads`
    builds a whole new Assembly and only then is it installed, so a truncated
    or wrong-schema file is an error message and nothing else. A half-applied
    load would be far worse than a refused one.
    """
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "Download model (JSON)",
            data=serialize.dumps(assembly),
            file_name="tierod_assembly.json",
            mime="application/json",
            width="stretch",
        )
    with c2:
        st.caption(
            f"Schema v{serialize.SCHEMA_VERSION}. The full frame triad is "
            "written, never re-derived from an axis name."
        )

    upload = st.file_uploader("Load a model", type="json",
                              key="tierod::b::upload")
    if upload is None:
        return
    token = f"{upload.name}:{upload.size}"
    if st.session_state.get("tierod::b::uploaded") == token:
        return
    try:
        loaded = serialize.loads(upload.getvalue().decode("utf-8"))
        loaded.validate()
    except Exception as exc:  # noqa: BLE001 — any bad file, one message
        st.error(f"That file did not load; the current model is unchanged. {exc}")
        return
    st.session_state[state_key] = loaded
    st.session_state["tierod::b::uploaded"] = token
    _purge()
    st.rerun()


def builder_tab(assembly: Assembly, state_key: str) -> None:
    """The whole construction UI. Order follows the dependency chain."""
    note = st.session_state.pop("tierod::b::note", None)
    if note:
        st.info(note)

    # The scene sits ABOVE the editors and stays on screen while you work.
    # Building blind — typing radii into a form and switching tabs to find out
    # what you made — is how the geometry ends up wrong in a way nobody
    # notices until the margins are.
    _build_scene(assembly)

    st.caption(
        "Build order is bodies → regions → rods, because each depends on the "
        "one before. Deleting cascades the same way, and says what it took."
    )
    b, r, d, s = st.tabs(["Bodies", "Regions", "Rods", "Save / load"])
    with b:
        body_builder(assembly)
    with r:
        region_builder(assembly)
    with d:
        rod_builder(assembly)
    with s:
        save_load(assembly, state_key)


__all__ = [
    "AXES",
    "CUSTOM_AXIS",
    "TRANSIENT_KEYS",
    "TRANSIENT_PREFIXES",
    "ParamField",
    "ReplaceReport",
    "apply_params",
    "axis_name",
    "body_builder",
    "builder_tab",
    "display_to_stored",
    "param_fields",
    "region_builder",
    "region_changed",
    "removal_message",
    "replace_region",
    "rod_builder",
    "scene_caption",
    "save_load",
    "stale_keys",
    "stored_to_display",
    "unique_id",
]
