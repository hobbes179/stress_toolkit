"""
Tie-rod layout analysis — body clearance primitives.

`Body.clearance` is a real type, not a placeholder. Each primitive is a convex
solid stored in its parent body's LOCAL frame (same convention as regions),
oriented by a full (e1, e2, e3) triad that a dropdown populates. Nothing
downstream branches on the dropdown value, so arbitrary orientation is later a
UI addition rather than a kernel refactor.

Every primitive exposes:

    outward(p)                 -> (3,) unit outward normal, body-local
    distance_to_segment(a, b)  -> float, >= 0, clearance to the solid
    distance_to_point(p)       -> float, >= 0, 0 inside the solid

These drive the §8.2 non-penetration constraint and the bracket standoff `h`.
Bodies are kept to CONVEX primitives on purpose: the half-space test is then
exact and differentiable. A mesh-based check would lose gradients and force
derivative-free optimization.

Convexity is also what makes `distance_to_segment` cheap and reliable here:
distance-to-a-convex-set is a convex function of the point, so along a segment
it is a convex function of one parameter and a golden-section search is
guaranteed to find the global minimum.

Pure numpy — no Streamlit, and (so far) no scipy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import ClassVar

import numpy as np

from library.tierod.model import ParamSpec, Vec3, as_vec3, check_orthonormal

_GOLDEN = 0.5 * (math.sqrt(5.0) - 1.0)  # 0.618...
_ON_SURFACE = 1e-12


def _golden_min(f, a: float = 0.0, b: float = 1.0, tol: float = 1e-13) -> float:
    """Minimum VALUE of a convex f on [a, b] by golden-section search.

    Endpoint minima are covered because the bracket never leaves [a, b]; a flat
    minimum plateau (a segment passing through the solid, f == 0 over an
    interval) still converges to the correct value.
    """
    x1 = b - _GOLDEN * (b - a)
    x2 = a + _GOLDEN * (b - a)
    f1, f2 = f(x1), f(x2)
    while (b - a) > tol:
        if f1 <= f2:
            b, x2, f2 = x2, x1, f1
            x1 = b - _GOLDEN * (b - a)
            f1 = f(x1)
        else:
            a, x1, f1 = x1, x2, f2
            x2 = a + _GOLDEN * (b - a)
            f2 = f(x2)
    return min(f(a), f(b), f1, f2)


@dataclass
class ClearancePrimitive:
    """Base class. Convex solid, body-local, axis-aligned via a stored triad."""

    origin: Vec3
    e1: Vec3
    e2: Vec3
    e3: Vec3

    def __post_init__(self) -> None:
        self.origin = as_vec3(self.origin, "clearance.origin")
        self.e1 = as_vec3(self.e1, "clearance.e1")
        self.e2 = as_vec3(self.e2, "clearance.e2")
        self.e3 = as_vec3(self.e3, "clearance.e3")
        check_orthonormal(self.e1, self.e2, self.e3, label=type(self).__name__)

    # -- frame helpers --------------------------------------------------

    @property
    def E(self) -> np.ndarray:
        """Columns (e1, e2, e3): maps primitive-local -> body-local."""
        return np.column_stack([self.e1, self.e2, self.e3])

    def to_local(self, p: Vec3) -> np.ndarray:
        return self.E.T @ (np.asarray(p, dtype=float) - self.origin)

    def to_body(self, p_local: Vec3) -> np.ndarray:
        return self.origin + self.E @ np.asarray(p_local, dtype=float)

    # -- interface ------------------------------------------------------

    def _nearest_local(self, pl: np.ndarray) -> np.ndarray:
        """Nearest point of the solid to pl, both in primitive-local coords."""
        raise NotImplementedError

    def _surface_normal_local(self, pl: np.ndarray) -> np.ndarray:
        """Outward normal of the nearest boundary FEATURE, for points on or
        inside the solid where `pl - nearest` carries no direction."""
        raise NotImplementedError

    def distance_to_point(self, p: Vec3) -> float:
        """Distance from p to the solid. Zero inside or on the boundary."""
        pl = self.to_local(p)
        return float(np.linalg.norm(pl - self._nearest_local(pl)))

    def outward(self, p: Vec3) -> Vec3:
        """Unit outward normal at p, body-local.

        Outside the solid this is the direction away from the nearest surface
        point; on or inside it is the normal of the nearest face. At an edge or
        rim the supporting normals span a cone and the choice is arbitrary —
        that ambiguity is real geometry (§8.2), so keep regions off rims.
        """
        pl = self.to_local(p)
        d = pl - self._nearest_local(pl)
        n = float(np.linalg.norm(d))
        if n > _ON_SURFACE:
            return self.E @ (d / n)
        return self.E @ self._surface_normal_local(pl)

    def distance_to_segment(self, a: Vec3, b: Vec3) -> float:
        """Clearance between segment a-b and the solid; 0 if it intersects."""
        a = np.asarray(a, dtype=float)
        b = np.asarray(b, dtype=float)
        d = b - a
        if float(np.linalg.norm(d)) < 1e-15:
            return self.distance_to_point(a)
        return _golden_min(lambda t: self.distance_to_point(a + t * d))


@dataclass
class Sphere(ClearancePrimitive):
    radius: float = 1.0
    PARAMS: ClassVar[tuple] = (
        ParamSpec("radius", "Radius (in)", 1.0, 0.25),
    )


    def _nearest_local(self, pl):
        r = float(np.linalg.norm(pl))
        if r <= self.radius:
            return pl
        return pl * (self.radius / r)

    def _surface_normal_local(self, pl):
        r = float(np.linalg.norm(pl))
        if r < _ON_SURFACE:
            raise ValueError("outward() is undefined at the centre of a sphere")
        return pl / r

    def distance_to_point(self, p):
        r = float(np.linalg.norm(self.to_local(p)))
        return max(0.0, r - self.radius)

    def distance_to_segment(self, a, b):
        """Exact closed form — a sphere needs no search."""
        a = np.asarray(a, dtype=float)
        b = np.asarray(b, dtype=float)
        c = self.origin
        d = b - a
        dd = float(d @ d)
        if dd < 1e-30:
            t = 0.0
        else:
            t = min(1.0, max(0.0, float((c - a) @ d) / dd))
        return max(0.0, float(np.linalg.norm(a + t * d - c)) - self.radius)


@dataclass
class Cylinder(ClearancePrimitive):
    """Finite circular cylinder. Axis is e3; z_min / z_max are along e3, so
    the sign of e3 matters."""

    radius: float = 1.0
    z_min: float = 0.0
    z_max: float = 1.0
    PARAMS: ClassVar[tuple] = (
        ParamSpec("radius", "Radius (in)", 1.0, 0.25),
        ParamSpec("z_min", "Z lower (in)", 0.0, 0.5),
        ParamSpec("z_max", "Z upper (in)", 1.0, 0.5),
    )


    def _nearest_local(self, pl):
        x, y, z = pl
        r = math.hypot(x, y)
        if r > self.radius:
            s = self.radius / r
            x, y = x * s, y * s
        z = min(max(z, self.z_min), self.z_max)
        return np.array([x, y, z])

    def _surface_normal_local(self, pl):
        x, y, z = pl
        r = math.hypot(x, y)
        slack_side = self.radius - r
        slack_hi = self.z_max - z
        slack_lo = z - self.z_min
        cap = np.array([0.0, 0.0, 1.0]) if slack_hi <= slack_lo else np.array([0.0, 0.0, -1.0])
        if r < _ON_SURFACE:
            return cap  # on the axis: radial is undefined, use the nearer cap
        if slack_side <= min(slack_hi, slack_lo):
            return np.array([x / r, y / r, 0.0])
        return cap

    def distance_to_point(self, p):
        x, y, z = self.to_local(p)
        dr = max(0.0, math.hypot(x, y) - self.radius)
        dz = max(0.0, z - self.z_max, self.z_min - z)
        return math.hypot(dr, dz)


@dataclass
class Box(ClearancePrimitive):
    """Rectangular box, centred on `origin`, half-extents along (e1, e2, e3)."""

    half_extents: Vec3 = (1.0, 1.0, 1.0)
    PARAMS: ClassVar[tuple] = (
        ParamSpec("half_extents", "Half extents (in)", (1.0, 1.0, 1.0), 0.5, "vec3"),
    )


    def __post_init__(self) -> None:
        super().__post_init__()
        self.half_extents = as_vec3(self.half_extents, "Box.half_extents")
        if np.any(self.half_extents < 0.0):
            raise ValueError("Box.half_extents must be non-negative")

    def _nearest_local(self, pl):
        h = self.half_extents
        return np.clip(pl, -h, h)

    def _surface_normal_local(self, pl):
        h = self.half_extents
        # the face whose plane the point is nearest, measured in units of that
        # face's own half-extent so a slab does not always pick its long axis
        with np.errstate(divide="ignore", invalid="ignore"):
            frac = np.where(h > 0.0, np.abs(pl) / np.where(h > 0.0, h, 1.0), np.inf)
        i = int(np.argmax(frac))
        n = np.zeros(3)
        n[i] = 1.0 if pl[i] >= 0.0 else -1.0
        return n

    def distance_to_point(self, p):
        pl = self.to_local(p)
        d = np.maximum(0.0, np.abs(pl) - self.half_extents)
        return float(np.linalg.norm(d))



# Registry shared by the builder UI and the JSON loader — see
# `model.REGION_TYPES` for why there is exactly one of these per family.
CLEARANCE_TYPES: dict[str, type] = {
    cls.__name__: cls for cls in (Sphere, Cylinder, Box)
}

__all__ = [
    "CLEARANCE_TYPES","ClearancePrimitive", "Sphere", "Cylinder", "Box"]


# ----------------------------------------------------------------------
# Boundary meshes
#
# A triangulated boundary of the solid, in PRIMITIVE-LOCAL coordinates. This
# is geometry, not rendering, so it lives with the primitive that defines it:
# the scene layer only transforms and colours what it gets back. Regions need
# no equivalent — their mesh comes from `region.point(q)`, the same function
# the optimizer differentiates.
#
# Every returned vertex lies ON the boundary, which is asserted in the tests
# via `distance_to_point`.
# ----------------------------------------------------------------------


def _grid_faces(n_u: int, n_v: int, wrap_u: bool = False) -> np.ndarray:
    """Triangles over an (n_u x n_v) vertex grid indexed row-major."""
    faces = []
    for i in range(n_u if wrap_u else n_u - 1):
        i2 = (i + 1) % n_u
        for j in range(n_v - 1):
            a = i * n_v + j
            b = i2 * n_v + j
            faces.append((a, b, a + 1))
            faces.append((b, b + 1, a + 1))
    return np.array(faces, dtype=int)


def _fan_faces(centre_index: int, ring: list[int]) -> list[tuple[int, int, int]]:
    return [
        (centre_index, ring[k], ring[(k + 1) % len(ring)]) for k in range(len(ring))
    ]


def _sphere_mesh(self, n: int = 16):
    n_th, n_ph = max(6, 2 * n), max(4, n)
    th = np.linspace(0.0, 2.0 * np.pi, n_th, endpoint=False)
    ph = np.linspace(0.0, np.pi, n_ph)
    T, P = np.meshgrid(th, ph, indexing="ij")
    v = self.radius * np.array(
        [np.sin(P) * np.cos(T), np.sin(P) * np.sin(T), np.cos(P)]
    ).reshape(3, -1)
    return v, _grid_faces(n_th, n_ph, wrap_u=True)


def _cylinder_mesh(self, n: int = 24):
    th = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    ring = np.array([np.cos(th), np.sin(th)]) * self.radius
    bottom = np.vstack([ring, np.full(n, self.z_min)])
    top = np.vstack([ring, np.full(n, self.z_max)])
    verts = [np.column_stack([bottom[:, k], top[:, k]]) for k in range(n)]
    v = np.hstack(verts)                      # interleaved (bottom, top) per k
    faces = list(_grid_faces(n, 2, wrap_u=True))
    c_lo, c_hi = v.shape[1], v.shape[1] + 1
    v = np.column_stack(
        [v, [0.0, 0.0, self.z_min], [0.0, 0.0, self.z_max]]
    )
    faces += _fan_faces(c_lo, [2 * k for k in range(n)])
    faces += _fan_faces(c_hi, [2 * k + 1 for k in range(n)])
    return v, np.array(faces, dtype=int)


def _box_mesh(self, n: int = 0):
    hx, hy, hz = self.half_extents
    v = np.array(
        [
            [sx * hx, sy * hy, sz * hz]
            for sx in (-1.0, 1.0)
            for sy in (-1.0, 1.0)
            for sz in (-1.0, 1.0)
        ]
    ).T
    # vertex index = 4*ix + 2*iy + iz with i in {0,1} for the -,+ side
    faces = np.array(
        [
            (0, 1, 3), (0, 3, 2),   # x = -hx
            (4, 6, 7), (4, 7, 5),   # x = +hx
            (0, 4, 5), (0, 5, 1),   # y = -hy
            (2, 3, 7), (2, 7, 6),   # y = +hy
            (0, 2, 6), (0, 6, 4),   # z = -hz
            (1, 5, 7), (1, 7, 3),   # z = +hz
        ],
        dtype=int,
    )
    return v, faces


def _surface_mesh(self, n: int = 20):
    """Triangulated boundary as `(vertices (3, m), faces (k, 3))`, body-local.

    `n` is a resolution hint; exact vertex counts are an implementation
    detail. Vertices are returned in the PARENT BODY's frame, i.e. the
    primitive's own frame and origin are already applied.
    """
    v_local, faces = self._local_mesh(n)
    return self.origin[:, None] + self.E @ v_local, faces


Sphere._local_mesh = _sphere_mesh
Cylinder._local_mesh = _cylinder_mesh
Box._local_mesh = _box_mesh
ClearancePrimitive.surface_mesh = _surface_mesh

__all__ = ["ClearancePrimitive", "Sphere", "Cylinder", "Box"]
