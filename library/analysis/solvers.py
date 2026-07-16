"""
library/analysis/solvers.py

Section shear/torsion solvers (design handoff §2.3, §3.2–3.3).

Phase 2 provides the ClassicalMidlineSolver for OPEN thin-walled sections:
Bruhn-style midline shear-flow theory. Closed cells (Bredt) and the FEM
wrapper arrive in Phase 3 / Phase 4. Everything here is pure engineering
math — no Streamlit, no matplotlib.

Coordinate / moment conventions (project-wide):
    y right, z up, origin at centroid.
    Iy = ∫z² dA, Iz = ∫y² dA, Iyz = ∫yz dA (all centroidal).

Open-section transverse shear flow, integrated from a free edge along the
wall, including the product of inertia (design handoff §3.2):

    q(s) = − [ (Vy·Iy − Vz·Iyz)·∫₀ˢ y·t ds
             + (Vz·Iz − Vy·Iyz)·∫₀ˢ z·t ds ] / Δ ,   Δ = Iy·Iz − Iyz²

With Iyz = 0 this reduces to q = −Vy·Qz/Iz − Vz·Qy/Iy (Qz = ∫y dA,
Qy = ∫z dA) — the physically correct pairing Vy↔(Iz, ∫y) and Vz↔(Iy, ∫z).

Torsion (open): J = Σ Lᵢ·tᵢ³ / 3 ; surface stress τ_T = T·t/J per segment.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, TypedDict

import numpy as np

from library.shapes.geometry import SectionGeometry, MidlineSegment
from library.analysis.polygon_props import PolygonProps


# ──────────────────────────────────────────────────────────────────────────
# Solver protocol / result (design handoff §2.3)
# ──────────────────────────────────────────────────────────────────────────
class SolverResult(TypedDict):
    """Per-solve outputs. Per-point arrays align with the query `points`."""
    J: float                              # torsion constant, in^4
    shear_center: tuple[float, float]     # (y_sc, z_sc) from centroid, in
    Cw: float | None                      # warping constant, in^6 (None if n/a)
    tau_v: np.ndarray                     # transverse shear stress at points, ksi
    tau_t: np.ndarray                     # torsional shear stress at points, ksi


class SectionSolver(Protocol):
    name: str
    method_citation: str

    def solve(self, geom: SectionGeometry, props: PolygonProps,
              Vy: float, Vz: float, T: float,
              points: np.ndarray) -> SolverResult: ...


# ──────────────────────────────────────────────────────────────────────────
# Midline tree utilities
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class _Tree:
    nodes: np.ndarray                     # (M, 2)
    segments: tuple[MidlineSegment, ...]
    adj: list[list[tuple[int, int]]]      # node -> [(neighbor, seg_index), ...]
    parent: list[int]                     # parent node index (-1 for root)
    parent_seg: list[int]                 # seg index linking node to its parent
    order: list[int]                      # nodes in root→leaf (pre-order)


def _build_tree(geom: SectionGeometry) -> _Tree:
    nodes = np.asarray(geom.nodes, dtype=float)
    M = len(nodes)
    adj: list[list[tuple[int, int]]] = [[] for _ in range(M)]
    for si, seg in enumerate(geom.segments):
        adj[seg.n1].append((seg.n2, si))
        adj[seg.n2].append((seg.n1, si))

    # Root at the highest-degree node so flange tips become leaves.
    root = max(range(M), key=lambda n: len(adj[n]))
    parent = [-1] * M
    parent_seg = [-1] * M
    order: list[int] = []
    seen = [False] * M
    stack = [root]
    seen[root] = True
    while stack:
        n = stack.pop()
        order.append(n)
        for nbr, si in adj[n]:
            if not seen[nbr]:
                seen[nbr] = True
                parent[nbr] = n
                parent_seg[nbr] = si
                stack.append(nbr)
    return _Tree(nodes, geom.segments, adj, parent, parent_seg, order)


def _seg_thickness(tree: _Tree, seg_index: int) -> float:
    return tree.segments[seg_index].t


def _subtree_moments(tree: _Tree) -> np.ndarray:
    """
    S[node] = Σ over the node's leaf-side subtree of ∫(y, z)·t ds
    (directed leaf→root). Accumulated by processing nodes in reverse
    pre-order (leaves first). Returns (M, 2): columns [∫y·t ds, ∫z·t ds].
    """
    M = len(tree.nodes)
    S = np.zeros((M, 2))
    for n in reversed(tree.order):
        p = tree.parent[n]
        if p < 0:
            continue
        # edge (child n → parent p): directed first-moment of the edge
        yc, zc = tree.nodes[n]
        yp, zp = tree.nodes[p]
        L = float(np.hypot(yp - yc, zp - zc))
        t = _seg_thickness(tree, tree.parent_seg[n])
        edge_moment = np.array([t * L * (yc + yp) / 2.0,
                                t * L * (zc + zp) / 2.0])
        S[p] += S[n] + edge_moment
    return S


# ──────────────────────────────────────────────────────────────────────────
# Shear-flow evaluation
# ──────────────────────────────────────────────────────────────────────────
def _shear_coeffs(props: PolygonProps, Vy: float, Vz: float
                  ) -> tuple[float, float, float]:
    """Return (A_yy, A_zz, Δ) for the §3.2 shear-flow expression."""
    Iy, Iz, Iyz = props.Iy, props.Iz, props.Iyz
    Delta = Iy * Iz - Iyz**2
    A_yy = Vy * Iy - Vz * Iyz      # multiplies ∫y·t ds
    A_zz = Vz * Iz - Vy * Iyz      # multiplies ∫z·t ds
    return A_yy, A_zz, Delta


def _q_on_edge(tree: _Tree, S: np.ndarray, child: int, parent: int,
               seg_index: int, u: np.ndarray,
               A_yy: float, A_zz: float, Delta: float) -> np.ndarray:
    """
    Shear flow q at parametric positions u∈[0,1] along edge child→parent.
    M(u) = S[child] + ∫₀^{uL} (y, z)·t dl (analytic for a straight edge).
    """
    yc, zc = tree.nodes[child]
    yp, zp = tree.nodes[parent]
    L = float(np.hypot(yp - yc, zp - zc))
    t = _seg_thickness(tree, seg_index)
    My_run = S[child, 0] + t * L * (yc * u + (yp - yc) * u**2 / 2.0)  # ∫y·t ds
    Mz_run = S[child, 1] + t * L * (zc * u + (zp - zc) * u**2 / 2.0)  # ∫z·t ds
    if Delta <= 0:
        return np.zeros_like(u)
    return -(A_yy * My_run + A_zz * Mz_run) / Delta


def _oriented_edges(tree: _Tree) -> list[tuple[int, int, int]]:
    """List of (child, parent, seg_index) for every edge, oriented leaf→root."""
    out = []
    for n in tree.order:
        p = tree.parent[n]
        if p >= 0:
            out.append((n, p, tree.parent_seg[n]))
    return out


def classical_shear_center(geom: SectionGeometry, props: PolygonProps,
                           n_sub: int = 200) -> tuple[float, float]:
    """
    Shear center (y_sc, z_sc) from the moment of the shear-flow distribution
    about the centroid, one unit load at a time (design handoff §3.2).

    For unit Vz the shear flow carries a net vertical force of 1; the torque
    it produces about the centroid equals the horizontal offset of its line
    of action, i.e. y_sc. Likewise unit Vy → z_sc.
    """
    tree = _build_tree(geom)
    S = _subtree_moments(tree)
    edges = _oriented_edges(tree)
    u = np.linspace(0.0, 1.0, n_sub + 1)

    def torque_for(Vy: float, Vz: float) -> float:
        A_yy, A_zz, Delta = _shear_coeffs(props, Vy, Vz)
        total = 0.0
        for child, parent, si in edges:
            yc, zc = tree.nodes[child]
            yp, zp = tree.nodes[parent]
            L = float(np.hypot(yp - yc, zp - zc))
            if L == 0:
                continue
            that_y = (yp - yc) / L
            that_z = (zp - zc) / L
            ys = yc + (yp - yc) * u
            zs = zc + (zp - zc) * u
            q = _q_on_edge(tree, S, child, parent, si, u, A_yy, A_zz, Delta)
            # dT = q·(y·t̂_z − z·t̂_y) ds  (moment about +X / centroid)
            arm = ys * that_z - zs * that_y
            total += np.trapezoid(q * arm, dx=L / n_sub)
        return total

    y_sc = torque_for(Vy=0.0, Vz=1.0)     # torque under unit vertical shear
    z_sc = -torque_for(Vy=1.0, Vz=0.0)    # sign fixed by the symmetry tests
    return float(y_sc), float(z_sc)


def classical_J_open(geom: SectionGeometry) -> float:
    """Open thin-walled torsion constant J = Σ Lᵢ·tᵢ³/3."""
    nodes = np.asarray(geom.nodes, dtype=float)
    J = 0.0
    for seg in geom.segments:
        L = float(np.hypot(*(nodes[seg.n2] - nodes[seg.n1])))
        J += L * seg.t**3 / 3.0
    return J


def _project_point_to_skeleton(tree: _Tree, y: float, z: float
                               ) -> tuple[int, int, int, float, float]:
    """
    Nearest skeleton location to (y, z). Returns
    (child, parent, seg_index, u, thickness) for the closest oriented edge,
    u the clamped foot-of-perpendicular parameter along child→parent.
    """
    best = None
    for n in tree.order:
        p = tree.parent[n]
        if p < 0:
            continue
        a = tree.nodes[n]
        b = tree.nodes[p]
        ab = b - a
        L2 = float(ab @ ab)
        if L2 == 0:
            continue
        u = float(np.clip(((np.array([y, z]) - a) @ ab) / L2, 0.0, 1.0))
        foot = a + u * ab
        d = float(np.hypot(y - foot[0], z - foot[1]))
        if best is None or d < best[0]:
            best = (d, n, p, tree.parent_seg[n], u, _seg_thickness(tree, tree.parent_seg[n]))
    _, child, parent, si, u, t = best
    return child, parent, si, u, t


def classical_shear_flow_at(geom: SectionGeometry, props: PolygonProps,
                            Vy: float, Vz: float,
                            points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Shear flow q and wall thickness t at each query point (projected to the
    nearest skeleton segment). Returns (q_array, t_array).
    """
    tree = _build_tree(geom)
    S = _subtree_moments(tree)
    A_yy, A_zz, Delta = _shear_coeffs(props, Vy, Vz)
    pts = np.atleast_2d(np.asarray(points, dtype=float))
    q_out = np.zeros(len(pts))
    t_out = np.zeros(len(pts))
    for i, (y, z) in enumerate(pts):
        child, parent, si, u, t = _project_point_to_skeleton(tree, y, z)
        q_out[i] = float(_q_on_edge(tree, S, child, parent, si,
                                    np.array([u]), A_yy, A_zz, Delta)[0])
        t_out[i] = t
    return q_out, t_out


# ──────────────────────────────────────────────────────────────────────────
# ClassicalMidlineSolver
# ──────────────────────────────────────────────────────────────────────────
class ClassicalMidlineSolver:
    """
    Bruhn-style midline solver for OPEN thin-walled sections. Requires a
    populated skeleton (geom.nodes / geom.segments); raises otherwise.
    """
    name = "Classical midline (Bruhn)"
    method_citation = "Bruhn C6/A15 open-section shear flow; St-Venant open torsion J=ΣLt³/3"

    def solve(self, geom: SectionGeometry, props: PolygonProps,
              Vy: float, Vz: float, T: float,
              points: np.ndarray) -> SolverResult:
        if geom.nodes is None or len(geom.segments) == 0:
            raise ValueError("ClassicalMidlineSolver requires a midline skeleton.")

        J = classical_J_open(geom)
        y_sc, z_sc = classical_shear_center(geom, props)
        q, t = classical_shear_flow_at(geom, props, Vy, Vz, points)

        tau_v = q / np.where(t > 0, t, np.nan) / 1000.0          # ksi
        if J > 0:
            tau_t = np.sign(T) * abs(T) * t / J / 1000.0         # ksi, per-segment surface
        else:
            tau_t = np.zeros_like(tau_v)

        return SolverResult(
            J=J, shear_center=(y_sc, z_sc), Cw=None,
            tau_v=tau_v, tau_t=tau_t,
        )
