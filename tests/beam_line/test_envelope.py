"""
tests/beam_line/test_envelope.py

The envelope is claimed to be EXACT, not a bound, and to cost n+1 solves
rather than 2^n. Both claims are checked against brute force over every
subset -- which is the only way to know the superposition shortcut is right,
and cheap enough to run for small n.
"""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from library.beam_line import (
    Beam,
    DistributedLoad,
    Hinge,
    PointLoad,
    PointMoment,
    Support,
    analyse,
)
from library.beam_line.envelope import MAX_ENVELOPE_LOADS, load_envelope

FIELDS = ("V", "M", "d")


def _brute(beam: Beam, xs: np.ndarray) -> dict[str, tuple[float, float]]:
    """True (max, min) of every field over all 2^n load subsets."""
    items = ([("p", p) for p in beam.point_loads]
             + [("m", m) for m in beam.moments]
             + [("d", d) for d in beam.distributed])
    hi = {f: -np.inf for f in FIELDS}
    lo = {f: np.inf for f in FIELDS}
    n = len(items)
    for r in range(n + 1):
        for subset in itertools.combinations(range(n), r):
            chosen = [items[i] for i in subset]
            b = Beam(beam.L, beam.EI, beam.supports,
                     tuple(o for k, o in chosen if k == "p"),
                     tuple(o for k, o in chosen if k == "m"),
                     tuple(o for k, o in chosen if k == "d"),
                     beam.hinges)
            _, sol, dg = analyse(b)
            assert dg is not None and dg.valid
            for f, fn in (("V", dg.V_at), ("M", dg.M_at),
                          ("d", dg.deflection_at)):
                vals = np.array([fn(float(x)) for x in xs])
                hi[f] = max(hi[f], float(vals.max()))
                lo[f] = min(lo[f], float(vals.min()))
    return {f: (hi[f], lo[f]) for f in FIELDS}


CASES = {
    "simply supported, mixed signs": Beam(
        200.0, 1.0e8, (Support(0.0), Support(200.0)),
        point_loads=(PointLoad(30.0, -700.0), PointLoad(150.0, 400.0)),
        moments=(PointMoment(120.0, 9000.0),),
        distributed=(DistributedLoad(0.0, 90.0, -14.0, -3.0),)),
    "indeterminate with a settled support": Beam(
        200.0, 1.0e8,
        (Support(0.0, uy="rigid", rz="rigid"), Support(90.0, dy=-0.02),
         Support(200.0)),
        point_loads=(PointLoad(150.0, -400.0),),
        moments=(PointMoment(120.0, 9000.0),),
        distributed=(DistributedLoad(0.0, 90.0, -14.0, -3.0),
                     DistributedLoad(140.0, 200.0, -6.0, -6.0))),
    "with an internal hinge": Beam(
        200.0, 1.0e8,
        (Support(0.0, uy="rigid", rz="rigid"), Support(200.0)),
        point_loads=(PointLoad(150.0, -1000.0), PointLoad(60.0, 250.0)),
        distributed=(DistributedLoad(0.0, 100.0, -5.0, -5.0),),
        hinges=(Hinge(100.0),)),
    "spring supports": Beam(
        120.0, 1.0e8,
        (Support(0.0, uy="spring", ky=6000.0), Support(120.0)),
        point_loads=(PointLoad(60.0, -900.0), PointLoad(90.0, 300.0)),
        distributed=(DistributedLoad(0.0, 60.0, -7.0, -2.0),)),
}


@pytest.mark.parametrize("name", list(CASES))
def test_the_envelope_matches_brute_force_over_every_subset(name):
    """Exact, not a bound. The superposition shortcut is the whole reason the
    feature is affordable, so it is checked against the thing it replaces."""
    beam = CASES[name]
    env = load_envelope(beam)
    assert env is not None
    want = _brute(beam, env.x)
    for f in FIELDS:
        got_hi, got_lo = env.bounds(f)
        exp_hi, exp_lo = want[f]
        scale = max(abs(exp_hi), abs(exp_lo), 1e-30)
        assert abs(got_hi - exp_hi) / scale < 1e-9, (f, got_hi, exp_hi)
        assert abs(got_lo - exp_lo) / scale < 1e-9, (f, got_lo, exp_lo)


@pytest.mark.parametrize("name", list(CASES))
def test_the_envelope_costs_one_solve_per_load_plus_one(name):
    beam = CASES[name]
    env = load_envelope(beam)
    assert env is not None
    n = (len(beam.point_loads) + len(beam.moments) + len(beam.distributed))
    assert env.n_loads == n
    assert env.n_solves == n + 1


def test_the_envelope_contains_the_all_on_model():
    """The obvious sanity property: whatever the full model does, the envelope
    must already allow. This is what makes it safe as an axis scale."""
    beam = CASES["simply supported, mixed signs"]
    env = load_envelope(beam)
    _, _, dg = analyse(beam)
    for f, fn in (("V", dg.V_at), ("M", dg.M_at), ("d", dg.deflection_at)):
        cur = np.array([fn(float(x)) for x in env.x])
        assert (cur <= env.hi[f] + 1e-6 * max(1.0, env.peak(f))).all()
        assert (cur >= env.lo[f] - 1e-6 * max(1.0, env.peak(f))).all()


def test_the_envelope_can_exceed_the_all_on_model():
    """The reason the scale is taken from the envelope and not simply from the
    all-on model: when two loads oppose, switching one OFF makes the diagram
    bigger. An axis locked to the all-on peak would be overflowed by a subset
    of it."""
    beam = Beam(120.0, 1.0e8, (Support(0.0), Support(120.0)),
                point_loads=(PointLoad(60.0, -1000.0),
                             PointLoad(60.0, 900.0)))
    env = load_envelope(beam)
    _, _, dg = analyse(beam)
    all_on = abs(dg.extremes("M")[2].value)
    assert env.peak("M") > all_on * 5, (env.peak("M"), all_on)


def test_settlement_is_counted_once_not_once_per_load():
    """An imposed settlement is a boundary condition, present in every subset
    including the empty one. Forgetting to subtract the empty-set response
    from each single-load solve counts it n times, which this catches."""
    settled = Beam(200.0, 1.0e8,
                   (Support(0.0), Support(100.0, dy=-0.3), Support(200.0)),
                   point_loads=(PointLoad(50.0, -100.0),
                                PointLoad(150.0, -100.0)))
    env = load_envelope(settled)
    want = _brute(settled, env.x)
    for f in FIELDS:
        exp_hi, exp_lo = want[f]
        got_hi, got_lo = env.bounds(f)
        scale = max(abs(exp_hi), abs(exp_lo), 1e-30)
        assert abs(got_hi - exp_hi) / scale < 1e-9
        assert abs(got_lo - exp_lo) / scale < 1e-9


def test_a_beam_with_no_loads_has_no_envelope():
    beam = Beam(120.0, 1.0e8, (Support(0.0), Support(120.0)))
    assert load_envelope(beam) is None


def test_an_unstable_beam_has_no_envelope():
    beam = Beam(120.0, 1.0e8, (Support(60.0),),
                point_loads=(PointLoad(0.0, -100.0),))
    assert load_envelope(beam) is None


def test_a_pathological_load_count_is_declined_rather_than_computed():
    """The cost is linear, so the cap is not about the exponent -- it is about
    a model big enough to turn a keystroke into a multi-second wait."""
    n = MAX_ENVELOPE_LOADS + 1
    beam = Beam(1000.0, 1.0e8, (Support(0.0), Support(1000.0)),
                point_loads=tuple(PointLoad(1.0 + i * 5.0, -10.0)
                                  for i in range(n)))
    assert load_envelope(beam) is None


def test_the_grid_samples_both_sides_of_a_discontinuity():
    """V steps at a point load. A purely uniform grid can straddle the step
    and miss the taller face, which would let a drawn curve overflow the axis
    the envelope is setting."""
    beam = Beam(120.0, 1.0e8, (Support(0.0), Support(120.0)),
                point_loads=(PointLoad(37.0, -1000.0),))
    env = load_envelope(beam)
    _, _, dg = analyse(beam)
    true_peak = abs(dg.extremes("V")[2].value)
    assert env.peak("V") >= true_peak * (1 - 1e-9)
