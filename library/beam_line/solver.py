"""
library/beam_line/solver.py

Direct-stiffness solve for the line beam. Pure: numpy only, no Streamlit.

WHY THE STIFFNESS METHOD
------------------------
The module has to handle beams that are statically indeterminate -- two or
more interior supports, fixed-fixed, a propped cantilever, elastic supports,
imposed settlement. A superposition/force method needs a redundant-selection
step that has to be re-derived for every support arrangement. The stiffness
method handles all of them with one assembly, and reports a mechanism (an
under-supported beam) as a detectable null space rather than as a plausible
wrong answer.

Two DOF per node -- transverse `v` (positive up) and rotation `th` (positive
counterclockwise). No axial DOF: see the note in `model.py` about why a pin
and a roller are the same restraint here.

ELEMENT EI IS PER-ELEMENT, NOT GLOBAL
-------------------------------------
`element_EI()` returns one value for every element today, because the UI
exposes a single prismatic section. The assembly, the reactions and the
diagram integration all read the per-element list, so a stepped or tapered
beam is a change to `element_EI()` and the UI -- not a solver rewrite.

MESH
----
Nodes go at every feature station (`Beam.feature_stations()`): the two ends,
every support, every hinge, every point load and moment, and both ends of
every distributed patch. There is no mesh refinement parameter and there does
not need to be one: Euler-Bernoulli elements are EXACT for these load types at
the nodes, and `diagrams.py` recovers the interior of each element in closed
form. Refining the mesh cannot change the answer.

HINGES
------
An internal moment release gives its node a second rotation DOF: elements to
the left of the hinge use `th_left`, elements to the right use `th_right`.
Nothing couples them, so moment cannot cross and the rotation is free to be
discontinuous -- which is exactly what a hinge is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from library.beam_line.model import POSITION_TOL, Beam

# Relative smallest-singular-value below which the free-DOF stiffness matrix is
# taken to be singular, i.e. the beam is a mechanism.
#
# This is a yes/no structural question, not a solution-quality metric, so a
# spectral test is the right tool here (unlike the condition number that was
# tried and removed from the bolt module, which was being asked to grade a
# solve). A genuine rigid-body mode sits at the 1e-16 floor while a real
# structure -- even one on deliberately soft springs -- sits many orders above,
# so the verdict does not hinge on where in that gap the threshold sits.
# `SolveResult.null_ratio` carries the measured value so it can be inspected.
SINGULAR_RATIO = 1.0e-10


@dataclass(frozen=True)
class Reaction:
    """Force and moment delivered TO the beam by one support.

    `Fy` positive up (lb), `Mz` positive counterclockwise (lb-in) -- the same
    convention as the applied loads, so reactions and loads can be summed
    directly in the equilibrium check.
    """

    x: float
    Fy: float
    Mz: float
    kind: str = ""
    label: str = ""


@dataclass(frozen=True)
class SolveResult:
    """Nodal solution plus the stability verdict.

    `th_left` / `th_right` differ only at a hinge. Everywhere else they hold
    the same value, and `diagrams.py` uses `th_right` when marching forward
    from a node.
    """

    nodes: tuple[float, ...]
    element_EI: tuple[float, ...]
    v: tuple[float, ...]
    th_left: tuple[float, ...]
    th_right: tuple[float, ...]
    reactions: tuple[Reaction, ...]
    stable: bool
    null_ratio: float
    message: str = ""

    @property
    def n_elements(self) -> int:
        return len(self.nodes) - 1


def element_EI(beam: Beam, x1: float, x2: float) -> float:
    """Bending stiffness of the element spanning `x1` to `x2`, lb-in^2.

    Constant today. The seam for stepped/tapered EI: return the value for the
    segment containing the element midpoint, and add nodes at every step to
    `Beam.feature_stations()` so no element straddles a change.
    """
    return float(beam.EI)


def _element_stiffness(EI: float, L: float) -> np.ndarray:
    """Euler-Bernoulli beam element, DOF order [v1, th1, v2, th2]."""
    c = EI / (L ** 3)
    return c * np.array([
        [12.0,      6.0 * L, -12.0,      6.0 * L],
        [6.0 * L, 4.0 * L * L, -6.0 * L, 2.0 * L * L],
        [-12.0,    -6.0 * L,  12.0,     -6.0 * L],
        [6.0 * L, 2.0 * L * L, -6.0 * L, 4.0 * L * L],
    ], dtype=float)


def _element_load_vector(w1: float, w2: float, L: float) -> np.ndarray:
    """Consistent nodal loads for a linearly varying intensity w1 -> w2.

    Obtained by integrating the Hermite shape functions against w(x):

        f1 = L  (0.35 w1 + 0.15 w2)
        f2 = L^2 (3 w1 + 2 w2) / 60
        f3 = L  (0.15 w1 + 0.35 w2)
        f4 = -L^2 (2 w1 + 3 w2) / 60

    which collapses to the familiar [wL/2, wL^2/12, wL/2, -wL^2/12] when
    w1 == w2, and whose first and third terms always sum to the true
    resultant L(w1 + w2)/2.
    """
    return np.array([
        L * (0.35 * w1 + 0.15 * w2),
        L * L * (3.0 * w1 + 2.0 * w2) / 60.0,
        L * (0.15 * w1 + 0.35 * w2),
        -L * L * (2.0 * w1 + 3.0 * w2) / 60.0,
    ], dtype=float)


def intensity_at(beam: Beam, x: float, side: str = "mid") -> float:
    """Total distributed intensity at station `x`, summed over every patch.

    Overlapping patches add, which is physical -- a snow load on top of a
    self-weight load is two patches, not an error. `side` disambiguates a
    station that is a patch boundary: "right" counts a patch starting exactly
    at `x`, "left" counts one ending exactly at `x`.
    """
    total = 0.0
    for d in beam.distributed:
        if d.length <= POSITION_TOL:
            continue
        lo, hi = d.x1 - POSITION_TOL, d.x2 + POSITION_TOL
        if side == "right":
            inside = (x >= d.x1 - POSITION_TOL) and (x < d.x2 - POSITION_TOL)
        elif side == "left":
            inside = (x > d.x1 + POSITION_TOL) and (x <= hi)
        else:
            inside = lo <= x <= hi
        if inside:
            total += d.intensity_at(min(max(x, d.x1), d.x2))
    return total


def _node_index(nodes: Sequence[float], x: float) -> int:
    """Index of the node at station `x`. Every feature has one by construction."""
    best, best_d = 0, float("inf")
    for i, xn in enumerate(nodes):
        d = abs(xn - x)
        if d < best_d:
            best, best_d = i, d
    return best


def solve(beam: Beam) -> SolveResult:
    """Assemble and solve. Never raises on an unstable beam -- it returns
    `stable=False` with a message, because a mechanism is a modelling mistake
    the user has to see, not an exception the page should crash on.
    """
    nodes = beam.feature_stations()
    n = len(nodes)
    if n < 2:
        return SolveResult((), (), (), (), (), (), False, 0.0,
                           "Span is degenerate.")

    hinge_nodes = {_node_index(nodes, h.x) for h in beam.hinges}

    # ---- DOF allocation -------------------------------------------------
    dof_v: list[int] = []
    th_l: list[int] = []
    th_r: list[int] = []
    ndof = 0
    for i in range(n):
        dof_v.append(ndof); ndof += 1
        a = ndof; ndof += 1
        if i in hinge_nodes and 0 < i < n - 1:
            b = ndof; ndof += 1
        else:
            b = a
        th_l.append(a)
        th_r.append(b)

    # ---- Assembly -------------------------------------------------------
    K = np.zeros((ndof, ndof), dtype=float)
    F = np.zeros(ndof, dtype=float)
    EIs: list[float] = []

    for e in range(n - 1):
        x1, x2 = nodes[e], nodes[e + 1]
        Le = x2 - x1
        EI = element_EI(beam, x1, x2)
        EIs.append(EI)
        idx = [dof_v[e], th_r[e], dof_v[e + 1], th_l[e + 1]]
        ke = _element_stiffness(EI, Le)
        w1 = intensity_at(beam, x1, side="right")
        w2 = intensity_at(beam, x2, side="left")
        fe = _element_load_vector(w1, w2, Le)
        for a in range(4):
            F[idx[a]] += fe[a]
            for b in range(4):
                K[idx[a], idx[b]] += ke[a, b]

    for p in beam.point_loads:
        F[dof_v[_node_index(nodes, p.x)]] += p.P
    for m in beam.moments:
        i = _node_index(nodes, m.x)
        # Validation rejects a moment applied exactly at a hinge, so th_l and
        # th_r are the same DOF here.
        F[th_l[i]] += m.M

    K_struct = K.copy()
    F_app = F.copy()

    # ---- Supports -------------------------------------------------------
    fixed: dict[int, float] = {}
    for s in beam.supports:
        i = _node_index(nodes, s.x)
        if s.uy == "rigid":
            fixed[dof_v[i]] = s.dy
        elif s.uy == "spring":
            K[dof_v[i], dof_v[i]] += s.ky
            F[dof_v[i]] += s.ky * s.dy
        if s.rz == "rigid":
            fixed[th_l[i]] = s.drz
        elif s.rz == "spring":
            K[th_l[i], th_l[i]] += s.krz
            F[th_l[i]] += s.krz * s.drz

    free = [d for d in range(ndof) if d not in fixed]
    if not free:
        d_full = np.zeros(ndof)
        for d, val in fixed.items():
            d_full[d] = val
        ratio = 1.0
    else:
        cons = sorted(fixed)
        d_c = np.array([fixed[d] for d in cons], dtype=float)
        Kff = K[np.ix_(free, free)]
        rhs = F[free] - (K[np.ix_(free, cons)] @ d_c if cons else 0.0)

        ratio = _null_ratio(Kff)
        if ratio < SINGULAR_RATIO:
            return SolveResult(
                tuple(nodes), tuple(EIs), (), (), (), (), False, ratio,
                _mechanism_message(beam),
            )

        d_free = np.linalg.solve(Kff, rhs)
        d_full = np.zeros(ndof)
        d_full[free] = d_free
        for d, val in fixed.items():
            d_full[d] = val

    # ---- Reactions ------------------------------------------------------
    # The structural residual is zero at every unsupported DOF and equals the
    # force the support delivers to the beam at every supported one. Springs
    # fall out of the same expression, because their stiffness was added to K
    # but not to K_struct.
    resid = K_struct @ d_full - F_app
    reactions: list[Reaction] = []
    for s in beam.supports:
        i = _node_index(nodes, s.x)
        Fy = float(resid[dof_v[i]]) if s.uy != "none" else 0.0
        Mz = float(resid[th_l[i]]) if s.rz != "none" else 0.0
        reactions.append(Reaction(s.x, Fy, Mz, s.kind, s.label))

    return SolveResult(
        nodes=tuple(nodes),
        element_EI=tuple(EIs),
        v=tuple(float(d_full[dof_v[i]]) for i in range(n)),
        th_left=tuple(float(d_full[th_l[i]]) for i in range(n)),
        th_right=tuple(float(d_full[th_r[i]]) for i in range(n)),
        reactions=tuple(reactions),
        stable=True,
        null_ratio=ratio,
    )


def _null_ratio(Kff: np.ndarray) -> float:
    """Smallest / largest singular value of the diagonally scaled matrix.

    The scaling matters: vertical DOFs carry stiffness of order EI/L^3 and
    rotations of order EI/L, so an unscaled spectrum spans L^2 for reasons
    that have nothing to do with stability. Normalising to a unit diagonal
    removes that, leaving a ratio that measures only how close the beam is to
    being a mechanism.
    """
    d = np.sqrt(np.abs(np.diag(Kff)))
    d[d <= 0.0] = 1.0
    Kn = Kff / np.outer(d, d)
    sv = np.linalg.svd(Kn, compute_uv=False)
    if sv.size == 0 or sv[0] <= 0.0:
        return 0.0
    return float(sv[-1] / sv[0])


def _mechanism_message(beam: Beam) -> str:
    """Explain the instability in terms the analyst can act on."""
    n_vert = sum(1 for s in beam.supports if s.uy != "none")
    n_rot = sum(1 for s in beam.supports if s.rz != "none")
    if n_vert + n_rot == 0:
        return ("The beam has no supports — it is free to translate and "
                "rotate. Add at least two vertical supports, or one fixed "
                "support.")
    if n_vert <= 1 and n_rot == 0:
        return ("The beam is a mechanism: one vertical support and no "
                "rotational restraint leaves it free to rotate. Add a second "
                "vertical support, or make this one fixed.")
    if beam.hinges:
        return ("The beam is a mechanism. There are enough supports for a "
                "continuous beam, but the internal hinges release more "
                "moment continuity than the supports can make up — each "
                "segment between hinges needs its own restraint.")
    return ("The beam is a mechanism — the supports do not restrain every "
            "rigid-body motion. Check that the supports are not all at the "
            "same station.")
