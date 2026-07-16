"""
library/analysis/fem_solver.py

FEM section solver — a thin wrapper over `sectionproperties` (design handoff
§4). WRAP, DON'T LEAK: nothing outside this module imports sectionproperties,
so the rest of the toolkit stays backend-agnostic and the heavy dependency is
imported lazily (keeps app start fast; only paid when FEM is actually used).

Axis mapping (the #1 defect risk — proven by tests, not inspection):
    sectionproperties uses an in-plane (x, y) with z longitudinal; this
    project uses (y, z) with x longitudinal. Our y ↔ their x, our z ↔ their y
    (identity in coordinate values), which gives:

        A          = area
        Iy (=∫z²)  = ixx           Iz (=∫y²) = iyy        Iyz (=∫yz) = ixy
        J          = j             Cw        = gamma
        (y_sc,z_sc)= sc            (identity)

    Load / stress sign mapping (probed on a rectangle, verified in
    tests/test_phase4.py for each component, both signs):

        n  = P        mxx = My      myy = -Mz     mzz = T
        vx = Vy       vy  = Vz

    The `myy = -Mz` flip matches sectionproperties' myy sign convention so
    that +Mz produces +σ at +y, consistent with the project's tensor-bending
    convention.

Units: loads in lb / lb·in and coordinates in inches give stresses in psi;
this module returns ksi (÷1000) to match the rest of the toolkit.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import TypedDict

import numpy as np


# ──────────────────────────────────────────────────────────────────────────
# Lazy backend import + meshed-section cache
# ──────────────────────────────────────────────────────────────────────────
_MESH_CACHE: dict = {}
_CACHE_ORDER: list = []
_CACHE_MAX = 16


def fem_available() -> bool:
    """True if the FEM backend (sectionproperties + shapely) can be imported."""
    try:
        import sectionproperties  # noqa: F401
        import shapely            # noqa: F401
        return True
    except Exception:
        return False


def sectionproperties_version() -> str:
    """Installed sectionproperties version (for the report citation)."""
    from importlib.metadata import version, PackageNotFoundError
    try:
        return version("sectionproperties")
    except PackageNotFoundError:
        return "unknown"


def _geom_key(outer: np.ndarray, voids, mesh_size: float):
    parts = [np.ascontiguousarray(np.round(outer, 9)).tobytes()]
    for v in voids:
        parts.append(b"|")
        parts.append(np.ascontiguousarray(np.round(np.asarray(v), 9)).tobytes())
    return (b"".join(parts), round(float(mesh_size), 12))


def _get_meshed(outer: np.ndarray, voids, mesh_size: float):
    """
    Build (and cache) a meshed, analysed sectionproperties Section for the
    given (y, z) polygon. Geometric + warping properties are computed once.
    """
    key = _geom_key(outer, voids, mesh_size)
    cached = _MESH_CACHE.get(key)
    if cached is not None:
        return cached

    from shapely import Polygon
    from sectionproperties.pre import Geometry
    from sectionproperties.analysis import Section

    shell = [(float(y), float(z)) for y, z in np.asarray(outer)]
    holes = [[(float(y), float(z)) for y, z in np.asarray(v)] for v in voids]
    poly = Polygon(shell, holes) if holes else Polygon(shell)
    geom = Geometry(poly)
    geom.create_mesh(mesh_sizes=[float(mesh_size)])
    sec = Section(geom)
    sec.calculate_geometric_properties()
    sec.calculate_warping_properties()

    _MESH_CACHE[key] = sec
    _CACHE_ORDER.append(key)
    if len(_CACHE_ORDER) > _CACHE_MAX:
        old = _CACHE_ORDER.pop(0)
        _MESH_CACHE.pop(old, None)
    return sec


def default_mesh_size(outer: np.ndarray, voids, min_wall: float | None = None) -> float:
    """
    Mesh size heuristic (design handoff §4): ~(min wall thickness)²/2 for
    thin-walled imports; otherwise a fraction of the bounding-box diagonal.
    """
    if min_wall and min_wall > 0:
        return max(min_wall**2 / 2.0, 1e-6)
    p = np.asarray(outer)
    diag = float(np.hypot(p[:, 0].ptp(), p[:, 1].ptp()))
    return max((diag / 40.0) ** 2, 1e-6)


# ──────────────────────────────────────────────────────────────────────────
# Properties + stress
# ──────────────────────────────────────────────────────────────────────────
def fem_properties(outer: np.ndarray, voids=(), mesh_size: float = 0.05) -> dict:
    """A, Iy, Iz, Iyz, J, Cw, shear_center from the FEM solve (our axes)."""
    sec = _get_meshed(outer, voids, mesh_size)
    ixx, iyy, ixy = sec.get_ic()
    x_sc, y_sc = sec.get_sc()
    return {
        "A": float(sec.get_area()),
        "Iy": float(ixx),
        "Iz": float(iyy),
        "Iyz": float(ixy),
        "J": float(sec.get_j()),
        "Cw": float(sec.get_gamma()),
        "shear_center": (float(x_sc), float(y_sc)),
    }


def fem_stress_at(outer: np.ndarray, voids, mesh_size: float,
                  P: float, Vy: float, Vz: float,
                  My: float, Mz: float, T: float,
                  points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Normal stress σ (ksi) and shear magnitude τ = √(τ_xz²+τ_yz²) (ksi) at each
    (y, z) query point, from the full FEM elasticity solve with all load
    components applied together (transverse shear and torsion are combined by
    the FEM itself — no manual combination needed). Points outside the mesh
    return NaN.
    """
    sec = _get_meshed(outer, voids, mesh_size)
    pts = [(float(y), float(z)) for y, z in np.atleast_2d(points)]
    res = sec.get_stress_at_points(
        pts, n=P, mxx=My, myy=-Mz, mzz=T, vx=Vy, vy=Vz,
    )
    sigma = np.full(len(pts), np.nan)
    tau = np.full(len(pts), np.nan)
    for i, r in enumerate(res):
        if r is None:
            continue
        szz, txz, tyz = r
        sigma[i] = szz / 1000.0
        tau[i] = float(np.hypot(txz, tyz)) / 1000.0
    return sigma, tau


# ──────────────────────────────────────────────────────────────────────────
# Solver wrapper
# ──────────────────────────────────────────────────────────────────────────
class FEMSolverResult(TypedDict):
    props: dict
    sigma: np.ndarray
    tau: np.ndarray


@dataclass
class FEMSolver:
    """
    sectionproperties FEM wrapper. Handles any polygon (catalog or imported);
    needs no midline skeleton. `mesh_size` defaults via `default_mesh_size`.
    """
    mesh_size: float | None = None

    name: str = "sectionproperties FEM"

    @property
    def method_citation(self) -> str:
        return f"sectionproperties v{sectionproperties_version()} (2-D FEM, Trefftz warping)"

    def _mesh(self, outer, voids, min_wall):
        return self.mesh_size or default_mesh_size(outer, voids, min_wall)

    def solve(self, outer: np.ndarray, voids, loads, points: np.ndarray,
              min_wall: float | None = None) -> FEMSolverResult:
        ms = self._mesh(outer, voids, min_wall)
        props = fem_properties(outer, voids, ms)
        sigma, tau = fem_stress_at(
            outer, voids, ms,
            loads.P, loads.Vy, loads.Vz, loads.My, loads.Mz, loads.T, points,
        )
        return FEMSolverResult(props=props, sigma=sigma, tau=tau)
