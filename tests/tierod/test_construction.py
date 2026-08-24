"""
tests/tierod/test_construction.py — Session 6 gate.

Until now a user could only re-parameterize one of three hand-written example
assemblies: there was no way to create a body, define a region on it, or add a
rod without editing Python. This session adds the model layer for that, and
persistence so the result survives a rerun.

Three things are gated here, all of them the sort that fail quietly:

  * **Form metadata lives on the class.** Each Region and clearance primitive
    declares its own editable parameters, exactly as `shapes.py` does with
    `dim_labels` / `dim_defaults` for the 11 beam sections. A test compares the
    declaration against the dataclass fields, so adding a field to a primitive
    and forgetting the UI is a test failure rather than a missing input box.
  * **Deletion cascades.** Removing a region while rods still hang off it leaves
    a dangling reference that `validate()` catches far from the cause. Removal
    reports what else it took with it.
  * **Round-trip fidelity is measured on the ANALYSIS, not on the fields.**
    Comparing dataclasses can pass while a dropped frame triad or a silently
    re-orthonormalized rotation moves every rod. The round-trip test requires
    the reloaded model to produce a bit-comparable transfer matrix.
"""
from __future__ import annotations

import dataclasses
import json

import numpy as np
import pytest

from apps.tierod import examples
from library.tierod import model as md
from library.tierod import serialize as ser
from library.tierod import sweep as sw
from library.tierod.kernel import SingularAssemblyError, assemble
from library.tierod.clearance import CLEARANCE_TYPES, Box, Cylinder, Sphere
from library.tierod.model import (
    Assembly,
    Body,
    FixedPoint,
    Region,
    Rod,
    RodEnd,
    frame_from_axis,
    frame_from_plane,
)


def _rot_z(deg: float) -> np.ndarray:
    c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


# ======================================================================
# Form metadata declared by the class, not by the UI
# ======================================================================


def test_every_region_subclass_is_in_the_registry():
    """A primitive missing from the registry is invisible to the builder AND
    unloadable from JSON — it would round-trip into an exception."""
    concrete = {c.__name__ for c in Region.__subclasses__()}
    assert concrete == {c.__name__ for c in md.REGION_TYPES.values()}
    assert set(md.REGION_TYPES) == {c.__name__ for c in Region.__subclasses__()}


def test_every_clearance_primitive_is_in_the_registry():
    assert set(CLEARANCE_TYPES) == {"Sphere", "Cylinder", "Box"}


@pytest.mark.parametrize("name,cls", sorted(md.REGION_TYPES.items()))
def test_region_params_cover_exactly_the_editable_fields(name, cls):
    """The declaration must track the dataclass. Adding `taper` to a primitive
    and forgetting to declare it would otherwise ship a field no one can edit
    and that JSON silently drops."""
    base = {f.name for f in dataclasses.fields(Region)}
    own = {f.name for f in dataclasses.fields(cls)} - base - {"ndim"}
    assert {p.attr for p in cls.PARAMS} == own, name


@pytest.mark.parametrize("name,cls", sorted(CLEARANCE_TYPES.items()))
def test_clearance_params_cover_exactly_the_editable_fields(name, cls):
    from library.tierod.clearance import ClearancePrimitive

    base = {f.name for f in dataclasses.fields(ClearancePrimitive)}
    own = {f.name for f in dataclasses.fields(cls)} - base
    assert {p.attr for p in cls.PARAMS} == own, name


def test_angle_parameters_are_marked_as_angles():
    """Stored in radians, edited in degrees. An unmarked theta would present a
    6.28 where the engineer expects 360."""
    for cls in md.REGION_TYPES.values():
        for p in cls.PARAMS:
            if p.attr.startswith(("theta", "phi")):
                assert p.kind == "angle", f"{cls.__name__}.{p.attr}"
            else:
                assert p.kind != "angle", f"{cls.__name__}.{p.attr}"


def test_every_declared_default_is_inside_its_own_bounds():
    for name, cls in md.REGION_TYPES.items():
        region = md.new_region(name, id="r", body_id="b", axis="Z")
        assert region.in_bounds(region.q0()), name


# ======================================================================
# Building a region / clearance primitive from a type name
# ======================================================================


def test_new_region_builds_every_primitive_with_a_usable_frame():
    for name in md.REGION_TYPES:
        region = md.new_region(name, id=f"r_{name}", body_id="b", axis="Y")
        md.check_orthonormal(region.e1, region.e2, region.e3)
        assert region.id == f"r_{name}"
        assert region.body_id == "b"
        assert region.point(region.q0()).shape == (3,)


@pytest.mark.parametrize("axis", ["X", "Y", "Z"])
def test_the_axis_dropdown_actually_orients_the_region(axis):
    """The dropdown POPULATES the triad — so a band built on X must lie along
    X. Checking only orthonormality would pass for all three identically."""
    want = frame_from_axis(axis)
    for name in md.REGION_TYPES:
        region = md.new_region(name, id="r", body_id="b", axis=axis)
        assert np.allclose([region.e1, region.e2, region.e3], want), (name, axis)


def test_a_band_built_on_x_sweeps_about_x():
    """The same claim in geometry rather than in triads: the axis has to reach
    `point(q)`, not just get stored."""
    band = md.new_region("CylindricalBand", id="b", body_id="x", axis="X",
                         radius=2.0, z_min=-1.0, z_max=1.0)
    pts = np.column_stack(
        [band.point([th, 0.0]) for th in np.linspace(0.0, 2.0 * np.pi, 32)]
    )
    assert np.allclose(pts[0], 0.0), "an X-axis band must not vary in x at z=0"
    assert np.allclose(np.hypot(pts[1], pts[2]), 2.0)


def test_new_region_overrides_land_on_the_primitive():
    region = md.new_region(
        "CylindricalBand", id="band", body_id="tank", axis="Z",
        origin=[1.0, 2.0, 3.0], radius=7.5, z_min=-2.0, z_max=4.0,
    )
    assert (region.radius, region.z_min, region.z_max) == (7.5, -2.0, 4.0)
    assert np.allclose(region.origin, [1.0, 2.0, 3.0])


def test_new_region_rejects_a_parameter_the_primitive_does_not_have():
    with pytest.raises(TypeError):
        md.new_region("PlanarPatch", id="p", body_id="b", radius=3.0)


def test_new_clearance_builds_every_primitive():
    for name in CLEARANCE_TYPES:
        prim = md.new_clearance(name, axis="X")
        v, faces = prim.surface_mesh()
        assert v.shape[0] == 3 and faces.shape[1] == 3


# ======================================================================
# Assembly mutation — add
# ======================================================================


@pytest.fixture
def empty() -> Assembly:
    return Assembly(bodies={}, regions={}, rods={})


def _six_anchor_ring(a: Assembly, body_id: str = "ground", radius: float = 6.0):
    e1, e2, e3 = frame_from_plane("XY")
    for k in range(6):
        th = 2.0 * np.pi * k / 6.0
        a.add_region(
            FixedPoint(id=f"anchor{k}", body_id=body_id,
                       origin=np.array([radius * np.cos(th), radius * np.sin(th), 0.0]),
                       e1=e1, e2=e2, e3=e3)
        )


def test_a_model_can_be_built_from_nothing(empty):
    """The whole point of the session: a complete, solvable assembly with no
    Python file behind it.

    Note the alternating z on the band. Six rods from a single ring down to a
    single ring is rank 3 — see the next test.
    """
    empty.add_body(Body(id="ground", is_ground=True))
    empty.add_body(Body(id="box", origin=[0.0, 0.0, 10.0], mass=100.0, g_factor=3.0))
    empty.add_region(
        md.new_region("CylindricalBand", id="shell", body_id="box", axis="Z",
                      radius=3.0, z_min=-3.0, z_max=3.0)
    )
    _six_anchor_ring(empty)
    for k in range(6):
        th = 2.0 * np.pi * k / 6.0
        empty.add_rod(
            md.new_rod(empty, id=f"tie{k}", region_a="shell", region_b=f"anchor{k}",
                       q_a=[th + 0.5, 2.5 if k % 2 == 0 else -2.5])
        )
    empty.validate()
    assert len(empty.rods) == 6
    assert sw.transfer_matrix(empty).shape == (6, 3)
    assert not assemble(empty).is_singular


def test_a_ui_built_layout_can_be_a_mechanism_and_the_tool_says_so(empty):
    """The obvious thing to draw — one flat pad, one ring of anchors — is rank
    3, because BOTH attachment sets are coplanar. A builder makes this easy to
    do by accident, so it has to fail loudly rather than return numbers."""
    empty.add_body(Body(id="ground", is_ground=True))
    empty.add_body(Body(id="box", origin=[0.0, 0.0, 10.0], mass=100.0))
    empty.add_region(
        md.new_region("PlanarPatch", id="pad", body_id="box", axis="Z",
                      origin=[-2.0, -2.0, 0.0], width=4.0, height=4.0)
    )
    _six_anchor_ring(empty)
    for k in range(6):
        th = 2.0 * np.pi * k / 6.0
        empty.add_rod(
            md.new_rod(empty, id=f"tie{k}", region_a="pad", region_b=f"anchor{k}",
                       q_a=[0.5 + 0.4 * np.cos(th), 0.5 + 0.4 * np.sin(th)])
        )
    empty.validate()          # structurally fine — it is the RANK that fails
    assert assemble(empty).rank == 3
    with pytest.raises(SingularAssemblyError):
        sw.transfer_matrix(empty)


def test_adding_a_duplicate_id_is_refused(empty):
    empty.add_body(Body(id="b"))
    with pytest.raises(ValueError, match="already"):
        empty.add_body(Body(id="b"))


def test_a_region_needs_its_body_to_exist_first(empty):
    with pytest.raises(KeyError):
        empty.add_region(md.new_region("CircleArc", id="r", body_id="ghost"))


def test_a_rod_needs_both_regions_to_exist(empty):
    empty.add_body(Body(id="b"))
    empty.add_region(md.new_region("CircleArc", id="r", body_id="b"))
    with pytest.raises(KeyError):
        empty.add_rod(
            Rod(id="x", end_a=RodEnd("r", [0.0]), end_b=RodEnd("ghost", []),
                E=1e7, A=0.1, I=1e-3, Fcy=1e5)
        )


def test_new_rod_seeds_each_end_at_its_region_midpoint(empty):
    """Midpoint, not zero. Zero is OUTSIDE the domain of several primitives —
    an Annulus starts at r_inner, a band at z_min — so a rod created at zero
    fails validation immediately, far from the click that made it."""
    empty.add_body(Body(id="b"))
    empty.add_region(md.new_region("PlanarPatch", id="p", body_id="b"))
    empty.add_region(
        md.new_region("Annulus", id="ring", body_id="b", r_inner=3.0, r_outer=5.0)
    )
    rod = md.new_rod(empty, id="r", region_a="p", region_b="ring")

    assert rod.end_a.q.size == 2 and rod.end_b.q.size == 2
    assert np.allclose(rod.end_a.q, empty.regions["p"].q0())
    assert np.allclose(rod.end_b.q, empty.regions["ring"].q0())
    assert rod.end_b.q[0] == pytest.approx(4.0), "seeded mid-annulus"
    assert not empty.regions["ring"].in_bounds(np.zeros(2)), "zero would be invalid"
    empty.add_rod(rod)
    empty.validate()


def test_a_rod_with_a_wrong_length_q_is_refused(empty):
    empty.add_body(Body(id="b"))
    empty.add_region(md.new_region("PlanarPatch", id="p", body_id="b"))
    empty.add_region(md.new_region("PlanarPatch", id="p2", body_id="b"))
    with pytest.raises(ValueError):
        empty.add_rod(
            Rod(id="r", end_a=RodEnd("p", [0.5]), end_b=RodEnd("p2", [0.5, 0.5]),
                E=1e7, A=0.1, I=1e-3, Fcy=1e5)
        )


# ======================================================================
# Assembly mutation — remove, and what it takes with it
# ======================================================================


def test_removing_a_region_removes_the_rods_hanging_off_it():
    a = examples.demo_assembly()
    removed = a.remove_region("band_a")
    assert removed.regions == ["band_a"]
    assert sorted(removed.rods) == [f"rod_a{k}" for k in range(6)]
    assert "band_a" not in a.regions
    assert all(not r.startswith("rod_a") for r in a.rods)
    a.validate()


def test_removing_a_body_removes_its_regions_and_their_rods():
    a = examples.demo_assembly()
    removed = a.remove_body("tank_a")
    assert removed.bodies == ["tank_a"]
    assert removed.regions == ["band_a"]
    assert len(removed.rods) == 6
    a.validate()
    assert len(a.rods) == 6


def test_refusing_to_cascade_raises_instead_of_orphaning():
    a = examples.demo_assembly()
    with pytest.raises(ValueError, match="rod"):
        a.remove_region("band_a", cascade=False)
    assert "band_a" in a.regions, "a refused removal must change nothing"
    assert len(a.rods) == 12


def test_a_refused_body_removal_leaves_the_model_untouched():
    a = examples.demo_assembly()
    before = ser.dumps(a)
    with pytest.raises(ValueError):
        a.remove_body("tank_a", cascade=False)
    assert ser.dumps(a) == before


def test_removing_a_rod_leaves_everything_else_alone():
    a = examples.demo_assembly()
    a.remove_rod("rod_a0")
    assert "rod_a0" not in a.rods and len(a.rods) == 11
    assert len(a.regions) == 4 and len(a.bodies) == 3
    a.validate()


def test_removing_something_that_is_not_there_raises():
    a = examples.demo_assembly()
    for fn in (a.remove_body, a.remove_region, a.remove_rod):
        with pytest.raises(KeyError):
            fn("nope")


# ======================================================================
# Rod groups — one spec per group (the assignment granularity)
# ======================================================================


def test_rods_default_to_a_single_group():
    a = examples.demo_assembly()
    assert {r.group for r in a.rods.values()} == {md.DEFAULT_GROUP}
    assert a.rod_groups() == {md.DEFAULT_GROUP: sorted(a.rods)}


def test_groups_partition_the_rods():
    a = examples.demo_assembly()
    for rod_id, rod in a.rods.items():
        rod.group = "tank_a" if "_a" in rod_id else "tank_b"
    groups = a.rod_groups()
    assert set(groups) == {"tank_a", "tank_b"}
    assert sum(len(v) for v in groups.values()) == len(a.rods)
    assert set().union(*groups.values()) == set(a.rods)


# ======================================================================
# Persistence
# ======================================================================


@pytest.mark.parametrize("name", list(examples.EXAMPLES))
def test_every_example_round_trips_through_json(name):
    a = examples.EXAMPLES[name]()
    back = ser.loads(ser.dumps(a))
    back.validate()
    assert set(back.bodies) == set(a.bodies)
    assert set(back.regions) == set(a.regions)
    assert set(back.rods) == set(a.rods)
    assert ser.dumps(back) == ser.dumps(a), "serialization is not a fixed point"


def test_a_round_trip_reproduces_the_analysis_exactly():
    """The real test. Field-by-field equality can pass while a dropped frame
    triad or a re-orthonormalized rotation moves every rod load."""
    a = examples.demo_assembly()
    back = ser.loads(ser.dumps(a))
    assert np.array_equal(sw.transfer_matrix(a), sw.transfer_matrix(back))
    r1, r2 = sw.run_sweep(a), sw.run_sweep(back)
    assert [x.rod_id for x in r1.rows] == [x.rod_id for x in r2.rows]
    assert [x.load_ratio for x in r1.rows] == pytest.approx(
        [x.load_ratio for x in r2.rows]
    )


@pytest.mark.parametrize("name", list(examples.EXAMPLES))
def test_every_example_keeps_its_geometry_through_a_round_trip(name):
    """Endpoint-by-endpoint, across all examples — the demo alone is built
    entirely on the XY frame, so it cannot detect a dropped triad."""
    a = examples.EXAMPLES[name]()
    back = ser.loads(ser.dumps(a))
    for rod_id, rod in a.rods.items():
        want = a.rod_endpoints(rod)
        got = back.rod_endpoints(back.rods[rod_id])
        assert np.allclose(want[0], got[0]) and np.allclose(want[1], got[1]), rod_id


def test_an_arbitrary_frame_triad_survives_the_round_trip():
    """A region may carry ANY right-handed orthonormal triad — `frame_from_axis`
    is an input convenience, not the storage format. Re-deriving a frame from
    the dropdown value that happened to produce it would silently rotate every
    region built any other way."""
    rng = np.random.default_rng(7)
    Q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
    if np.linalg.det(Q) < 0:
        Q[:, 0] = -Q[:, 0]

    a = examples.demo_assembly()
    band = a.regions["band_a"]
    band.e1, band.e2, band.e3 = Q[:, 0], Q[:, 1], Q[:, 2]
    before = a.rod_endpoints(a.rods["rod_a0"])[0]

    back = ser.loads(ser.dumps(a))
    assert np.allclose(back.regions["band_a"].e1, Q[:, 0])
    assert np.allclose(back.rod_endpoints(back.rods["rod_a0"])[0], before)
    assert np.array_equal(sw.transfer_matrix(a), sw.transfer_matrix(back))


def test_a_rotated_body_survives_the_round_trip():
    """R is a 3x3 that json has to carry as nested lists. A body left at
    identity would still solve, just wrongly."""
    a = examples.demo_assembly()
    a.bodies["tank_a"].R = _rot_z(37.0)
    back = ser.loads(ser.dumps(a))
    assert np.allclose(back.bodies["tank_a"].R, _rot_z(37.0))
    assert np.array_equal(sw.transfer_matrix(a), sw.transfer_matrix(back))


def test_clearance_primitives_keep_their_type_and_size():
    a = examples.demo_assembly()
    back = ser.loads(ser.dumps(a))
    assert isinstance(back.bodies["plate"].clearance, Box)
    assert isinstance(back.bodies["tank_a"].clearance, Cylinder)
    assert back.bodies["tank_a"].clearance.radius == 5.0
    assert np.allclose(
        back.bodies["plate"].clearance.half_extents,
        a.bodies["plate"].clearance.half_extents,
    )


def test_a_body_with_no_clearance_round_trips_as_none():
    a = Assembly(bodies={"b": Body(id="b")}, regions={}, rods={})
    assert ser.loads(ser.dumps(a)).bodies["b"].clearance is None


def test_rod_strength_data_and_group_survive():
    a = examples.demo_assembly()
    a.rods["rod_a0"].P_tension_allow = 4321.0
    a.rods["rod_a0"].group = "heavies"
    back = ser.loads(ser.dumps(a))
    rod = back.rods["rod_a0"]
    assert rod.P_tension_allow == 4321.0
    assert rod.group == "heavies"
    assert rod.Fty == a.rods["rod_a0"].Fty
    assert rod.k_backup_a == float("inf"), "an infinite backup must not become null"


def test_the_standoff_survives():
    a = examples.demo_assembly()
    assert a.rods["rod_a0"].end_a.h == 0.75
    assert ser.loads(ser.dumps(a)).rods["rod_a0"].end_a.h == 0.75


def test_the_payload_is_plain_json_with_a_schema_version():
    a = examples.demo_assembly()
    text = ser.dumps(a)
    payload = json.loads(text)
    assert payload["schema"] == ser.SCHEMA_VERSION
    assert set(payload) >= {"schema", "bodies", "regions", "rods"}
    json.dumps(payload)  # no numpy types left anywhere


def test_a_future_schema_is_refused_rather_than_half_read():
    payload = json.loads(ser.dumps(examples.demo_assembly()))
    payload["schema"] = ser.SCHEMA_VERSION + 99
    with pytest.raises(ValueError, match="schema"):
        ser.loads(json.dumps(payload))


def test_an_unknown_region_type_names_itself_in_the_error():
    payload = json.loads(ser.dumps(examples.demo_assembly()))
    payload["regions"]["band_a"]["type"] = "Hyperboloid"
    with pytest.raises(ValueError, match="Hyperboloid"):
        ser.loads(json.dumps(payload))


def test_save_and_load_through_a_file(tmp_path):
    a = examples.demo_assembly()
    path = tmp_path / "assembly.json"
    ser.save(a, path)
    back = ser.load(path)
    assert np.array_equal(sw.transfer_matrix(a), sw.transfer_matrix(back))


def test_a_model_built_in_the_ui_round_trips_too(empty):
    """Not just the shipped examples — something assembled piece by piece,
    which is what a user will actually save."""
    empty.add_body(Body(id="g", is_ground=True, clearance=md.new_clearance("Box")))
    empty.add_body(
        Body(id="m", origin=[0.0, 0.0, 4.0], mass=25.0, cg=[0.1, 0.0, 0.0],
             clearance=md.new_clearance("Sphere", radius=1.5))
    )
    empty.add_region(md.new_region("SphericalPatch", id="dome", body_id="m",
                                   axis="Z", radius=1.5))
    empty.add_region(md.new_region("Annulus", id="ring", body_id="g", axis="Z",
                                   r_inner=2.0, r_outer=5.0))
    empty.add_rod(md.new_rod(empty, id="t0", region_a="dome", region_b="ring"))

    back = ser.loads(ser.dumps(empty))
    back.validate()
    assert isinstance(back.bodies["m"].clearance, Sphere)
    assert np.allclose(
        back.rod_endpoints(back.rods["t0"])[0],
        empty.rod_endpoints(empty.rods["t0"])[0],
    )


# ======================================================================
# Clearance orientation — it reaches the physics through the standoff
# ======================================================================


@pytest.mark.parametrize("axis", ["X", "Y", "Z"])
def test_the_axis_dropdown_actually_orients_the_clearance(axis):
    want = frame_from_axis(axis)
    for name in CLEARANCE_TYPES:
        prim = md.new_clearance(name, axis=axis)
        assert np.allclose([prim.e1, prim.e2, prim.e3], want), (name, axis)


def test_a_clearance_frame_reaches_the_rod_endpoint_through_the_standoff():
    """`h` offsets the pin along `clearance.outward(p)`, so the shell's
    orientation is not decoration — it moves the attachment point. The demo's
    rod_a0 carries a 0.75 in standoff, which is what makes this measurable."""
    a = examples.demo_assembly()
    assert a.rods["rod_a0"].end_a.h == 0.75
    before = a.rod_endpoints(a.rods["rod_a0"])[0].copy()

    clearance = a.bodies["tank_a"].clearance
    clearance.e1, clearance.e2, clearance.e3 = frame_from_axis("X")
    after = a.rod_endpoints(a.rods["rod_a0"])[0]
    assert not np.allclose(before, after), "turning the shell must move the pin"


def test_a_turned_clearance_frame_survives_the_round_trip():
    a = examples.demo_assembly()
    clearance = a.bodies["tank_a"].clearance
    clearance.e1, clearance.e2, clearance.e3 = frame_from_axis("X")
    want = a.rod_endpoints(a.rods["rod_a0"])[0]

    back = ser.loads(ser.dumps(a))
    assert np.allclose(back.bodies["tank_a"].clearance.e3, frame_from_axis("X")[2])
    assert np.allclose(back.rod_endpoints(back.rods["rod_a0"])[0], want)


def test_a_shifted_clearance_origin_survives_the_round_trip():
    """The shell's ORIGIN is body-local and independent of the body datum, so
    it is its own stored value. Every shipped example happens to leave it at
    zero, which is exactly why it needs its own test."""
    a = examples.demo_assembly()
    a.bodies["tank_a"].clearance.origin = np.array([0.4, -0.7, 1.1])
    want = a.rod_endpoints(a.rods["rod_a0"])[0].copy()

    back = ser.loads(ser.dumps(a))
    assert np.allclose(back.bodies["tank_a"].clearance.origin, [0.4, -0.7, 1.1])
    assert np.allclose(back.rod_endpoints(back.rods["rod_a0"])[0], want)
