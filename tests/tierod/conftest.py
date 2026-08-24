"""
tests/tierod/conftest.py

Golden fixtures shared across the tierod test files.

The repo-root sys.path insert lives in `tests/conftest.py` (one level up) and
applies here too, so `library.tierod` imports resolve regardless of how pytest
is invoked.

Nothing in here may import Streamlit.
"""
from __future__ import annotations

import numpy as np
import pytest

from library.tierod.cases import generate_cases
from library.tierod.clearance import Box, Cylinder, Sphere
from library.tierod.model import (
    Annulus,
    Assembly,
    Body,
    CircleArc,
    CylindricalBand,
    FixedPoint,
    PlanarPatch,
    Rod,
    RodEnd,
    Segment,
    SphericalPatch,
    frame_from_axis,
    frame_from_plane,
)

SEED = 20260821


@pytest.fixture
def rng() -> np.random.Generator:
    """Deterministic generator — golden tests must not flake."""
    return np.random.default_rng(SEED)


# ----------------------------------------------------------------------
# One instance of every region primitive, deliberately on mixed frames
# so the stored triad (not an implicit global-axis assumption) is what
# the geometry actually uses.
# ----------------------------------------------------------------------


def _region_zoo() -> list:
    xy = frame_from_plane("XY")
    yz = frame_from_plane("YZ")
    zx = frame_from_plane("ZX")
    ax_x = frame_from_axis("X")

    return [
        FixedPoint(
            id="r_fixed", body_id="b", origin=np.array([1.0, -2.0, 3.0]), **_triad(xy)
        ),
        Segment(
            id="r_seg",
            body_id="b",
            origin=np.array([0.5, 0.25, -1.0]),
            length=7.0,
            **_triad(yz),
        ),
        CircleArc(
            id="r_arc",
            body_id="b",
            origin=np.array([-1.0, 0.0, 2.0]),
            radius=4.0,
            theta_min=0.2,
            theta_max=2.4,
            **_triad(zx),
        ),
        PlanarPatch(
            id="r_patch",
            body_id="b",
            origin=np.array([2.0, 2.0, 0.0]),
            width=6.0,
            height=3.5,
            **_triad(xy),
        ),
        Annulus(
            id="r_ann",
            body_id="b",
            origin=np.array([0.0, 0.0, 5.0]),
            r_inner=1.5,
            r_outer=4.5,
            theta_min=-0.9,
            theta_max=2.7,
            **_triad(ax_x),
        ),
        CylindricalBand(
            id="r_band",
            body_id="b",
            origin=np.array([-3.0, 1.0, 0.0]),
            radius=2.75,
            z_min=1.0,
            z_max=9.0,
            theta_min=0.0,
            theta_max=np.pi,
            **_triad(zx),
        ),
        SphericalPatch(
            id="r_sph",
            body_id="b",
            origin=np.array([4.0, -1.0, 1.0]),
            radius=3.25,
            theta_min=-1.1,
            theta_max=1.9,
            phi_min=0.25,
            phi_max=1.35,
            **_triad(yz),
        ),
    ]


def _triad(frame) -> dict:
    e1, e2, e3 = frame
    return {"e1": e1, "e2": e2, "e3": e3}


@pytest.fixture
def region_zoo() -> list:
    """One of every region primitive. Parametrized tests iterate this."""
    return _region_zoo()


@pytest.fixture
def clearance_zoo() -> list:
    """One of every clearance primitive, on mixed frames."""
    e1, e2, e3 = frame_from_plane("XY")
    ax_x1, ax_x2, ax_x3 = frame_from_axis("X")
    return [
        Sphere(origin=np.zeros(3), e1=e1, e2=e2, e3=e3, radius=3.0),
        Cylinder(
            origin=np.zeros(3),
            e1=e1,
            e2=e2,
            e3=e3,
            radius=2.0,
            z_min=0.0,
            z_max=10.0,
        ),
        # axis along global X — exercises the stored triad
        Cylinder(
            origin=np.array([1.0, 2.0, 3.0]),
            e1=ax_x1,
            e2=ax_x2,
            e3=ax_x3,
            radius=1.5,
            z_min=-4.0,
            z_max=4.0,
        ),
        Box(origin=np.zeros(3), e1=e1, e2=e2, e3=e3, half_extents=(1.0, 2.0, 3.0)),
    ]


@pytest.fixture
def cases() -> list:
    return generate_cases()


# ----------------------------------------------------------------------
# Demo assembly — two cylinders on a baseplate, 12 rods.
#
# This is the push-1 definition-of-done geometry. Session 1 only asserts it
# is a structurally valid model; the kernel gates land in later sessions.
# ----------------------------------------------------------------------

_TANK_R = 5.0
_TANK_H = 30.0
_ROD_E = 29.0e6
_ROD_A = 0.1104  # 0.375 dia
_ROD_I = 9.71e-4
_ROD_FCY = 180.0e3


def _tank(body_id: str, x: float) -> Body:
    e1, e2, e3 = frame_from_plane("XY")
    return Body(
        id=body_id,
        is_ground=False,
        origin=np.array([x, 0.0, 0.0]),
        mass=50.0,
        cg=np.array([0.0, 0.0, 0.5 * _TANK_H]),
        g_factor=6.0,
        clearance=Cylinder(
            origin=np.zeros(3),
            e1=e1,
            e2=e2,
            e3=e3,
            radius=_TANK_R,
            z_min=0.0,
            z_max=_TANK_H,
        ),
    )


def _demo_assembly() -> Assembly:
    e1, e2, e3 = frame_from_plane("XY")

    plate = Body(
        id="plate",
        is_ground=True,
        origin=np.array([0.0, 0.0, -0.5]),
        mass=400.0,  # retained though grounded — toggling ground keeps data
        cg=np.zeros(3),
        g_factor=6.0,
        clearance=Box(
            origin=np.zeros(3),
            e1=e1,
            e2=e2,
            e3=e3,
            half_extents=(24.0, 16.0, 0.5),
        ),
    )
    tank_a = _tank("tank_a", -10.0)
    tank_b = _tank("tank_b", +10.0)

    bodies = {b.id: b for b in (plate, tank_a, tank_b)}

    regions: dict = {}
    for tag, x in (("a", -10.0), ("b", +10.0)):
        # rod feet: an annulus on the plate top face, ringing each tank
        regions[f"foot_{tag}"] = Annulus(
            id=f"foot_{tag}",
            body_id="plate",
            origin=np.array([x, 0.0, 0.5]),
            e1=e1,
            e2=e2,
            e3=e3,
            r_inner=_TANK_R + 2.0,
            r_outer=_TANK_R + 6.0,
        )
        # rod heads: a band around the tank wall
        regions[f"band_{tag}"] = CylindricalBand(
            id=f"band_{tag}",
            body_id=f"tank_{tag}",
            origin=np.zeros(3),
            e1=e1,
            e2=e2,
            e3=e3,
            radius=_TANK_R,
            z_min=4.0,
            z_max=26.0,
        )

    rods: dict = {}
    for tag in ("a", "b"):
        for k in range(6):
            th = 2.0 * np.pi * k / 6.0
            z = 22.0 if k % 2 == 0 else 8.0
            rods[f"rod_{tag}{k}"] = Rod(
                id=f"rod_{tag}{k}",
                end_a=RodEnd(
                    region_id=f"band_{tag}", q=np.array([th, z]), h=0.75
                ),
                end_b=RodEnd(
                    region_id=f"foot_{tag}",
                    q=np.array([_TANK_R + 4.0, th + 0.5]),
                    h=0.0,
                ),
                E=_ROD_E,
                A=_ROD_A,
                I=_ROD_I,
                Fcy=_ROD_FCY,
                Ftu=180.0e3,
                A_net=0.08,
            )

    return Assembly(bodies=bodies, regions=regions, rods=rods)


@pytest.fixture
def demo_assembly() -> Assembly:
    """2 cylinders + baseplate, 12 rods, 2 free bodies (12 DOF)."""
    return _demo_assembly()


# ======================================================================
# Session 2 — kernel fixtures
#
# `build_assembly` creates one FixedPoint region per rod end from GLOBAL
# points, converting to body-local itself. Kernel tests care about screws and
# loads, not about parameterized regions, so this keeps their geometry
# readable as coordinates.
#
# Every layout below has been checked for rank and conditioning; the
# nonsingular ones assert it in the tests rather than assuming it.
# ======================================================================

DEFAULT_ROD = {
    "E": 29.0e6,
    "A": 0.1104,
    "I": 9.71e-4,
    "Fcy": 180.0e3,
}


def build_assembly(bodies, rod_specs) -> Assembly:
    """Build an Assembly from global rod endpoints.

    bodies    : iterable of Body
    rod_specs : iterable of dicts, each {'id', 'a': (body_id, p_global),
                'b': (body_id, p_global), **rod property overrides}
    """
    body_map = {b.id: b for b in bodies}
    e1, e2, e3 = frame_from_plane("XY")
    regions: dict = {}
    rods: dict = {}
    for spec in rod_specs:
        ends = {}
        for tag in ("a", "b"):
            body_id, p_global = spec[tag]
            body = body_map[body_id]
            p_local = body.R.T @ (np.asarray(p_global, dtype=float) - body.origin)
            rid = f"{spec['id']}_{tag}"
            regions[rid] = FixedPoint(
                id=rid, body_id=body_id, origin=p_local, e1=e1, e2=e2, e3=e3
            )
            ends[tag] = RodEnd(region_id=rid, q=np.zeros(0))
        props = dict(DEFAULT_ROD)
        props.update({k: v for k, v in spec.items() if k not in ("id", "a", "b")})
        rods[spec["id"]] = Rod(
            id=spec["id"], end_a=ends["a"], end_b=ends["b"], **props
        )
    return Assembly(bodies=body_map, regions=regions, rods=rods)


def _ground(body_id="ground") -> Body:
    return Body(id=body_id, is_ground=True)


def _free(body_id, origin, mass=100.0, cg=None, g_factor=1.0) -> Body:
    return Body(
        id=body_id,
        is_ground=False,
        origin=np.asarray(origin, dtype=float),
        mass=mass,
        cg=np.zeros(3) if cg is None else np.asarray(cg, dtype=float),
        g_factor=g_factor,
    )


# -- V1: unit cage ------------------------------------------------------
# One free body, six rods, statically determinate. Three rods meet the body
# datum (no moment arm) and carry pure translation; three offset rods lock the
# rotations. Under a load along one global axis exactly ONE rod is loaded,
# which makes the sign convention unambiguous.

_CAGE_RODS = [
    ("r_x", (0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
    ("r_y", (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
    ("r_z", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    ("r_rz", (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)),
    ("r_rx", (0.0, 0.0, 1.0), (0.0, 1.0, 1.0)),
    ("r_ry", (1.0, 0.0, 0.0), (1.0, 0.0, 1.0)),
]


def make_unit_cage(**rod_overrides) -> Assembly:
    return build_assembly(
        [_free("body", (0.0, 0.0, 0.0)), _ground()],
        [
            {"id": rid, "a": ("body", a), "b": ("ground", b), **rod_overrides}
            for rid, a, b in _CAGE_RODS
        ],
    )


@pytest.fixture
def unit_cage() -> Assembly:
    return make_unit_cage()


# -- V2: tripod ---------------------------------------------------------
# Three rods from a common apex on the body, splayed at half-angle theta to
# ground. Concurrent lines, so all three rotations are free and K is singular
# BY CONSTRUCTION — the statics is still exact and that is what V2 checks.


def make_tripod(theta_deg=25.0, height=20.0) -> Assembly:
    th = np.radians(theta_deg)
    apex = np.array([0.0, 0.0, height])
    radius = height * np.tan(th)
    specs = []
    for k in range(3):
        phi = np.radians(120.0 * k)
        g = (radius * np.cos(phi), radius * np.sin(phi), 0.0)
        specs.append({"id": f"leg{k}", "a": ("body", tuple(apex)), "b": ("ground", g)})
    return build_assembly([_free("body", apex), _ground()], specs)


@pytest.fixture
def tripod() -> Assembly:
    return make_tripod()


# -- V3 / V4: 6-3 hexapod -----------------------------------------------
# Six rods, one free body, statically determinate and well conditioned
# (sigma_min/sigma_max = 0.58 on the non-dimensionalized screw matrix).

_HEX_RT, _HEX_RB, _HEX_H, _HEX_ALPHA = 10.0, 14.0, 12.0, 15.0


def make_hexapod(rod_overrides=None, extra_rods=(), scale=1.0) -> Assembly:
    """`scale` multiplies every length, leaving the layout geometrically
    similar — used to prove the screw spectrum is scale invariant once
    non-dimensionalized."""
    rod_overrides = rod_overrides or {}
    rt, rb, h = _HEX_RT * scale, _HEX_RB * scale, _HEX_H * scale
    specs = []
    for i in range(3):
        base = 120.0 * i
        for sgn, tag in ((-1.0, "m"), (+1.0, "p")):
            at = np.radians(base + sgn * _HEX_ALPHA)
            bt = np.radians(base + sgn * 60.0)
            specs.append(
                {
                    "id": f"h{i}{tag}",
                    "a": ("body", (rt * np.cos(at), rt * np.sin(at), h)),
                    "b": ("ground", (rb * np.cos(bt), rb * np.sin(bt), 0.0)),
                    **rod_overrides.get(f"h{i}{tag}", {}),
                }
            )
    specs.extend(extra_rods)
    return build_assembly(
        [_free("body", (0.0, 0.0, h), mass=200.0), _ground()], specs
    )


@pytest.fixture
def hexapod() -> Assembly:
    return make_hexapod()


# -- deliberately singular: the 6-6 rotary hexapod ----------------------
# Top and bottom attachment circles with a UNIFORM angular offset. Six rods,
# one free body, and rank 3 — three mechanism modes. Every rod line is tangent
# to a common hyperboloid, the classic singular Stewart platform.
#
# Kept as a fixture on purpose: it is the case where K is rank deficient but
# LAPACK's LU finds no exact zero pivot, so `np.linalg.solve` returns a large
# WRONG answer instead of raising. That is what `kernel._solve_checked`'s
# residual guard exists to catch, and this is the only fixture that exercises
# it. Session 3 should reuse it for the geometric-degeneracy checks.


def make_rotary_hexapod(offset_deg=30.0) -> Assembly:
    rt, rb, h = 10.0, 14.0, 12.0
    specs = []
    for k in range(6):
        at = np.radians(60.0 * k)
        bt = np.radians(60.0 * k + offset_deg)
        specs.append(
            {
                "id": f"r{k}",
                "a": ("body", (rt * np.cos(at), rt * np.sin(at), h)),
                "b": ("ground", (rb * np.cos(bt), rb * np.sin(bt), 0.0)),
            }
        )
    return build_assembly([_free("body", (0.0, 0.0, h)), _ground()], specs)


@pytest.fixture
def rotary_hexapod() -> Assembly:
    return make_rotary_hexapod()


# -- V5 / V6: 8-rod, 4-fold symmetric, redundant ------------------------
# Four splayed legs plus four tangential braces, invariant under a 90 deg
# rotation about Z. N = 8 against 6 DOF, so two redundancies. A load along -Z
# is invariant under the same rotation, so the four legs must carry equal load
# and the four braces likewise.

_S8_R, _S8_RG, _S8_H = 8.0, 12.0, 10.0


def make_symmetric8(leg_scale=None) -> Assembly:
    """leg_scale: optional {rod_id: A multiplier} to break the symmetry."""
    leg_scale = leg_scale or {}
    P = [
        (
            _S8_R * np.cos(np.radians(90.0 * k)),
            _S8_R * np.sin(np.radians(90.0 * k)),
            _S8_H,
        )
        for k in range(4)
    ]
    G = [
        (
            _S8_RG * np.cos(np.radians(90.0 * k)),
            _S8_RG * np.sin(np.radians(90.0 * k)),
            0.0,
        )
        for k in range(4)
    ]
    specs = []
    for k in range(4):
        for rid, b_pt in ((f"leg{k}", G[k]), (f"brace{k}", G[(k + 1) % 4])):
            spec = {"id": rid, "a": ("body", P[k]), "b": ("ground", b_pt)}
            if rid in leg_scale:
                spec["A"] = DEFAULT_ROD["A"] * leg_scale[rid]
            specs.append(spec)
    return build_assembly(
        [_free("body", (0.0, 0.0, _S8_H), mass=300.0), _ground()], specs
    )


@pytest.fixture
def symmetric8() -> Assembly:
    return make_symmetric8()


# -- multi-body: two free bodies, body-to-body rods ---------------------


def _hex_pairs(cx, rt=4.0, rb=7.0, h=8.0, alpha=15.0):
    """6-3 hexapod endpoint pairs about a centre at x = cx.

    NOT the 6-6 rotary pattern (top and bottom on circles with a uniform
    angular offset) — that arrangement is rank 3, a genuine singularity, and
    silently poisons any fixture built on it.
    """
    pairs = []
    for i in range(3):
        base = 120.0 * i
        for sgn in (-1.0, +1.0):
            at = np.radians(base + sgn * alpha)
            bt = np.radians(base + sgn * 60.0)
            pairs.append(
                (
                    (cx + rt * np.cos(at), rt * np.sin(at), h),
                    (cx + rb * np.cos(bt), rb * np.sin(bt), 0.0),
                )
            )
    return pairs


def make_two_body() -> Assembly:
    """Two free bodies, each on its own 6-3 hexapod of ground rods, tied to
    each other by two body-to-body rods. 14 rods against 12 DOF, so genuinely
    redundant. Exercises the multi-block Ghat assembly."""
    specs = []
    for tag, x in (("a", -10.0), ("b", 10.0)):
        for k, (a_pt, b_pt) in enumerate(_hex_pairs(x)):
            specs.append(
                {
                    "id": f"g_{tag}{k}",
                    "a": (f"body_{tag}", a_pt),
                    "b": ("ground", b_pt),
                }
            )
    for k in range(2):
        z = 6.0 + 2.0 * k
        specs.append(
            {
                "id": f"tie{k}",
                "a": ("body_a", (-6.0, 1.5 - 3.0 * k, z)),
                "b": ("body_b", (6.0, -1.5 + 3.0 * k, z)),
            }
        )
    return build_assembly(
        [
            _free("body_a", (-10.0, 0.0, 8.0), mass=60.0, cg=(0.0, 0.0, 2.0)),
            _free("body_b", (10.0, 0.0, 8.0), mass=90.0, cg=(0.0, 0.0, 3.0)),
            _ground(),
        ],
        specs,
    )


@pytest.fixture
def two_body() -> Assembly:
    return make_two_body()


# ======================================================================
# Session 3 — mechanism fixtures
#
# Each is a DELIBERATE degeneracy of a specific kind, so the diagnostic can be
# checked against a known cause rather than only against a rank number.
# ======================================================================


def make_five_rod() -> Assembly:
    """V7: the unit cage with one rod removed. Five constraints cannot fix six
    DOF, whatever the arrangement."""
    a = make_unit_cage()
    del a.rods["r_ry"]
    return a


def make_line_supported(n_rods=6, axis="x") -> Assembly:
    """V8: every GROUND-side attachment on one line.

    A guaranteed mechanism for any number of rods in any arrangement: each
    ground point lies ON the axis, so rotating the whole free assembly about
    that line leaves every rod length unchanged. This is what a baseplate
    idealized as a line rather than a plane does to a model.
    """
    specs = []
    for k in range(n_rods):
        t = -6.0 + 12.0 * k / (n_rods - 1)
        phi = np.radians(37.0 * k)
        body_pt = (t * 0.6, 3.0 + 1.5 * np.cos(phi), 9.0 + 1.5 * np.sin(phi))
        ground_pt = (t, 0.0, 0.0) if axis == "x" else (0.0, t, 0.0)
        specs.append({"id": f"s{k}", "a": ("body", body_pt), "b": ("ground", ground_pt)})
    return build_assembly([_free("body", (0.0, 3.0, 9.0)), _ground()], specs)


def make_concurrent6() -> Assembly:
    """All six rod lines through one point on the body: every rod's moment
    about that point is zero, so all three rotations are free."""
    apex = (0.0, 0.0, 10.0)
    specs = []
    for k in range(6):
        phi = np.radians(60.0 * k)
        specs.append(
            {
                "id": f"c{k}",
                "a": ("body", apex),
                "b": ("ground", (8.0 * np.cos(phi), 8.0 * np.sin(phi), 0.0)),
            }
        )
    return build_assembly([_free("body", apex), _ground()], specs)


def make_parallel4() -> Assembly:
    """Four vertical rods: nothing can react a horizontal load."""
    specs = []
    for k in range(4):
        phi = np.radians(90.0 * k)
        x, y = 6.0 * np.cos(phi), 6.0 * np.sin(phi)
        specs.append(
            {"id": f"p{k}", "a": ("body", (x, y, 10.0)), "b": ("ground", (x, y, 0.0))}
        )
    return build_assembly([_free("body", (0.0, 0.0, 10.0)), _ground()], specs)


def make_floating_island() -> Assembly:
    """One properly supported body, plus two bodies tied only to each other —
    a whole component with no ground in it. The graph pre-check must name
    those two bodies, which is far more useful than 'K is rank deficient'."""
    specs = [
        {"id": f"g{k}", "a": ("anchored", a_pt), "b": ("ground", b_pt)}
        for k, (a_pt, b_pt) in enumerate(_hex_pairs(0.0))
    ]
    for k in range(3):
        phi = np.radians(120.0 * k)
        specs.append(
            {
                "id": f"island{k}",
                "a": ("drifter_a", (20.0 + 2.0 * np.cos(phi), 2.0 * np.sin(phi), 5.0)),
                "b": ("drifter_b", (26.0 + 2.0 * np.cos(phi), 2.0 * np.sin(phi), 9.0)),
            }
        )
    return build_assembly(
        [
            _free("anchored", (0.0, 0.0, 8.0)),
            _free("drifter_a", (20.0, 0.0, 5.0)),
            _free("drifter_b", (26.0, 0.0, 9.0)),
            _ground(),
        ],
        specs,
    )


def make_free_free() -> Assembly:
    """V12: zero ground bodies. Legitimate diagnostic mode — 'is this
    subassembly internally rigid?' — expecting nullity exactly 6."""
    a = make_hexapod()
    a.bodies["ground"].is_ground = False
    return a


def make_orphan_body() -> Assembly:
    """A free body with no rods at all."""
    a = make_hexapod()
    a.bodies["lonely"] = _free("lonely", (50.0, 0.0, 0.0))
    return a


@pytest.fixture
def five_rod() -> Assembly:
    return make_five_rod()


@pytest.fixture
def line_supported() -> Assembly:
    return make_line_supported()


@pytest.fixture
def concurrent6() -> Assembly:
    return make_concurrent6()


@pytest.fixture
def parallel4() -> Assembly:
    return make_parallel4()


@pytest.fixture
def floating_island() -> Assembly:
    return make_floating_island()


@pytest.fixture
def free_free() -> Assembly:
    return make_free_free()


SCREW_PITCH = 3.0   # inches of advance per radian of turn


def make_screw_motion(pitch=SCREW_PITCH, n=5, seed=0) -> Assembly:
    """A layout whose single free motion is a SCREW, not a pure rotation.

    A rod resists a twist `(d, theta)` unless `u . (d + theta x a) == 0`. For
    the twist "rotate about Z while advancing along Z at `pitch`" that reads
    `u . (pitch*z_hat + z_hat x a) == 0`, so choosing each rod direction
    perpendicular to `w = pitch*z_hat + z_hat x a` builds rods that cannot
    resist it. Five independent such rods leave exactly that one motion free.

    Needed because a screw has NO stationary line: `axis_line()` and
    `common_axis()` must both decline to name one. Nothing else in the fixture
    set produces a screw — every rotationally symmetric two-circle layout
    collapses to rank 3 instead.
    """
    rng = np.random.default_rng(seed)
    z_hat = np.array([0.0, 0.0, 1.0])
    specs = []
    for k in range(n):
        th = 2.0 * np.pi * k / n
        a = np.array([10.0 * np.cos(th), 10.0 * np.sin(th), 6.0 + 2.0 * k])
        w = pitch * z_hat + np.cross(z_hat, a)
        u = np.cross(w, rng.normal(size=3))
        u /= np.linalg.norm(u)
        specs.append(
            {"id": f"sc{k}", "a": ("body", tuple(a)), "b": ("ground", tuple(a + 9.0 * u))}
        )
    return build_assembly([_free("body", (0.0, 0.0, 0.0)), _ground()], specs)


@pytest.fixture
def screw_motion() -> Assembly:
    return make_screw_motion()
