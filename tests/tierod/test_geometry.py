"""
tests/tierod/test_geometry.py — Session 1 gate.

Covers:
  * every region primitive: analytic jacobian vs central finite difference
  * frame orthonormality after every dropdown-populated construction
  * clearance primitives: known segment distances, outward() unit + outward
  * standoff h, per-body sweep block with the scalar g_factor, ground semantics
  * V16 — the 26-case generator

No kernel code is exercised here; none exists yet.
"""
from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from library.tierod import cases as cases_mod
from library.tierod.cases import LoadCase, direction_matrix, generate_cases
from library.tierod.clearance import Box, Cylinder, Sphere
from library.tierod.model import (
    Assembly,
    Body,
    CircleArc,
    PlanarPatch,
    Region,
    Rod,
    RodEnd,
    Segment,
    frame_from_axis,
    frame_from_plane,
    skew,
)

TOL = 1e-6


# ======================================================================
# Regions — jacobian vs finite difference
# ======================================================================


def _fd_jacobian(region, q, eps=1e-6):
    q = np.asarray(q, dtype=float)
    J = np.zeros((3, q.size))
    for k in range(q.size):
        qp, qm = q.copy(), q.copy()
        qp[k] += eps
        qm[k] -= eps
        J[:, k] = (region.point(qp) - region.point(qm)) / (2.0 * eps)
    return J


def _interior_q(region, rng, margin=0.05):
    """Random q strictly interior to bounds()."""
    out = []
    for lo, hi in region.bounds():
        span = hi - lo
        out.append(rng.uniform(lo + margin * span, hi - margin * span))
    return np.array(out, dtype=float)


def test_every_primitive_is_covered(region_zoo):
    """Guard: if a new Region subclass is added, the zoo must grow with it."""
    covered = {type(r).__name__ for r in region_zoo}
    defined = {c.__name__ for c in _all_subclasses(Region)}
    assert defined - covered == set(), f"region primitives with no fixture: {defined - covered}"


def _all_subclasses(cls):
    out = set()
    for sub in cls.__subclasses__():
        out.add(sub)
        out |= _all_subclasses(sub)
    return out


def test_jacobian_matches_finite_difference(region_zoo, rng):
    for region in region_zoo:
        if region.ndim == 0:
            continue
        for _ in range(20):
            q = _interior_q(region, rng)
            J_an = region.jacobian(q)
            J_fd = _fd_jacobian(region, q)
            assert J_an.shape == (3, region.ndim)
            assert np.allclose(J_an, J_fd, rtol=TOL, atol=TOL), (
                f"{region.id}: analytic jacobian disagrees with FD at q={q}\n"
                f"analytic=\n{J_an}\nfd=\n{J_fd}"
            )


def test_zero_dim_region_interface(region_zoo):
    for region in region_zoo:
        if region.ndim != 0:
            continue
        assert region.bounds() == []
        assert region.point(np.zeros(0)).shape == (3,)
        assert region.jacobian(np.zeros(0)).shape == (3, 0)


def test_bounds_and_q0_are_consistent(region_zoo):
    for region in region_zoo:
        b = region.bounds()
        assert len(b) == region.ndim, f"{region.id}: bounds length != ndim"
        assert all(lo < hi for lo, hi in b), f"{region.id}: empty parameter range"
        q0 = region.q0()
        assert q0.shape == (region.ndim,)
        for qi, (lo, hi) in zip(q0, b):
            assert lo <= qi <= hi
        assert region.point(q0).shape == (3,)


def test_point_lies_on_the_declared_geometry(region_zoo, rng):
    """Spot-check a couple of primitives against their own closed form."""
    arc = next(r for r in region_zoo if isinstance(r, CircleArc))
    for _ in range(10):
        q = _interior_q(arc, rng)
        r = arc.point(q) - arc.origin
        assert np.isclose(np.linalg.norm(r), arc.radius, atol=1e-12)
        assert np.isclose(r @ arc.e3, 0.0, atol=1e-12), "arc must lie in the e1-e2 plane"

    patch = next(r for r in region_zoo if isinstance(r, PlanarPatch))
    for _ in range(10):
        q = _interior_q(patch, rng)
        d = patch.point(q) - patch.origin
        assert np.isclose(d @ patch.e3, 0.0, atol=1e-12), "patch must be planar"


# ======================================================================
# Frames — orthonormality after dropdown-populated construction
# ======================================================================


def _assert_orthonormal(e1, e2, e3, label=""):
    M = np.column_stack([e1, e2, e3])
    assert np.allclose(M.T @ M, np.eye(3), atol=1e-12), f"{label}: triad not orthonormal"
    assert np.isclose(np.linalg.det(M), 1.0, atol=1e-12), f"{label}: triad not right-handed"


@pytest.mark.parametrize("plane", ["XY", "YZ", "ZX", "xy", "yz", "zx"])
def test_frame_from_plane_is_orthonormal(plane):
    e1, e2, e3 = frame_from_plane(plane)
    _assert_orthonormal(e1, e2, e3, plane)


@pytest.mark.parametrize("axis,expected", [("X", 0), ("Y", 1), ("Z", 2)])
def test_frame_from_axis_is_orthonormal_and_normal_is_the_named_axis(axis, expected):
    e1, e2, e3 = frame_from_axis(axis)
    _assert_orthonormal(e1, e2, e3, axis)
    assert np.allclose(e3, np.eye(3)[expected]), "e3 must be the named axis"


@pytest.mark.parametrize("bad", ["", "XX", "Q", "XYZ"])
def test_frame_dropdowns_reject_garbage(bad):
    with pytest.raises(ValueError):
        frame_from_plane(bad)
    with pytest.raises(ValueError):
        frame_from_axis(bad)


def test_constructed_regions_carry_orthonormal_frames(region_zoo):
    for region in region_zoo:
        _assert_orthonormal(region.e1, region.e2, region.e3, region.id)


def test_region_rejects_a_non_orthonormal_frame():
    with pytest.raises(ValueError):
        Segment(
            id="bad",
            body_id="b",
            origin=np.zeros(3),
            e1=np.array([1.0, 0.0, 0.0]),
            e2=np.array([1.0, 1.0, 0.0]),  # not orthogonal, not unit
            e3=np.array([0.0, 0.0, 1.0]),
        )


def test_clearance_primitives_carry_orthonormal_frames(clearance_zoo):
    for prim in clearance_zoo:
        _assert_orthonormal(prim.e1, prim.e2, prim.e3, type(prim).__name__)


# ======================================================================
# Regression guard — the deleted cone model must not come back
# ======================================================================


def test_library_tierod_never_imports_streamlit():
    """Hard architectural rule: the kernel is importable and testable without
    the app. Checked in a subprocess so an unrelated test importing Streamlit
    cannot mask it."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    code = (
        "import sys; import library.tierod as t; "
        "sys.exit(1 if any(m == 'streamlit' or m.startswith('streamlit.') "
        "for m in sys.modules) else 0)"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"library.tierod pulled in Streamlit\n{r.stdout}{r.stderr}"


def test_mount_axis_model_is_gone():
    """§3.4: rods are spherical-bearing two-force members. A surface-normal
    misalignment cone was removed deliberately and must not be reintroduced."""
    assert not hasattr(Region, "mount_axis")
    region_fields = {f.name for c in _all_subclasses(Region) for f in dataclasses.fields(c)}
    region_fields |= {f.name for f in dataclasses.fields(Region)}
    assert "misalign_limit_deg" not in region_fields
    assert "axis_mode" not in region_fields
    assert not hasattr(Assembly, "mount_axis")


# ======================================================================
# Clearance — known distances
# ======================================================================


def _sphere():
    e1, e2, e3 = frame_from_plane("XY")
    return Sphere(origin=np.zeros(3), e1=e1, e2=e2, e3=e3, radius=3.0)


def _cylinder():
    e1, e2, e3 = frame_from_plane("XY")
    return Cylinder(
        origin=np.zeros(3), e1=e1, e2=e2, e3=e3, radius=2.0, z_min=0.0, z_max=10.0
    )


def _box():
    e1, e2, e3 = frame_from_plane("XY")
    return Box(origin=np.zeros(3), e1=e1, e2=e2, e3=e3, half_extents=(1.0, 2.0, 3.0))


SEGMENT_CASES = [
    # (primitive factory, a, b, expected distance, label)
    (_sphere, (-10, 0, 0), (10, 0, 0), 0.0, "sphere: through the centre"),
    (_sphere, (-10, 3, 0), (10, 3, 0), 0.0, "sphere: tangent"),
    (_sphere, (10, 0, 0), (10, 10, 0), 7.0, "sphere: clear, min at an endpoint"),
    (_sphere, (-10, 5, 0), (10, 5, 0), 2.0, "sphere: clear, min interior to the segment"),
    (_sphere, (0, 0, 1), (0, 0, 2), 0.0, "sphere: segment wholly inside"),
    (_cylinder, (-5, 0, 5), (5, 0, 5), 0.0, "cylinder: through the wall"),
    (_cylinder, (-5, 2, 5), (5, 2, 5), 0.0, "cylinder: tangent to the wall"),
    (_cylinder, (6, 0, 5), (6, 0, 6), 4.0, "cylinder: clear of the side"),
    (_cylinder, (0, 0, 14), (1, 0, 14), 4.0, "cylinder: clear beyond the end cap"),
    (_cylinder, (5, 0, 14), (5, 0, 15), 5.0, "cylinder: clear of the rim (3-4-5)"),
    (_cylinder, (-9, 0, 14), (9, 0, 14), 4.0, "cylinder: passes over the cap"),
    (_box, (-5, 0, 0), (5, 0, 0), 0.0, "box: through"),
    (_box, (1, -5, 0), (1, 5, 0), 0.0, "box: tangent on the +x face"),
    (_box, (5, 0, 0), (5, 1, 0), 4.0, "box: clear of one face"),
    (_box, (4, 6, 0), (4, 6, 1), 5.0, "box: clear of an edge (3-4-5)"),
    (_box, (-10, 6, 0), (10, 6, 0), 4.0, "box: clear, min interior to the segment"),
]


@pytest.mark.parametrize("factory,a,b,expected,label", SEGMENT_CASES)
def test_distance_to_segment_known_values(factory, a, b, expected, label):
    prim = factory()
    got = prim.distance_to_segment(np.array(a, float), np.array(b, float))
    assert got == pytest.approx(expected, abs=1e-8), label


@pytest.mark.parametrize("factory,a,b,expected,label", SEGMENT_CASES)
def test_distance_to_segment_is_endpoint_symmetric(factory, a, b, expected, label):
    prim = factory()
    fwd = prim.distance_to_segment(np.array(a, float), np.array(b, float))
    rev = prim.distance_to_segment(np.array(b, float), np.array(a, float))
    assert fwd == pytest.approx(rev, abs=1e-9), label


def test_distance_to_segment_respects_the_stored_frame():
    """The same geometry, rotated onto the X axis, must give the same answer."""
    ax = frame_from_axis("X")
    cyl_x = Cylinder(
        origin=np.zeros(3), e1=ax[0], e2=ax[1], e3=ax[2], radius=2.0, z_min=0.0, z_max=10.0
    )
    # cylinder now runs along +X; the sphere-case geometry rotated to match
    assert cyl_x.distance_to_segment(
        np.array([5.0, -5.0, 0.0]), np.array([5.0, 5.0, 0.0])
    ) == pytest.approx(0.0, abs=1e-9)
    assert cyl_x.distance_to_segment(
        np.array([5.0, 6.0, 0.0]), np.array([6.0, 6.0, 0.0])
    ) == pytest.approx(4.0, abs=1e-8)


def test_degenerate_segment_is_the_point_distance(clearance_zoo, rng):
    for prim in clearance_zoo:
        for _ in range(5):
            p = rng.uniform(-8.0, 8.0, size=3)
            assert prim.distance_to_segment(p, p.copy()) == pytest.approx(
                prim.distance_to_point(p), abs=1e-12
            )


def test_distance_to_segment_never_exceeds_either_endpoint(clearance_zoo, rng):
    for prim in clearance_zoo:
        for _ in range(25):
            a = rng.uniform(-12.0, 12.0, size=3)
            b = rng.uniform(-12.0, 12.0, size=3)
            d = prim.distance_to_segment(a, b)
            assert d >= -1e-12
            assert d <= min(prim.distance_to_point(a), prim.distance_to_point(b)) + 1e-9


# ======================================================================
# Clearance — outward()
# ======================================================================


def _boundary_points(prim, rng, n=40):
    """Sample boundary points, staying off edges/rims where the outward
    normal is legitimately ambiguous (§8.2 edge case)."""
    E = np.column_stack([prim.e1, prim.e2, prim.e3])
    pts = []
    if isinstance(prim, Sphere):
        for _ in range(n):
            v = rng.normal(size=3)
            pts.append(prim.origin + prim.radius * v / np.linalg.norm(v))
    elif isinstance(prim, Cylinder):
        for _ in range(n // 2):  # side wall
            th = rng.uniform(0.0, 2.0 * np.pi)
            z = rng.uniform(prim.z_min + 0.5, prim.z_max - 0.5)
            local = np.array([prim.radius * np.cos(th), prim.radius * np.sin(th), z])
            pts.append(prim.origin + E @ local)
        for _ in range(n // 2):  # end caps, well inside the rim
            th = rng.uniform(0.0, 2.0 * np.pi)
            r = rng.uniform(0.0, 0.85 * prim.radius)
            z = prim.z_max if rng.random() < 0.5 else prim.z_min
            local = np.array([r * np.cos(th), r * np.sin(th), z])
            pts.append(prim.origin + E @ local)
    elif isinstance(prim, Box):
        h = np.asarray(prim.half_extents, float)
        for _ in range(n):
            i = rng.integers(0, 3)
            local = rng.uniform(-0.85, 0.85, size=3) * h
            local[i] = h[i] if rng.random() < 0.5 else -h[i]
            pts.append(prim.origin + E @ local)
    else:  # pragma: no cover - guards a future primitive with no sampler
        raise AssertionError(f"no boundary sampler for {type(prim).__name__}")
    return pts


def test_outward_is_unit_length_and_points_out(clearance_zoo, rng):
    eps = 1e-4
    for prim in clearance_zoo:
        for p in _boundary_points(prim, rng):
            n = prim.outward(p)
            assert n.shape == (3,)
            assert np.isclose(np.linalg.norm(n), 1.0, atol=1e-12)
            assert prim.distance_to_point(p) == pytest.approx(0.0, abs=1e-9), (
                "sampled point should be on the boundary"
            )
            # stepping out leaves the solid, stepping in stays inside
            assert prim.distance_to_point(p + eps * n) == pytest.approx(eps, rel=1e-6)
            assert prim.distance_to_point(p - eps * n) == pytest.approx(0.0, abs=1e-12)


def test_outward_on_exterior_points_faces_away_from_the_body(clearance_zoo, rng):
    """For a convex solid the nearest-point map is constant along the outward
    normal ray, so distance grows by exactly the step taken. A merely
    'increasing' assertion would pass on a wrong-but-plausible direction."""
    for prim in clearance_zoo:
        for _ in range(20):
            p = rng.uniform(-15.0, 15.0, size=3)
            d0 = prim.distance_to_point(p)
            if d0 < 1e-3:
                continue
            n = prim.outward(p)
            assert np.isclose(np.linalg.norm(n), 1.0, atol=1e-12)
            for step in (0.1, 1.0):
                assert prim.distance_to_point(p + step * n) == pytest.approx(
                    d0 + step, rel=1e-9, abs=1e-9
                )


def test_nearest_point_agrees_with_distance_to_point(clearance_zoo, rng):
    """`distance_to_point` is overridden with a closed form on every primitive
    while `outward` goes through `_nearest_local`. Pin the two together."""
    for prim in clearance_zoo:
        for _ in range(40):
            p = rng.uniform(-15.0, 15.0, size=3)
            pl = prim.to_local(p)
            via_nearest = float(np.linalg.norm(pl - prim._nearest_local(pl)))
            assert via_nearest == pytest.approx(prim.distance_to_point(p), abs=1e-12)


def test_cylinder_outward_off_the_rim_is_the_diagonal():
    """A point clear of the rim in both r and z: the outward direction is the
    3-4-5 diagonal, not pure radial and not pure axial."""
    c = _cylinder()  # R = 2, z in [0, 10]
    n = c.outward(np.array([5.0, 0.0, 14.0]))
    assert np.allclose(n, [0.6, 0.0, 0.8])


def test_sphere_outward_is_radial():
    s = _sphere()
    p = np.array([3.0, 0.0, 0.0])
    assert np.allclose(s.outward(p), [1.0, 0.0, 0.0])


def test_cylinder_outward_side_is_radial_and_cap_is_axial():
    c = _cylinder()
    assert np.allclose(c.outward(np.array([2.0, 0.0, 5.0])), [1.0, 0.0, 0.0])
    assert np.allclose(c.outward(np.array([0.5, 0.0, 10.0])), [0.0, 0.0, 1.0])
    assert np.allclose(c.outward(np.array([0.5, 0.0, 0.0])), [0.0, 0.0, -1.0])


def test_box_outward_is_the_nearest_face():
    b = _box()
    assert np.allclose(b.outward(np.array([1.0, 0.0, 0.0])), [1.0, 0.0, 0.0])
    assert np.allclose(b.outward(np.array([0.0, -2.0, 0.0])), [0.0, -1.0, 0.0])
    assert np.allclose(b.outward(np.array([0.0, 0.0, 3.0])), [0.0, 0.0, 1.0])


# ======================================================================
# Bodies — ground semantics and the g-factored sweep block
# ======================================================================


def test_sweep_block_applies_the_scalar_g_factor():
    b = Body(id="b", mass=10.0, cg=np.array([1.0, 2.0, 3.0]), g_factor=4.0)
    W = b.sweep_block()
    assert W.shape == (6, 3)
    expected = 40.0 * np.vstack([np.eye(3), skew(np.array([1.0, 2.0, 3.0]))])
    assert np.allclose(W, expected)
    assert np.allclose(W[:3], 40.0 * np.eye(3))
    assert np.allclose(W[3:], 40.0 * np.array([[0, -3, 2], [3, 0, -1], [-2, 1, 0]]))


def test_sweep_block_is_isotropic_so_every_direction_gives_equal_force():
    """The magnitude lives on the body, the direction on the case. A unit
    direction must therefore produce the same force magnitude whichever way it
    points — that is the whole point of the convention."""
    b = Body(id="b", mass=10.0, cg=np.array([1.0, 2.0, 3.0]), g_factor=4.0)
    W = b.sweep_block()
    rng = np.random.default_rng(7)
    mags = []
    for _ in range(50):
        n = rng.normal(size=3)
        n /= np.linalg.norm(n)
        mags.append(np.linalg.norm((W @ n)[:3]))
    assert np.allclose(mags, 40.0), "force magnitude must not depend on direction"


def test_sweep_block_defaults_to_one_g():
    b = Body(id="b", mass=7.0, cg=np.array([0.0, 0.0, 1.0]))
    assert b.g_factor == 1.0
    assert np.allclose(b.sweep_block()[:3], 7.0 * np.eye(3))


def test_ground_body_carries_no_inertial_load():
    g = Body(id="g", is_ground=True, mass=99.0, cg=np.array([1.0, 1.0, 1.0]))
    with pytest.raises(ValueError):
        g.sweep_block()
    # ground is a flag, not a subclass, and mass/cg survive the toggle
    assert type(g) is Body
    assert g.mass == 99.0


def test_assembly_dof_bookkeeping_skips_ground(demo_assembly):
    a = demo_assembly
    assert a.free_bodies() == ["tank_a", "tank_b"]
    assert a.n_dof() == 12
    assert a.dof_slice("plate") is None
    assert a.dof_slice("tank_a") == slice(0, 6)
    assert a.dof_slice("tank_b") == slice(6, 12)
    assert a.expected_rank() == 12


def test_sweep_map_stacks_free_bodies_only(demo_assembly):
    W = demo_assembly.sweep_map()
    assert W.shape == (12, 3)
    assert np.allclose(W[0:6], demo_assembly.bodies["tank_a"].sweep_block())
    assert np.allclose(W[6:12], demo_assembly.bodies["tank_b"].sweep_block())


def test_zero_ground_bodies_is_a_legal_model(demo_assembly):
    """Free-free is a diagnostic mode, not an error, at the model level."""
    demo_assembly.bodies["plate"].is_ground = False
    assert len(demo_assembly.free_bodies()) == 3
    assert demo_assembly.n_dof() == 18
    demo_assembly.validate()


def test_multiple_ground_bodies_are_legal(demo_assembly):
    demo_assembly.bodies["tank_b"].is_ground = True
    assert demo_assembly.free_bodies() == ["tank_a"]
    assert demo_assembly.n_dof() == 6
    demo_assembly.validate()


# ======================================================================
# Rod ends — standoff h, topology, design vector layout
# ======================================================================


def test_standoff_offsets_along_the_outward_direction():
    e1, e2, e3 = frame_from_plane("XY")
    body = Body(
        id="b",
        origin=np.array([1.0, 2.0, 3.0]),
        clearance=Cylinder(
            origin=np.zeros(3), e1=e1, e2=e2, e3=e3, radius=5.0, z_min=0.0, z_max=20.0
        ),
    )
    from library.tierod.model import CylindricalBand

    band = CylindricalBand(
        id="band",
        body_id="b",
        origin=np.zeros(3),
        e1=e1,
        e2=e2,
        e3=e3,
        radius=5.0,
        z_min=0.0,
        z_max=20.0,
    )
    asm = Assembly(bodies={"b": body}, regions={"band": band}, rods={})

    q = np.array([0.0, 10.0])  # theta = 0 -> +X side of the wall
    flush = asm.endpoint_global(RodEnd(region_id="band", q=q, h=0.0))[0]
    stood = asm.endpoint_global(RodEnd(region_id="band", q=q, h=2.0))[0]

    assert np.allclose(flush, [6.0, 2.0, 13.0])
    assert np.allclose(stood, [8.0, 2.0, 13.0])
    assert np.linalg.norm(stood - flush) == pytest.approx(2.0)


def test_standoff_default_is_zero_and_needs_no_clearance():
    end = RodEnd(region_id="r", q=np.zeros(0))
    assert end.h == 0.0


def test_nonzero_standoff_without_a_clearance_primitive_is_an_error():
    e1, e2, e3 = frame_from_plane("XY")
    body = Body(id="b", clearance=None)
    seg = Segment(
        id="s", body_id="b", origin=np.zeros(3), e1=e1, e2=e2, e3=e3, length=4.0
    )
    asm = Assembly(bodies={"b": body}, regions={"s": seg}, rods={})
    with pytest.raises(ValueError, match="clearance"):
        asm.endpoint_global(RodEnd(region_id="s", q=np.array([0.5]), h=1.0))


def test_design_vector_layout_skips_fixed_points():
    e1, e2, e3 = frame_from_plane("XY")
    body = Body(id="b")
    from library.tierod.model import FixedPoint

    regions = {
        "fix": FixedPoint(id="fix", body_id="b", origin=np.zeros(3), e1=e1, e2=e2, e3=e3),
        "patch": PlanarPatch(
            id="patch",
            body_id="b",
            origin=np.zeros(3),
            e1=e1,
            e2=e2,
            e3=e3,
            width=2.0,
            height=2.0,
        ),
    }
    rod = Rod(
        id="r1",
        end_a=RodEnd(region_id="fix", q=np.zeros(0)),
        end_b=RodEnd(region_id="patch", q=np.array([0.5, 0.5])),
        E=1.0,
        A=1.0,
        I=1.0,
        Fcy=1.0,
    )
    asm = Assembly(bodies={"b": body}, regions=regions, rods={"r1": rod})
    assert asm.design_vector_layout() == [("r1", "b", 2)]
    assert asm.n_design_vars() == 2


def test_demo_assembly_layout_and_validation(demo_assembly):
    demo_assembly.validate()
    assert len(demo_assembly.rods) == 12
    # every rod spans a 2-D band and a 2-D annulus -> 4 variables each
    assert demo_assembly.n_design_vars() == 48
    layout = demo_assembly.design_vector_layout()
    assert len(layout) == 24
    assert all(nd == 2 for _, _, nd in layout)


def test_rod_carries_the_phase5_backup_stiffness_hook():
    rod = Rod(
        id="r",
        end_a=RodEnd(region_id="a", q=np.zeros(0)),
        end_b=RodEnd(region_id="b", q=np.zeros(0)),
        E=1.0,
        A=1.0,
        I=1.0,
        Fcy=1.0,
    )
    assert rod.end_fixity == 1.0
    assert np.isinf(rod.k_backup_a) and np.isinf(rod.k_backup_b)  # rigid default


def test_validate_rejects_a_mismatched_q_length():
    e1, e2, e3 = frame_from_plane("XY")
    body = Body(id="b")
    seg = Segment(
        id="s", body_id="b", origin=np.zeros(3), e1=e1, e2=e2, e3=e3, length=4.0
    )
    rod = Rod(
        id="r",
        end_a=RodEnd(region_id="s", q=np.array([0.5, 0.5])),  # wrong length
        end_b=RodEnd(region_id="s", q=np.array([0.5])),
        E=1.0,
        A=1.0,
        I=1.0,
        Fcy=1.0,
    )
    asm = Assembly(bodies={"b": body}, regions={"s": seg}, rods={"r": rod})
    with pytest.raises(ValueError, match="q"):
        asm.validate()


def test_validate_rejects_a_dangling_region_reference():
    body = Body(id="b")
    rod = Rod(
        id="r",
        end_a=RodEnd(region_id="nope", q=np.zeros(0)),
        end_b=RodEnd(region_id="nope", q=np.zeros(0)),
        E=1.0,
        A=1.0,
        I=1.0,
        Fcy=1.0,
    )
    asm = Assembly(bodies={"b": body}, regions={}, rods={"r": rod})
    with pytest.raises(ValueError, match="region"):
        asm.validate()


def test_body_R_is_applied_to_region_geometry():
    """Body.R stays identity in the UI for now but must be honoured."""
    e1, e2, e3 = frame_from_plane("XY")
    Rz = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    body = Body(id="b", origin=np.array([0.0, 0.0, 1.0]), R=Rz)
    seg = Segment(
        id="s", body_id="b", origin=np.zeros(3), e1=e1, e2=e2, e3=e3, length=4.0
    )
    asm = Assembly(bodies={"b": body}, regions={"s": seg}, rods={})
    p, body_id = asm.endpoint_global(RodEnd(region_id="s", q=np.array([1.0])))
    assert body_id == "b"
    assert np.allclose(p, [0.0, 4.0, 1.0])  # local +4X rotated to +4Y, then offset


# ======================================================================
# V16 — load case generator
#
# Revised convention (owner decision, 2026-08-21): a case is a UNIT DIRECTION
# with a per-case factor. Magnitude lives on the body as a scalar `g_factor`.
# Every case therefore has the same magnitude; the sweep varies direction only.
# ======================================================================


def test_v16_every_case_is_unit_magnitude(cases):
    """The defining property of the convention. If this fails, multi-axis
    cases are stacking factors and the sweep is no longer a pure direction
    sweep."""
    for c in cases:
        assert np.linalg.norm(c.direction) == pytest.approx(1.0, abs=1e-12), (
            f"{c.id} {c.name} has magnitude {np.linalg.norm(c.direction)}"
        )


def test_v16_case_magnitudes_are_all_identical(cases):
    mags = [float(np.linalg.norm(c.direction)) for c in cases]
    assert max(mags) - min(mags) == pytest.approx(0.0, abs=1e-12)


def test_v16_exactly_26_unique_directions(cases):
    assert len(cases) == 26
    D = np.array([c.direction for c in cases])
    for i in range(len(D)):
        for j in range(i + 1, len(D)):
            assert not np.allclose(D[i], D[j], atol=1e-12), f"cases {i} and {j} coincide"


def test_v16_group_counts_are_6_face_12_edge_8_corner(cases):
    counts: dict[int, int] = {}
    for c in cases:
        n = int(np.count_nonzero(np.abs(c.direction) > 1e-12))
        counts[n] = counts.get(n, 0) + 1
    assert counts == {1: 6, 2: 12, 3: 8}


def test_v16_direction_components_are_the_normalized_cube_normals(cases):
    for c in cases:
        n_active = int(np.count_nonzero(np.abs(c.direction) > 1e-12))
        expected = 1.0 / np.sqrt(n_active)
        nz = c.direction[np.abs(c.direction) > 1e-12]
        assert np.allclose(np.abs(nz), expected, atol=1e-12), (
            f"{c.name}: components should be +-1/sqrt({n_active})"
        )


def test_v16_the_set_is_antipodally_symmetric(cases):
    """Every direction has its opposite in the set — a rod must see both
    senses of every orientation."""
    D = [c.direction for c in cases]
    for d in D:
        assert any(np.allclose(-d, other, atol=1e-12) for other in D), (
            f"no antipode for {d}"
        )


def test_v16_ordering_and_naming_are_stable(cases):
    again = generate_cases()
    assert [c.id for c in cases] == [c.id for c in again]
    assert [c.name for c in cases] == [c.name for c in again]
    assert all(np.allclose(a.direction, b.direction) for a, b in zip(cases, again))
    order = [int(np.count_nonzero(np.abs(c.direction) > 1e-12)) for c in cases]
    assert order == sorted(order), "faces, then edges, then corners"
    assert [c.name for c in cases[:6]] == ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]
    assert cases[6].name == "+X+Y"
    assert cases[-1].name == "-X-Y-Z"
    assert [c.id for c in cases[:3]] == ["C01", "C02", "C03"]
    assert len({c.id for c in cases}) == 26


def test_v16_axis_cases_are_the_global_axes(cases):
    assert np.allclose(cases_mod.case_by_name(cases, "+X").direction, [1.0, 0.0, 0.0])
    assert np.allclose(cases_mod.case_by_name(cases, "-Z").direction, [0.0, 0.0, -1.0])


def test_v16_names_round_trip_to_their_directions(cases):
    for c in cases:
        assert np.allclose(cases_mod.parse_case_name(c.name), c.direction, atol=1e-12)


def test_v16_factor_defaults_to_one_and_is_user_settable(cases):
    assert all(c.factor == 1.0 for c in cases)
    damaged = generate_cases(factor=0.67)
    assert all(c.factor == pytest.approx(0.67) for c in damaged)
    # the factor scales the load, never the direction
    assert all(np.linalg.norm(c.direction) == pytest.approx(1.0) for c in damaged)


def test_v16_direction_matrix_shape_and_weighting(cases):
    N = direction_matrix(cases)
    assert N.shape == (3, 26)
    assert np.allclose(np.linalg.norm(N, axis=0), 1.0)
    for j, c in enumerate(cases):
        assert np.allclose(N[:, j], c.direction)
    damaged = generate_cases(factor=0.5)
    assert np.allclose(direction_matrix(damaged, weighted=True), 0.5 * N)
    assert np.allclose(direction_matrix(damaged, weighted=False), N)


def test_v16_direction_sets_are_a_registry(cases):
    """Adding a finer sweep must be a new registry entry, not a refactor."""
    assert set(cases_mod.DIRECTION_SETS) >= {"axes6", "cube26"}
    assert cases_mod.DEFAULT_DIRECTION_SET == "cube26"
    six = generate_cases(set_name="axes6")
    assert len(six) == 6
    assert all(np.linalg.norm(c.direction) == pytest.approx(1.0) for c in six)
    assert [c.name for c in six] == ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]
    with pytest.raises(ValueError, match="unknown direction set"):
        generate_cases(set_name="nope")


def test_v16_custom_direction_set_is_normalized_for_you():
    """The escape hatch for a bespoke sweep still cannot produce a non-unit
    case."""
    raw = [[3.0, 0.0, 0.0], [0.0, -7.0, 0.0], [1.0, 1.0, 1.0]]
    custom = cases_mod.cases_from_directions(raw, factor=1.5)
    assert len(custom) == 3
    assert all(np.linalg.norm(c.direction) == pytest.approx(1.0) for c in custom)
    assert np.allclose(custom[0].direction, [1.0, 0.0, 0.0])
    assert all(c.factor == 1.5 for c in custom)
    with pytest.raises(ValueError):
        cases_mod.cases_from_directions([[0.0, 0.0, 0.0]])
    with pytest.raises(ValueError, match="names"):
        cases_mod.cases_from_directions(raw, names=["only", "two"])


def test_load_case_rejects_a_degenerate_direction():
    with pytest.raises(ValueError):
        LoadCase(id="C99", name="bad", direction=np.zeros(3))
    with pytest.raises(ValueError):
        LoadCase(id="C99", name="bad", direction=np.array([1.0, 0.0]))


def test_load_case_normalizes_on_construction():
    c = LoadCase(id="C01", name="+X", direction=np.array([5.0, 0.0, 0.0]))
    assert np.allclose(c.direction, [1.0, 0.0, 0.0])


def test_case_lookup_by_name_and_id(cases):
    c = cases_mod.case_by_name(cases, "+X-Y+Z")
    assert np.allclose(c.direction, np.array([1.0, -1.0, 1.0]) / np.sqrt(3.0))
    assert cases_mod.case_by_id(cases, "C01").name == "+X"
    with pytest.raises(KeyError):
        cases_mod.case_by_name(cases, "+Q")
    with pytest.raises(KeyError):
        cases_mod.case_by_id(cases, "C99")


def test_nearest_case_labels_an_arbitrary_direction(cases):
    """The closed-form worst direction gets a name the engineer recognizes,
    plus the angle — the honest measure of how well the set covers it."""
    c, angle = cases_mod.nearest_case(cases, [1.0, 0.0, 0.0])
    assert c.name == "+X" and angle == pytest.approx(0.0, abs=1e-9)
    c, angle = cases_mod.nearest_case(cases, [1.0, 1.0, 0.0])
    assert c.name == "+X+Y" and angle == pytest.approx(0.0, abs=1e-9)
    c, angle = cases_mod.nearest_case(cases, [10.0, 1.0, 0.0])
    assert c.name == "+X" and 0.0 < angle < 10.0
    with pytest.raises(ValueError):
        cases_mod.nearest_case(cases, [0.0, 0.0, 0.0])


def test_enumerated_set_never_exceeds_the_closed_form_envelope(demo_assembly, cases):
    """The convention's key consequence, and the reason the closed form is the
    reportable value: with unit directions the exact envelope over ALL
    orientations is the row 2-norm, and any enumerated set is a sample of it
    that can only fall short."""
    W = demo_assembly.sweep_map()
    N = direction_matrix(cases)
    rng = np.random.default_rng(3)
    T = rng.normal(size=(12, W.shape[0])) @ W  # stand-in for T = G W (no kernel yet)

    enumerated = np.max(np.abs(T @ N), axis=1)
    closed_form = np.linalg.norm(T, axis=1)
    assert np.all(enumerated <= closed_form + 1e-9)
    for i in range(T.shape[0]):
        n_star = T[i] / np.linalg.norm(T[i])
        assert abs(T[i] @ n_star) == pytest.approx(closed_form[i], rel=1e-12)


def test_per_case_loads_are_a_single_matmul(demo_assembly, cases):
    """The shape contract the sweep (Session 5) is built on."""
    W = demo_assembly.sweep_map()
    F = W @ direction_matrix(cases)
    assert F.shape == (12, 26)
    ix = [c.name for c in cases].index("+X")
    imx = [c.name for c in cases].index("-X")
    assert np.allclose(F[:, ix], -F[:, imx])


def test_every_case_produces_the_same_applied_force_magnitude(demo_assembly, cases):
    """End-to-end statement of the owner requirement: no case double-dips."""
    W = demo_assembly.sweep_map()
    F = W @ direction_matrix(cases)
    for body_i in range(len(demo_assembly.free_bodies())):
        rows = slice(6 * body_i, 6 * body_i + 3)  # force rows for this body
        mags = np.linalg.norm(F[rows, :], axis=0)
        assert np.allclose(mags, mags[0]), "force magnitude varies between cases"
