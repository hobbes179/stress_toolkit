"""
tests/tierod/test_mechanisms.py — Session 3 gate (V7, V8, V11, V12).

Mechanism detection is half the success criterion, so it is tested as a
first-class feature and not as a guard clause. Three layers, each asserted:

  1. graph pre-check   — names the unsupported BODY, before any linear algebra
  2. rank check        — nullity against expectation, on the NON-DIMENSIONALIZED
                         screws; zero ground bodies expects nullity 6 and is
                         reported as expected, not as an error
  3. geometric checks  — WHY the layout is a mechanism, in plain language

The hard part of V8 is not that nullity == 1. It is that the recovered null
mode is provably rotation about the ground-attachment line — that is the output
the engineer actually uses.
"""
from __future__ import annotations

import numpy as np
import pytest

from conftest import (
    make_concurrent6,
    make_five_rod,
    make_floating_island,
    make_free_free,
    make_hexapod,
    make_line_supported,
    make_orphan_body,
    make_parallel4,
    make_rotary_hexapod,
    make_symmetric8,
    make_tripod,
    make_two_body,
    make_unit_cage,
)
from library.tierod import mechanisms as mech
from library.tierod.kernel import (
    SingularAssemblyError,
    assemble,
    elongations,
    influence,
    solve,
)

LEN_TOL = 1e-7


def _unit(v):
    return np.asarray(v, dtype=float) / np.linalg.norm(v)


def _parallel_to(a, b, tol=1e-7):
    """Direction equality up to sign — an axis has no preferred sense."""
    return abs(abs(float(_unit(a) @ _unit(b))) - 1.0) < tol


# ======================================================================
# Graph pre-check (§5.1) — runs first, names the body
# ======================================================================


def test_graph_check_passes_on_a_supported_layout(hexapod):
    g = mech.body_graph(make_hexapod())
    assert g.ok
    assert g.unsupported == []
    assert len(g.components) == 1


def test_graph_check_names_the_unsupported_bodies(floating_island):
    """'Body 4 is not connected to ground' is worth far more than
    'K is rank deficient by 6'."""
    g = mech.body_graph(floating_island)
    assert not g.ok
    assert sorted(g.unsupported) == ["drifter_a", "drifter_b"]
    assert "anchored" not in g.unsupported
    assert "drifter_a" in g.message and "drifter_b" in g.message
    # the whole report surfaces it too, in plain language
    report = mech.check(floating_island)
    assert not report.ok
    assert any("drifter_a" in m for m in report.messages)


def test_graph_check_catches_a_body_with_no_rods_at_all():
    g = mech.body_graph(make_orphan_body())
    assert g.unsupported == ["lonely"]


def test_graph_check_accepts_a_body_reaching_ground_through_another_body(two_body):
    """body_to_body rods count as connectivity: a body grounded only via a
    neighbour is still in a component containing ground."""
    a = make_two_body()
    for k in range(6):
        del a.rods[f"g_b{k}"]      # body_b now reaches ground only through the ties
    g = mech.body_graph(a)
    assert g.ok, "connectivity is a graph property, not a rank property"
    assert g.unsupported == []
    # ... though it is of course now a mechanism, which the RANK check catches
    assert mech.check(a).nullity > 0


def test_graph_check_handles_multiple_ground_bodies():
    a = make_two_body()
    a.bodies["ground2"] = type(a.bodies["ground"])(id="ground2", is_ground=True)
    g = mech.body_graph(a)
    assert g.ok


# ======================================================================
# Rank check (§5.2) — against the DOF expectation
# ======================================================================


def test_rank_check_is_clean_on_a_good_layout(hexapod):
    r = mech.check(hexapod)
    assert r.ok
    assert (r.n_dof, r.rank, r.nullity, r.expected_nullity) == (6, 6, 0, 0)
    assert not r.free_free
    assert r.modes == []
    assert r.sigma_min > 0.1


def test_rank_check_uses_non_dimensionalized_screws():
    """A raw spectrum moves with model scale, so a fixed threshold on it would
    be meaningless. Geometrically similar layouts must report identically."""
    reports = [mech.check(make_hexapod(scale=s)) for s in (0.01, 1.0, 250.0)]
    assert all(r.ok and r.rank == 6 for r in reports)
    assert np.allclose(
        [r.sigma_min for r in reports], reports[0].sigma_min, rtol=1e-9
    ), "sigma_min must not depend on model scale"


def test_nullity_counts_independent_mechanism_modes():
    for factory, expected in (
        (make_five_rod, 1),
        (make_line_supported, 1),
        (make_concurrent6, 3),
        (make_parallel4, 3),
        (make_tripod, 3),
        (make_rotary_hexapod, 3),
    ):
        r = mech.check(factory())
        assert r.nullity == expected, f"{factory.__name__}: nullity {r.nullity}"
        assert len(r.modes) == expected, "one animation payload per mode"
        assert not r.ok


# ======================================================================
# Null modes as an animation payload (§5.3)
# ======================================================================


def test_null_modes_are_genuine_zero_energy_motions():
    """The defining property: a null mode stretches no rod, to first order."""
    for factory in (make_five_rod, make_line_supported, make_concurrent6, make_parallel4):
        asm = assemble(factory())
        for mode in mech.null_modes(asm):
            delta = elongations(asm, mode.vector)
            scale = max(1.0, float(np.abs(mode.vector).max()) * asm.L_c)
            assert np.max(np.abs(delta)) / scale < 1e-8, (
                f"{factory.__name__} mode {mode.index} changes rod lengths"
            )


def test_null_modes_are_independent_and_normalized():
    asm = assemble(make_concurrent6())
    modes = mech.null_modes(asm)
    M = np.column_stack([m.vector for m in modes])
    assert np.linalg.matrix_rank(M) == 3
    for m in modes:
        # normalized so amplitude is roughly a real displacement in inches
        scale = max(
            np.linalg.norm(mo.d) + asm.L_c * np.linalg.norm(mo.theta)
            for mo in m.per_body.values()
        )
        assert scale == pytest.approx(1.0, rel=1e-9)
    # every rod here meets the body at the SAME apex, and the modes are
    # rotations about it, so no attachment point moves at all. Normalizing on
    # attachment motion would have left these modes unscaled.
    assert all(m.max_point_displacement == pytest.approx(0.0, abs=1e-9) for m in modes)


def test_mode_gives_a_rigid_motion_per_free_body(floating_island):
    asm = assemble(floating_island)
    modes = mech.null_modes(asm)
    assert modes
    for mode in modes:
        assert set(mode.per_body) == {"anchored", "drifter_a", "drifter_b"}
        for motion in mode.per_body.values():
            assert motion.d.shape == (3,) and motion.theta.shape == (3,)
    # the anchored body is fully restrained, so no mode may move it
    for mode in modes:
        m = mode.per_body["anchored"]
        assert np.allclose(m.d, 0.0, atol=1e-9) and np.allclose(m.theta, 0.0, atol=1e-9)


def test_displace_is_a_rigid_body_field():
    """The animation payload must move a body rigidly: distances preserved to
    first order, and the field must be d + theta x (p - datum)."""
    a = make_line_supported()
    asm = assemble(a)
    mode = mech.null_modes(asm)[0]
    motion = mode.per_body["body"]
    datum = a.bodies["body"].origin

    pts = np.column_stack(
        [np.array([1.0, 2.0, 3.0]), np.array([-4.0, 0.5, 11.0]), datum]
    )
    disp = mode.displace("body", pts, amplitude=0.25)
    assert disp.shape == (3, 3)
    for j in range(pts.shape[1]):
        expected = 0.25 * (motion.d + np.cross(motion.theta, pts[:, j] - datum))
        assert np.allclose(disp[:, j], expected)
    # the datum itself moves by d alone
    assert np.allclose(disp[:, 2], 0.25 * motion.d)


def test_displace_rejects_a_grounded_or_unknown_body():
    mode = mech.null_modes(assemble(make_line_supported()))[0]
    with pytest.raises(KeyError):
        mode.displace("ground", np.zeros((3, 1)))


# ======================================================================
# V7 — five rods on one free body
# ======================================================================


def test_v7_five_rods_cannot_fix_six_dof(five_rod):
    """Five constraints against six DOF: a mechanism whatever the arrangement.
    No numerical output is produced — the solver refuses rather than returning
    a plausible-looking answer."""
    r = mech.check(five_rod)
    assert not r.ok
    assert (r.n_dof, r.rank, r.nullity) == (6, 5, 1)
    assert r.graph.ok, "connectivity is fine; the deficiency is rank, not topology"
    assert len(r.modes) == 1
    assert any("mechanism" in m.lower() for m in r.messages)

    asm = assemble(five_rod)
    with pytest.raises(SingularAssemblyError):
        solve(asm.K, np.array([0.0, 0.0, -1000.0, 0.0, 0.0, 0.0]))
    with pytest.raises(SingularAssemblyError):
        influence(asm)


def test_v7_the_mode_is_the_motion_the_missing_rod_would_have_stopped(five_rod):
    """The cage's `r_ry` runs +Z at (1,0,0) and is the only rod resisting
    rotation about Y. Remove it and the free motion must be exactly that."""
    mode = mech.null_modes(assemble(five_rod))[0]
    motion = mode.per_body["body"]
    assert _parallel_to(motion.theta, [0.0, 1.0, 0.0]), (
        f"expected rotation about Y, got theta = {motion.theta}"
    )


# ======================================================================
# V8 — all ground attachments collinear
# ======================================================================


def test_v8_collinear_ground_attachments_are_flagged_with_their_own_message(
    line_supported,
):
    r = mech.check(line_supported)
    assert not r.ok
    assert r.nullity == 1
    kinds = {f.kind for f in r.findings}
    assert "collinear_ground" in kinds, (
        "this case is guaranteed and deserves its own message, not a generic "
        f"rank complaint; got {kinds}"
    )
    finding = next(f for f in r.findings if f.kind == "collinear_ground")
    assert _parallel_to(finding.axis, [1.0, 0.0, 0.0])
    assert any("collinear" in m.lower() for m in r.messages)


def test_v8_the_null_mode_is_rotation_about_that_line(line_supported):
    """The substance of V8. Not 'nullity == 1' — the recovered mode must BE a
    rotation, about the ground line, and nothing else."""
    a = make_line_supported()
    asm = assemble(a)
    modes = mech.null_modes(asm)
    assert len(modes) == 1
    mode = modes[0]

    axis = mode.common_axis()
    assert axis is not None, "the mode must be a pure rotation, not a screw"
    point, direction = axis

    # direction is the ground line
    assert _parallel_to(direction, [1.0, 0.0, 0.0])
    # and the axis passes through the ground attachment line (the global X axis)
    assert point[1] == pytest.approx(0.0, abs=1e-7)
    assert point[2] == pytest.approx(0.0, abs=1e-7)

    # every GROUND attachment point lies on the recovered axis, so it is fixed
    for j, rod_id in enumerate(asm.rod_ids):
        g = asm.points_b[:, j]
        offset = (g - point) - direction * ((g - point) @ direction)
        assert np.linalg.norm(offset) < 1e-7, f"{rod_id}: ground point off the axis"

    # no rod generates moment about the axis — the proof sketch in §5.4
    for j in range(asm.n_rods):
        m_about_axis = direction @ np.cross(asm.points_a[:, j] - point, asm.units[:, j])
        assert abs(m_about_axis) < 1e-6 * asm.L_c


def test_v8_holds_for_a_line_on_a_different_axis_and_more_rods():
    """'Any number of rods in any arrangement' — so vary both.

    Note the guarantee is AT LEAST one mechanism, not exactly one: four rods
    cannot fix six DOF regardless of where they go, so that case is doubly
    deficient. The assertion that survives every count is that rotation about
    the ground line is free, which is checked by constructing that motion
    explicitly rather than hoping the SVD basis isolates it.
    """
    for n_rods in (4, 6, 9):
        a = make_line_supported(n_rods=n_rods, axis="y")
        asm = assemble(a)
        r = mech.check(a, assembled=asm)
        assert r.nullity >= 1, f"{n_rods} rods on a line is still a mechanism"
        assert "collinear_ground" in {f.kind for f in r.findings}
        finding = next(f for f in r.findings if f.kind == "collinear_ground")
        assert _parallel_to(finding.axis, [0.0, 1.0, 0.0])

        rigid = mech.rigid_rotation_mode(asm, finding.point, finding.axis)
        assert np.max(np.abs(elongations(asm, rigid))) < 1e-7 * asm.L_c, (
            "rotation about the ground line must stretch no rod"
        )
    # with enough rods the ONLY deficiency is that rotation
    assert mech.check(make_line_supported(n_rods=6, axis="y")).nullity == 1


def test_v8_body_to_body_rods_do_not_help():
    """Explicitly called out in §5.4: the assembly rotates as a rigid unit, so
    adding rods between free bodies cannot remove the mechanism."""
    from conftest import build_assembly, _free, _ground

    specs = []
    for k in range(6):
        t = -6.0 + 2.4 * k
        specs.append(
            {
                "id": f"s{k}",
                "a": ("body_a" if k % 2 else "body_b", (t * 0.6, 3.0, 9.0 + 0.5 * k)),
                "b": ("ground", (t, 0.0, 0.0)),
            }
        )
    for k in range(4):
        specs.append(
            {
                "id": f"tie{k}",
                "a": ("body_a", (1.0 + k, 4.0, 10.0)),
                "b": ("body_b", (-1.0 - k, 2.0, 8.0 + k)),
            }
        )
    a = build_assembly(
        [_free("body_a", (0.0, 3.0, 9.0)), _free("body_b", (0.0, 3.0, 9.0)), _ground()],
        specs,
    )
    asm = assemble(a)
    r = mech.check(a, assembled=asm)
    assert r.nullity >= 1
    assert "collinear_ground" in {f.kind for f in r.findings}
    finding = next(f for f in r.findings if f.kind == "collinear_ground")
    assert _parallel_to(finding.axis, [1.0, 0.0, 0.0])

    # An SVD null basis is arbitrary within the null space, so with nullity > 1
    # the whole-assembly rotation is generally a COMBINATION of the returned
    # modes and appears in none of them. Build it explicitly and show it is a
    # genuine zero-energy motion.
    rigid = mech.rigid_rotation_mode(asm, finding.point, finding.axis)
    assert np.max(np.abs(elongations(asm, rigid))) < 1e-7 * asm.L_c
    # and it turns BOTH bodies identically — a rigid unit
    assert np.allclose(rigid[3:6], rigid[9:12], atol=1e-12)
    assert _parallel_to(rigid[3:6], [1.0, 0.0, 0.0])


# ======================================================================
# V11 — two free bodies, body-to-body rods, N ground rods
# ======================================================================


def test_v11_two_free_bodies_reach_full_rank(two_body):
    r = mech.check(two_body)
    assert r.ok
    assert (r.n_dof, r.rank, r.nullity) == (12, 12, 0)
    assert r.graph.ok and r.graph.unsupported == []
    assert r.modes == []
    assert r.findings == [], "a healthy layout should raise no degeneracy flags"
    assert r.sigma_min > 0.1


def test_v11_the_kernel_solves_it_end_to_end(two_body):
    asm = assemble(two_body)
    F = np.zeros(12)
    F[2], F[8] = -4000.0, -6000.0
    P = -asm.k_d * (asm.G_hat.T @ solve(asm.K, F))
    assert np.max(np.abs(asm.G_hat @ P + F)) < 1e-6


# ======================================================================
# V12 — zero ground bodies is a diagnostic mode, not an error
# ======================================================================


def test_v12_free_free_expects_nullity_exactly_six(free_free):
    r = mech.check(free_free)
    assert r.free_free
    assert r.n_dof == 12
    assert r.nullity == 6
    assert r.expected_nullity == 6
    assert r.ok, "free-free is a legitimate check of internal rigidity, not a failure"
    assert any("free-free" in m.lower() or "no ground" in m.lower() for m in r.messages)
    assert not any("unsupported" in m.lower() for m in r.messages)


def test_v12_free_free_modes_are_the_six_rigid_body_motions(free_free):
    """Both bodies must move together: the six modes span whole-assembly
    translation and rotation, and no mode stretches a rod."""
    asm = assemble(free_free)
    modes = mech.null_modes(asm)
    assert len(modes) == 6
    for mode in modes:
        assert np.max(np.abs(elongations(asm, mode.vector))) < 1e-8 * max(
            1.0, asm.L_c
        )
    M = np.column_stack([m.vector for m in modes])
    assert np.linalg.matrix_rank(M) == 6


def test_v12_an_internally_floppy_free_free_assembly_exceeds_six():
    """The point of the free-free mode: nullity ABOVE six means the
    subassembly is not internally rigid."""
    a = make_free_free()
    del a.rods["h0m"]
    r = mech.check(a)
    assert r.free_free
    assert r.nullity == 7
    assert not r.ok, "one internal mechanism on top of the six rigid-body modes"
    assert any("internally" in m.lower() or "beyond" in m.lower() for m in r.messages)


def test_v12_graph_check_does_not_cry_unsupported_when_there_is_no_ground(free_free):
    """With no ground body at all, 'not connected to ground' is not the useful
    message — free-free is."""
    g = mech.body_graph(free_free)
    assert g.unsupported == []
    assert g.ok


# ======================================================================
# Geometric degeneracy checks (§5.4) — the "why"
# ======================================================================


def test_concurrent_rod_lines_are_identified_with_their_point(concurrent6):
    r = mech.check(concurrent6)
    assert r.nullity == 3
    finding = next(f for f in r.findings if f.kind == "concurrent")
    assert np.allclose(finding.point, [0.0, 0.0, 10.0], atol=1e-7)
    assert "rotation" in finding.message.lower()
    # all three rotations about that point are free
    for mode in r.modes:
        motion = mode.per_body["body"]
        assert np.linalg.norm(motion.theta) > 1e-9


def test_parallel_rod_lines_are_identified_with_their_direction(parallel4):
    r = mech.check(parallel4)
    finding = next(f for f in r.findings if f.kind == "parallel")
    assert _parallel_to(finding.axis, [0.0, 0.0, 1.0])
    assert "perpendicular" in finding.message.lower()
    # nothing reacts a horizontal load: two of the modes are horizontal
    # translations
    trans = [
        m.per_body["body"].d
        for m in r.modes
        if np.linalg.norm(m.per_body["body"].theta) < 1e-7
    ]
    assert len(trans) >= 2
    for d in trans:
        assert abs(d[2]) < 1e-7, "the free translations must be horizontal"


def test_rotary_hexapod_is_caught_even_though_no_named_cause_applies(rotary_hexapod):
    """Documents the boundary of the geometric checks.

    The 6-6 rotary hexapod is rank 3 — six rods all tangent to a common
    hyperboloid — yet it is NOT parallel, NOT concurrent (the best-fit
    concurrency point misses by 9.6 in against L_c = 10) and its ground
    attachments lie on a circle, not a line. None of §5.4's four named causes
    applies, and inventing a message would be worse than staying quiet.

    What must still happen: the layout is caught, and three animatable modes
    are produced. Per §5.3 the animation IS the diagnosis.
    """
    r = mech.check(rotary_hexapod)
    assert r.nullity == 3
    assert not r.ok
    assert len(r.modes) == 3
    assert r.findings == [], "no named geometric cause fits this one"
    assert "rank 3 against 6" in r.summary()

    asm = assemble(rotary_hexapod)
    for mode in r.modes:
        assert np.max(np.abs(elongations(asm, mode.vector))) < 1e-8 * asm.L_c


def test_a_healthy_layout_produces_no_geometric_findings():
    for factory in (make_hexapod, make_symmetric8, make_unit_cage, make_two_body):
        r = mech.check(factory())
        assert r.ok
        assert r.findings == [], f"{factory.__name__} flagged {r.findings}"


def test_tripod_is_reported_as_concurrent_not_merely_singular(tripod):
    r = mech.check(tripod)
    assert r.nullity == 3
    kinds = {f.kind for f in r.findings}
    assert "concurrent" in kinds
    finding = next(f for f in r.findings if f.kind == "concurrent")
    assert np.allclose(finding.point, [0.0, 0.0, 20.0], atol=1e-6), "the apex"


# ======================================================================
# Report shape — this is what the UI renders
# ======================================================================


def test_report_summary_is_plain_language(line_supported, hexapod):
    bad = mech.check(line_supported).summary()
    good = mech.check(make_hexapod()).summary()
    assert isinstance(bad, str) and isinstance(good, str)
    assert bad and good
    assert "1" in bad  # one mechanism mode
    for text in (bad, good):
        assert "ndarray" not in text and "array(" not in text


def test_check_accepts_a_prebuilt_assembled_to_avoid_reassembling(hexapod):
    asm = assemble(hexapod)
    r1 = mech.check(hexapod)
    r2 = mech.check(hexapod, assembled=asm)
    assert (r1.rank, r1.nullity) == (r2.rank, r2.nullity)
    assert r1.sigma_min == pytest.approx(r2.sigma_min)


def test_report_is_deterministic(line_supported):
    a = make_line_supported()
    r1, r2 = mech.check(a), mech.check(a)
    assert r1.messages == r2.messages
    assert [f.kind for f in r1.findings] == [f.kind for f in r2.findings]
    assert np.allclose(
        np.abs(r1.modes[0].vector), np.abs(r2.modes[0].vector), atol=1e-12
    )


# ======================================================================
# Screw motions — a rotation with no stationary line
# ======================================================================


def test_a_screw_mode_is_not_reported_as_a_rotation_about_a_line(screw_motion):
    """A screw advances along its axis as it turns, so no line stays put.
    Naming one would put a false axis in the UI and in the report."""
    from conftest import SCREW_PITCH

    asm = assemble(screw_motion)
    r = mech.check(screw_motion, assembled=asm)
    assert r.nullity == 1 and not r.ok

    mode = r.modes[0]
    motion = mode.per_body["body"]
    axis = motion.theta / np.linalg.norm(motion.theta)

    assert _parallel_to(axis, [0.0, 0.0, 1.0])
    assert not motion.is_pure_translation()
    # it genuinely translates ALONG its own rotation axis — that is the screw
    assert abs(float(motion.d @ axis)) > 1e-6
    assert float(motion.d @ axis) / float(np.linalg.norm(motion.theta)) == pytest.approx(
        SCREW_PITCH, rel=1e-6
    ), "recovered pitch must match the constructed one"

    assert motion.axis_line(asm.body_datums["body"]) is None, "a screw has no fixed line"
    assert mode.common_axis() is None
    # and no geometric finding should claim otherwise
    assert not any(f.kind in ("common_line", "collinear_ground") for f in r.findings)


def test_a_pure_rotation_is_still_recognised_next_to_the_screw_case(line_supported):
    """Guard against 'fixing' the screw case by refusing every axis."""
    mode = mech.null_modes(assemble(line_supported))[0]
    assert mode.common_axis() is not None
