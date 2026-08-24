"""
Tie-rod layout analysis — the analysis kernel (build prompt §4).

Pure numpy. **Never imports Streamlit.**

Conventions (fixed by the spec — do not re-derive, do not flip signs)
---------------------------------------------------------------------
Rod i runs from point `a` on body p to point `b` on body q:

    v = b - a ,   L = |v| ,   u = v / L ,   P > 0 is TENSION

Tension applies `+P u` to body p at a, and `-P u` to body q at b. Each body
keeps its OWN datum and rotations are about that datum, so the moment arms
`r_a`, `r_b` are measured from each body's origin, not from global zero.

Rod i contributes one column to Ghat:

    body p block (the 'a' end):   + [ u ; r_a x u ]
    body q block (the 'b' end):   - [ u ; r_b x u ]
    ground bodies:                  no block at all

and then

    delta = -Ghat^T U            elongation of each rod
    k_i   = A_i E_i / L_i        in series with k_backup at either end
    K     = Ghat K_d Ghat^T      (n_dof x n_dof)
    K U   = F
    P     = -K_d Ghat^T U
    G     = -K_d Ghat^T K^-1     load influence matrix, P = G F

with the identity `Ghat P = -F` (equilibrium) following directly. That identity
is the cheapest possible check on the whole chain and the tests assert it
everywhere.

> The `K U = F` sign matters. An earlier draft of the spec had `K u = -F`,
> where two sign errors cancelled in the rod loads but inverted the reported
> displacement — which is the engineer's only check on the small-displacement
> assumption.

Properties this implementation exhibits
---------------------------------------
* `K` is `6 * n_free` square regardless of rod count. At 10 free bodies that is
  60x60; dense factorization is correct and fast. No sparse solvers.
* When statically determinate, `P = -Ghat^-1 F`, independent of every `k_i`.
* `K` is factored once per geometry (`solve` takes many right-hand sides, and
  `influence` does a single multi-RHS solve), so a load sweep is one matmul.

Rank, conditioning and mechanism diagnosis are deliberately NOT here — that is
`mechanisms.py`. This module raises `SingularAssemblyError` and points at it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from library.tierod.model import Assembly, Rod, Vec3, skew

_COINCIDENT_TOL = 1e-12
_RANK_TOL = 1e-9        # relative to the largest singular value


class SingularAssemblyError(RuntimeError):
    """K is singular: the layout is a mechanism, or numerically close to one.

    Raised instead of returning inf/NaN loads, which would silently poison a
    sweep or an optimizer run. Use `mechanisms.py` to find out WHICH motion the
    layout permits — that diagnosis is the useful output, not this exception.
    """


@dataclass
class Assembled:
    """Everything the geometry determines, before any load is applied.

    The build prompt names `assemble(assembly) -> Ghat, K_d, K`; those three are
    `G_hat`, `K_d` and `K` here. The remaining fields are bookkeeping that
    later stages need (`lengths` for the column allowable, `body_order` for
    interpreting null modes, `rod_ids` for labelling results) and that would
    otherwise have to be recomputed from the geometry a second time.
    """

    G_hat: np.ndarray          # (n_dof, N) screw matrix
    k_d: np.ndarray            # (N,) rod axial stiffnesses
    K: np.ndarray              # (n_dof, n_dof)
    rod_ids: list[str]
    body_order: list[str]      # free bodies, in DOF-block order
    lengths: np.ndarray        # (N,) rod lengths
    units: np.ndarray          # (3, N) unit vectors, a -> b
    L_c: float = 1.0           # characteristic length: max attachment radius
    points_a: np.ndarray = field(default_factory=lambda: np.zeros((3, 0)))
    points_b: np.ndarray = field(default_factory=lambda: np.zeros((3, 0)))
    rod_body_a: list[str] = field(default_factory=list)   # body at each 'a' end
    rod_body_b: list[str] = field(default_factory=list)   # body at each 'b' end
    body_datums: dict = field(default_factory=dict)       # body id -> datum

    @property
    def K_d(self) -> np.ndarray:
        """Diagonal stiffness matrix, so the equations read as written."""
        return np.diag(self.k_d)

    @property
    def n_dof(self) -> int:
        return self.G_hat.shape[0]

    @property
    def n_rods(self) -> int:
        return self.G_hat.shape[1]

    @property
    def n_free(self) -> int:
        return len(self.body_order)

    # -- rank, on the NON-DIMENSIONALIZED screws ------------------------
    #
    # Ghat mixes units: the translation rows are dimensionless, the moment rows
    # carry a length. Any singular value or condition number taken on the raw
    # matrix is meaningless, so the moment rows are divided by the
    # characteristic length L_c first. Session 3 owns mechanism DIAGNOSIS (which
    # body, which motion, which geometric degeneracy); what lives here is only
    # the yes/no invertibility guard that `influence` cannot be safe without.

    def nondim_screws(self) -> np.ndarray:
        """Ghat with the moment rows scaled to be dimensionless."""
        G = self.G_hat.copy()
        for i in range(self.n_free):
            G[6 * i + 3 : 6 * i + 6, :] /= self.L_c
        return G

    def screw_singular_values(self) -> np.ndarray:
        if self.n_rods == 0 or self.n_dof == 0:
            return np.zeros(0)
        return np.linalg.svd(self.nondim_screws(), compute_uv=False)

    @property
    def rank(self) -> int:
        """rank(K) == rank(Ghat), since K = Ghat K_d Ghat^T with K_d positive."""
        s = self.screw_singular_values()
        if s.size == 0:
            return 0
        return int(np.count_nonzero(s > _RANK_TOL * s[0]))

    @property
    def is_singular(self) -> bool:
        return self.rank < self.n_dof

    def assert_nonsingular(self) -> None:
        if self.is_singular:
            raise SingularAssemblyError(
                f"the layout is a mechanism: rank {self.rank} against "
                f"{self.n_dof} free-body DOF, so {self.n_dof - self.rank} "
                f"independent rigid-body motions are unrestrained. Run the "
                f"mechanism checks to see which motions those are and which "
                f"body is unsupported."
            )


def rod_stiffness(rod: Rod, length: float) -> float:
    """Axial stiffness `k_i` of one rod, backup compliance included.

    The rod itself is `A E / L`. `k_backup_a` / `k_backup_b` are springs in
    SERIES at each end representing backup-structure compliance, so
    compliances add:

        1/k = L/(A E) + 1/k_backup_a + 1/k_backup_b

    Both default to infinity (rigid backup), which leaves `k = A E / L`
    exactly. The hook is live from Session 2 so the kernel signature never has
    to change; Phase 5 is where it gets driven from the UI.
    """
    if length <= 0.0:
        raise ValueError(f"rod {rod.id!r}: length must be positive, got {length}")
    if rod.A <= 0.0 or rod.E <= 0.0:
        raise ValueError(f"rod {rod.id!r}: A and E must be positive")
    compliance = length / (rod.A * rod.E)
    for tag, k_backup in (("a", rod.k_backup_a), ("b", rod.k_backup_b)):
        if np.isfinite(k_backup):
            if k_backup <= 0.0:
                raise ValueError(
                    f"rod {rod.id!r}: k_backup_{tag} must be positive or infinite, "
                    f"got {k_backup}"
                )
            compliance += 1.0 / k_backup
    return 1.0 / compliance


def assemble(assembly: Assembly) -> Assembled:
    """Build Ghat, K_d and K from the geometry.

    Ground bodies contribute no DOF block, so `n_dof = 6 * n_free` no matter
    how many grounds there are — including zero, which is the legitimate
    free-free diagnostic mode rather than an error.
    """
    free = assembly.free_bodies()
    slots = {body_id: i for i, body_id in enumerate(free)}
    n_dof = 6 * len(free)
    rod_ids = list(assembly.rods.keys())
    n_rods = len(rod_ids)

    G_hat = np.zeros((n_dof, n_rods))
    k_d = np.zeros(n_rods)
    lengths = np.zeros(n_rods)
    units = np.zeros((3, n_rods))
    points_a = np.zeros((3, n_rods))
    points_b = np.zeros((3, n_rods))
    rod_body_a: list[str] = []
    rod_body_b: list[str] = []

    for j, rod_id in enumerate(rod_ids):
        rod = assembly.rods[rod_id]
        a, body_a = assembly.endpoint_global(rod.end_a)
        b, body_b = assembly.endpoint_global(rod.end_b)

        v = b - a
        L = float(np.linalg.norm(v))
        if L <= _COINCIDENT_TOL:
            raise ValueError(
                f"rod {rod_id!r} has zero length: its ends are coincident at {a}"
            )
        u = v / L

        lengths[j] = L
        units[:, j] = u
        points_a[:, j] = a
        points_b[:, j] = b
        rod_body_a.append(body_a)
        rod_body_b.append(body_b)
        k_d[j] = rod_stiffness(rod, L)

        # + [u ; r_a x u] on the 'a' body, - [u ; r_b x u] on the 'b' body,
        # each moment arm taken about THAT body's own datum.
        for body_id, point, sign in ((body_a, a, +1.0), (body_b, b, -1.0)):
            if body_id not in slots:
                continue  # ground: no block
            r = point - assembly.bodies[body_id].origin
            block = slice(6 * slots[body_id], 6 * slots[body_id] + 6)
            G_hat[block, j] += sign * np.concatenate([u, skew(r) @ u])

    K = (G_hat * k_d) @ G_hat.T
    K = 0.5 * (K + K.T)  # symmetric by construction; kill roundoff asymmetry

    return Assembled(
        G_hat=G_hat,
        k_d=k_d,
        K=K,
        rod_ids=rod_ids,
        body_order=list(free),
        lengths=lengths,
        units=units,
        L_c=_characteristic_length(assembly, slots, points_a, points_b),
        points_a=points_a,
        points_b=points_b,
        rod_body_a=rod_body_a,
        rod_body_b=rod_body_b,
        body_datums={
            body_id: np.asarray(body.origin, dtype=float)
            for body_id, body in assembly.bodies.items()
        },
    )


def _characteristic_length(assembly, slots, points_a, points_b) -> float:
    """Max attachment radius over the FREE bodies, measured from each body's
    own datum. Used only to non-dimensionalize the screws before any rank or
    conditioning question is asked (build prompt §5.5).

    Falls back to 1.0 when there is nothing to measure, so the scaling is a
    no-op rather than a division by zero.
    """
    radii = [0.0]
    for j, rod_id in enumerate(assembly.rods):
        rod = assembly.rods[rod_id]
        for end, pts in ((rod.end_a, points_a), (rod.end_b, points_b)):
            body_id = assembly.regions[end.region_id].body_id
            if body_id not in slots:
                continue
            r = pts[:, j] - assembly.bodies[body_id].origin
            radii.append(float(np.linalg.norm(r)))
    L_c = max(radii)
    return L_c if L_c > 0.0 else 1.0


_RESIDUAL_TOL = 1e-6


def _solve_checked(A: np.ndarray, B: np.ndarray, message: str) -> np.ndarray:
    """`A X = B`, refusing to return a meaningless answer.

    LAPACK's LU only raises when it hits an EXACT zero pivot. A rank-deficient
    K assembled from real geometry rarely obliges: it usually returns a huge,
    silently wrong X instead. That wrong X propagates into rod loads, margins
    and the optimizer with no outward sign of trouble, so verify the solution
    instead of trusting the absence of an exception.

    The check is a relative residual on the system actually solved — not a
    condition number. Raw-K condition numbers are meaningless here because K
    mixes force/length and force*length blocks; conditioning has to be done on
    the non-dimensionalized matrix and belongs to `mechanisms.py`.
    """
    try:
        X = np.linalg.solve(A, B)
    except np.linalg.LinAlgError as exc:
        raise SingularAssemblyError(message) from exc
    if not np.all(np.isfinite(X)):
        raise SingularAssemblyError(message)
    scale = float(np.linalg.norm(B))
    if scale > 0.0:
        residual = float(np.linalg.norm(A @ X - B)) / scale
        if residual > _RESIDUAL_TOL:
            raise SingularAssemblyError(
                f"{message} (relative residual {residual:.3e} — the solution "
                f"does not satisfy the system)"
            )
    return X


_SINGULAR_MSG = (
    "K is singular: the layout permits a rigid-body motion. Run the mechanism "
    "checks to see which motion the layout allows and which body is "
    "unsupported, rather than treating this as a numerical failure."
)


def solve(K: np.ndarray, F: np.ndarray) -> np.ndarray:
    """Solve `K U = F` for the displacement of every free body.

    `F` may be a single wrench `(n_dof,)` or a stack of load cases
    `(n_dof, n_cases)` — the factorization is shared across the columns, which
    is what makes the orientation sweep one matrix operation.

    U stacks `[d_p ; theta_p]` per free body in `Assembled.body_order`.
    Rotations are about each body's own datum.

    Raises `SingularAssemblyError` rather than returning a wrong answer when
    the layout is a mechanism.
    """
    F = np.asarray(F, dtype=float)
    if K.shape[0] != F.shape[0]:
        raise ValueError(
            f"F has {F.shape[0]} rows but K is {K.shape[0]}x{K.shape[1]}"
        )
    return _solve_checked(K, F, _SINGULAR_MSG)


def rod_loads(asm: Assembled, U: np.ndarray) -> np.ndarray:
    """`P = -K_d Ghat^T U`. Positive is TENSION.

    Accepts a single `U` or a stack of columns, returning `(N,)` or
    `(N, n_cases)` to match.
    """
    U = np.asarray(U, dtype=float)
    if U.shape[0] != asm.n_dof:
        raise ValueError(f"U has {U.shape[0]} rows but n_dof is {asm.n_dof}")
    if U.ndim == 1:
        return -asm.k_d * (asm.G_hat.T @ U)
    return -asm.k_d[:, None] * (asm.G_hat.T @ U)


def elongations(asm: Assembled, U: np.ndarray) -> np.ndarray:
    """`delta = -Ghat^T U`. Positive is stretch, so `P = k_d * delta`."""
    U = np.asarray(U, dtype=float)
    return -(asm.G_hat.T @ U)


def influence(asm: Assembled) -> np.ndarray:
    """`G = -K_d Ghat^T K^-1`, shape (N, n_dof), so that `P = G F`.

    This is the object the orientation sweep is built on: with `T = G W`, every
    load direction is a single matrix product. Computed with one multi-RHS
    solve rather than an explicit inverse, and without assuming K is exactly
    symmetric.
    """
    # A singular K makes `K^T X = Ghat` CONSISTENT (range(Ghat) == range(K)),
    # so the residual check inside _solve_checked cannot see the problem — it
    # would return one of infinitely many influence matrices. Rank first.
    asm.assert_nonsingular()
    Kt_inv_G = _solve_checked(
        asm.K.T,
        asm.G_hat,
        "K is singular, so no load influence matrix exists: the layout permits "
        "a rigid-body motion. Run the mechanism checks.",
    )
    return -asm.k_d[:, None] * Kt_inv_G.T


def equilibrium_residual(asm: Assembled, P: np.ndarray, F: np.ndarray) -> np.ndarray:
    """`Ghat P + F`, which must be zero. Exposed because it is the cheapest
    end-to-end check on the whole chain and belongs in the report page."""
    return asm.G_hat @ np.asarray(P, dtype=float) + np.asarray(F, dtype=float)


__all__ = [
    "SingularAssemblyError",
    "Assembled",
    "rod_stiffness",
    "assemble",
    "solve",
    "rod_loads",
    "elongations",
    "influence",
    "equilibrium_residual",
]
