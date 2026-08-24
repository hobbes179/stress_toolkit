"""
Feasibility and scoring for a tie-rod layout.

Pure numpy. **Never imports Streamlit.**

This module answers the question the tool is actually for: *"here is what we
need to hold down, here is where we have room to mount — where do we tie it,
with the fewest members, to work and be fail-safe?"* Margins are a **gate**
here, not the goal. The goal is a layout that is stable, single-failure
tolerant, and made of stubby rods.

Why slenderness and not length
------------------------------
Length alone is section-blind. Buckling responds to `lambda = L / (rho sqrt c)`,
and `lambda_crit = pi sqrt(2E/Fcy)` is a KNEE rather than a slope:

    lambda <= lambda_crit   Johnson  — allowable near material yield;
                                       the rod is barely buckling limited
    lambda >  lambda_crit   Euler    — allowable falls as 1/lambda^2

So "get every rod under the knee" is the real target, and `n_euler` is the
headline the objective drives toward zero. Expressing it in `lambda` also makes
"use a fatter section" and "use a shorter rod" the same currency, which is what
lets the rod pool and the geometry be optimized together.

Why rho^2 and not N re-solves
-----------------------------
`rho_j^2` is rod j's share of the self-stress space — the diagonal of the
projector onto `null(Ghat)` on the ROD-index side. It obeys

    rho_j^2 > 0   <=>   rod j can be lost without creating a mechanism

so ONE svd replaces N rank re-solves for the structural half of fail-safe. It
is invariant to row scaling, hence independent of the characteristic length.
`sum(rho^2) = N - rank` is the degree of redundancy. A statically determinate
layout has `rho^2 = 0` everywhere: every rod critical, no fail-safe path, no
matter how good the margins look.

The strength half — do the survivors still close their margins — does need the
re-solves, and `check_failsafe` runs them. Screen with `layout_metrics` and
`feasible` first: they cost one assemble and one svd.

Counting bounds (hard, and worth surfacing before anyone sizes anything)
------------------------------------------------------------------------
    N >= 6 n_free       no mechanism
    N >= 6 n_free + 1   survive any single loss

At exactly `6 n_free + 1` the self-stress space is one-dimensional, so the
layout is fail-safe only if that single state involves EVERY rod.

The short-rod cliff
-------------------
Short rods mean small moment arms mean nothing reacting moments. A
length-hungry search will happily drive a layout off that cliff, so
`sigma_floor` is a hard constraint here and not a diagnostic. On the shipped
demo geometry: pulling every attachment to one height gives max lambda 60 —
excellent — and rank 6 of 12, a mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from library.tierod import allowables as al
from library.tierod import clash
from library.tierod import sweep as sw
from library.tierod.cases import LoadCase, generate_cases
from library.tierod.kernel import Assembled, SingularAssemblyError, assemble
from library.tierod.model import Assembly

__all__ = [
    "RHO_TOL",
    "Redundancy",
    "LayoutMetrics",
    "MIN_GAP_DEFAULT",
    "Criteria",
    "Verdict",
    "FailureState",
    "FailSafeReport",
    "min_rods_for_mechanism_free",
    "min_rods_for_single_failure",
    "self_stress",
    "layout_metrics",
    "feasible",
    "objective",
    "check_failsafe",
]

RHO_TOL = 1e-9
_INFEASIBLE = float("inf")


# ----------------------------------------------------------------------
# Counting bounds
# ----------------------------------------------------------------------


def min_rods_for_mechanism_free(n_free: int) -> int:
    """`6 n_free` — the determinate floor. At exactly this count every rod is
    critical by construction."""
    return 6 * n_free


def min_rods_for_single_failure(n_free: int) -> int:
    """`6 n_free + 1`. Necessary, not sufficient: the one self-stress state at
    that count must involve every rod."""
    return 6 * n_free + 1


# ----------------------------------------------------------------------
# Self-stress redundancy
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Redundancy:
    rod_ids: list[str]
    rho2: np.ndarray            # (N,) share of the self-stress space per rod
    total: float                # == N - rank, the degree of redundancy

    @property
    def critical(self) -> list[str]:
        """Rods whose loss creates a mechanism. Empty is the goal."""
        return [r for r, v in zip(self.rod_ids, self.rho2) if v <= RHO_TOL]

    @property
    def any_redundancy(self) -> bool:
        return self.total > RHO_TOL

    @property
    def spread(self) -> float:
        """Max minus min rho^2. Zero means the redundant duty is shared
        evenly — a design target in itself, since a near-zero rho^2 on one rod
        is a fail-safe path that exists only on paper."""
        if self.rho2.size == 0:
            return 0.0
        return float(self.rho2.max() - self.rho2.min())


def _spectrum(G: np.ndarray, n_rods: int) -> tuple[np.ndarray, np.ndarray, int]:
    """`(singular values, rho2, rank)` from ONE decomposition.

    Both numbers come out of the same SVD. Taking them separately — as an
    earlier version did, calling `self_stress` and `screw_singular_values`
    back to back — decomposes the same matrix twice and rebuilds the
    non-dimensionalized copy twice with it. That is the inner loop of the
    layout search, so it is worth doing once.
    """
    if G.size == 0:
        return np.zeros(0), np.zeros(n_rods), 0
    _, s, Vt = np.linalg.svd(G, full_matrices=True)
    tol = 1e-9 * (s[0] if s.size else 1.0)
    rank = int(np.count_nonzero(s > tol))
    V = Vt[rank:].T                       # (N, N - rank) self-stress basis
    rho2 = np.einsum("ij,ij->i", V, V) if V.size else np.zeros(n_rods)
    return s, rho2, rank


def self_stress(asm: Assembled, nondimensional: bool = True) -> Redundancy:
    """Per-rod self-stress redundancy from one SVD.

    `nondimensional` selects which form of Ghat to decompose. It changes
    nothing — row scaling cannot move a null space on the column-index side —
    and the test asserts that, because a fail-safe verdict that depended on the
    characteristic length would be a bookkeeping artefact.
    """
    G = asm.nondim_screws() if nondimensional else asm.G_hat
    _, rho2, rank = _spectrum(G, asm.n_rods)
    return Redundancy(list(asm.rod_ids), rho2, float(asm.n_rods - rank))


# ----------------------------------------------------------------------
# The cheap score: geometry, conditioning, slenderness, redundancy
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class LayoutMetrics:
    """Everything judgeable about a layout without applying a load.

    One assemble plus one SVD, so a search can afford this on every candidate
    and reserve the load sweep for the survivors.
    """

    n_rods: int
    n_free: int
    n_dof: int
    rank: int
    sigma_min: float
    lengths: np.ndarray
    lambdas: np.ndarray
    lambda_crit: float
    rho2: np.ndarray
    rod_ids: list[str] = field(default_factory=list)

    #: Worst clearance shortfall in inches, or **None meaning NOT CHECKED**.
    #: The distinction matters: 0.0 is a positive statement that nothing
    #: interferes, None is the absence of a statement, and a gate that treats
    #: them alike would pass clashing layouts in silence.
    worst_clash: float | None = None
    clashes: tuple = ()

    # -- mechanism ------------------------------------------------------

    @property
    def is_mechanism(self) -> bool:
        return self.rank < self.n_dof

    @property
    def nullity(self) -> int:
        return self.n_dof - self.rank

    # -- slenderness ----------------------------------------------------

    @property
    def max_length(self) -> float:
        return float(self.lengths.max()) if self.lengths.size else 0.0

    @property
    def total_length(self) -> float:
        return float(self.lengths.sum())

    @property
    def max_lambda(self) -> float:
        return float(self.lambdas.max()) if self.lambdas.size else 0.0

    @property
    def n_euler(self) -> int:
        """Rods past the buckling knee — the count the objective drives down."""
        return int(np.count_nonzero(self.lambdas > self.lambda_crit))

    @property
    def euler_fraction(self) -> float:
        return self.n_euler / self.n_rods if self.n_rods else 0.0

    # -- redundancy -----------------------------------------------------

    @property
    def rho2_min(self) -> float:
        return float(self.rho2.min()) if self.rho2.size else 0.0

    @property
    def redundancy(self) -> float:
        return float(self.rho2.sum())

    @property
    def critical(self) -> list[str]:
        return [r for r, v in zip(self.rod_ids, self.rho2) if v <= RHO_TOL]

    @property
    def survives_single_loss(self) -> bool:
        return not self.is_mechanism and self.rho2_min > RHO_TOL

    @property
    def interferes(self) -> bool:
        """True only when clearance was checked AND something clashes."""
        return self.worst_clash is not None and self.worst_clash > 0.0


def layout_metrics(assembly: Assembly, asm: Assembled | None = None,
                   min_gap: float | None = clash.MIN_GAP_DEFAULT) -> LayoutMetrics:
    """Score a candidate layout. Never raises on a mechanism — a search
    generates those constantly and needs them ranked last, not fatal.

    `min_gap` controls the physical-interference check and defaults to the
    same value `Criteria` does, so the natural `feasible(layout_metrics(a))`
    is checked. Interference costs about as much again as everything else
    here; pass `min_gap=None` to skip it, which is then a DELIBERATE choice
    rather than something that happens by forgetting an argument. `feasible`
    raises if criteria demand a gap the metrics never measured.
    """
    if asm is None:
        asm = assemble(assembly)
    s, rho2, rank = _spectrum(asm.nondim_screws(), asm.n_rods)

    report = (None if min_gap is None
              else clash.check_clearance(assembly, min_gap=float(min_gap)))

    lambdas = np.zeros(asm.n_rods)
    crits = []
    for j, rod_id in enumerate(asm.rod_ids):
        rod = assembly.rods[rod_id]
        try:
            state = al.column_state(rod, float(asm.lengths[j]))
        except ValueError:
            # Not characterizable as a column (no I, no Fcy). Rank it worst
            # rather than dropping it: an unscoreable rod is not a good rod.
            lambdas[j] = np.inf
            continue
        lambdas[j] = state.lam
        crits.append(state.lam_crit)

    return LayoutMetrics(
        n_rods=asm.n_rods,
        n_free=asm.n_free,
        n_dof=asm.n_dof,
        rank=rank,
        # sigma_min is the SMALLEST singular value that a full-rank layout would
        # need, i.e. the n_dof-th — not `s[-1]`, which for a redundant layout is
        # a null-space value and identically zero.
        sigma_min=float(s[asm.n_dof - 1]) if s.size >= asm.n_dof > 0 else 0.0,
        lengths=asm.lengths.copy(),
        lambdas=lambdas,
        lambda_crit=float(np.min(crits)) if crits else float("inf"),
        rho2=rho2,
        rod_ids=list(asm.rod_ids),
        worst_clash=None if min_gap is None else report.worst_shortfall,
        clashes=() if min_gap is None else report.clashes,
    )


# ----------------------------------------------------------------------
# Feasibility
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Criteria:
    """The feasibility gate. Every number is a user input with a default —
    none of them is hardcoded at a call site.

    `damaged_factors` defaults to an ULTIMATE factor of 1.0 because the usual
    fail-safe statement is "survive limit load with any one member gone", which
    is a different check from the intact ultimate case, not a rerun of it.
    """

    sigma_floor: float = 0.05
    ms_required: float = 0.0
    ms_required_damaged: float = 0.0
    intact_factors: al.SafetyFactors = al.SafetyFactors()
    damaged_factors: al.SafetyFactors = al.SafetyFactors(ultimate=1.0, yield_=1.0)
    damaged_load_factor: float = 1.0
    require_single_failure: bool = True
    max_lambda: float | None = None        # optional hard slenderness cap

    #: Minimum clearance between things that are not bolted together, inches.
    #: `None` switches the interference check off entirely — which is a
    #: deliberate choice a caller has to make, not something that can happen by
    #: forgetting to pass a number.
    min_gap: float | None = clash.MIN_GAP_DEFAULT


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reasons: list[str]          # empty when ok; each one actionable


def feasible(metrics: LayoutMetrics, criteria: Criteria | None = None) -> Verdict:
    """The cheap screen — no load sweep. Reasons name the shortfall and, where
    there is one, the number that would fix it."""
    criteria = criteria or Criteria()
    reasons: list[str] = []

    if metrics.is_mechanism:
        reasons.append(
            f"mechanism: rank {metrics.rank} of {metrics.n_dof} DOF, so "
            f"{metrics.nullity} rigid-body motion(s) are unrestrained"
        )
    elif metrics.sigma_min < criteria.sigma_floor:
        # Deliberately a different vocabulary from the rank failure above:
        # "mechanism" means rank-deficient and nothing else, so a reason can be
        # matched on unambiguously.
        reasons.append(
            f"conditioning: sigma_min {metrics.sigma_min:.4f} is below the "
            f"floor {criteria.sigma_floor:.4f} — full rank, but fragile"
        )

    if criteria.require_single_failure:
        need = min_rods_for_single_failure(metrics.n_free)
        if metrics.n_rods < need:
            reasons.append(
                f"too few rods for single-failure tolerance: {metrics.n_rods} "
                f"present, {need} needed (6 x {metrics.n_free} + 1)"
            )
        elif metrics.critical:
            reasons.append(
                f"critical rod(s) {metrics.critical}: losing any one creates a "
                f"mechanism (rho^2 = 0). {metrics.n_rods} rods present, "
                f"{need} is the minimum that can be fail-safe"
            )

    if criteria.min_gap is not None and metrics.worst_clash is None:
        # The dangerous silence: criteria demand clearance, metrics never
        # measured it, and a gate that shrugged here would hand back layouts
        # with rods through tanks. Loud, because it is a wiring error.
        raise ValueError(
            "criteria require a clearance check (min_gap="
            f"{criteria.min_gap}) but these metrics were computed without one. "
            "Pass min_gap=criteria.min_gap to layout_metrics()."
        )

    # `criteria.min_gap is None` means the caller switched interference off.
    # Metrics computed WITH a check must then not be gated on it, or turning
    # the check off in criteria would have no effect whenever the metrics
    # happened to measure it anyway.
    if criteria.min_gap is not None and metrics.interferes:
        worst = min(metrics.clashes, key=lambda c: c.gap)
        reasons.append(
            f"interference: {worst.message()} "
            f"({len(metrics.clashes)} clashing pair(s) in total)"
        )

    if criteria.max_lambda is not None and metrics.max_lambda > criteria.max_lambda:
        reasons.append(
            f"slenderness: max lambda {metrics.max_lambda:.0f} exceeds the cap "
            f"{criteria.max_lambda:.0f}"
        )

    return Verdict(ok=not reasons, reasons=reasons)


def objective(metrics: LayoutMetrics, criteria: Criteria | None = None) -> tuple:
    """What a layout search minimizes, lexicographically:

        (max lambda, total length, rod count)

    Slenderness first because it sets buckling performance and therefore the
    section every group needs; total length second as the cost and weight
    tiebreaker; count last because two layouts rarely tie on the first two.

    An infeasible layout returns `inf` in the leading slot, so it can never
    outrank a feasible one however short its rods are.
    """
    if not feasible(metrics, criteria).ok:
        return (_INFEASIBLE, _INFEASIBLE, metrics.n_rods)
    return (metrics.max_lambda, metrics.total_length, metrics.n_rods)


# ----------------------------------------------------------------------
# The strength half — one re-solve per failure state
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class FailureState:
    removed: str                # 'leg0' or 'leg0+brace0'
    ok: bool                    # still solvable, i.e. not a mechanism
    rank: int
    worst_rod: str | None = None
    worst_margin: float | None = None
    note: str = ""


@dataclass(frozen=True)
class FailSafeReport:
    rod_ids: list[str]
    metrics: LayoutMetrics
    states: list[FailureState]
    criteria: Criteria
    intact_worst_margin: float | None
    intact_worst_rod: str | None

    @property
    def n_critical(self) -> int:
        return len(self.metrics.critical)

    @property
    def damaged_worst_margin(self) -> float | None:
        got = [s.worst_margin for s in self.states if s.worst_margin is not None]
        return min(got) if got else None

    @property
    def ok(self) -> bool:
        if not feasible(self.metrics, self.criteria).ok:
            return False
        if self.intact_worst_margin is None:
            return False
        if self.intact_worst_margin < self.criteria.ms_required:
            return False
        if not all(s.ok for s in self.states):
            return False
        worst = self.damaged_worst_margin
        return worst is not None and worst >= self.criteria.ms_required_damaged

    @property
    def summary(self) -> str:
        if self.metrics.is_mechanism:
            return "The intact layout is already a mechanism."
        if self.n_critical == self.metrics.n_rods and self.metrics.n_rods:
            return (
                f"Statically determinate: all {self.metrics.n_rods} rods are "
                f"critical, so no single-failure path exists at any load. "
                f"{min_rods_for_single_failure(self.metrics.n_free)} rods is "
                f"the minimum that could be fail-safe."
            )
        if self.n_critical:
            return f"{self.n_critical} critical rod(s): {self.metrics.critical}."
        if self.ok:
            return (
                f"Fail-safe: survives the loss of any one rod with margin "
                f"{self.damaged_worst_margin:+.3f} at a load factor of "
                f"{self.criteria.damaged_load_factor:g}."
            )
        return "Structurally single-failure tolerant, but a damaged case has no margin."


def _worst(result: sw.SweepResult) -> tuple[str | None, float | None]:
    rows = [r for r in result.rows if r.margin is not None]
    if not rows:
        return None, None
    row = min(rows, key=lambda r: r.margin)
    return row.rod_id, row.margin


def check_failsafe(
    assembly: Assembly,
    criteria: Criteria | None = None,
    subsets=None,
    cases: list[LoadCase] | None = None,
) -> FailSafeReport:
    """Full check: the cheap screen plus one load sweep per failure state.

    `subsets` is an iterable of rod-id tuples to remove; the default is every
    singleton. Two-rod losses and named groups are the same machinery, so
    Phase 3 widening the damage set is a caller change, not a rewrite.
    """
    criteria = criteria or Criteria()
    asm = assemble(assembly)
    # Pass the criteria's own gap down, so a report cannot be built on metrics
    # that measured interference differently from the criteria judging them.
    metrics = layout_metrics(assembly, asm, min_gap=criteria.min_gap)
    all_rods = list(asm.rod_ids)

    intact_rod = intact_margin = None
    if not metrics.is_mechanism:
        intact = sw.run_sweep(
            assembly, cases=cases, factors=criteria.intact_factors, asm=asm
        )
        intact_rod, intact_margin = _worst(intact)

    damaged_cases = (
        cases if cases is not None
        else generate_cases(factor=criteria.damaged_load_factor)
    )

    states: list[FailureState] = []
    for subset in (subsets if subsets is not None else [(r,) for r in all_rods]):
        subset = (subset,) if isinstance(subset, str) else tuple(subset)
        label = "+".join(subset)
        survivors = [r for r in all_rods if r not in set(subset)]
        try:
            damaged = sw.run_sweep(
                assembly,
                cases=damaged_cases,
                factors=criteria.damaged_factors,
                active_rods=survivors,
                asm=asm,
            )
        except (SingularAssemblyError, ValueError) as exc:
            states.append(
                FailureState(
                    removed=label, ok=False,
                    rank=sw.mask_assembled(asm, survivors).rank if survivors else 0,
                    note=str(exc).split(".")[0],
                )
            )
            continue
        rod, margin = _worst(damaged)
        states.append(
            FailureState(removed=label, ok=True, rank=metrics.rank,
                         worst_rod=rod, worst_margin=margin)
        )

    return FailSafeReport(
        rod_ids=all_rods,
        metrics=metrics,
        states=states,
        criteria=criteria,
        intact_worst_margin=intact_margin,
        intact_worst_rod=intact_rod,
    )
