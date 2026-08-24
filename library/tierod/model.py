"""
Tie-rod layout analysis — core data model.

Ported from an early sketch with the §3.4 revisions of the build prompt
applied; that sketch (`apps/tierod/model_draft.py`) was deleted once this
module superseded it. This module is pure numpy: **it must never import
Streamlit.**

Coordinate conventions
----------------------
Every Region is defined in the LOCAL frame of its parent Body. A Body carries
(origin, R) placing its local frame in global space. Body mass properties
(cg, inertia) are likewise body-local. `Body.clearance` is body-local too.

Every Region exposes the same interface, a function of its parameter q:

    bounds()      -> [(lo, hi)] * ndim
    point(q)      -> (3,)            position, body-local
    jacobian(q)   -> (3, ndim)       dr/dq, body-local

`ndim` is exactly the number of design variables that rod end contributes.
The optimizer differentiates through point(); the renderer evaluates point()
on a grid to build the mesh. One geometry definition, one code path.

What is deliberately NOT here
-----------------------------
`Region.mount_axis()`, `Region.misalign_limit_deg` and `CircleArc.axis_mode`
were removed (§3.4). They modelled the rod as constrained to a cone about the
surface normal, which is wrong: rods are two-force members on spherical
bearings at both ends and the rod axis is routinely far from the surface
normal. Non-penetration comes from the `Body.clearance` half-space test
instead (see `clearance.py`). Do not reintroduce them.

The one place a surface direction is still needed is the bracket standoff `h`,
which offsets the pin point off the surface. That direction comes from the
body's clearance primitive (`outward()`), not from the region — so a standoff
never implies a constraint on rod direction.

Units: IPS throughout (lb, in, psi).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

import numpy as np

Vec3 = np.ndarray

_ORTHO_TOL = 1e-9


def unit(v: Vec3) -> Vec3:
    """Normalize, refusing to guess a direction for a zero-length vector."""
    v = np.asarray(v, dtype=float)
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        raise ValueError("cannot normalize a zero-length vector")
    return v / n


def skew(c: Vec3) -> np.ndarray:
    """Matrix [c]x such that [c]x @ n == c x n."""
    cx, cy, cz = np.asarray(c, dtype=float)
    return np.array([[0.0, -cz, cy], [cz, 0.0, -cx], [-cy, cx, 0.0]])


def frame_from_plane(plane: str) -> tuple[Vec3, Vec3, Vec3]:
    """Populate a local frame from a major-plane selection.

    This is an INPUT CONVENIENCE ONLY. The stored frame is always a full
    (e1, e2, e3) triad; nothing downstream may branch on `plane`. Arbitrary
    orientation is therefore a UI addition later, not a kernel refactor.
    """
    X, Y, Z = np.eye(3)
    table = {"XY": (X, Y, Z), "YZ": (Y, Z, X), "ZX": (Z, X, Y)}
    try:
        return table[str(plane).upper()]
    except KeyError:
        raise ValueError(f"plane must be one of {sorted(table)}, got {plane!r}") from None


def frame_from_axis(axis: str) -> tuple[Vec3, Vec3, Vec3]:
    """Populate a local frame from an axis selection; `axis` becomes e3.

    Same contract as `frame_from_plane` — a dropdown convenience that produces
    a full triad and nothing more.
    """
    table = {"X": "YZ", "Y": "ZX", "Z": "XY"}
    try:
        return frame_from_plane(table[str(axis).upper()])
    except KeyError:
        raise ValueError(f"axis must be one of {sorted(table)}, got {axis!r}") from None


def check_orthonormal(e1: Vec3, e2: Vec3, e3: Vec3, label: str = "frame") -> None:
    """Reject a triad that is not right-handed orthonormal.

    Every dropdown-populated construction runs through here, so a bad frame is
    caught at build time rather than as a silently skewed geometry later.
    """
    M = np.column_stack([e1, e2, e3])
    if not np.allclose(M.T @ M, np.eye(3), atol=_ORTHO_TOL):
        raise ValueError(f"{label}: (e1, e2, e3) is not orthonormal")
    if not np.isclose(float(np.linalg.det(M)), 1.0, atol=_ORTHO_TOL):
        raise ValueError(f"{label}: (e1, e2, e3) is not right-handed")


def as_vec3(v, name: str) -> Vec3:
    a = np.asarray(v, dtype=float).reshape(-1)
    if a.size != 3:
        raise ValueError(f"{name} must be a 3-vector, got shape {np.shape(v)}")
    return a


# ----------------------------------------------------------------------
# Mountable regions
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ParamSpec:
    """One editable parameter of a Region or clearance primitive.

    Declared BY THE CLASS, next to the geometry it controls — the same pattern
    `library/shapes/shapes.py` uses with `dim_labels` / `dim_defaults` for the
    11 beam sections. The builder UI reads these and nothing else, so adding a
    primitive never touches the UI, and adding a FIELD to a primitive without
    declaring it is a test failure rather than a silently uneditable input.

    `kind` is 'length', 'angle' or 'vec3'. Angles are stored in RADIANS and
    edited in degrees; an undeclared angle would present 6.28 where the
    engineer expects 360.
    """

    attr: str
    label: str
    default: float = 1.0
    step: float = 0.25
    kind: str = "length"


@dataclass
class Region:
    """Base class. A bounded manifold of dimension ndim embedded in R^3.

    ndim is the number of design variables this attachment contributes:
        0 -> fixed point      1 -> curve (rail, bolt circle)
        2 -> surface (patch, band, annulus, spherical cap)
    """

    id: str
    body_id: str
    origin: Vec3
    e1: Vec3
    e2: Vec3
    e3: Vec3
    keepouts: list = field(default_factory=list)

    ndim: int = 0

    #: Editable parameters beyond the frame — see `ParamSpec`.
    PARAMS: ClassVar[tuple] = ()

    def __post_init__(self) -> None:
        self.origin = as_vec3(self.origin, f"{self.id}.origin")
        self.e1 = as_vec3(self.e1, f"{self.id}.e1")
        self.e2 = as_vec3(self.e2, f"{self.id}.e2")
        self.e3 = as_vec3(self.e3, f"{self.id}.e3")
        check_orthonormal(self.e1, self.e2, self.e3, label=f"region {self.id!r}")

    # -- interface ------------------------------------------------------

    def bounds(self) -> list[tuple[float, float]]:
        raise NotImplementedError

    def point(self, q=None) -> Vec3:
        raise NotImplementedError

    def jacobian(self, q=None) -> np.ndarray:
        raise NotImplementedError

    # -- helpers --------------------------------------------------------

    def q0(self) -> np.ndarray:
        """Midpoint of the parameter domain — default seed."""
        return np.array([0.5 * (lo + hi) for lo, hi in self.bounds()], dtype=float)

    def clip(self, q) -> np.ndarray:
        """Project q onto the parameter box."""
        q = np.asarray(q, dtype=float).reshape(-1)
        b = self.bounds()
        return np.array([min(max(qi, lo), hi) for qi, (lo, hi) in zip(q, b)])

    def in_bounds(self, q, tol: float = 1e-9) -> bool:
        q = np.asarray(q, dtype=float).reshape(-1)
        return all(lo - tol <= qi <= hi + tol for qi, (lo, hi) in zip(q, self.bounds()))


@dataclass
class FixedPoint(Region):
    """An existing fitting. No design freedom."""

    ndim: int = 0
    PARAMS: ClassVar[tuple] = ()

    def bounds(self):
        return []

    def point(self, q=None):
        return self.origin.copy()

    def jacobian(self, q=None):
        return np.zeros((3, 0))


@dataclass
class Segment(Region):
    """Straight rail. q = (s,), s in [0, 1] along length L * e1."""

    length: float = 1.0
    ndim: int = 1

    PARAMS: ClassVar[tuple] = (
        ParamSpec("length", "Length (in)", 1.0, 0.5),
    )

    def bounds(self):
        return [(0.0, 1.0)]

    def point(self, q):
        q = np.asarray(q, dtype=float)
        return self.origin + q[0] * self.length * self.e1

    def jacobian(self, q=None):
        return (self.length * self.e1).reshape(3, 1)


@dataclass
class CircleArc(Region):
    """Bolt circle or rim. q = (theta,), measured from e1 toward e2.

    e3 sets the plane the arc lies in (sign irrelevant).
    """

    radius: float = 1.0
    theta_min: float = 0.0
    theta_max: float = 2.0 * np.pi
    ndim: int = 1

    PARAMS: ClassVar[tuple] = (
        ParamSpec("radius", "Radius (in)", 1.0, 0.25),
        ParamSpec("theta_min", "Theta start (deg)", 0.0, 5.0, "angle"),
        ParamSpec("theta_max", "Theta end (deg)", 2.0 * np.pi, 5.0, "angle"),
    )

    def bounds(self):
        return [(self.theta_min, self.theta_max)]

    def _radial(self, th: float) -> Vec3:
        return np.cos(th) * self.e1 + np.sin(th) * self.e2

    def point(self, q):
        q = np.asarray(q, dtype=float)
        return self.origin + self.radius * self._radial(q[0])

    def jacobian(self, q):
        th = float(np.asarray(q, dtype=float)[0])
        d = self.radius * (-np.sin(th) * self.e1 + np.cos(th) * self.e2)
        return d.reshape(3, 1)


@dataclass
class PlanarPatch(Region):
    """Flat rectangular pad. q = (u, v), both in [0, 1]."""

    width: float = 1.0
    height: float = 1.0
    ndim: int = 2

    PARAMS: ClassVar[tuple] = (
        ParamSpec("width", "Width along e1 (in)", 1.0, 0.5),
        ParamSpec("height", "Height along e2 (in)", 1.0, 0.5),
    )

    def bounds(self):
        return [(0.0, 1.0), (0.0, 1.0)]

    def point(self, q):
        q = np.asarray(q, dtype=float)
        return self.origin + q[0] * self.width * self.e1 + q[1] * self.height * self.e2

    def jacobian(self, q=None):
        return np.column_stack([self.width * self.e1, self.height * self.e2])


@dataclass
class Annulus(Region):
    """Flange face or end cap. q = (rho, theta), in the e1-e2 plane."""

    r_inner: float = 0.0
    r_outer: float = 1.0
    theta_min: float = 0.0
    theta_max: float = 2.0 * np.pi
    ndim: int = 2

    PARAMS: ClassVar[tuple] = (
        ParamSpec("r_inner", "Inner radius (in)", 0.0, 0.25),
        ParamSpec("r_outer", "Outer radius (in)", 1.0, 0.25),
        ParamSpec("theta_min", "Theta start (deg)", 0.0, 5.0, "angle"),
        ParamSpec("theta_max", "Theta end (deg)", 2.0 * np.pi, 5.0, "angle"),
    )

    def bounds(self):
        return [(self.r_inner, self.r_outer), (self.theta_min, self.theta_max)]

    def point(self, q):
        rho, th = np.asarray(q, dtype=float)
        return self.origin + rho * (np.cos(th) * self.e1 + np.sin(th) * self.e2)

    def jacobian(self, q):
        rho, th = np.asarray(q, dtype=float)
        d_rho = np.cos(th) * self.e1 + np.sin(th) * self.e2
        d_th = rho * (-np.sin(th) * self.e1 + np.cos(th) * self.e2)
        return np.column_stack([d_rho, d_th])


@dataclass
class CylindricalBand(Region):
    """Tank wall or actuator body. q = (theta, z).

    e3 is the cylinder axis and sets the sense of z_min / z_max (sign matters).
    """

    radius: float = 1.0
    z_min: float = 0.0
    z_max: float = 1.0
    theta_min: float = 0.0
    theta_max: float = 2.0 * np.pi
    ndim: int = 2

    PARAMS: ClassVar[tuple] = (
        ParamSpec("radius", "Radius (in)", 1.0, 0.25),
        ParamSpec("z_min", "Z lower (in)", 0.0, 0.5),
        ParamSpec("z_max", "Z upper (in)", 1.0, 0.5),
        ParamSpec("theta_min", "Theta start (deg)", 0.0, 5.0, "angle"),
        ParamSpec("theta_max", "Theta end (deg)", 2.0 * np.pi, 5.0, "angle"),
    )

    def bounds(self):
        return [(self.theta_min, self.theta_max), (self.z_min, self.z_max)]

    def _radial(self, th: float) -> Vec3:
        return np.cos(th) * self.e1 + np.sin(th) * self.e2

    def point(self, q):
        th, z = np.asarray(q, dtype=float)
        return self.origin + self.radius * self._radial(th) + z * self.e3

    def jacobian(self, q):
        th, _ = np.asarray(q, dtype=float)
        d_th = self.radius * (-np.sin(th) * self.e1 + np.cos(th) * self.e2)
        return np.column_stack([d_th, self.e3])


@dataclass
class SphericalPatch(Region):
    """Dome or spherical end cap. q = (theta, phi).

    phi is measured from e3, theta from e1 toward e2. The theta jacobian
    column vanishes at the poles (phi = 0 or pi) — that is the geometry, not
    a defect; keep patch bounds off the pole if the optimizer must move there.
    """

    radius: float = 1.0
    theta_min: float = 0.0
    theta_max: float = 2.0 * np.pi
    phi_min: float = 0.0
    phi_max: float = 0.5 * np.pi
    ndim: int = 2

    PARAMS: ClassVar[tuple] = (
        ParamSpec("radius", "Radius (in)", 1.0, 0.25),
        ParamSpec("theta_min", "Theta start (deg)", 0.0, 5.0, "angle"),
        ParamSpec("theta_max", "Theta end (deg)", 2.0 * np.pi, 5.0, "angle"),
        ParamSpec("phi_min", "Phi start (deg)", 0.0, 5.0, "angle"),
        ParamSpec("phi_max", "Phi end (deg)", 0.5 * np.pi, 5.0, "angle"),
    )

    def bounds(self):
        return [(self.theta_min, self.theta_max), (self.phi_min, self.phi_max)]

    def point(self, q):
        th, ph = np.asarray(q, dtype=float)
        return self.origin + self.radius * (
            np.sin(ph) * np.cos(th) * self.e1
            + np.sin(ph) * np.sin(th) * self.e2
            + np.cos(ph) * self.e3
        )

    def jacobian(self, q):
        th, ph = np.asarray(q, dtype=float)
        d_th = self.radius * np.sin(ph) * (-np.sin(th) * self.e1 + np.cos(th) * self.e2)
        d_ph = self.radius * (
            np.cos(ph) * np.cos(th) * self.e1
            + np.cos(ph) * np.sin(th) * self.e2
            - np.sin(ph) * self.e3
        )
        return np.column_stack([d_th, d_ph])


# ----------------------------------------------------------------------
# Bodies
# ----------------------------------------------------------------------


@dataclass
class Body:
    """A rigid body. Ground is a FLAG, not a subclass.

    A ground body contributes no DOF block to K and no inertial term to the
    load sweep. It is otherwise a full participant: it has a frame, it holds
    regions, it renders. mass / cg / g_factor are retained but ignored when
    is_ground — toggling ground must never destroy data.
    """

    id: str
    is_ground: bool = False
    origin: Vec3 = field(default_factory=lambda: np.zeros(3))
    R: np.ndarray = field(default_factory=lambda: np.eye(3))
    mass: float = 0.0
    cg: Vec3 = field(default_factory=lambda: np.zeros(3))
    g_factor: float = 1.0  # scalar load factor on this body's mass
    inertia: np.ndarray | None = None  # reserved: rotational sweep terms (§7.3)
    clearance: object | None = None  # Sphere / Cylinder / Box, body-local

    def __post_init__(self) -> None:
        self.origin = as_vec3(self.origin, f"{self.id}.origin")
        self.cg = as_vec3(self.cg, f"{self.id}.cg")
        self.g_factor = float(self.g_factor)
        self.R = np.asarray(self.R, dtype=float).reshape(3, 3)

    def to_global(self, p_local: Vec3) -> Vec3:
        return self.origin + self.R @ np.asarray(p_local, dtype=float)

    def dir_to_global(self, v_local: Vec3) -> Vec3:
        return self.R @ np.asarray(v_local, dtype=float)

    def shell_centroid(self) -> Vec3 | None:
        """Centre of volume of this body's clearance shell, body-local.

        `None` when the body has no shell, which is a real state and not an
        error: a body can carry mass with no geometry declared.
        """
        return None if self.clearance is None else self.clearance.centroid()

    def snap_cg_to_shell(self) -> bool:
        """Move `cg` to the shell's centre of volume. True if it moved.

        Reported rather than silent because it overwrites a number the user
        may have entered on purpose.
        """
        centre = self.shell_centroid()
        if centre is None:
            return False
        moved = not np.allclose(self.cg, centre)
        self.cg = np.asarray(centre, dtype=float)
        return moved

    def sweep_block(self) -> np.ndarray:
        """W_p = m G [I3 ; [R cg]x], the 6x3 map from a UNIT load direction to
        the wrench applied at this body's datum.

        Magnitude lives here, in the scalar `g_factor`; the load case supplies
        only a unit direction. That split is what keeps every case the same
        magnitude and makes the orientation envelope closed-form: F is linear
        in n_hat, so the worst case over all directions is a row norm rather
        than a search.

        The moment arm is `R @ cg`, not `cg`. `cg` is stored body-local, but
        the load direction and the screw matrix's moment rows are both in
        GLOBAL axes about the body datum, so the arm has to be rotated into
        global before the cross product. With `R = I` — every example so far —
        the two agree, which is exactly why this is worth stating.
        """
        if self.is_ground:
            raise ValueError(f"body {self.id!r} is ground: it carries no inertial load")
        arm = self.R @ self.cg
        return self.mass * self.g_factor * np.vstack([np.eye(3), skew(arm)])


# ----------------------------------------------------------------------
# Rods
# ----------------------------------------------------------------------


@dataclass
class RodEnd:
    """One end of a rod.

    `h` is the optional bracket standoff: the pin sits `h` off the surface
    along the body's outward direction at that point. A 2 in standoff on a
    20 in moment arm is a 10% lever error, so it is modelled, not ignored.
    """

    region_id: str
    q: np.ndarray  # length == region.ndim; empty for FixedPoint
    h: float = 0.0

    def __post_init__(self) -> None:
        self.q = np.asarray(self.q, dtype=float).reshape(-1)
        self.h = float(self.h)


@dataclass
class Rod:
    """Two-force member, spherical bearing both ends: axial load only, no
    moment. Topology (which regions it spans) is a user input; only the
    parameters q at each end are optimized.

    `k_backup_*` is the Phase-5 backup-structure compliance hook: a series
    spring at each rod end. Infinite (the default) means a rigid backup, i.e.
    the pure-rod stiffness A E / L. The field exists from Session 1 so the
    kernel signature never has to change; it is unused until Phase 5.
    """

    id: str
    end_a: RodEnd
    end_b: RodEnd
    E: float
    A: float
    I: float
    Fcy: float
    group: str = "main"  # rods sharing a group share one section+material spec
    end_fixity: float = 1.0  # c, pinned-pinned — correct for spherical bearings
    P_tension_allow: float | None = None  # vendor rated; None -> A_net * Ftu
    Ftu: float | None = None
    Fty: float | None = None  # optional: enables the tension yield check A*Fty
    A_net: float | None = None
    k_backup_a: float = float("inf")  # Phase 5 hook — rigid backup by default
    k_backup_b: float = float("inf")


# ----------------------------------------------------------------------
# Assembly
# ----------------------------------------------------------------------


@dataclass
class Assembly:
    bodies: dict[str, Body]
    regions: dict[str, Region]
    rods: dict[str, Rod]

    # -- DOF bookkeeping ------------------------------------------------

    def free_bodies(self) -> list[str]:
        return [b.id for b in self.bodies.values() if not b.is_ground]

    def n_dof(self) -> int:
        return 6 * len(self.free_bodies())

    def dof_slice(self, body_id: str) -> slice | None:
        """Global DOF block for a body, or None if grounded."""
        free = self.free_bodies()
        if body_id not in free:
            return None
        i = free.index(body_id)
        return slice(6 * i, 6 * i + 6)

    def expected_rank(self) -> int:
        """K must reach this. Shortfall == number of mechanism modes, and the
        null vectors of K are those modes — animate them."""
        return self.n_dof()

    # -- load sweep -----------------------------------------------------

    def sweep_map(self) -> np.ndarray:
        """W: (6 * n_free, 3). Stacked inertial load blocks, free bodies only.

        The load for a case with unit direction n_hat is W @ n_hat, linear in
        n_hat — the property that makes the orientation envelope closed-form
        rather than sampled. One direction is shared by every body; per-body
        directions would make W block-structured and are not in scope.
        """
        free = self.free_bodies()
        if not free:
            return np.zeros((0, 3))
        return np.vstack([self.bodies[b].sweep_block() for b in free])

    # -- geometry -------------------------------------------------------

    def endpoint_global(self, end: RodEnd) -> tuple[Vec3, str]:
        """Return (pin position in global coordinates, body id).

        The standoff is applied in the body-local frame along the outward
        direction of the body's clearance primitive, then transformed. There
        is deliberately no region-level 'mount axis' — see the module
        docstring.
        """
        region = self.regions[end.region_id]
        body = self.bodies[region.body_id]
        p_local = region.point(end.q)
        if end.h != 0.0:
            if body.clearance is None:
                raise ValueError(
                    f"rod end on region {end.region_id!r}: standoff h={end.h} needs a "
                    f"clearance primitive on body {body.id!r} to define the outward "
                    f"direction"
                )
            p_local = p_local + end.h * body.clearance.outward(p_local)
        return body.to_global(p_local), body.id

    def rod_endpoints(self, rod: Rod) -> tuple[Vec3, Vec3, str, str]:
        """(a, b, body_a, body_b) in global coordinates."""
        a, body_a = self.endpoint_global(rod.end_a)
        b, body_b = self.endpoint_global(rod.end_b)
        return a, b, body_a, body_b

    # -- design vector --------------------------------------------------

    def design_vector_layout(self) -> list[tuple[str, str, int]]:
        """Ordered (rod_id, 'a'|'b', ndim) for packing/unpacking x.

        d = 0 ends are skipped, so a rod anchored to an existing fitting
        contributes zero variables with no special-casing anywhere else.
        """
        layout = []
        for rod in self.rods.values():
            for tag, end in (("a", rod.end_a), ("b", rod.end_b)):
                nd = self.regions[end.region_id].ndim
                if nd:
                    layout.append((rod.id, tag, nd))
        return layout

    def n_design_vars(self) -> int:
        return sum(nd for _, _, nd in self.design_vector_layout())

    def design_vector(self) -> np.ndarray:
        """Pack every rod end's q into one vector, in layout order."""
        parts = []
        for rod_id, tag, _ in self.design_vector_layout():
            rod = self.rods[rod_id]
            parts.append((rod.end_a if tag == "a" else rod.end_b).q)
        return np.concatenate(parts) if parts else np.zeros(0)

    def set_design_vector(self, x) -> None:
        """Unpack a design vector back onto the rod ends.

        The inverse of `design_vector()`; the sliders and (later) the optimizer
        both drive the model through this pair rather than reaching into rod
        ends directly.
        """
        x = np.asarray(x, dtype=float).reshape(-1)
        expected = self.n_design_vars()
        if x.size != expected:
            raise ValueError(
                f"design vector has {x.size} entries but the layout needs {expected}"
            )
        i = 0
        for rod_id, tag, nd in self.design_vector_layout():
            rod = self.rods[rod_id]
            end = rod.end_a if tag == "a" else rod.end_b
            end.q = x[i : i + nd].copy()
            i += nd

    def design_bounds(self) -> list[tuple[float, float]]:
        """Bounds for every design variable, in the same order."""
        out: list[tuple[float, float]] = []
        for rod_id, tag, _ in self.design_vector_layout():
            rod = self.rods[rod_id]
            end = rod.end_a if tag == "a" else rod.end_b
            out.extend(self.regions[end.region_id].bounds())
        return out

    # -- construction ---------------------------------------------------
    #
    # Every mutation validates its own references at the point of the edit.
    # `validate()` would catch a dangling region id eventually, but by then the
    # message points at the rod rather than at the deletion that orphaned it.

    def add_body(self, body: Body) -> Body:
        if body.id in self.bodies:
            raise ValueError(f"body {body.id!r} already exists")
        self.bodies[body.id] = body
        return body

    def add_region(self, region: Region) -> Region:
        if region.id in self.regions:
            raise ValueError(f"region {region.id!r} already exists")
        if region.body_id not in self.bodies:
            raise KeyError(
                f"region {region.id!r} names unknown body {region.body_id!r}"
            )
        self.regions[region.id] = region
        return region

    def add_rod(self, rod: Rod) -> Rod:
        if rod.id in self.rods:
            raise ValueError(f"rod {rod.id!r} already exists")
        for tag, end in (("a", rod.end_a), ("b", rod.end_b)):
            if end.region_id not in self.regions:
                raise KeyError(
                    f"rod {rod.id!r} end {tag!r} names unknown region "
                    f"{end.region_id!r}"
                )
            region = self.regions[end.region_id]
            if end.q.size != region.ndim:
                raise ValueError(
                    f"rod {rod.id!r} end {tag!r}: q has length {end.q.size} but "
                    f"region {region.id!r} has ndim {region.ndim}"
                )
        self.rods[rod.id] = rod
        return rod

    def rods_on_regions(self, region_ids) -> list[str]:
        wanted = set(region_ids)
        return sorted(
            rod_id
            for rod_id, rod in self.rods.items()
            if rod.end_a.region_id in wanted or rod.end_b.region_id in wanted
        )

    def remove_rod(self, rod_id: str) -> Removed:
        if rod_id not in self.rods:
            raise KeyError(f"unknown rod {rod_id!r}")
        del self.rods[rod_id]
        return Removed(rods=[rod_id])

    def remove_region(self, region_id: str, cascade: bool = True) -> Removed:
        """Delete a region and, unless refused, the rods attached to it."""
        if region_id not in self.regions:
            raise KeyError(f"unknown region {region_id!r}")
        attached = self.rods_on_regions([region_id])
        if attached and not cascade:
            raise ValueError(
                f"region {region_id!r} still carries rod(s) "
                f"{attached} — remove them first or pass cascade=True"
            )
        for rod_id in attached:
            del self.rods[rod_id]
        del self.regions[region_id]
        return Removed(regions=[region_id], rods=attached)

    def remove_body(self, body_id: str, cascade: bool = True) -> Removed:
        """Delete a body, its regions, and the rods on those regions."""
        if body_id not in self.bodies:
            raise KeyError(f"unknown body {body_id!r}")
        owned = sorted(
            r.id for r in self.regions.values() if r.body_id == body_id
        )
        attached = self.rods_on_regions(owned)
        if (owned or attached) and not cascade:
            raise ValueError(
                f"body {body_id!r} still carries region(s) {owned} and rod(s) "
                f"{attached} — remove them first or pass cascade=True"
            )
        for rod_id in attached:
            del self.rods[rod_id]
        for region_id in owned:
            del self.regions[region_id]
        del self.bodies[body_id]
        return Removed(bodies=[body_id], regions=owned, rods=attached)

    def rod_groups(self) -> dict[str, list[str]]:
        """`{group name: [rod_id, ...]}`. A partition of the rods.

        One spec per group is the assignment granularity: rods are grouped and
        a group is sized as a unit, because a dozen individually-sized rods is
        not something anyone manufactures. The default is a single group.
        """
        out: dict[str, list[str]] = {}
        for rod_id, rod in self.rods.items():
            out.setdefault(rod.group, []).append(rod_id)
        return {k: sorted(v) for k, v in sorted(out.items())}

    # -- validation -----------------------------------------------------

    def validate(self, check_bounds: bool = True) -> None:
        """Raise ValueError on a structurally inconsistent model.

        Deliberately silent about mechanisms and rank — that is the kernel's
        job, and a free-free assembly (zero ground bodies) is a legitimate
        diagnostic mode, not a model error.
        """
        for region in self.regions.values():
            if region.body_id not in self.bodies:
                raise ValueError(
                    f"region {region.id!r} names unknown body {region.body_id!r}"
                )
        for rod in self.rods.values():
            for tag, end in (("a", rod.end_a), ("b", rod.end_b)):
                if end.region_id not in self.regions:
                    raise ValueError(
                        f"rod {rod.id!r} end {tag!r} references unknown region "
                        f"{end.region_id!r}"
                    )
                region = self.regions[end.region_id]
                if end.q.size != region.ndim:
                    raise ValueError(
                        f"rod {rod.id!r} end {tag!r}: q has length {end.q.size} but "
                        f"region {region.id!r} has ndim {region.ndim}"
                    )
                if check_bounds and not region.in_bounds(end.q):
                    raise ValueError(
                        f"rod {rod.id!r} end {tag!r}: q={end.q} is outside the bounds "
                        f"{region.bounds()} of region {region.id!r}"
                    )


# ----------------------------------------------------------------------
# Type registries and factories — what the builder UI and the loader share
# ----------------------------------------------------------------------
#
# Both the "add a region" dropdown and the JSON loader need to turn a type NAME
# into a class. One registry serves both, so a primitive that is buildable is
# automatically loadable and vice versa — a test asserts the registry covers
# every subclass, because a primitive missing from it would round-trip into an
# exception rather than a wrong answer.

REGION_TYPES: dict[str, type] = {
    cls.__name__: cls
    for cls in (
        FixedPoint, Segment, CircleArc, PlanarPatch,
        Annulus, CylindricalBand, SphericalPatch,
    )
}

DEFAULT_GROUP = "main"

# Placeholder section+material for a rod created in the UI: 0.375 dia alloy
# steel. Superseded per group by the rod pool; this only keeps `new_rod` from
# demanding six numbers before the geometry even exists.
DEFAULT_ROD_PROPS = dict(
    E=29.0e6, A=0.1104, I=9.71e-4, Fcy=180.0e3,
    Ftu=180.0e3, Fty=163.0e3, A_net=0.0775,
)


def _resolve_params(cls, params: dict) -> dict:
    """Merge caller overrides onto the class's declared defaults."""
    allowed = {p.attr: p.default for p in cls.PARAMS}
    unknown = set(params) - set(allowed)
    if unknown:
        raise TypeError(
            f"{cls.__name__} has no parameter(s) {sorted(unknown)}; "
            f"it accepts {sorted(allowed)}"
        )
    allowed.update(params)
    return allowed


def new_region(type_name: str, id: str, body_id: str, axis: str = "Z",
               origin=None, **params) -> Region:
    """Build a region of the named type with its declared defaults.

    The axis dropdown POPULATES the frame triad; nothing downstream ever
    branches on the axis name again.
    """
    try:
        cls = REGION_TYPES[type_name]
    except KeyError:
        raise ValueError(
            f"unknown region type {type_name!r}; have {sorted(REGION_TYPES)}"
        ) from None
    e1, e2, e3 = frame_from_axis(axis)
    return cls(
        id=id, body_id=body_id,
        origin=np.zeros(3) if origin is None else origin,
        e1=e1, e2=e2, e3=e3,
        **_resolve_params(cls, params),
    )


def new_clearance(type_name: str, axis: str = "Z", origin=None, **params):
    """Build a body clearance shell of the named type. See `clearance.py`."""
    from library.tierod.clearance import CLEARANCE_TYPES

    try:
        cls = CLEARANCE_TYPES[type_name]
    except KeyError:
        raise ValueError(
            f"unknown clearance type {type_name!r}; have {sorted(CLEARANCE_TYPES)}"
        ) from None
    e1, e2, e3 = frame_from_axis(axis)
    return cls(
        origin=np.zeros(3) if origin is None else origin,
        e1=e1, e2=e2, e3=e3,
        **_resolve_params(cls, params),
    )


def new_rod(assembly: "Assembly", id: str, region_a: str, region_b: str,
            q_a=None, q_b=None, h_a: float = 0.0, h_b: float = 0.0,
            group: str = DEFAULT_GROUP, **props) -> Rod:
    """Build a rod spanning two existing regions, seeded at their midpoints.

    Seeding from `q0()` rather than zeros matters: a zero `q` is outside the
    domain of several primitives (an Annulus starts at r_inner, a band at
    z_min), so a rod created at zero would fail validation immediately, far
    from the click that made it.
    """
    for name in (region_a, region_b):
        if name not in assembly.regions:
            raise KeyError(f"unknown region {name!r}")
    merged = dict(DEFAULT_ROD_PROPS)
    merged.update(props)
    return Rod(
        id=id,
        end_a=RodEnd(
            region_id=region_a,
            q=assembly.regions[region_a].q0() if q_a is None else q_a,
            h=h_a,
        ),
        end_b=RodEnd(
            region_id=region_b,
            q=assembly.regions[region_b].q0() if q_b is None else q_b,
            h=h_b,
        ),
        group=group,
        **merged,
    )


@dataclass
class Removed:
    """What a deletion actually took with it.

    Returned rather than logged so the UI can say "also removed 6 rods" —
    a silent cascade is how a user loses work without noticing.
    """

    bodies: list = field(default_factory=list)
    regions: list = field(default_factory=list)
    rods: list = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.bodies or self.regions or self.rods)


__all__ = [
    "Vec3",
    "as_vec3",
    "unit",
    "skew",
    "frame_from_plane",
    "frame_from_axis",
    "check_orthonormal",
    "Region",
    "FixedPoint",
    "Segment",
    "CircleArc",
    "PlanarPatch",
    "Annulus",
    "CylindricalBand",
    "SphericalPatch",
    "Body",
    "RodEnd",
    "Rod",
    "Assembly",
    "ParamSpec",
    "REGION_TYPES",
    "DEFAULT_GROUP",
    "DEFAULT_ROD_PROPS",
    "new_region",
    "new_clearance",
    "new_rod",
    "Removed",
]
