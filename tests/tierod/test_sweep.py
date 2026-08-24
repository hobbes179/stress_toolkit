"""
tests/tierod/test_sweep.py — Session 5 gate, orientation-sweep half.

Gates here:

  * **V15** — the closed-form envelope vs a densely sampled sphere. This is the
    test that justifies not sampling at all. `F` is linear in the unit
    direction `n_hat`, so `max|P_i| = ||row_i(T)||_2` exactly; a dense sample
    must approach that value from below and never cross it.
  * **V17** — the *enumerated* 26-direction set is a readable SAMPLE, not the
    envelope. Its per-rod maximum must be <= the closed form for every rod, and
    the closed-form direction must reproduce the row norm exactly. Reporting
    the enumerated maximum as the envelope would under-predict by up to 11%
    (the cube26 set's worst coverage gap is 27.6 degrees).

Also gated, because they are the assumptions the closed form rests on:

  * `T = G W` must agree with actually solving `K U = F` case by case. If the
    influence matrix and the direct solve ever disagree the sweep is fiction.
  * a symmetric direction set drives every rod to BOTH +||t|| and -||t||, so
    only `min(tension allowable, compression allowable)` matters (§7.2).
  * the rod mask (Phase 3's failure states) is a column deletion of `Ghat`,
    not a re-assembly, and must not silently return loads for a masked rod.
"""
from __future__ import annotations

import numpy as np
import pytest

from library.tierod import allowables as al
from library.tierod import sweep as sw
from library.tierod.cases import direction_matrix, generate_cases, nearest_case
from library.tierod.kernel import SingularAssemblyError, assemble, rod_loads, solve

from conftest import (
    make_hexapod,
    make_symmetric8,
    make_two_body,
    make_unit_cage,
)


def _fibonacci_sphere(n: int) -> np.ndarray:
    """(3, n) near-uniform unit directions. Deterministic — no seed to drift."""
    i = np.arange(n, dtype=float) + 0.5
    phi = np.arccos(1.0 - 2.0 * i / n)
    theta = np.pi * (1.0 + 5.0**0.5) * i
    return np.vstack(
        [np.cos(theta) * np.sin(phi), np.sin(theta) * np.sin(phi), np.cos(phi)]
    )


# ======================================================================
# T = G W  — the sweep must agree with the kernel it claims to summarize
# ======================================================================


def test_transfer_matrix_matches_a_direct_solve_for_every_case():
    """The single highest-value test in this file: the whole sweep is one
    matmul, and this is the only thing standing between that shortcut and a
    plausible-looking wrong answer."""
    a = make_two_body()
    asm = assemble(a)
    T = sw.transfer_matrix(a, asm)
    W = a.sweep_map()

    for case in generate_cases():
        P_sweep = T @ case.direction * case.factor
        P_direct = rod_loads(asm, solve(asm.K, case.load(W)))
        assert np.allclose(P_sweep, P_direct, rtol=1e-9, atol=1e-9)


def test_transfer_matrix_is_n_rods_by_three():
    a = make_hexapod()
    T = sw.transfer_matrix(a)
    assert T.shape == (len(a.rods), 3)


def test_case_loads_are_one_matmul_over_the_direction_matrix():
    a = make_hexapod()
    cases = generate_cases()
    T = sw.transfer_matrix(a)
    P = sw.case_loads(T, cases)
    assert P.shape == (len(a.rods), len(cases))
    assert np.allclose(P, T @ direction_matrix(cases, weighted=True))


def test_every_enumerated_case_satisfies_equilibrium():
    a = make_two_body()
    asm = assemble(a)
    W = a.sweep_map()
    T = sw.transfer_matrix(a, asm)
    for case in generate_cases():
        P = T @ case.direction * case.factor
        residual = asm.G_hat @ P + case.load(W)
        assert np.max(np.abs(residual)) < 1e-6 * max(1.0, np.max(np.abs(P)))


def test_a_case_factor_scales_the_load_and_not_the_direction():
    a = make_hexapod()
    T = sw.transfer_matrix(a)
    base = generate_cases(factor=1.0)
    doubled = generate_cases(factor=2.0)
    assert np.allclose(
        sw.case_loads(T, doubled), 2.0 * sw.case_loads(T, base)
    )
    assert all(
        np.isclose(np.linalg.norm(c.direction), 1.0) for c in doubled
    )


def test_ground_bodies_contribute_no_inertial_load():
    """The demo's baseplate keeps a mass and a g_factor while grounded. If that
    leaked into W the whole sweep would be wrong by the heaviest body."""
    a = make_hexapod()
    a.bodies["ground"].mass = 5000.0
    a.bodies["ground"].g_factor = 9.0
    T_with = sw.transfer_matrix(a)
    a.bodies["ground"].mass = 0.0
    assert np.allclose(T_with, sw.transfer_matrix(a))


def test_the_sweep_is_independent_of_ae_scaling_when_determinate():
    """V4 seen through the sweep: a determinate layout's loads come from
    equilibrium alone, so the envelope cannot depend on rod stiffness."""
    rng = np.random.default_rng(4)
    base = sw.envelope(sw.transfer_matrix(make_unit_cage()))
    for _ in range(10):
        scale = {rid: float(rng.uniform(0.2, 5.0)) for rid in make_unit_cage().rods}
        a = make_unit_cage()
        for rid, s in scale.items():
            a.rods[rid].A *= s
        got = sw.envelope(sw.transfer_matrix(a))
        assert np.allclose(got.magnitudes, base.magnitudes, rtol=1e-9)


# ======================================================================
# V17 — enumerated set vs closed form
# ======================================================================


def test_v17_no_enumerated_case_exceeds_the_closed_form():
    for build in (make_hexapod, make_symmetric8, make_two_body):
        a = build()
        T = sw.transfer_matrix(a)
        env = sw.envelope(T)
        P = sw.case_loads(T, generate_cases())
        worst = np.max(np.abs(P), axis=1)
        assert np.all(worst <= env.magnitudes * (1.0 + 1e-12)), build.__name__


def test_v17_the_closed_form_direction_reproduces_the_row_norm_exactly():
    a = make_two_body()
    T = sw.transfer_matrix(a)
    env = sw.envelope(T)
    for i in range(T.shape[0]):
        assert np.isclose(np.linalg.norm(env.directions[:, i]), 1.0)
        assert T[i] @ env.directions[:, i] == pytest.approx(
            env.magnitudes[i], rel=1e-12
        )


def test_v17_the_enumerated_sample_genuinely_under_predicts_somewhere():
    """If the enumerated max always equalled the closed form the previous test
    would be vacuous. On a real layout the 26-direction set misses."""
    a = make_two_body()
    T = sw.transfer_matrix(a)
    env = sw.envelope(T)
    worst = np.max(np.abs(sw.case_loads(T, generate_cases())), axis=1)
    shortfall = 1.0 - worst / env.magnitudes
    assert np.max(shortfall) > 0.01, "expected the coarse sample to fall short"


def test_the_worst_direction_is_labelled_by_the_nearest_enumerated_case():
    a = make_hexapod()
    env = sw.envelope(sw.transfer_matrix(a))
    cases = generate_cases()
    labels = sw.label_directions(env, cases)
    assert len(labels) == len(a.rods)
    for i, (name, angle) in enumerate(labels):
        expected_case, expected_angle = nearest_case(cases, env.directions[:, i])
        assert name == expected_case.name
        assert angle == pytest.approx(expected_angle)
        assert 0.0 <= angle <= 90.0


# ======================================================================
# V15 — closed form vs a dense sampled sphere
# ======================================================================


def test_v15_dense_sampling_converges_to_the_closed_form_from_below():
    a = make_two_body()
    T = sw.transfer_matrix(a)
    env = sw.envelope(T)

    N = _fibonacci_sphere(40000)
    sampled = np.max(np.abs(T @ N), axis=1)

    assert np.all(sampled <= env.magnitudes * (1.0 + 1e-12)), "sampling exceeded the bound"
    assert np.allclose(sampled, env.magnitudes, rtol=2e-4)


def test_v15_the_sampled_maximum_tightens_as_the_sample_refines():
    a = make_hexapod()
    T = sw.transfer_matrix(a)
    env = sw.envelope(T)
    gaps = []
    for n in (200, 2000, 20000):
        sampled = np.max(np.abs(T @ _fibonacci_sphere(n)), axis=1)
        gaps.append(float(np.max(1.0 - sampled / env.magnitudes)))
    assert gaps[0] > gaps[1] > gaps[2]
    assert gaps[-1] < 1e-4


def test_v15_no_random_direction_ever_beats_the_closed_form():
    rng = np.random.default_rng(15)
    a = make_symmetric8()
    T = sw.transfer_matrix(a)
    env = sw.envelope(T)
    D = rng.normal(size=(3, 5000))
    D /= np.linalg.norm(D, axis=0)
    assert np.all(np.abs(T @ D) <= env.magnitudes[:, None] * (1.0 + 1e-12))


def test_both_senses_of_the_envelope_are_attainable():
    """n_hat* and -n_hat* are both unit directions, so a full sweep loads every
    rod to +||t|| AND -||t||. That is why only the weaker allowable matters."""
    a = make_hexapod()
    T = sw.transfer_matrix(a)
    env = sw.envelope(T)
    assert np.allclose(T @ env.directions[:, 0] * -1.0, -T @ env.directions[:, 0])
    for i in range(T.shape[0]):
        assert T[i] @ (-env.directions[:, i]) == pytest.approx(-env.magnitudes[i])


def test_a_rod_that_carries_no_load_has_a_zero_envelope_and_no_direction():
    """A zero row of T has no worst direction. It must not produce a NaN unit
    vector that then poisons nearest_case."""
    a = make_unit_cage()
    for body in a.bodies.values():
        body.mass = 0.0
    env = sw.envelope(sw.transfer_matrix(a))
    assert np.allclose(env.magnitudes, 0.0)
    assert np.all(np.isfinite(env.directions))


# ======================================================================
# Rod mask — Phase 3's failure states as a parameter, not a rewrite
# ======================================================================


def test_masking_a_rod_drops_its_column_and_reroutes_the_load():
    a = make_symmetric8()
    full = sw.transfer_matrix(a)
    masked = sw.transfer_matrix(a, active_rods=[r for r in a.rods if r != "brace0"])

    assert masked.shape == (len(a.rods) - 1, 3)
    kept = [r for r in a.rods if r != "brace0"]
    idx = {rid: i for i, rid in enumerate(a.rods)}
    # the surviving rods pick the load up — the layout is redundant, so at
    # least one of them must change
    before = np.array([full[idx[r]] for r in kept])
    assert not np.allclose(before, masked)


def test_a_masked_rod_never_appears_in_the_results():
    a = make_symmetric8()
    result = sw.run_sweep(a, active_rods=[r for r in a.rods if r != "leg2"])
    assert "leg2" not in result.rod_ids
    assert all(row.rod_id != "leg2" for row in result.rows)


def test_masking_down_to_a_mechanism_raises_rather_than_returning_numbers():
    a = make_hexapod()
    with pytest.raises(SingularAssemblyError):
        sw.transfer_matrix(a, active_rods=[r for r in a.rods][:5])


def test_masking_preserves_the_characteristic_length():
    """L_c describes the GEOMETRY, not the surviving rod set. If it shrank with
    the mask, rank checks across failure states would not be comparable."""
    a = make_symmetric8()
    asm = assemble(a)
    masked = sw.mask_assembled(asm, ["leg0", "leg1", "leg2", "leg3", "brace0", "brace1", "brace2"])
    assert masked.L_c == asm.L_c
    assert masked.body_order == asm.body_order
    assert masked.n_rods == 7


def test_an_unknown_rod_in_the_mask_is_an_error():
    a = make_hexapod()
    with pytest.raises(KeyError):
        sw.transfer_matrix(a, active_rods=["not_a_rod"])


def test_an_empty_mask_is_an_error_not_an_empty_answer():
    a = make_hexapod()
    with pytest.raises((ValueError, SingularAssemblyError)):
        sw.transfer_matrix(a, active_rods=[])


# ======================================================================
# run_sweep — the reportable result
# ======================================================================


def _steel(a):
    """Give every rod a complete strength definition."""
    for rod in a.rods.values():
        rod.Ftu, rod.Fty, rod.A_net = 180.0e3, 160.0e3, 0.08
    return a


def test_run_sweep_reports_one_row_per_rod_sorted_by_load_ratio():
    result = sw.run_sweep(_steel(make_two_body()))
    assert len(result.rows) == len(result.rod_ids)
    ratios = [r.load_ratio for r in result.rows]
    assert ratios == sorted(ratios, reverse=True)
    assert result.rows[0] is result.governing_row


def test_each_row_carries_the_closed_form_value_not_the_enumerated_one():
    a = _steel(make_two_body())
    result = sw.run_sweep(a)
    env = sw.envelope(sw.transfer_matrix(a))
    for i, row in enumerate(sorted(result.rows, key=lambda r: result.rod_ids.index(r.rod_id))):
        assert row.P_envelope == pytest.approx(env.magnitudes[i])
        assert row.P_enumerated <= row.P_envelope * (1.0 + 1e-12)


def test_margins_agree_with_the_allowables_module():
    a = _steel(make_two_body())
    result = sw.run_sweep(a, factors=al.SafetyFactors(ultimate=1.5, yield_=1.0))
    for row in result.rows:
        assert row.margin == pytest.approx(al.margin_of_safety(row.load_ratio))
        assert row.sense in ("T", "C")


def test_the_safety_factor_moves_every_margin():
    a = _steel(make_hexapod())
    loose = sw.run_sweep(a, factors=al.SafetyFactors(ultimate=1.0, yield_=1.0))
    tight = sw.run_sweep(a, factors=al.SafetyFactors(ultimate=1.5, yield_=1.0))
    by_id = {r.rod_id: r for r in loose.rows}
    for row in tight.rows:
        assert row.load_ratio >= by_id[row.rod_id].load_ratio - 1e-12


def test_a_rod_with_no_tension_source_is_named_not_quietly_half_checked():
    """Fcy is required, so a rod with no Ftu / A_net / vendor rating still
    produces a margin — off the compression side alone. That number is not
    wrong, it is INCOMPLETE, and in a table the two are indistinguishable."""
    a = make_hexapod()
    for rod in a.rods.values():
        rod.Ftu = rod.A_net = rod.P_tension_allow = rod.Fty = None

    result = sw.run_sweep(a)
    assert sorted(result.incomplete_rods) == sorted(a.rods)
    assert all(row.load_ratio is not None for row in result.rows)
    assert all(row.sense == "C" for row in result.rows)

    _steel(a)
    assert sw.run_sweep(a).incomplete_rods == []


def test_a_rod_that_is_not_even_a_column_is_listed_and_gets_no_row():
    a = _steel(make_hexapod())
    a.rods["h0m"].Fcy = None
    result = sw.run_sweep(a)
    assert "h0m" in result.incomplete_rods
    assert all(row.rod_id != "h0m" for row in result.rows)


def test_the_result_exposes_the_case_table_for_display():
    a = _steel(make_hexapod())
    result = sw.run_sweep(a)
    assert result.P_cases.shape == (len(a.rods), len(result.cases))
    assert result.load_ratios().keys() == set(a.rods)


def test_a_custom_direction_set_flows_through_untouched():
    """Nothing downstream may branch on which direction set is in use."""
    from library.tierod.cases import cases_from_directions

    a = _steel(make_hexapod())
    custom = cases_from_directions(_fibonacci_sphere(37).T)
    result = sw.run_sweep(a, cases=custom)
    assert result.P_cases.shape == (len(a.rods), 37)
    # the closed form is a property of the geometry, not the sample
    assert np.allclose(
        [r.P_envelope for r in sorted(result.rows, key=lambda r: r.rod_id)],
        [r.P_envelope for r in sorted(sw.run_sweep(a).rows, key=lambda r: r.rod_id)],
    )


def test_a_mechanism_is_reported_as_a_mechanism_not_a_margin():
    from conftest import make_five_rod

    with pytest.raises(SingularAssemblyError):
        sw.run_sweep(make_five_rod())


# ======================================================================
# The inertial arm is R @ cg, not cg
# ======================================================================


def _rot_x(deg: float) -> np.ndarray:
    c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])


def _hexapod_with_frame(R: np.ndarray, cg_offset: np.ndarray):
    """The same physical hexapod, its free body expressed in frame `R`.

    `cg_offset` is the GLOBAL offset from the datum to the CG, so the physical
    layout is identical in every case and only the bookkeeping frame changes.
    """
    from conftest import Body, _ground, _hex_pairs, build_assembly

    body = Body(
        id="body", origin=np.array([0.0, 0.0, 8.0]), R=R,
        mass=200.0, cg=R.T @ cg_offset, g_factor=6.0,
    )
    specs = [
        {"id": f"h{k}", "a": ("body", a), "b": ("ground", b)}
        for k, (a, b) in enumerate(_hex_pairs(0.0))
    ]
    return build_assembly([body, _ground()], specs)


def test_a_rotated_body_frame_leaves_every_rod_load_unchanged():
    """`cg` is stored body-local, but the load direction and Ghat's moment rows
    are both global about the datum — so the inertial moment arm has to be
    `R @ cg`. Re-expressing one physical layout in a turned frame must not move
    a single rod load. With `R = I` (every example so far) the two forms agree,
    which is why this needs a rotated fixture to catch."""
    cg_offset = np.array([0.7, -1.3, 2.1])
    plain = _hexapod_with_frame(np.eye(3), cg_offset)
    turned = _hexapod_with_frame(_rot_x(40.0), cg_offset)

    assert not np.allclose(plain.bodies["body"].cg, turned.bodies["body"].cg)
    assert np.allclose(
        sw.transfer_matrix(plain), sw.transfer_matrix(turned), atol=1e-9
    )


def test_the_inertial_arm_is_the_global_offset_to_the_cg():
    from library.tierod.model import skew

    R = _rot_x(40.0)
    cg_offset = np.array([0.7, -1.3, 2.1])
    body = _hexapod_with_frame(R, cg_offset).bodies["body"]
    W = body.sweep_map() if hasattr(body, "sweep_map") else body.sweep_block()
    assert np.allclose(W[:3], body.mass * body.g_factor * np.eye(3))
    assert np.allclose(W[3:], body.mass * body.g_factor * skew(cg_offset))
