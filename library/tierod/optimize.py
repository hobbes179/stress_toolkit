"""
Layout search — propose rod layouts, do not merely score them.

Pure numpy + scipy. **Never imports Streamlit.**

The user declares what is being held down and where there is room to mount.
This module answers *where to tie it*:

    seed  ->  refine  ->  score  ->  rank

**Seeding.** Symmetric families first, random draws second. On the demo
geometry a coarse symmetric grid beat 4000 random draws by 2.6x on the
objective — but at one rod count the symmetric family found nothing feasible
while a random draw did. Neither strategy is sufficient alone, and neither is
sufficient without local refinement on top.

**Refinement** minimizes a smooth surrogate, not the real objective. The real
one is lexicographic `(max lambda, sum L, N)` behind a hard feasibility gate:
`max` has no gradient and the gate is a cliff, so a gradient method cannot see
across either. The surrogate is a p-norm softmax of the slenderness plus
penalties that grow as the conditioning floor and the criticality floor are
approached. The true objective ranks the results; it never steers them.

**Why slenderness.** `lambda_crit` is a knee: below it a rod is on the Johnson
branch and barely buckling limited, above it the allowable dies as
`1/lambda^2`. Driving `max lambda` down is what buys compression capability,
and it is also the currency in which "shorter rod" and "fatter section" are
comparable.

Two traps this module is shaped around
--------------------------------------
* **The short-rod cliff.** Shorter rods mean smaller moment arms mean nothing
  reacting moments. On the demo geometry, pulling every attachment to one
  height gives an excellent max lambda of 60 and rank 6 of 12 — a mechanism.
  `sigma_floor` is therefore a penalty during refinement AND a hard gate
  afterwards, never just a diagnostic.
* **Topology raises the counting floor.** `N >= 6 n_free + 1` is global, but
  the offered region pairs can demand more: with only tank->plate rods and no
  tank-to-tank pairing, each tank needs 7 of its own, so the demo's real floor
  is 14 against a global bound of 13. The search discovers this by failing
  honestly at 13 rather than by being told.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
from scipy.optimize import minimize

from library.tierod import failsafe as fs
from library.tierod.model import (
    DEFAULT_ROD_PROPS,
    Assembly,
    Region,
    new_rod,
)

__all__ = [
    "SOFTMAX_P",
    "LayoutSpace",
    "Candidate",
    "SearchResult",
    "space_from",
    "topology_options",
    "spread_axis",
    "seed_symmetric",
    "seed_random",
    "softmax_lambda",
    "surrogate",
    "refine",
    "search",
    "plan_counts",
    "plan_size",
]

SOFTMAX_P = 8.0
_PENALTY = 10.0
_RHO_TARGET = 0.01        # push rods off the criticality boundary, not onto it


# ----------------------------------------------------------------------
# The declared design space
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class LayoutSpace:
    """Bodies and regions with no rods, plus the region pairs a rod may span.

    Topology stays a user decision: the search picks within what is offered, it
    does not invent access that does not exist.
    """

    template: Assembly
    topologies: list[tuple[str, str]]
    rod_props: dict = field(default_factory=lambda: dict(DEFAULT_ROD_PROPS))

    def restrict(self, topologies) -> "LayoutSpace":
        allowed = [tuple(t) for t in topologies]
        unknown = [t for t in allowed if t not in self.topologies]
        if unknown:
            raise ValueError(f"topologies not offered by this space: {unknown}")
        return replace(self, topologies=allowed)

    def blank(self) -> Assembly:
        """A fresh copy of the template with no rods."""
        from library.tierod import serialize as ser

        return ser.loads(ser.dumps(self.template))


def topology_options(assembly: Assembly) -> list[tuple[str, str]]:
    """Every CROSS-BODY region pair, in a stable order.

    Same-body pairs are excluded because such a rod contributes a column of
    exactly zero: its two blocks cancel in the translation rows, and the moment
    rows carry `(a - b) x u`, which vanishes because `a - b` is parallel to
    `u`. It is not a weak constraint — it is no constraint at all.
    """
    ids = sorted(assembly.regions)
    out = []
    for i, ra in enumerate(ids):
        for rb in ids[i + 1 :]:
            if assembly.regions[ra].body_id != assembly.regions[rb].body_id:
                out.append((ra, rb))
    return out


def space_from(assembly: Assembly, rod_props: dict | None = None) -> LayoutSpace:
    """Strip the rods off an assembly, keep its bodies and regions."""
    from library.tierod import serialize as ser

    template = ser.loads(ser.dumps(assembly))
    props = dict(rod_props) if rod_props is not None else _props_of(assembly)
    for rod_id in list(template.rods):
        template.remove_rod(rod_id)
    return LayoutSpace(
        template=template, topologies=topology_options(template), rod_props=props
    )


def _props_of(assembly: Assembly) -> dict:
    """Reuse the section+material already in the model, if there is one."""
    if not assembly.rods:
        return dict(DEFAULT_ROD_PROPS)
    rod = next(iter(assembly.rods.values()))
    return {
        name: getattr(rod, name)
        for name in ("E", "A", "I", "Fcy", "Ftu", "Fty", "A_net", "P_tension_allow")
    }


# ----------------------------------------------------------------------
# Seeding
# ----------------------------------------------------------------------


def spread_axis(region: Region, samples: int = 24) -> int:
    """Which parameter to spread rods along: the one with the longest ARC.

    Not the one with the widest bounds, and never the type name. An Annulus
    indexes `(r, theta)` while a CylindricalBand indexes `(theta, z)`, so any
    "parameter 0 is angular" rule is wrong half the time. Measuring path length
    through `point(q)` is type-blind, so a new primitive needs no code here.
    Straight-line lo-to-hi distance would also fail, since a full revolution
    returns to where it started.
    """
    if region.ndim < 2:
        return 0
    q0 = region.q0()
    best, best_len = 0, -1.0
    for axis, (lo, hi) in enumerate(region.bounds()):
        pts = []
        for t in np.linspace(lo, hi, samples):
            q = np.array(q0, dtype=float)
            q[axis] = t
            pts.append(region.point(q))
        length = float(np.sum(np.linalg.norm(np.diff(np.array(pts), axis=0), axis=1)))
        if length > best_len:
            best, best_len = axis, length
    return best


def _alternate_values(region: Region, axis: int, spread) -> tuple[float, float]:
    """Two values of the non-spread parameter, used alternately.

    All attachments at one value is the coplanar trap — on the demo geometry it
    is rank 6 of 12. Alternating by construction keeps the seeder out of it.
    """
    lo, hi = region.bounds()[axis]
    if spread is not None:
        a, b = float(spread[0]), float(spread[1])
        return (min(max(a, lo), hi), min(max(b, lo), hi))
    span = hi - lo
    return (lo + 0.75 * span, lo + 0.25 * span)


def _place(region: Region, k: int, n: int, spread=None,
           offset: float = 0.0) -> np.ndarray:
    """Attachment k of n on this region: evenly spread, alternating, offset.

    `offset` is the TWIST, as a fraction of the spread parameter's range, and
    it is applied to one end only. Without it both ends of every rod land at
    the same angle, every rod lies in a plane through the body axis, and
    nothing reacts rotation about that axis — the layout is a mechanism no
    matter how many rods it has. Every symmetric seed built without a twist on
    the demo geometry came out with sigma_min exactly 0.
    """
    if region.ndim == 0:
        return np.zeros(0)
    q = region.q0()
    axis = spread_axis(region)
    lo, hi = region.bounds()[axis]
    q[axis] = lo + (hi - lo) * (((k + 0.5) / n + offset) % 1.0)
    if region.ndim >= 2:
        other = 1 - axis
        hi_v, lo_v = _alternate_values(region, other, spread)
        q[other] = hi_v if k % 2 == 0 else lo_v
    return q


def _distribute(n: int, n_topologies: int) -> list[int]:
    """Rods per topology, as even as the count allows."""
    base, extra = divmod(n, n_topologies)
    return [base + (1 if i < extra else 0) for i in range(n_topologies)]


def seed_symmetric(space: LayoutSpace, n: int, spread=None,
                   twist: float = 0.25) -> Assembly:
    """`n` rods spread evenly over the offered topologies, alternating.

    `twist` offsets the 'b' end's spread parameter relative to the 'a' end, as
    a fraction of its range. It defaults to a quarter turn rather than zero
    because zero is degenerate — see `_place`.
    """
    layout = space.blank()
    counts = _distribute(n, len(space.topologies))
    idx = 0
    for (ra, rb), count in zip(space.topologies, counts):
        for k in range(count):
            layout.add_rod(
                new_rod(
                    layout, id=f"r{idx:02d}", region_a=ra, region_b=rb,
                    q_a=_place(layout.regions[ra], k, count, spread),
                    q_b=_place(layout.regions[rb], k, count, spread, offset=twist),
                    **space.rod_props,
                )
            )
            idx += 1
    return layout


def seed_random(space: LayoutSpace, n: int, rng: np.random.Generator) -> Assembly:
    """`n` rods at uniformly random points in the declared regions."""
    layout = space.blank()
    counts = _distribute(n, len(space.topologies))
    idx = 0
    for (ra, rb), count in zip(space.topologies, counts):
        for _ in range(count):
            layout.add_rod(
                new_rod(
                    layout, id=f"r{idx:02d}", region_a=ra, region_b=rb,
                    q_a=_uniform(layout.regions[ra], rng),
                    q_b=_uniform(layout.regions[rb], rng),
                    **space.rod_props,
                )
            )
            idx += 1
    return layout


def _uniform(region: Region, rng: np.random.Generator) -> np.ndarray:
    return np.array([rng.uniform(lo, hi) for lo, hi in region.bounds()])


# ----------------------------------------------------------------------
# The smooth surrogate
# ----------------------------------------------------------------------


def softmax_lambda(lambdas: np.ndarray, p: float = SOFTMAX_P) -> float:
    """`(sum lambda^p)^(1/p)` — a smooth upper bound on `max lambda`.

    The real objective takes a max, which has no gradient at the crossover
    where the governing rod changes; a gradient method stalls or chatters
    there. The p-norm bounds the max from above and converges to it as p grows,
    so minimizing it minimizes the right thing while staying differentiable.
    """
    x = np.asarray(lambdas, dtype=float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return float("inf")
    scale = float(x.max())
    if scale <= 0.0:
        return 0.0
    return scale * float(np.sum((x / scale) ** p) ** (1.0 / p))


def surrogate(metrics: fs.LayoutMetrics, criteria: fs.Criteria) -> float:
    """What refinement actually minimizes.

    Penalties are ADDITIVE and measured in units of `lambda_crit` — the natural
    scale of the objective, since the buckling knee is what the slenderness
    term is trying to reach.

    Two earlier shapes both failed and are worth recording:

    * **Multiplicative on the slenderness** (`penalty * softmax_lambda`) makes
      the objective ~1e3 times larger than the quantity being optimized and
      couples the two terms' gradients. Measured on the demo: f = 6.3e5 with
      gradients of 4e4, and L-BFGS-B stopping after ONE iteration with no
      improvement. Additive keeps a constant violation a constant offset, so
      the gradient comes cleanly from lambda.
    * **`inf` for a mechanism** kills the line search outright. A mechanism has
      `sigma_min = 0`, which already saturates the conditioning penalty, so the
      continuous form covers it and stays differentiable on the way in.
    """
    value = softmax_lambda(metrics.lambdas)
    ref = metrics.lambda_crit if np.isfinite(metrics.lambda_crit) else max(value, 1.0)

    short = max(0.0, 1.0 - metrics.sigma_min / max(criteria.sigma_floor, 1e-12))
    value += _PENALTY * ref * short * short

    if criteria.require_single_failure:
        thin = max(0.0, 1.0 - metrics.rho2_min / _RHO_TARGET)
        value += _PENALTY * ref * thin * thin
    return value


# ----------------------------------------------------------------------
# Local refinement
# ----------------------------------------------------------------------


def refine(assembly: Assembly, criteria: fs.Criteria | None = None,
           max_iter: int = 120) -> Assembly:
    """Improve rod POSITIONS for a fixed count and topology.

    Bounded L-BFGS-B on the design vector, whose box bounds are exactly the
    declared region bounds — so a refined layout is inside the declared space
    by construction, not by a fixup afterwards.

    Never returns something worse than it was given: the result is accepted
    only if the true lexicographic objective improves. A surrogate that
    disagrees with the objective at the margin is a real possibility, and
    silently shipping a worse layout would be the wrong way to find out.
    """
    criteria = criteria or fs.Criteria()
    x0 = assembly.design_vector()
    if x0.size == 0:
        return assembly

    bounds = assembly.design_bounds()
    working = _copy(assembly)

    def f(x: np.ndarray) -> float:
        working.set_design_vector(x)
        try:
            return surrogate(fs.layout_metrics(working), criteria)
        except (ValueError, np.linalg.LinAlgError):
            return float("inf")

    result = minimize(
        f, x0, method="L-BFGS-B", bounds=bounds,
        options={"maxiter": int(max_iter), "eps": 1e-4},
    )

    best = _copy(assembly)
    best.set_design_vector(np.clip(result.x, *_bound_arrays(bounds)))
    if fs.objective(fs.layout_metrics(best), criteria) <= fs.objective(
        fs.layout_metrics(assembly), criteria
    ):
        return best
    return assembly


def _bound_arrays(bounds):
    lo = np.array([b[0] for b in bounds], dtype=float)
    hi = np.array([b[1] for b in bounds], dtype=float)
    return lo, hi


def _copy(assembly: Assembly) -> Assembly:
    from library.tierod import serialize as ser

    return ser.loads(ser.dumps(assembly))


# ----------------------------------------------------------------------
# The search
# ----------------------------------------------------------------------


@dataclass
class Candidate:
    assembly: Assembly
    metrics: fs.LayoutMetrics
    objective: tuple
    n_rods: int
    seed_kind: str

    @property
    def feasible(self) -> bool:
        return self.objective[0] != float("inf")


@dataclass
class SearchResult:
    candidates: list[Candidate]          # ranked, best first
    n_evaluated: int
    criteria: fs.Criteria

    @property
    def feasible_candidates(self) -> list[Candidate]:
        return [c for c in self.candidates if c.feasible]

    @property
    def best(self) -> Candidate | None:
        found = self.feasible_candidates
        return found[0] if found else None

    def best_for(self, n: int) -> Candidate | None:
        found = [c for c in self.feasible_candidates if c.n_rods == n]
        return found[0] if found else None

    def trade_curve(self) -> list[dict]:
        """One row per rod count: what that much complexity buys.

        This is the headline output. "14 rods gets max lambda 198; 16 gets 75"
        answers the complexity question directly, which a margin never does.
        """
        rows = []
        for n in sorted({c.n_rods for c in self.candidates}):
            best = self.best_for(n)
            rows.append(
                {
                    "n_rods": n,
                    "feasible": best is not None,
                    "max_lambda": best.metrics.max_lambda if best else None,
                    "total_length": best.metrics.total_length if best else None,
                    "sigma_min": best.metrics.sigma_min if best else None,
                    "n_euler": best.metrics.n_euler if best else None,
                    "reason": (
                        "" if best
                        else "; ".join(_why_not(self.candidates, n, self.criteria))
                    ),
                }
            )
        return rows


def _why_not(candidates, n: int, criteria) -> list[str]:
    """The best explanation available for a rod count that found nothing."""
    at_n = [c for c in candidates if c.n_rods == n]
    if not at_n:
        return ["not searched"]
    return fs.feasible(at_n[0].metrics, criteria).reasons


def plan_counts(space: LayoutSpace, n_range) -> list[int]:
    """The rod counts `search` will actually visit.

    A count below the number of offered topologies cannot place one rod on
    each path, so it is skipped. Exposed because a caller that quotes a cost
    up front has to skip exactly what the search skips — an estimate that
    re-derives the rule by hand goes stale the moment the rule changes.
    """
    return [n for n in n_range if n >= len(space.topologies)]


def plan_size(space: LayoutSpace, n_range, n_symmetric: int,
              n_random: int) -> int:
    """How many candidates a run with these settings will evaluate."""
    per_n = len(_symmetric_family(max(0, n_symmetric))) + max(0, n_random)
    return per_n * len(plan_counts(space, n_range))


def search(
    space: LayoutSpace,
    criteria: fs.Criteria | None = None,
    n_range=None,
    n_symmetric: int = 6,
    n_random: int = 6,
    max_iter: int = 80,
    rng: np.random.Generator | None = None,
    on_candidate=None,
) -> SearchResult:
    """Seed, refine and rank layouts across a range of rod counts.

    `n_range` defaults to the counting floor through floor + 4. The floor is
    the GLOBAL bound `6 n_free + 1`; the offered topology may demand more, and
    the search discovers that by finding nothing at the lower counts rather
    than by being told.

    `on_candidate(candidate, done, total)` is called after each layout is
    scored, for progress reporting. **An exception from it is swallowed**: a
    run is minutes of work, and losing all of it because a progress bar failed
    would be a bad trade. It reports, it must never steer.
    """
    criteria = criteria or fs.Criteria()
    rng = rng if rng is not None else np.random.default_rng()

    n_free = len([b for b in space.template.bodies.values() if not b.is_ground])
    if n_range is None:
        floor = fs.min_rods_for_single_failure(n_free)
        n_range = range(floor, floor + 5)

    candidates: list[Candidate] = []
    evaluated = 0
    total = plan_size(space, n_range, n_symmetric, n_random)

    for n in plan_counts(space, n_range):
        seeds: list[tuple[str, Assembly]] = []
        for frac, twist in _symmetric_family(max(0, n_symmetric)):
            seeds.append(
                ("symmetric",
                 seed_symmetric(space, n, spread=_spread_pair(space, frac),
                                twist=twist))
            )
        for _ in range(max(0, n_random)):
            seeds.append(("random", seed_random(space, n, rng)))

        for kind, layout in seeds:
            evaluated += 1
            try:
                refined = refine(layout, criteria, max_iter=max_iter)
                metrics = fs.layout_metrics(refined)
            except (ValueError, np.linalg.LinAlgError):
                continue
            candidate = Candidate(
                assembly=refined, metrics=metrics,
                objective=fs.objective(metrics, criteria),
                n_rods=n, seed_kind=kind,
            )
            candidates.append(candidate)
            if on_candidate is not None:
                try:
                    on_candidate(candidate, evaluated, total)
                except Exception:  # noqa: BLE001 — see the docstring
                    pass

    candidates.sort(key=lambda c: c.objective)
    return SearchResult(
        candidates=candidates, n_evaluated=evaluated, criteria=criteria
    )


#: The symmetric family is a grid over two knobs, both of which have
#: degenerate endpoints that must be excluded rather than merely disfavoured:
#:   * spread fraction 0.5 puts every attachment at one height -> coplanar
#:   * twist 0 or 0.5 leaves every rod in a plane through the body axis, so
#:     nothing reacts rotation about it -> sigma_min exactly 0, measured
_SYM_FRACS = (0.60, 0.78, 0.95)
_SYM_TWISTS = (0.10, 0.20, 0.30, 0.40)


def _symmetric_family(count: int) -> list[tuple[float, float]]:
    """`count` members of the (spread, twist) grid, deterministically."""
    combos = [(f, t) for f in _SYM_FRACS for t in _SYM_TWISTS]
    if count <= 0:
        return []
    if count >= len(combos):
        return combos
    idx = np.linspace(0, len(combos) - 1, count).round().astype(int)
    return [combos[i] for i in dict.fromkeys(idx)]


def _spread_pair(space: LayoutSpace, frac: float):
    """A pair of alternating values expressed as fractions of the span.

    Wide separation gives moment arm and conditioning; narrow gives short rods.
    Sweeping the pair is how the symmetric family covers that trade instead of
    committing to one point on it.
    """
    region = space.template.regions[space.topologies[0][0]]
    if region.ndim < 2:
        return None
    axis = 1 - spread_axis(region)
    lo, hi = region.bounds()[axis]
    span = hi - lo
    frac = min(max(float(frac), 0.55), 0.98)   # 0.5 would collapse the two
    return (lo + frac * span, lo + (1.0 - frac) * span)
