"""
tests/tierod/test_examples.py — the shipped demonstrations.

These are the geometries a new user meets first, so what each one demonstrates
is a property worth pinning. Every number here was measured from the model
before it was written down; the sweep that produced the payload deck is
recorded in `apps/tierod/examples.py`.

Deliberately NOT a source of fixtures for other test files. Demos get replaced
when a better demonstration turns up — that happened on 2026-08-24 and took 69
tests with it, all keyed to region names in the old one. Frozen fixtures live
in `legacy_demo.py`.
"""
from __future__ import annotations

import numpy as np
import pytest

from apps.tierod import examples
from library.tierod import clash
from library.tierod import failsafe as fs
from library.tierod import mechanisms as mech
from library.tierod import serialize
from library.tierod.kernel import assemble


@pytest.fixture(scope="module")
def deck():
    return examples.payload_deck()


# ----------------------------------------------------------------------
# Contract shared by every example
# ----------------------------------------------------------------------


@pytest.mark.parametrize("name", list(examples.EXAMPLES))
def test_every_example_is_a_valid_model(name):
    examples.EXAMPLES[name]().validate()


@pytest.mark.parametrize("name", list(examples.EXAMPLES))
def test_every_example_round_trips_through_json(name):
    a = examples.EXAMPLES[name]()
    serialize.loads(serialize.dumps(a)).validate()


@pytest.mark.parametrize("name", list(examples.EXAMPLES))
def test_every_example_assembles_without_raising(name):
    """A mechanism is a legitimate example; a crash is not."""
    assemble(examples.EXAMPLES[name]())


def test_the_default_example_is_one_of_them():
    assert examples.DEFAULT_EXAMPLE in examples.EXAMPLES


def test_every_body_carries_a_clearance_shell():
    """The shells are what the interference check measures against. A body
    without one is invisible to it — silently passable."""
    for name, build in examples.EXAMPLES.items():
        for body in build().bodies.values():
            assert body.clearance is not None, f"{name}: {body.id} has no shell"


# ----------------------------------------------------------------------
# Payload deck — the default, and the tool's brief as a model
# ----------------------------------------------------------------------


def test_the_payload_deck_restrains_everything(deck):
    metrics = fs.layout_metrics(deck)
    assert metrics.n_free == 3 and metrics.n_dof == 18
    assert metrics.rank == 18, "full rank: no mechanism"
    assert metrics.sigma_min > 0.05, "and not merely full rank on paper"


def test_the_payload_deck_is_redundant_not_merely_restrained(deck):
    """21 rods for 18 DOF. At exactly 18 every rod is critical by
    construction, which is the thing the body-to-body ties exist to fix."""
    metrics = fs.layout_metrics(deck)
    assert metrics.n_rods == 21
    assert metrics.survives_single_loss
    assert metrics.critical == []


def test_the_payload_deck_is_clash_free(deck):
    report = clash.check_clearance(deck)
    assert report.ok, [c.message() for c in report.clashes]


def test_the_payload_deck_passes_the_whole_feasibility_gate(deck):
    verdict = fs.feasible(fs.layout_metrics(deck), fs.Criteria())
    assert verdict.ok, verdict.reasons


def test_the_payload_deck_ties_bodies_to_each_other_not_only_to_ground(deck):
    """Half the owner's brief. A model where everything goes straight to
    ground would not exercise multi-body load paths at all."""
    cross = [
        rod_id for rod_id, rod in deck.rods.items()
        if not any(deck.regions[e.region_id].body_id == "deck"
                   for e in (rod.end_a, rod.end_b))
    ]
    assert len(cross) >= 3, cross


def test_the_payload_deck_shows_off_the_2d_region_primitives(deck):
    kinds = {type(r).__name__ for r in deck.regions.values()}
    assert {"Annulus", "CylindricalBand", "SphericalPatch"} <= kinds


def test_the_payloads_sit_above_the_deck(deck):
    """'Shapes in space above a base surface' — the owner's words. A payload
    intersecting the deck would be a different picture entirely."""
    for body_id in ("tank", "avionics", "vessel"):
        body = deck.bodies[body_id]
        lowest = body.origin[2] + body.clearance.centroid()[2]
        assert lowest > 5.0, body_id


def test_every_payload_has_its_cg_at_its_shell_centre(deck):
    """`snap_cg_to_shell` is used when building this, so it should hold. It is
    also the case that catches a Cylinder whose centroid is not its origin."""
    for body_id in ("tank", "avionics", "vessel"):
        body = deck.bodies[body_id]
        assert np.allclose(body.cg, body.clearance.centroid())


def test_the_tank_cg_is_not_at_its_body_origin(deck):
    """Which is the whole reason the snap exists: the tank shell spans
    z = 10..26, so its centre of volume is 18 in up, not at the datum."""
    assert deck.bodies["tank"].cg[2] == pytest.approx(18.0)


def test_equal_twists_would_collapse_the_hexapods():
    """The finding the sweep turned up, pinned so it cannot be reintroduced:
    when the base and top twists match, each pair becomes a parallelogram and
    the whole 18-DOF assembly drops to rank 9."""
    import apps.tierod.examples as ex

    original = ex._TOP_TWIST
    try:
        ex._TOP_TWIST = ex._TWIST
        broken = fs.layout_metrics(ex.payload_deck(), min_gap=None)
    finally:
        ex._TOP_TWIST = original
    assert broken.rank < broken.n_dof
    assert fs.layout_metrics(ex.payload_deck(), min_gap=None).rank == 18


# ----------------------------------------------------------------------
# Mechanism turntable
# ----------------------------------------------------------------------


def test_the_turntable_is_a_mechanism_despite_having_six_rods():
    """Six rods, three degrees of freedom restrained. Counting rods proves
    nothing — this has a working hexapod's rod count and half its rank."""
    a = examples.mechanism_turntable()
    metrics = fs.layout_metrics(a)
    assert metrics.n_rods == 6
    assert metrics.rank == 3 and metrics.nullity == 3


def test_the_turntable_names_a_geometric_cause_not_just_a_number():
    """The Mechanism tab's value is the diagnosis, not the rank."""
    a = examples.mechanism_turntable()
    report = mech.check(a)
    assert not report.ok
    assert {f.kind for f in report.findings} & {"concurrent", "common_line"}
    assert report.modes, "there must be modes to animate"


def test_the_turntable_is_not_ALSO_an_interference_example():
    """One demonstration per example. A mechanism that also clashed would
    teach two things at once and neither clearly."""
    assert clash.check_clearance(examples.mechanism_turntable()).ok


# ----------------------------------------------------------------------
# Interference gantry
# ----------------------------------------------------------------------


def test_the_gantry_load_path_is_sound():
    """The point of it: everything except clearance reports healthy."""
    a = examples.clash_gantry()
    metrics = fs.layout_metrics(a, min_gap=None)
    assert metrics.rank == metrics.n_dof
    assert mech.check(a).ok


def test_the_gantry_is_nevertheless_unbuildable():
    report = clash.check_clearance(examples.clash_gantry())
    assert not report.ok
    assert "passes through" in report.worst.message()


def test_the_gantry_fails_the_gate_ONLY_on_interference():
    """If it failed for several reasons the demonstration would be muddled."""
    verdict = fs.feasible(
        fs.layout_metrics(examples.clash_gantry()),
        fs.Criteria(require_single_failure=False),
    )
    assert not verdict.ok
    assert all(r.startswith("interference") for r in verdict.reasons), verdict.reasons


def test_turning_the_check_off_hides_the_gantry_s_problem_entirely():
    """Which is what the tool did before the check existed."""
    verdict = fs.feasible(
        fs.layout_metrics(examples.clash_gantry(), min_gap=None),
        fs.Criteria(require_single_failure=False, min_gap=None),
    )
    assert verdict.ok
