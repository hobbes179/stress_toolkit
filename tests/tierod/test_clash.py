"""
tests/tierod/test_clash.py — physical interference.

Every geometric expectation here is a hand-computable number on a shape chosen
so the answer is obvious (a cylinder of radius 3, a box of half-extents
2/3/4). Nothing is asserted against what the code currently returns.

The two rules that carry the design, and that a careless refactor would break
in opposite directions:

* the sampling margin must be applied to pairs that are NOT bolted together,
  or the check silently over-reports clearance;
* it must NOT be applied to the body a rod IS bolted to, or every legal rod
  reads as penetrating its own mounting face.
"""
from __future__ import annotations

import numpy as np
import pytest

from library.tierod import clash
from library.tierod.clearance import Box, Cylinder, Sphere
from library.tierod.model import (
    Assembly,
    Body,
    frame_from_axis,
    new_region,
    new_rod,
)

FRAME = dict(zip(("e1", "e2", "e3"), frame_from_axis("Z")))


@pytest.fixture
def cyl() -> Cylinder:
    """Radius 3, spanning z = 0 … 10, on the global frame."""
    return Cylinder(origin=np.zeros(3), radius=3.0, z_min=0.0, z_max=10.0, **FRAME)


@pytest.fixture
def box() -> Box:
    return Box(origin=np.zeros(3), half_extents=(2.0, 3.0, 4.0), **FRAME)


@pytest.fixture
def sph() -> Sphere:
    return Sphere(origin=np.zeros(3), radius=3.0, **FRAME)


# ----------------------------------------------------------------------
# signed_clearance — the thing plain distance could not do
# ----------------------------------------------------------------------


def test_the_surface_is_zero_the_inside_is_negative_the_outside_positive(cyl):
    """The whole reason this module exists. Unsigned distance returns 0 for
    the first two of these, which is why it could not be used."""
    on, inside, outside = clash.signed_clearance(
        cyl, [[3, 0, 5], [0, 0, 5], [5, 0, 5]]
    )
    assert on == pytest.approx(0.0)
    assert inside == pytest.approx(-3.0)
    assert outside == pytest.approx(2.0)


def test_depth_inside_a_cylinder_is_to_the_NEAREST_surface_not_the_wall(cyl):
    """A point just inside a cap is shallow even though it is on the axis.
    Taking only the radial term would call it 3 in deep."""
    assert clash.signed_clearance(cyl, [[0, 0, 0.2]])[0] == pytest.approx(-0.2)


def test_the_cylinder_corner_distance_is_the_diagonal(cyl):
    """Outside both the wall and the cap: sqrt(2² + 4²), not either alone."""
    got = clash.signed_clearance(cyl, [[5, 0, 14]])[0]
    assert got == pytest.approx(float(np.hypot(2.0, 4.0)))


@pytest.mark.parametrize(
    "point, expected",
    [([0, 0, 0], -2.0), ([4, 0, 0], 2.0), ([0, 5, 0], 2.0), ([0, 0, 6], 2.0)],
)
def test_box_clearance_uses_the_nearest_face(box, point, expected):
    assert clash.signed_clearance(box, [point])[0] == pytest.approx(expected)


@pytest.mark.parametrize("point, expected", [([8, 0, 0], 5.0), ([0, 0, 0], -3.0)])
def test_sphere_clearance_is_radial(sph, point, expected):
    assert clash.signed_clearance(sph, [point])[0] == pytest.approx(expected)


def test_clearance_is_measured_in_the_primitive_s_own_frame():
    """A shell on X must not be measured as though it were on Z."""
    on_x = Cylinder(origin=np.zeros(3), radius=3.0, z_min=0.0, z_max=10.0,
                    **dict(zip(("e1", "e2", "e3"), frame_from_axis("X"))))
    # 5 along global X is 5 along the cylinder's own axis: inside the length,
    # on the axis, so 3 in from the wall.
    assert clash.signed_clearance(on_x, [[5, 0, 0]])[0] == pytest.approx(-3.0)


def test_an_unknown_primitive_is_refused_rather_than_silently_cleared():
    class Blob:
        origin = np.zeros(3)
        E = np.eye(3)

    with pytest.raises(TypeError, match="no clearance rule"):
        clash.signed_clearance(Blob(), [[0, 0, 0]])


def test_clearance_is_vectorized_over_points(cyl):
    values = clash.signed_clearance(cyl, [[3, 0, 5], [0, 0, 5], [5, 0, 5]])
    assert values.shape == (3,)


# ----------------------------------------------------------------------
# Segments
# ----------------------------------------------------------------------


def test_a_rod_driven_through_a_body_is_distinguished_from_one_skimming_it(cyl):
    """The measurement that plain distance collapsed to a single 0.0."""
    through = clash.segment_depth(cyl, [3, 0, 5], [-3, 0, 5])
    skimming = clash.segment_depth(cyl, [3, 0, 5], [3, 0, 20])
    assert through == pytest.approx(3.0)
    assert skimming == pytest.approx(0.0)


def test_a_segment_that_stays_outside_has_no_depth(cyl):
    assert clash.segment_depth(cyl, [5, 0, 5], [20, 0, 5]) == 0.0


def test_the_sampling_margin_shrinks_with_more_samples():
    margin = [float(clash.sample_margin([[0, 0, 0]], [[10, 0, 0]], s)[0])
              for s in (11, 101)]
    assert margin[0] == pytest.approx(0.5)
    assert margin[1] == pytest.approx(0.05)


def test_the_margin_makes_the_bound_conservative_never_optimistic(cyl):
    """A coarse sample can miss the true minimum; the margin must cover it.

    The segment grazes the cap corner between samples, so the raw sampled
    minimum over-reports the clearance.
    """
    a, b = [[-8.0, 0.0, 12.0]], [[8.0, 0.0, 12.0]]
    raw = float(clash.segment_clearance(cyl, a, b, samples=5)[0])
    bound = raw - float(clash.sample_margin(a, b, samples=5)[0])
    truth = float(clash.segment_clearance(cyl, a, b, samples=2001)[0])
    assert bound <= truth + 1e-9
    assert raw > truth - 1e-9


@pytest.mark.parametrize(
    "args, expected",
    [
        (([-1, 0, 0], [1, 0, 0], [0, -1, 1], [0, 1, 1]), 1.0),     # crossing
        (([-1, 0, 0], [1, 0, 0], [0, -1, 0], [0, 1, 0]), 0.0),     # intersecting
        (([0, 0, 0], [1, 0, 0], [0, 2, 0], [1, 2, 0]), 2.0),       # parallel
        (([0, 0, 0], [1, 0, 0], [5, 0, 3], [6, 0, 3]), 5.0),       # past the end
        (([0, 0, 0], [0, 0, 0], [3, 4, 0], [3, 4, 0]), 5.0),       # degenerate
    ],
)
def test_segment_gap_known_values(args, expected):
    assert clash.segment_gap(*args) == pytest.approx(expected)


def test_parallel_segments_do_not_divide_by_zero():
    """The naive determinant solution blows up here."""
    assert np.isfinite(clash.segment_gap([0, 0, 0], [1, 0, 0],
                                         [0, 1, 0], [1, 1, 0]))


def test_segment_gap_is_symmetric():
    a = ([0, 0, 0], [2, 1, 0])
    b = ([1, -3, 4], [1, 3, 4])
    assert clash.segment_gap(*a, *b) == pytest.approx(clash.segment_gap(*b, *a))


def test_segment_gaps_batches_agree_with_the_scalar_call(rng):
    P1, Q1, P2, Q2 = (rng.normal(size=(12, 3)) * 5 for _ in range(4))
    batch = clash.segment_gaps(P1, Q1, P2, Q2)
    one = [clash.segment_gap(P1[i], Q1[i], P2[i], Q2[i]) for i in range(12)]
    assert np.allclose(batch, one)


def test_the_gap_never_exceeds_any_endpoint_pair_distance(rng):
    """Closest approach is a minimum, so no endpoint pair can beat it."""
    for _ in range(30):
        p1, q1, p2, q2 = (rng.normal(size=3) * 4 for _ in range(4))
        gap = clash.segment_gap(p1, q1, p2, q2)
        ends = [np.linalg.norm(x - y) for x in (p1, q1) for y in (p2, q2)]
        assert gap <= min(ends) + 1e-9


# ----------------------------------------------------------------------
# Assembly-level check
# ----------------------------------------------------------------------


def _stack() -> Assembly:
    """Ground plate + a tank above it, one rod between mounting rings.

    Every coordinate here was probed before the expectations below were
    written, because `q0()` of a full CircleArc is **pi**, not 0 — five tests
    in the first draft of this file quietly placed two rods on top of each
    other, or a blocker on the opposite side of the model from the rod.

        plate_r at q = 0     ->  (12,  0,  0)
        tank_r  at q = 0     ->  ( 3,  0, 14)      ring at mid-height
        rod r1               ->  (12, 0, 0) - (3, 0, 14),  midpoint (7.5, 0, 7)

    The tank ring sits at mid-height rather than on the rim so a chord across
    it genuinely cuts the shell; on the rim it would lie exactly on the cap
    boundary at clearance 0 and correctly register as no penetration.
    """
    asm = Assembly({}, {}, {})
    plate = Body("plate", is_ground=True)
    plate.clearance = Box(origin=np.array([0.0, 0.0, -0.5]),
                          half_extents=(20.0, 20.0, 0.5), **FRAME)
    tank = Body("tank", mass=300.0, origin=np.array([0.0, 0.0, 10.0]))
    tank.clearance = Cylinder(origin=np.zeros(3), radius=3.0,
                              z_min=0.0, z_max=8.0, **FRAME)
    asm.add_body(plate)
    asm.add_body(tank)
    asm.add_region(new_region("CircleArc", "plate_r", "plate", axis="Z",
                              radius=12.0))
    asm.add_region(new_region("CircleArc", "tank_r", "tank", axis="Z",
                              origin=[0.0, 0.0, 4.0], radius=3.0))
    asm.add_rod(new_rod(asm, "r1", "plate_r", "tank_r", q_a=[0.0], q_b=[0.0]))
    return asm


#: Midpoint of r1 in `_stack`, where a blocker has to sit to be in the way.
R1_MID = np.array([7.5, 0.0, 7.0])


def test_a_clean_stack_reports_no_interference():
    report = clash.check_clearance(_stack())
    assert report.ok
    assert report.n_checked > 0


def test_a_rod_touching_the_body_it_is_bolted_to_is_not_a_clash():
    """THE rule that makes rod-vs-body usable. Every rod touches its own two
    bodies by construction; a plain gap test condemns all of them."""
    report = clash.check_clearance(_stack(), min_gap=1.0)
    assert report.ok, [c.message() for c in report.clashes]


def test_the_sampling_margin_is_not_charged_against_an_attached_body():
    """The first version subtracted it everywhere and turned the shipped demo
    from clean into twelve interferences. A long rod makes the margin large."""
    report = clash.check_clearance(_stack(), samples=5)
    assert report.ok, [c.message() for c in report.clashes]


def test_a_rod_driven_through_a_third_body_is_caught():
    asm = _stack()
    blocker = Body("blocker", is_ground=True, origin=R1_MID)
    blocker.clearance = Sphere(origin=np.zeros(3), radius=2.0, **FRAME)
    asm.add_body(blocker)
    report = clash.check_clearance(asm)
    assert not report.ok
    assert any(c.kind == "rod-body" and c.b == "blocker" for c in report.clashes)


def test_a_rod_chording_through_its_OWN_body_is_still_caught():
    """The attached exemption is about contact, not a licence to tunnel."""
    asm = _stack()
    # Move both ends onto the tank ring, opposite each other: the rod is a
    # diameter of the tank it is bolted to.
    asm.remove_rod("r1")
    asm.add_rod(new_rod(asm, "chord", "tank_r", "tank_r",
                        q_a=[0.0], q_b=[np.pi]))
    report = clash.check_clearance(asm)
    assert any(c.b == "tank" for c in report.clashes), report.summary()
    assert report.worst.gap == pytest.approx(-3.0, abs=1e-6)   # the radius


def test_two_rods_in_the_same_place_clash():
    asm = _stack()
    asm.add_rod(new_rod(asm, "r2", "plate_r", "tank_r",
                        q_a=[0.0], q_b=[0.0]))          # exactly on top of r1
    report = clash.check_clearance(asm)
    assert any(c.kind == "rod-rod" for c in report.clashes)


def test_two_well_separated_rods_do_not_clash():
    """r1 is at q = 0; the opposite side of the ring is q = pi."""
    asm = _stack()
    asm.add_rod(new_rod(asm, "r2", "plate_r", "tank_r",
                        q_a=[np.pi], q_b=[np.pi]))
    assert clash.check_clearance(asm).ok


def test_the_required_gap_includes_both_rod_radii():
    """Two fat rods need more room than two thin ones at the same spacing."""
    asm = _stack()
    asm.add_rod(new_rod(asm, "r2", "plate_r", "tank_r",
                        q_a=[0.35], q_b=[0.35]))
    thin = clash.check_clearance(asm, min_gap=0.0)
    fat = clash.check_clearance(asm, min_gap=0.0,
                                radii={"r1": 3.0, "r2": 3.0})
    assert thin.ok and not fat.ok


def test_raising_the_minimum_gap_can_turn_a_pass_into_a_failure():
    asm = _stack()
    asm.add_rod(new_rod(asm, "r2", "plate_r", "tank_r",
                        q_a=[0.5], q_b=[0.5]))
    assert clash.check_clearance(asm, min_gap=0.0).ok
    assert not clash.check_clearance(asm, min_gap=50.0).ok


def test_a_body_with_no_shell_is_skipped_not_assumed_solid():
    asm = _stack()
    asm.bodies["tank"].clearance = None
    report = clash.check_clearance(asm)
    assert report.ok
    assert not any(c.b == "tank" for c in report.clashes)


def test_an_oriented_body_is_measured_in_its_own_frame():
    """`R` brings rods into the shell's frame. With R = I this is invisible —
    exactly how the same omission survived four sessions in `Body.sweep_block`.

    A thin bar centred at (7.5, 4, 7) running along its own local y, half
    length 4.3. Unrotated it spans global y in [-0.3, 8.3] and so reaches the
    rod at y = 0. Rotated a quarter turn about z it runs along global x
    instead, staying at y ~ 4 and missing the rod by four inches.
    """
    asm = _stack()
    blocker = Body("blocker", is_ground=True, origin=np.array([7.5, 4.0, 7.0]))
    blocker.clearance = Box(origin=np.zeros(3), half_extents=(0.3, 4.3, 0.3),
                            **FRAME)
    asm.add_body(blocker)
    assert not clash.check_clearance(asm, min_gap=0.0).ok, "bar should reach it"

    asm.bodies["blocker"].R = np.array([[0.0, -1.0, 0.0],
                                        [1.0, 0.0, 0.0],
                                        [0.0, 0.0, 1.0]])
    assert clash.check_clearance(asm, min_gap=0.0).ok, "rotated bar should miss"


def test_an_assembly_with_no_rods_is_vacuously_clear():
    asm = _stack()
    asm.remove_rod("r1")
    report = clash.check_clearance(asm)
    assert report.ok and report.n_checked == 0


def test_the_rod_radius_comes_from_the_section_area():
    asm = _stack()
    asm.rods["r1"].A = np.pi * 4.0          # r = 2
    assert clash.rod_radius(asm.rods["r1"]) == pytest.approx(2.0)


# ----------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------


def test_a_clash_names_both_ends_and_the_shortfall():
    asm = _stack()
    asm.add_rod(new_rod(asm, "r2", "plate_r", "tank_r", q_a=[0.0], q_b=[0.0]))
    worst = clash.check_clearance(asm).worst
    assert worst.a and worst.b and worst.shortfall > 0
    assert worst.a in worst.message() and worst.b in worst.message()


def test_a_penetration_reads_as_passing_through_not_merely_close():
    asm = _stack()
    blocker = Body("blocker", is_ground=True, origin=R1_MID)
    blocker.clearance = Sphere(origin=np.zeros(3), radius=2.0, **FRAME)
    asm.add_body(blocker)
    assert "passes through" in clash.check_clearance(asm).worst.message()


def test_a_clean_report_states_the_tightest_clearance():
    """Needs a pair that is actually measured. Where every pair is a rod and
    the body it is bolted to, there is nothing to be tight about and the
    report says only that nothing interferes — which is the honest output."""
    asm = _stack()
    asm.add_rod(new_rod(asm, "r2", "plate_r", "tank_r",
                        q_a=[np.pi], q_b=[np.pi]))
    summary = clash.check_clearance(asm).summary()
    assert "no interference" in summary.lower() and "tightest" in summary.lower()


def test_worst_gap_is_zero_when_everything_clears():
    assert clash.worst_gap(_stack()) == 0.0


def test_worst_gap_is_positive_and_grows_with_the_violation():
    asm = _stack()
    # Close but not touching, so raising the required gap changes the answer.
    asm.add_rod(new_rod(asm, "r2", "plate_r", "tank_r", q_a=[0.1], q_b=[0.1]))
    assert clash.worst_gap(asm, min_gap=5.0) > clash.worst_gap(asm, min_gap=2.0) > 0


def test_the_check_is_cheap_enough_for_the_optimizer_s_inner_loop():
    """It has to sit beside `layout_metrics` on every objective evaluation.

    The first version called the existing golden-section `distance_to_segment`
    and cost 6 ms against that function's 0.5 ms — a 12x tax that would have
    turned a four-minute search into fifty. The bound is generous; it is here
    to catch a return to per-point Python, not to police microseconds.
    """
    import time

    from library.tierod import failsafe as fs
    from apps.tierod import examples

    asm = examples.EXAMPLES[examples.DEFAULT_EXAMPLE]()

    def bench(fn, n=60):
        start = time.perf_counter()
        for _ in range(n):
            fn()
        return (time.perf_counter() - start) / n

    metrics = bench(lambda: fs.layout_metrics(asm))
    check = bench(lambda: clash.check_clearance(asm))
    assert check < 6.0 * metrics, f"{check * 1e3:.2f} ms vs {metrics * 1e3:.2f} ms"


def test_the_margin_is_applied_to_bodies_the_rod_is_NOT_bolted_to():
    """The other half of the margin rule, and it needs its own case.

    A blocker placed just clear of the rod: with a coarse sample the raw
    minimum says it fits, and only the Lipschitz correction reveals that the
    true clearance could be smaller. Dropping the margin here is the silent,
    unconservative direction — no other test in this file distinguishes it.
    """
    asm = _stack()
    blocker = Body("blocker", is_ground=True, origin=R1_MID + np.array([0.0, 3.0, 0.0]))
    blocker.clearance = Sphere(origin=np.zeros(3), radius=2.0, **FRAME)
    asm.add_body(blocker)

    coarse = clash.check_clearance(asm, min_gap=0.6, samples=5, radii={"r1": 0.0})
    fine = clash.check_clearance(asm, min_gap=0.6, samples=2001, radii={"r1": 0.0})
    assert not coarse.ok, "the coarse bound must be the pessimistic one"
    assert fine.ok, "with enough samples the rod genuinely clears"


def test_a_fat_rod_clashes_with_a_body_a_thin_one_clears():
    """The rod radius has to enter the rod-vs-BODY requirement too, not only
    rod-vs-rod. A 3 in bar needs 3 in more room than a wire on the same line."""
    asm = _stack()
    blocker = Body("blocker", is_ground=True, origin=R1_MID + np.array([0.0, 4.0, 0.0]))
    blocker.clearance = Sphere(origin=np.zeros(3), radius=2.0, **FRAME)
    asm.add_body(blocker)
    assert clash.check_clearance(asm, min_gap=0.0, radii={"r1": 0.1}).ok
    assert not clash.check_clearance(asm, min_gap=0.0, radii={"r1": 3.0}).ok


# ======================================================================
# Rods sharing a pin
#
# Two rods on one lug is normal hardware -- a bipod, a hexapod pair, any
# fitting taking two eyes on a common bolt. Measured raw such a pair has a gap
# of exactly zero and reads as a clash, which condemned three shipped fixtures
# the moment interference went into the feasibility gate.
#
# But co-mounted is not a blanket exemption: two nearly collinear rods occupy
# the same space for their whole length. Each is pulled back from the shared
# pin by the clearance it needs anyway, and measured on what remains.
#
# This section exists because four mutations of `_trim_shared_ends` survived
# the first pass -- it was written under pressure to fix other failures and
# never tested on its own.
# ======================================================================


def _bipod(base_a, base_b, apex=(0.0, 0.0, 10.0), apex_b=None):
    """Two rods from a shared apex down to two ground points.

    `FixedPoint` tops give an EXACT shared coordinate, which is what the
    shared-pin exemption keys on; an arc would leave it to floating point.

    The top body carries NO clearance shell. The first version gave it a
    sphere centred on the apex, which put both rod ends at the centre of their
    own body and read as a 0.4 in penetration -- a correct finding about a
    nonsense fixture. These tests are about rod-against-rod, so the body that
    would confound them is left out rather than worked around.
    """
    from library.tierod.model import FixedPoint

    asm = Assembly({}, {}, {})
    ground = Body("ground", is_ground=True)
    ground.clearance = Box(origin=np.array([0.0, 0.0, -0.5]),
                           half_extents=(20.0, 20.0, 0.5), **FRAME)
    top = Body("top", mass=100.0)
    asm.add_body(ground)
    asm.add_body(top)
    asm.add_region(new_region("Annulus", "ring", "ground", axis="Z",
                              r_inner=0.0, r_outer=14.0))
    asm.add_region(FixedPoint(id="apex", body_id="top", origin=np.array(apex),
                              **FRAME))
    asm.add_region(FixedPoint(id="apex_b", body_id="top",
                              origin=np.array(apex if apex_b is None else apex_b),
                              **FRAME))
    asm.add_rod(new_rod(asm, "leg_a", "ring", "apex",
                        q_a=base_a, q_b=np.zeros(0)))
    asm.add_rod(new_rod(asm, "leg_b", "ring",
                        "apex" if apex_b is None else "apex_b",
                        q_a=base_b, q_b=np.zeros(0)))
    return asm


def test_two_rods_on_one_pin_that_diverge_are_fine():
    """A 90 degree bipod. Raw, its gap at the pin is exactly zero."""
    asm = _bipod([10.0, 0.0], [10.0, np.pi])
    assert clash.check_clearance(asm).ok, [
        c.message() for c in clash.check_clearance(asm).clashes
    ]


def test_two_rods_on_one_pin_that_are_nearly_parallel_still_clash():
    """The exemption is for meeting at the pin, not for occupying the same
    space all the way down. Four degrees apart is two rods in one hole."""
    asm = _bipod([10.0, 0.0], [10.0, np.radians(4.0)])
    report = clash.check_clearance(asm)
    assert not report.ok
    assert any(c.kind == "rod-rod" for c in report.clashes)


def test_the_exemption_needs_an_EXACTLY_shared_point_not_merely_a_close_one():
    """Two lugs a hundredth of an inch apart are two lugs. If the tolerance
    were loose enough to call them one pin, genuinely interfering rods would
    be trimmed apart and pass."""
    asm = _bipod([10.0, 0.0], [10.0, np.radians(4.0)],
                 apex_b=(0.0, 0.01, 10.0))
    assert not clash.check_clearance(asm).ok


def test_rods_that_share_no_pin_are_measured_untrimmed():
    """Trimming every pair would shorten rods that never met, hiding a
    mid-span crossing near either end."""
    asm = _stack()
    asm.add_rod(new_rod(asm, "r2", "plate_r", "tank_r",
                        q_a=[0.02], q_b=[0.02]))
    assert not clash.check_clearance(asm).ok


def test_the_trim_never_walks_past_the_far_end_of_a_short_rod():
    """Asserted on the ENDPOINT, not on the resulting gap.

    An unclamped trim on a 1 in rod that wants 50 in of clearance puts the
    moved end 50 in away, off the rod entirely and pointing the wrong way. The
    gap it then computes is still finite and still positive -- which is why an
    earlier version of this test, checking only that, could not tell the two
    apart and let the mutation through.
    """
    A1, B1 = np.array([[0.0, 0.0, 0.0]]), np.array([[1.0, 0.0, 0.0]])
    A2, B2 = np.array([[0.0, 0.0, 0.0]]), np.array([[0.0, 1.0, 0.0]])
    a1, b1, a2, b2 = clash._trim_shared_ends(A1, B1, A2, B2, np.array([50.0]))

    for moved, start, end in ((a1[0], A1[0], B1[0]), (a2[0], A2[0], B2[0])):
        along = float((moved - start) @ (end - start))
        assert 0.0 <= along <= float((end - start) @ (end - start)), (
            "the trimmed end left its own rod"
        )
        assert not np.allclose(moved, end), "and it must not reach the far end"


def test_a_short_rod_still_produces_a_usable_measurement():
    """The assembly-level consequence: nonsense geometry in, nonsense out."""
    asm = _bipod([0.2, 0.0], [0.2, np.pi], apex=(0.0, 0.0, 0.25))
    report = clash.check_clearance(asm, min_gap=5.0)
    assert np.isfinite(report.min_gap)
    for c in report.clashes:
        assert np.isfinite(c.gap)


def test_trimming_moves_the_shared_end_along_its_own_rod():
    """Unit-level: the trimmed endpoint must stay ON the segment, moving
    toward the far end by the required amount."""
    A1 = np.array([[0.0, 0.0, 0.0]])
    B1 = np.array([[10.0, 0.0, 0.0]])
    A2 = np.array([[0.0, 0.0, 0.0]])
    B2 = np.array([[0.0, 10.0, 0.0]])
    a1, b1, a2, b2 = clash._trim_shared_ends(A1, B1, A2, B2, np.array([2.0]))
    assert np.allclose(a1[0], [2.0, 0.0, 0.0])
    assert np.allclose(a2[0], [0.0, 2.0, 0.0])
    assert np.allclose(b1, B1) and np.allclose(b2, B2), "far ends untouched"


def test_trimming_leaves_unshared_pairs_exactly_as_they_were():
    A1 = np.array([[0.0, 0.0, 0.0]])
    B1 = np.array([[10.0, 0.0, 0.0]])
    A2 = np.array([[0.0, 3.0, 0.0]])
    B2 = np.array([[10.0, 3.0, 0.0]])
    out = clash._trim_shared_ends(A1, B1, A2, B2, np.array([2.0]))
    for got, want in zip(out, (A1, B1, A2, B2)):
        assert np.allclose(got, want)
