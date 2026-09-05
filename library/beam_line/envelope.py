"""
library/beam_line/envelope.py

The envelope of every diagram over every ON/OFF combination of the applied
loads, for a fixed support arrangement.

WHY THIS IS NOT 2^n
-------------------
The obvious reading is that an envelope over "every combination of loads"
needs a solve per combination -- 2^n of them, which is 14 minutes at twenty
loads and hopeless beyond that.

It does not, because the model is **linear in the loads**. With the supports,
the hinges and any prescribed settlement held fixed, the response to a set of
loads is the response to the empty set plus the sum of each load's own
contribution:

    V_S(x) = V_0(x) + SUM_{i in S} [ V_i(x) - V_0(x) ]

So at any station the largest value reachable by ANY subset is obtained by
including exactly those loads whose contribution is positive there, and the
smallest by including exactly those whose contribution is negative:

    upper(x) = V_0(x) + SUM_i max(V_i(x) - V_0(x), 0)
    lower(x) = V_0(x) + SUM_i min(V_i(x) - V_0(x), 0)

That is **n + 1 solves**, and the result is exact -- not a bound. It is
checked against brute force over all 2^n subsets in
`tests/beam_line/test_envelope.py`, which agrees to ~5e-15.

The empty-set term matters and is easy to drop: an imposed support settlement
is a boundary condition, not a load, so it is present in every subset
including the empty one. Subtracting `V_0` from each single-load solve is what
stops it being counted n times.

WHAT VARIES AND WHAT DOES NOT
-----------------------------
Loads only. Switching a SUPPORT off changes the structure rather than the
load, and the response is not linear in that -- a different support
arrangement gets its own envelope. That is the honest split, and it matches
what the envelope is wanted for: a scale that holds still while loads are
toggled, and that is allowed to move when the structure itself changes.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from library.beam_line.diagrams import Diagrams, build
from library.beam_line.model import Beam
from library.beam_line.solver import solve

# Above this many loads the envelope is skipped rather than computed. The cost
# is linear, so this is not about the exponent -- it is about a pathological
# model (80 loads on 20 supports measured at ~20 ms a solve) turning a
# keystroke into a two-second wait. Callers degrade to the all-on model, which
# is one solve and still a stable scale for same-signed loads.
MAX_ENVELOPE_LOADS = 48

# Sample count for the common grid. The envelope is used to set an axis scale,
# and is floored by the actual current peak at the call site, so a slight
# under-resolution here can never clip a drawn curve.
GRID = 257

FIELDS = ("V", "M", "d")


@dataclass(frozen=True)
class Envelope:
    """Upper and lower reachable bounds for each diagram, over all subsets."""

    x: np.ndarray
    hi: dict[str, np.ndarray]
    lo: dict[str, np.ndarray]
    n_solves: int
    n_loads: int

    def peak(self, field: str) -> float:
        """Largest magnitude the field can reach under any load subset."""
        return float(max(np.abs(self.hi[field]).max(),
                         np.abs(self.lo[field]).max()))

    def bounds(self, field: str) -> tuple[float, float]:
        """(most positive, most negative) reachable value."""
        return float(self.hi[field].max()), float(self.lo[field].min())


def _load_items(beam: Beam) -> list[Beam]:
    """One single-load copy of `beam` per applied load."""
    empty = replace(beam, point_loads=(), moments=(), distributed=())
    out: list[Beam] = []
    for p in beam.point_loads:
        out.append(replace(empty, point_loads=(p,)))
    for m in beam.moments:
        out.append(replace(empty, moments=(m,)))
    for d in beam.distributed:
        out.append(replace(empty, distributed=(d,)))
    return out


def _grid(beam: Beam, n: int) -> np.ndarray:
    """Uniform stations plus both sides of every feature.

    V steps at a point load and M steps at an applied couple, so a purely
    uniform grid can straddle a discontinuity and miss the extreme on one side
    of it. Sampling each feature station from the left and from the right
    catches both faces.
    """
    eps = max(beam.L, 1.0) * 1.0e-9
    xs = list(np.linspace(0.0, beam.L, max(3, n)))
    for f in beam.feature_stations():
        xs += [max(0.0, f - eps), min(beam.L, f + eps)]
    return np.unique(np.asarray(xs, dtype=float))


def _sample(dg: Diagrams, xs: np.ndarray) -> dict[str, np.ndarray]:
    return {
        "V": np.array([dg.V_at(float(x)) for x in xs]),
        "M": np.array([dg.M_at(float(x)) for x in xs]),
        "d": np.array([dg.deflection_at(float(x)) for x in xs]),
    }


def load_envelope(beam: Beam, grid: int = GRID) -> Envelope | None:
    """Envelope over every ON/OFF combination of `beam`'s loads.

    `beam` is the FULL model -- every load present, switched on or not. The
    support arrangement is taken as given and is not varied.

    Returns None when there is nothing to envelope (no loads), when the model
    does not solve, or when there are more loads than `MAX_ENVELOPE_LOADS`.
    A caller that gets None should fall back to scaling on the model as drawn.
    """
    singles = _load_items(beam)
    if not singles or len(singles) > MAX_ENVELOPE_LOADS:
        return None

    xs = _grid(beam, grid)

    base_beam = replace(beam, point_loads=(), moments=(), distributed=())
    sol = solve(base_beam)
    if not sol.stable:
        return None
    dg = build(base_beam, sol)
    if not dg.valid:
        return None
    base = _sample(dg, xs)

    hi = {f: base[f].copy() for f in FIELDS}
    lo = {f: base[f].copy() for f in FIELDS}

    for one in singles:
        s = solve(one)
        if not s.stable:
            return None
        d = build(one, s)
        if not d.valid:
            return None
        cur = _sample(d, xs)
        for f in FIELDS:
            c = cur[f] - base[f]
            hi[f] += np.maximum(c, 0.0)
            lo[f] += np.minimum(c, 0.0)

    return Envelope(x=xs, hi=hi, lo=lo,
                    n_solves=len(singles) + 1, n_loads=len(singles))
