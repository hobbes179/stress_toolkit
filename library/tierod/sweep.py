"""
Load orientation sweep (build prompt §7).

Pure numpy. **Never imports Streamlit.**

The design target is robustness across a full sweep of load orientations, and
that sweep has a **closed form — do not sample the sphere.**

    W       = vstack over free bodies of  m_p G_p [I3 ; [R cg_p]x]     (n_dof, 3)
    G       = -K_d Ghat^T K^-1                                          (N, n_dof)
    T       = G W                                                       (N, 3)

    F(n_hat) = W n_hat      is LINEAR in n_hat, so
    P(n_hat) = T n_hat      is too, and with ||n_hat|| = 1:

    max |P_i| = || row_i(T) ||_2      at   n_hat*_i = row_i(T) / || row_i(T) ||_2

One matrix product and one row norm per rod. No discretization error. `n_hat*_i`
is the diagnostic that tells the engineer *why* a rod governs.

The enumerated direction set (`cases.cube26` by default) is a readable SAMPLE of
that sphere for the case table — it can only under-predict the closed form,
never exceed it. `label_directions` names each rod's true worst direction with
the nearest enumerated case and the angle to it, so the shortfall of the
sampling is visible rather than hidden.

Two consequences worth stating outright:

* **Both senses reach full magnitude.** `-n_hat*_i` is a unit direction too, so
  a symmetric sweep drives every rod to `+||t||` AND `-||t||` and only
  `min(P_tension_allow, P_comp_allow)` matters. For tie rods that is almost
  always compression: a full-sweep design is a buckling-driven design.
* **`P_comp_allow` depends on `L`, which is a design variable.** The margin
  therefore moves when a rod end moves, in both the load and the allowable.

Rod mask
--------
`active_rods` removes rods from the solve by DELETING COLUMNS of `Ghat` and
rebuilding `K` — it never re-assembles from geometry. That keeps a failure
state a parameter rather than a rewrite, which is what Phase 3 needs, and it
keeps `L_c` pinned to the geometry so rank checks stay comparable across
failure states.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from library.tierod import allowables as al
from library.tierod.cases import (
    LoadCase,
    direction_matrix,
    generate_cases,
    nearest_case,
)
from library.tierod.kernel import Assembled, assemble, influence
from library.tierod.model import Assembly

__all__ = [
    "Envelope",
    "RodResult",
    "SweepResult",
    "mask_assembled",
    "transfer_matrix",
    "case_loads",
    "envelope",
    "label_directions",
    "run_sweep",
]

_ZERO_TOL = 1e-12


# ----------------------------------------------------------------------
# Rod mask — column deletion, not re-assembly
# ----------------------------------------------------------------------


def mask_assembled(asm: Assembled, active_rods) -> Assembled:
    """An `Assembled` restricted to `active_rods`, in the original rod order.

    A failure state is the removal of a rod's constraint, which is exactly the
    deletion of its column from `Ghat`; every other quantity that depends only
    on geometry — the body order, the datums, the characteristic length — is
    unchanged and is carried straight through. Recomputing `L_c` from the
    surviving rods would make each failure state's rank check scaled
    differently from the intact one.
    """
    active = list(active_rods)
    unknown = [r for r in active if r not in asm.rod_ids]
    if unknown:
        raise KeyError(f"unknown rod ids in the mask: {unknown}")
    if not active:
        raise ValueError("the rod mask is empty: nothing is holding the assembly")

    keep = [j for j, rid in enumerate(asm.rod_ids) if rid in set(active)]
    idx = np.array(keep, dtype=int)

    G_hat = asm.G_hat[:, idx]
    k_d = asm.k_d[idx]
    K = (G_hat * k_d) @ G_hat.T
    K = 0.5 * (K + K.T)

    return replace(
        asm,
        G_hat=G_hat,
        k_d=k_d,
        K=K,
        rod_ids=[asm.rod_ids[j] for j in keep],
        lengths=asm.lengths[idx],
        units=asm.units[:, idx],
        points_a=asm.points_a[:, idx],
        points_b=asm.points_b[:, idx],
        rod_body_a=[asm.rod_body_a[j] for j in keep],
        rod_body_b=[asm.rod_body_b[j] for j in keep],
    )


# ----------------------------------------------------------------------
# The transfer matrix
# ----------------------------------------------------------------------


def transfer_matrix(assembly: Assembly, asm: Assembled | None = None,
                    active_rods=None) -> np.ndarray:
    """`T = G W`, shape (N, 3): rod load per unit load direction.

    Raises `SingularAssemblyError` (from `influence`) when the layout — or the
    layout minus the masked rods — is a mechanism. A mechanism has no influence
    matrix, so there is nothing honest to return.
    """
    if asm is None:
        asm = assemble(assembly)
    if active_rods is not None:
        asm = mask_assembled(asm, active_rods)
    W = assembly.sweep_map()
    if asm.n_dof == 0:
        return np.zeros((asm.n_rods, 3))
    return influence(asm) @ W


def case_loads(T: np.ndarray, cases: list[LoadCase]) -> np.ndarray:
    """`(N, n_cases)` rod loads for the enumerated set, in one matmul.

    Case `factor` scales the load; the direction stays a unit vector.
    """
    return np.asarray(T, dtype=float) @ direction_matrix(cases, weighted=True)


# ----------------------------------------------------------------------
# The closed-form envelope
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Envelope:
    """Per-rod worst case over ALL orientations.

    `magnitudes[i] = ||row_i(T)||_2` is reachable in both senses;
    `directions[:, i]` is the unit direction that produces `+magnitudes[i]`.
    """

    magnitudes: np.ndarray      # (N,)
    directions: np.ndarray      # (3, N), unit columns


def envelope(T: np.ndarray, factor: float = 1.0) -> Envelope:
    """Row norms and their directions, scaled by the load factor.

    `factor` matters and is easy to drop: the closed form is a property of the
    UNIT sphere, so nothing about `T` knows that the cases carry a factor. An
    unscaled envelope silently reports every margin at factor 1.0 while the
    enumerated case table shows the scaled loads — the two disagree and the
    margins are the unconservative half.

    A rod that carries no load has a zero row and therefore no worst
    direction. It gets a placeholder unit vector rather than a NaN one — a NaN
    here would propagate straight into `nearest_case` and the cone glyph.
    """
    T = np.asarray(T, dtype=float)
    raw = np.linalg.norm(T, axis=1)
    mags = float(factor) * raw
    dirs = np.zeros((3, T.shape[0]))
    scale = np.where(raw > _ZERO_TOL, raw, 1.0)
    dirs[:] = (T / scale[:, None]).T
    dead = raw <= _ZERO_TOL
    if np.any(dead):
        dirs[:, dead] = np.array([0.0, 0.0, 1.0])[:, None]
    return Envelope(magnitudes=mags, directions=dirs)


def label_directions(env: Envelope, cases: list[LoadCase]) -> list[tuple[str, float]]:
    """`[(nearest case name, angle in degrees)]`, one per rod.

    The angle is the honest measure of how well the enumerated set covers that
    rod's actual worst case. cube26's worst gap is 27.6 degrees, which is an
    11% under-prediction — cite the closed form, label it with the name.
    """
    return [
        (lambda pair: (pair[0].name, pair[1]))(
            nearest_case(cases, env.directions[:, i])
        )
        for i in range(env.magnitudes.size)
    ]


# ----------------------------------------------------------------------
# The reportable result
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class RodResult:
    """One row of the results table."""

    rod_id: str
    L: float
    P_envelope: float           # closed form, ||t||_2 — the governing value
    P_enumerated: float         # max |P| over the enumerated set (a sample)
    worst_direction: np.ndarray
    nearest_case: str
    nearest_case_angle: float
    governing_case: str         # enumerated case producing P_enumerated
    sense: str                  # 'T' or 'C' — the weaker side
    allowable: float | None
    allowable_source: str
    load_ratio: float | None
    margin: float | None
    column: al.ColumnState

    @property
    def sample_shortfall(self) -> float:
        """How much the enumerated set under-predicts, as a fraction."""
        if self.P_envelope <= _ZERO_TOL:
            return 0.0
        return 1.0 - self.P_enumerated / self.P_envelope


@dataclass(frozen=True)
class SweepResult:
    rod_ids: list[str]
    cases: list[LoadCase]
    T: np.ndarray
    P_cases: np.ndarray
    env: Envelope
    rows: list[RodResult]                       # sorted, worst load ratio first
    factors: al.SafetyFactors
    envelope_factor: float = 1.0                # max case factor, applied to ||t||
    # Rods whose reported margin does NOT cover every limit state: no tension
    # source (§6.1), or not even characterizable as a column. A compression-only
    # margin looks exactly like a complete one in a table, so it gets named.
    incomplete_rods: list[str] = field(default_factory=list)

    @property
    def governing_row(self) -> RodResult | None:
        return self.rows[0] if self.rows else None

    def load_ratios(self) -> dict[str, float | None]:
        """`{rod_id: LR}` — the scene's colouring input."""
        return {r.rod_id: r.load_ratio for r in self.rows}

    def row(self, rod_id: str) -> RodResult:
        for r in self.rows:
            if r.rod_id == rod_id:
                return r
        raise KeyError(f"no result for rod {rod_id!r}")


def _sort_key(row: RodResult):
    """Worst first. Rods with no computable ratio sort last, not first — an
    unknown is not a failure, and burying the real governing rod under
    incomplete data would be the worse error."""
    return (0, -row.load_ratio) if row.load_ratio is not None else (1, 0.0)


def run_sweep(
    assembly: Assembly,
    cases: list[LoadCase] | None = None,
    factors: al.SafetyFactors | None = None,
    active_rods=None,
    asm: Assembled | None = None,
) -> SweepResult:
    """Full orientation sweep with allowables and margins.

    The governing value per rod is the **closed form** `||t_i||_2`, not the
    enumerated maximum. The enumerated set is carried alongside for the case
    table and for the "nearest named direction" label.

    Because the envelope is reachable in both senses, each rod is checked
    against the weaker of its tension and compression allowables
    (`two_sided_load_ratio`).
    """
    cases = list(cases) if cases is not None else generate_cases()
    factors = factors or al.SafetyFactors()

    if asm is None:
        asm = assemble(assembly)
    if active_rods is not None:
        asm = mask_assembled(asm, active_rods)

    T = transfer_matrix(assembly, asm=asm)
    P_cases = case_loads(T, cases)
    # The envelope is over the unit sphere, so the case factor has to be
    # applied explicitly. Taking the max is the conservative reading of a
    # mixed-factor set: the worst direction is available at the worst factor.
    envelope_factor = max((c.factor for c in cases), default=1.0)
    env = envelope(T, factor=envelope_factor)
    labels = label_directions(env, cases) if cases else []

    rows: list[RodResult] = []
    incomplete: list[str] = []
    for i, rod_id in enumerate(asm.rod_ids):
        rod = assembly.rods[rod_id]
        L = float(asm.lengths[i])
        try:
            ra = al.rod_allowables(rod, L)
        except ValueError:
            # The rod cannot even be characterized as a column — no Fcy, no I.
            # Report it; do not drop it, and do not invent an allowable.
            incomplete.append(rod_id)
            continue

        lr = al.two_sided_load_ratio(env.magnitudes[i], ra, factors)
        # A rod with no tension source still produces a margin — off the
        # compression side alone, because Fcy is required and A*Fcy always
        # exists. That margin is not wrong, it is INCOMPLETE, and the two look
        # identical in a table. Name the rod instead.
        if not ra.tension_ult.available:
            incomplete.append(rod_id)

        if P_cases.shape[1]:
            j = int(np.argmax(np.abs(P_cases[i])))
            enumerated, governing_case = float(abs(P_cases[i, j])), cases[j].name
        else:
            enumerated, governing_case = 0.0, ""

        name, angle = labels[i] if labels else ("", 0.0)
        rows.append(
            RodResult(
                rod_id=rod_id,
                L=L,
                P_envelope=float(env.magnitudes[i]),
                P_enumerated=enumerated,
                worst_direction=env.directions[:, i].copy(),
                nearest_case=name,
                nearest_case_angle=angle,
                governing_case=governing_case,
                sense=lr.sense,
                allowable=lr.allowable,
                allowable_source=lr.source,
                load_ratio=lr.value,
                margin=lr.margin,
                column=ra.column,
            )
        )

    rows.sort(key=_sort_key)
    return SweepResult(
        rod_ids=list(asm.rod_ids),
        cases=cases,
        T=T,
        P_cases=P_cases,
        env=env,
        rows=rows,
        factors=factors,
        envelope_factor=envelope_factor,
        incomplete_rods=incomplete,
    )
