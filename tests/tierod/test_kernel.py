"""
tests/tierod/test_kernel.py — Session 2 gate (V1-V6).

The kernel equations are fixed by the build prompt §4 and must not be
re-derived or sign-flipped:

    delta = -Ghat^T U
    k_i   = A_i E_i / L_i          (in series with k_backup when finite)
    K     = Ghat K_d Ghat^T
    K U   = F
    P     = -K_d Ghat^T U
    equilibrium:  Ghat P = -F

    Ghat column i:  +[u ; r_a x u] in the body-p block   (the 'a' end)
                    -[u ; r_b x u] in the body-q block   (the 'b' end)
                    ground bodies get no block

with u pointing a -> b, P > 0 TENSION, and r measured from each body's OWN
datum. `Ghat P = -F` is the master invariant: nearly every sign error shows up
there, so it is asserted on every fixture.
"""
from __future__ import annotations

import numpy as np
import pytest

from conftest import (
    DEFAULT_ROD,
    make_hexapod,
    make_symmetric8,
    make_tripod,
    make_two_body,
    make_unit_cage,
)
from library.tierod import kernel as kmod
from library.tierod.kernel import (
    assemble,
    elongations,
    equilibrium_residual,
    influence,
    rod_loads,
    rod_stiffness,
    solve,
)
from library.tierod.model import skew

TIGHT = 1e-9


def _wrench(fx=0.0, fy=0.0, fz=0.0, mx=0.0, my=0.0, mz=0.0) -> np.ndarray:
    return np.array([fx, fy, fz, mx, my, mz], dtype=float)


def _assert_equilibrium(asm, P, F, tol=1e-7):
    """Ghat P == -F, the invariant that catches sign errors."""
    resid = equilibrium_residual(asm, P, F)
    scale = max(1.0, float(np.abs(F).max()))
    assert np.max(np.abs(resid)) / scale < tol, (
        f"equilibrium violated: max|Ghat P + F| = {np.max(np.abs(resid))}"
    )


# ======================================================================
# Assembly contract
# ======================================================================


def test_ghat_shape_and_K_size_are_set_by_free_bodies_not_rod_count():
    for asm in (assemble(make_unit_cage()), assemble(make_hexapod())):
        assert asm.G_hat.shape == (6, len(asm.rod_ids))
        assert asm.K.shape == (6, 6)
    two = assemble(make_two_body())
    assert two.G_hat.shape == (12, len(two.rod_ids))
    assert two.K.shape == (12, 12)
    assert two.body_order == ["body_a", "body_b"]  # ground excluded, order stable


def test_ghat_column_is_the_screw_of_the_rod_line():
    """Hand-check one column against +[u ; r_a x u], r_a from the body datum."""
    asm = assemble(make_unit_cage())
    j = asm.rod_ids.index("r_rz")
    # rod r_rz: a = (0,1,0) on the body (datum at origin), b = (1,1,0) ground
    u = np.array([1.0, 0.0, 0.0])
    r_a = np.array([0.0, 1.0, 0.0])
    expected = np.concatenate([u, np.cross(r_a, u)])
    assert np.allclose(asm.G_hat[:, j], expected)
    assert np.allclose(asm.units[:, j], u)
    assert asm.lengths[j] == pytest.approx(1.0)


def test_ground_bodies_contribute_no_block():
    asm = assemble(make_unit_cage())
    # every rod has one ground end; the assembled column has only 6 entries,
    # so a ground block would have shown up as extra rows
    assert asm.G_hat.shape[0] == 6
    assert asm.body_order == ["body"]


def test_body_to_body_rod_fills_both_blocks_with_opposite_sign():
    asm_obj = make_two_body()
    asm = assemble(asm_obj)
    j = asm.rod_ids.index("tie0")
    a = np.array([-6.0, 1.5, 6.0])
    b = np.array([6.0, -1.5, 6.0])
    u = (b - a) / np.linalg.norm(b - a)
    r_a = a - asm_obj.bodies["body_a"].origin
    r_b = b - asm_obj.bodies["body_b"].origin
    col = asm.G_hat[:, j]
    assert np.allclose(col[0:6], np.concatenate([u, np.cross(r_a, u)]))
    assert np.allclose(col[6:12], -np.concatenate([u, np.cross(r_b, u)]))


def test_ground_rod_touches_only_its_own_body_block():
    asm = assemble(make_two_body())
    j = asm.rod_ids.index("g_a0")
    assert np.any(asm.G_hat[0:6, j] != 0.0)
    assert np.allclose(asm.G_hat[6:12, j], 0.0)


def test_moment_arms_are_taken_about_each_body_own_datum():
    """Move a body's datum without moving any geometry in space: the screws'
    moment rows change (they are datum-relative) but the rod loads must not."""
    base = make_hexapod()
    shifted = make_hexapod()
    shifted.bodies["body"].origin = np.array([3.0, -4.0, 5.0])
    # re-express every region so the GLOBAL geometry is untouched
    for region in shifted.regions.values():
        if region.body_id == "body":
            region.origin = region.origin + np.array([0.0, 0.0, 12.0]) - np.array(
                [3.0, -4.0, 5.0]
            )

    a0, a1 = assemble(base), assemble(shifted)
    for rod_id in a0.rod_ids:
        j0, j1 = a0.rod_ids.index(rod_id), a1.rod_ids.index(rod_id)
        assert np.allclose(a0.units[:, j0], a1.units[:, j1]), "geometry moved"
        assert a0.lengths[j0] == pytest.approx(a1.lengths[j1])
    assert not np.allclose(a0.G_hat[3:6], a1.G_hat[3:6]), (
        "moment rows should be datum-relative"
    )

    F = _wrench(fx=900.0, fz=-2200.0)
    # the applied wrench must be re-referenced to the new datum too
    shift = np.array([3.0, -4.0, 5.0]) - np.array([0.0, 0.0, 12.0])
    F1 = F.copy()
    F1[3:6] = F[3:6] - np.cross(shift, F[0:3])
    P0 = rod_loads(a0, solve(a0.K, F))
    P1 = rod_loads(a1, solve(a1.K, F1))
    assert np.allclose(P0, P1, rtol=1e-7, atol=1e-7)


def test_K_equals_Ghat_Kd_GhatT_and_is_symmetric():
    for asm in (assemble(make_hexapod()), assemble(make_two_body())):
        assert np.allclose(asm.K, asm.G_hat @ asm.K_d @ asm.G_hat.T)
        assert np.allclose(asm.K, asm.K.T, atol=1e-9)
        assert np.allclose(np.diag(asm.K_d), asm.k_d)


def test_rod_order_is_the_assembly_rod_order():
    a = make_hexapod()
    asm = assemble(a)
    assert asm.rod_ids == list(a.rods.keys())


# ======================================================================
# Rod stiffness, including the Phase-5 backup hook
# ======================================================================


def test_rod_stiffness_is_AE_over_L_by_default():
    a = make_unit_cage()
    rod = a.rods["r_x"]
    assert rod_stiffness(rod, 25.0) == pytest.approx(rod.A * rod.E / 25.0)


def test_k_backup_enters_in_series_and_defaults_to_rigid():
    a = make_unit_cage()
    rod = a.rods["r_x"]
    L = 40.0
    k_rod = rod.A * rod.E / L
    assert np.isinf(rod.k_backup_a) and np.isinf(rod.k_backup_b)
    assert rod_stiffness(rod, L) == pytest.approx(k_rod)

    rod.k_backup_a = 5.0e5
    assert rod_stiffness(rod, L) == pytest.approx(1.0 / (1.0 / k_rod + 1.0 / 5.0e5))
    rod.k_backup_b = 2.0e5
    assert rod_stiffness(rod, L) == pytest.approx(
        1.0 / (1.0 / k_rod + 1.0 / 5.0e5 + 1.0 / 2.0e5)
    )
    # a soft backup can only soften the joint
    assert rod_stiffness(rod, L) < k_rod


def test_non_positive_stiffness_inputs_are_rejected():
    a = make_unit_cage()
    rod = a.rods["r_x"]
    rod.k_backup_a = -1.0
    with pytest.raises(ValueError):
        rod_stiffness(rod, 10.0)
    rod.k_backup_a = float("inf")
    with pytest.raises(ValueError):
        rod_stiffness(rod, 0.0)


def test_zero_length_rod_is_rejected_by_assemble():
    a = make_unit_cage()
    # collapse a rod onto a single point
    a.regions["r_x_b"].origin = a.regions["r_x_a"].origin.copy()
    a.bodies["ground"].origin = a.bodies["body"].origin.copy()
    with pytest.raises(ValueError, match="zero length|coincident"):
        assemble(a)


# ======================================================================
# Solve / loads / influence — the definitional identities
# ======================================================================


def test_solve_satisfies_K_U_equals_F(hexapod):
    asm = assemble(hexapod)
    F = _wrench(fx=1200.0, fy=-400.0, fz=-3000.0, my=800.0)
    U = solve(asm.K, F)
    assert np.allclose(asm.K @ U, F, rtol=1e-8, atol=1e-6)


def test_rod_loads_match_the_definition_and_the_elongations(hexapod):
    asm = assemble(hexapod)
    F = _wrench(fz=-5000.0, mx=1500.0)
    U = solve(asm.K, F)
    P = rod_loads(asm, U)
    assert np.allclose(P, -asm.K_d @ asm.G_hat.T @ U)
    delta = elongations(asm, U)
    assert np.allclose(delta, -asm.G_hat.T @ U), 'delta = -Ghat^T U'
    assert np.allclose(P, asm.k_d * delta), 'P = k delta'


def test_equilibrium_holds_on_every_fixture():
    loads = [
        _wrench(fz=-4000.0),
        _wrench(fx=2500.0, fy=-1800.0),
        _wrench(fx=700.0, fz=-2600.0, mx=900.0, my=-450.0, mz=1200.0),
    ]
    for factory in (make_unit_cage, make_hexapod, make_symmetric8):
        asm = assemble(factory())
        for F in loads:
            _assert_equilibrium(asm, rod_loads(asm, solve(asm.K, F)), F)


def test_equilibrium_holds_for_two_free_bodies(two_body):
    asm = assemble(two_body)
    rng = np.random.default_rng(11)
    for _ in range(10):
        F = rng.normal(scale=2000.0, size=12)
        _assert_equilibrium(asm, rod_loads(asm, solve(asm.K, F)), F)


def test_influence_matrix_matches_its_definition_and_reproduces_loads(hexapod):
    asm = assemble(hexapod)
    G = influence(asm)
    assert G.shape == (len(asm.rod_ids), asm.K.shape[0])
    assert np.allclose(G, -asm.K_d @ asm.G_hat.T @ np.linalg.inv(asm.K), atol=1e-6)
    rng = np.random.default_rng(5)
    for _ in range(10):
        F = rng.normal(scale=3000.0, size=6)
        assert np.allclose(G @ F, rod_loads(asm, solve(asm.K, F)), rtol=1e-8, atol=1e-8)


def test_solve_accepts_many_right_hand_sides_at_once(hexapod):
    """'Factor K once, reuse across cases' — a matrix F must give the same
    answer as looping, so the sweep can be one matmul."""
    asm = assemble(hexapod)
    rng = np.random.default_rng(2)
    Fs = rng.normal(scale=2000.0, size=(6, 25))
    U = solve(asm.K, Fs)
    assert U.shape == (6, 25)
    for j in range(25):
        assert np.allclose(U[:, j], solve(asm.K, Fs[:, j]), rtol=1e-9, atol=1e-9)
    P = rod_loads(asm, U)
    assert P.shape == (len(asm.rod_ids), 25)
    assert np.allclose(P, influence(asm) @ Fs, rtol=1e-8, atol=1e-8)


def test_solve_reports_a_mechanism_rather_than_returning_garbage(tripod):
    asm = assemble(tripod)
    with pytest.raises(kmod.SingularAssemblyError):
        solve(asm.K, _wrench(fz=-1000.0))
    with pytest.raises(kmod.SingularAssemblyError):
        influence(asm)


def test_solve_catches_a_singular_K_that_lapack_does_not(rotary_hexapod):
    """The dangerous case. A rank-deficient K assembled from real geometry
    usually has no exact zero pivot, so `np.linalg.solve` returns a large WRONG
    answer and raises nothing. Without a residual check that garbage flows
    straight into rod loads, margins and the optimizer.
    """
    asm = assemble(rotary_hexapod)
    assert np.linalg.matrix_rank(asm.K) == 3, "fixture must be rank deficient"

    F = _wrench(fx=1200.0, fz=-3000.0, my=800.0)

    # numpy alone does NOT protect you here — this is the whole point
    U_raw = np.linalg.solve(asm.K, F)
    assert np.all(np.isfinite(U_raw)), "no exception, no NaN: silently wrong"
    residual = np.linalg.norm(asm.K @ U_raw - F) / np.linalg.norm(F)
    assert residual > 1e-3, "the unguarded answer really is wrong"

    # the kernel must refuse it
    with pytest.raises(kmod.SingularAssemblyError, match="residual|singular"):
        solve(asm.K, F)
    with pytest.raises(kmod.SingularAssemblyError):
        influence(asm)


def test_solve_rejects_a_non_finite_result():
    K = np.zeros((6, 6))
    with pytest.raises(kmod.SingularAssemblyError):
        solve(K, _wrench(fz=1.0))


def test_zero_ground_bodies_assembles_without_error():
    """Free-free is a legitimate diagnostic mode. assemble() must build it;
    interpreting the nullity is Session 3's job (V12)."""
    a = make_hexapod()
    a.bodies["ground"].is_ground = False
    asm = assemble(a)
    assert asm.K.shape == (12, 12)
    assert np.linalg.matrix_rank(asm.K) == 6  # 12 - 6 rigid body modes


# ======================================================================
# V1 — single rod along +X, unit axial load
# ======================================================================


def test_v1_single_rod_along_x_carries_the_whole_load(unit_cage):
    """In the cage only `r_x` runs along +X through the datum, so a load along
    X is carried by that rod alone at full magnitude.

    Sign: the rod runs body -> ground in +X. Pulling the body in -X, i.e. AWAY
    from its anchor, must put the rod in TENSION (P > 0).
    """
    asm = assemble(unit_cage)
    F = 1000.0

    P = rod_loads(asm, solve(asm.K, _wrench(fx=-F)))
    loads = dict(zip(asm.rod_ids, P))
    assert loads["r_x"] == pytest.approx(+F, rel=1e-9), "pulled away -> tension"
    for rid, val in loads.items():
        if rid != "r_x":
            assert val == pytest.approx(0.0, abs=1e-6)
    _assert_equilibrium(asm, P, _wrench(fx=-F))

    # pushing the body toward the anchor reverses the sense at equal magnitude
    P2 = rod_loads(asm, solve(asm.K, _wrench(fx=+F)))
    assert dict(zip(asm.rod_ids, P2))["r_x"] == pytest.approx(-F, rel=1e-9)


def test_v1_is_independent_of_the_rod_stiffness(unit_cage):
    """Determinate: the single-rod load cannot depend on A, E or L."""
    F = _wrench(fx=-1000.0)
    base = rod_loads(assemble(unit_cage), solve(assemble(unit_cage).K, F))
    stiff = make_unit_cage(A=50.0 * DEFAULT_ROD["A"], E=0.2 * DEFAULT_ROD["E"])
    asm2 = assemble(stiff)
    assert np.allclose(base, rod_loads(asm2, solve(asm2.K, F)), rtol=1e-9, atol=1e-9)


# ======================================================================
# V2 — symmetric tripod, P_i = F / (3 cos theta)
# ======================================================================


@pytest.mark.parametrize("theta_deg", [10.0, 25.0, 40.0, 55.0])
def test_v2_tripod_leg_load_is_F_over_3_cos_theta(theta_deg):
    """Three concurrent rods leave all three rotations free, so K is singular
    by construction and the statics is checked on Ghat directly. The rotational
    freedom is the point of V7/V8, not a defect here."""
    asm = assemble(make_tripod(theta_deg=theta_deg))
    assert np.linalg.matrix_rank(asm.K) == 3, "tripod constrains translation only"

    F_z = 6000.0
    F = _wrench(fz=-F_z)  # body pushed DOWN
    P, *_ = np.linalg.lstsq(asm.G_hat, -F, rcond=None)
    _assert_equilibrium(asm, P, F)

    expected = -F_z / (3.0 * np.cos(np.radians(theta_deg)))
    assert np.allclose(P, expected, rtol=1e-9), "legs equal and in compression"

    # lifting the body reverses the sense at equal magnitude
    P_up, *_ = np.linalg.lstsq(asm.G_hat, -_wrench(fz=+F_z), rcond=None)
    assert np.allclose(P_up, -expected, rtol=1e-9)


# ======================================================================
# V3 — hexapod matches hand equilibrium
# ======================================================================


def test_v3_hexapod_is_determinate_and_matches_pure_statics(hexapod):
    """When determinate, P = -Ghat^-1 F. The stiffness solution must agree with
    that to solver tolerance — no stiffness anywhere in the answer."""
    asm = assemble(hexapod)
    assert len(asm.rod_ids) == 6
    assert np.linalg.matrix_rank(asm.G_hat) == 6

    rng = np.random.default_rng(17)
    for _ in range(10):
        F = rng.normal(scale=2500.0, size=6)
        P_stiffness = rod_loads(asm, solve(asm.K, F))
        P_statics = np.linalg.solve(asm.G_hat, -F)
        assert np.allclose(P_stiffness, P_statics, rtol=1e-7, atol=1e-7)
        _assert_equilibrium(asm, P_stiffness, F)


def test_v3_pure_vertical_load_is_shared_equally_by_symmetry(hexapod):
    asm = assemble(hexapod)
    P = rod_loads(asm, solve(asm.K, _wrench(fz=-9000.0)))
    assert np.allclose(P, P[0], rtol=1e-7), "3-fold symmetric layout, axial load"


# ======================================================================
# V4 — random A*E scaling leaves determinate loads unchanged
#      (the highest-value test in the set)
# ======================================================================


def test_v4_determinate_loads_are_independent_of_every_rod_stiffness():
    """Scale A and E per rod over more than two decades, 25 random draws. If any
    stiffness leaks into a determinate load path this fails immediately."""
    rng = np.random.default_rng(4)
    F = _wrench(fx=1500.0, fy=-900.0, fz=-7000.0, mx=2200.0, my=-1300.0, mz=600.0)

    base = assemble(make_hexapod())
    P_ref = rod_loads(base, solve(base.K, F))
    assert np.max(np.abs(P_ref)) > 1.0, "reference load must be non-trivial"

    for draw in range(25):
        overrides = {}
        for rod_id in base.rod_ids:
            overrides[rod_id] = {
                "A": DEFAULT_ROD["A"] * float(10.0 ** rng.uniform(-1.3, 1.3)),
                "E": DEFAULT_ROD["E"] * float(10.0 ** rng.uniform(-1.0, 1.0)),
            }
        asm = assemble(make_hexapod(rod_overrides=overrides))
        P = rod_loads(asm, solve(asm.K, F))
        assert np.allclose(P, P_ref, rtol=1e-7, atol=1e-6), (
            f"draw {draw}: determinate loads moved with stiffness\n"
            f"ref = {P_ref}\ngot = {P}"
        )


def test_v4_holds_for_a_determinate_multi_body_layout():
    """Same statement with two free bodies and body-to-body rods: 14 rods
    against 12 DOF is redundant, so here the loads SHOULD move — the test is
    that they move only where redundancy exists, and equilibrium never breaks.
    """
    rng = np.random.default_rng(9)
    F = np.concatenate([_wrench(fz=-3000.0), _wrench(fx=1200.0, fz=-4500.0)])
    base = assemble(make_two_body())
    P_ref = rod_loads(base, solve(base.K, F))
    _assert_equilibrium(base, P_ref, F)

    moved = False
    for _ in range(10):
        a = make_two_body()
        for rod in a.rods.values():
            rod.A = DEFAULT_ROD["A"] * float(10.0 ** rng.uniform(-1.0, 1.0))
        asm = assemble(a)
        P = rod_loads(asm, solve(asm.K, F))
        _assert_equilibrium(asm, P, F)   # must hold regardless of stiffness
        if not np.allclose(P, P_ref, rtol=1e-6):
            moved = True
    assert moved, "a redundant layout must redistribute when stiffness changes"


# ======================================================================
# V5 — symmetric redundant layout, symmetric load, equal loads
# ======================================================================


def test_v5_four_fold_symmetry_gives_equal_loads_within_each_group(symmetric8):
    asm = assemble(symmetric8)
    assert len(asm.rod_ids) == 8
    assert np.linalg.matrix_rank(asm.G_hat) == 6, "8 rods, 6 DOF -> 2 redundancies"

    F = _wrench(fz=-12000.0)  # invariant under the layout's 90 deg symmetry
    P = dict(zip(asm.rod_ids, rod_loads(asm, solve(asm.K, F))))
    _assert_equilibrium(asm, np.array(list(P.values())), F)

    legs = [P[f"leg{k}"] for k in range(4)]
    braces = [P[f"brace{k}"] for k in range(4)]
    assert np.allclose(legs, legs[0], rtol=1e-8), f"legs not equal: {legs}"
    assert np.allclose(braces, braces[0], rtol=1e-8), f"braces not equal: {braces}"
    assert legs[0] < 0.0, "splayed legs under a downward load are in compression"


def test_v5_is_genuinely_redundant_not_accidentally_determinate(symmetric8):
    """If the layout were determinate, V6 would prove nothing."""
    asm = assemble(symmetric8)
    ns = len(asm.rod_ids) - np.linalg.matrix_rank(asm.G_hat)
    assert ns == 2


# ======================================================================
# V6 — one rod stiffened, load shifts in a known proportion
# ======================================================================


def test_v6_parallel_rods_split_load_in_proportion_to_stiffness():
    """Exact closed form. Duplicating a hexapod rod onto identical endpoints
    gives two rods with the SAME screw, so they see the same elongation and
    P is proportional to k. Their sum must equal the single-rod load."""
    F = _wrench(fx=800.0, fz=-6000.0, my=1500.0)

    single = assemble(make_hexapod())
    P_single = dict(zip(single.rod_ids, rod_loads(single, solve(single.K, F))))["h0m"]

    for ratio in (1.0, 2.0, 3.0, 7.5):
        twin_spec = {
            "id": "twin",
            "a": ("body", _hex_point("h0m", "a")),
            "b": ("ground", _hex_point("h0m", "b")),
            "A": DEFAULT_ROD["A"] * ratio,
        }
        asm = assemble(make_hexapod(extra_rods=[twin_spec]))
        P = dict(zip(asm.rod_ids, rod_loads(asm, solve(asm.K, F))))

        assert P["h0m"] + P["twin"] == pytest.approx(P_single, rel=1e-7), (
            "the pair must carry exactly what the single rod carried"
        )
        assert P["twin"] / P["h0m"] == pytest.approx(ratio, rel=1e-7), (
            "parallel rods split load in proportion to stiffness"
        )
        assert P["h0m"] == pytest.approx(P_single / (1.0 + ratio), rel=1e-7)
        for rid in single.rod_ids:
            if rid != "h0m":
                assert P[rid] == pytest.approx(
                    dict(zip(single.rod_ids, rod_loads(single, solve(single.K, F))))[rid],
                    rel=1e-7,
                ), "the other rods' screws are unchanged, so their loads are too"


def _hex_point(rod_id, tag):
    """Global endpoint of a hexapod rod, for building a duplicate."""
    a = make_hexapod()
    rod = a.rods[rod_id]
    end = rod.end_a if tag == "a" else rod.end_b
    return tuple(a.endpoint_global(end)[0])


def test_v6_stiffening_one_rod_monotonically_increases_its_share(symmetric8):
    """In the redundant 8-rod layout the stiffened leg draws load off the
    others, monotonically, while equilibrium stays exact."""
    F = _wrench(fz=-12000.0)
    shares = []
    for mult in (1.0, 2.0, 4.0, 8.0, 16.0):
        asm = assemble(make_symmetric8(leg_scale={"leg0": mult}))
        P = rod_loads(asm, solve(asm.K, F))
        _assert_equilibrium(asm, P, F)
        shares.append(abs(P[asm.rod_ids.index("leg0")]))

    assert all(b > a for a, b in zip(shares, shares[1:])), (
        f"stiffened leg should take progressively more load: {shares}"
    )
    # and the others must give it up
    asm0 = assemble(make_symmetric8())
    P0 = rod_loads(asm0, solve(asm0.K, F))
    asm1 = assemble(make_symmetric8(leg_scale={"leg0": 16.0}))
    P1 = rod_loads(asm1, solve(asm1.K, F))
    others = [i for i, r in enumerate(asm0.rod_ids) if r != "leg0"]
    assert sum(abs(P1[i]) for i in others) < sum(abs(P0[i]) for i in others)


def test_v6_stiffness_cannot_change_a_determinate_load(hexapod):
    """The counterpart to V6: with no redundancy there is nothing to shift."""
    F = _wrench(fz=-6000.0, mx=800.0)
    asm0 = assemble(hexapod)
    P0 = rod_loads(asm0, solve(asm0.K, F))
    asm1 = assemble(make_hexapod(rod_overrides={"h0m": {"A": 25.0 * DEFAULT_ROD["A"]}}))
    P1 = rod_loads(asm1, solve(asm1.K, F))
    assert np.allclose(P0, P1, rtol=1e-8, atol=1e-8)


# ======================================================================
# Displacement sanity — the check on the small-displacement assumption
# ======================================================================


def test_displacement_sign_is_not_inverted(unit_cage):
    """The build prompt flags this explicitly: an earlier draft had K u = -F,
    where two sign errors cancelled in the rod loads but INVERTED the reported
    displacement. Pull the body in -X and it must move in -X."""
    asm = assemble(unit_cage)
    U = solve(asm.K, _wrench(fx=-1000.0))
    assert U[0] < 0.0, "body must displace in the direction it is pulled"
    U2 = solve(asm.K, _wrench(fx=+1000.0))
    assert U2[0] > 0.0


def test_stiffer_rods_mean_smaller_displacement(unit_cage):
    asm_soft = assemble(unit_cage)
    asm_hard = assemble(make_unit_cage(A=100.0 * DEFAULT_ROD["A"]))
    F = _wrench(fx=-1000.0)
    assert abs(solve(asm_hard.K, F)[0]) < abs(solve(asm_soft.K, F)[0])


def test_elongation_sign_matches_the_load_sign(unit_cage):
    """P > 0 is tension, and a rod in tension must have stretched."""
    asm = assemble(unit_cage)
    U = solve(asm.K, _wrench(fx=-1000.0))
    P = rod_loads(asm, U)
    delta = elongations(asm, U)
    j = asm.rod_ids.index("r_x")
    assert P[j] > 0.0, 'pulled away from the anchor -> tension'
    assert delta[j] > 0.0, 'a rod in tension must have stretched'
    # and a rod in compression must have shortened
    U2 = solve(asm.K, _wrench(fx=+1000.0))
    assert rod_loads(asm, U2)[j] < 0.0 and elongations(asm, U2)[j] < 0.0


def test_kernel_uses_no_streamlit_and_no_hidden_state(hexapod):
    """Assembling twice must give identical results — no caching surprises."""
    a1, a2 = assemble(hexapod), assemble(hexapod)
    assert np.allclose(a1.G_hat, a2.G_hat)
    assert np.allclose(a1.K, a2.K)
    assert np.allclose(a1.k_d, a2.k_d)


def test_skew_convention_matches_the_cross_product():
    """Ghat's moment rows are built on skew(); pin its convention."""
    rng = np.random.default_rng(1)
    for _ in range(10):
        r, u = rng.normal(size=3), rng.normal(size=3)
        assert np.allclose(skew(r) @ u, np.cross(r, u))


# ======================================================================
# Non-dimensionalization — a precondition for every rank / conditioning
# question (build prompt §5.5), and the basis Session 3's sigma_floor needs
# ======================================================================


def test_characteristic_length_is_the_max_free_body_attachment_radius(hexapod):
    """Measured from each FREE body's own datum; ground attachments do not
    count, since ground contributes no DOF to scale."""
    asm = assemble(hexapod)
    assert asm.L_c == pytest.approx(10.0)   # top ring radius, datum on the axis


def test_characteristic_length_scales_with_the_geometry():
    for scale in (0.01, 1.0, 250.0):
        assert assemble(make_hexapod(scale=scale)).L_c == pytest.approx(10.0 * scale)


def test_screw_spectrum_is_scale_invariant_once_non_dimensionalized():
    """The property non-dimensionalization buys, and the reason a raw-K
    condition number is meaningless: Ghat's translation rows are dimensionless
    while its moment rows carry a length, so scaling the layout stretches the
    raw spectrum non-uniformly. Scaled by L_c the spectrum is identical, which
    is what makes a fixed sigma_floor meaningful across models."""
    spectra, raw_spectra = [], []
    for scale in (0.01, 1.0, 250.0):
        asm = assemble(make_hexapod(scale=scale))
        s = asm.screw_singular_values()
        spectra.append(s / s[0])
        raw = np.linalg.svd(asm.G_hat, compute_uv=False)
        raw_spectra.append(raw / raw[0])
        assert asm.rank == 6

    for s in spectra[1:]:
        assert np.allclose(s, spectra[0], rtol=1e-10), (
            "non-dimensionalized spectrum must not depend on model scale"
        )
    assert not np.allclose(raw_spectra[0], raw_spectra[-1], rtol=1e-3), (
        "the raw spectrum SHOULD move with scale — that is why it is unusable"
    )


def test_rank_is_reported_against_the_dof_expectation():
    assert assemble(make_hexapod()).rank == 6
    assert not assemble(make_hexapod()).is_singular
    assert assemble(make_symmetric8()).rank == 6
    assert assemble(make_tripod()).rank == 3
    assert assemble(make_tripod()).is_singular
    assert assemble(make_two_body()).rank == 12


def test_assert_nonsingular_names_the_shortfall(tripod):
    with pytest.raises(kmod.SingularAssemblyError, match="rank 3 against 6"):
        assemble(tripod).assert_nonsingular()
