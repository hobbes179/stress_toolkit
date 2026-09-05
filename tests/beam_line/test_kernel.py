"""
tests/beam_line/test_kernel.py

Closed-form gates on `library/beam_line/`.

Every case here has a textbook answer, so the assertions are against published
formulae rather than against a previously recorded output. The tolerance is
deliberately tight -- these are exact methods for these load types, and the
observed error is at the 1e-15 level, so a 1e-9 gate catches a real regression
without being a floating-point tripwire.

Coverage note: the four indeterminate cases (fixed-fixed, propped cantilever,
two-span continuous, imposed settlement) are the ones that would silently
break if the stiffness assembly, the boundary-condition partition, or the
reaction recovery were wrong. A determinate beam can be got right by accident.
"""

from __future__ import annotations

import math

import pytest

from library.beam_line import (
    Beam,
    DistributedLoad,
    Hinge,
    PointLoad,
    PointMoment,
    Support,
    analyse,
    solve,
    validate,
)

EI = 1.0e7
L = 100.0
W = -10.0        # 10 lb/in downward
P = -1000.0      # 1000 lb downward

TOL = 1.0e-9


def run(beam: Beam):
    errs, sol, dg = analyse(beam)
    assert errs == [], errs
    assert sol is not None and sol.stable, sol.message if sol else "no solve"
    assert dg is not None and dg.valid, dg.message if dg else "no diagrams"
    return sol, dg


def R(sol, x: float):
    return next(r for r in sol.reactions if abs(r.x - x) < 1e-9)


def close(got: float, want: float, scale: float | None = None) -> None:
    s = scale if scale is not None else max(abs(want), 1.0)
    assert abs(got - want) / s <= TOL, f"got {got!r}, want {want!r}"


# ==========================================================================
# Determinate
# ==========================================================================
def test_simply_supported_under_uniform_load():
    b = Beam(L, EI, (Support(0.0), Support(L)),
             distributed=(DistributedLoad(0, L, W, W),))
    sol, dg = run(b)
    close(R(sol, 0).Fy, -W * L / 2)
    close(R(sol, L).Fy, -W * L / 2)
    hi, _, _ = dg.extremes("M")
    close(hi.value, -W * L ** 2 / 8)
    close(hi.x, L / 2)
    close(dg.deflection_at(L / 2), 5 * W * L ** 4 / (384 * EI))


def test_simply_supported_under_a_central_point_load():
    b = Beam(L, EI, (Support(0.0), Support(L)),
             point_loads=(PointLoad(L / 2, P),))
    sol, dg = run(b)
    close(dg.extremes("M")[0].value, -P * L / 4)
    close(dg.deflection_at(L / 2), P * L ** 3 / (48 * EI))


def test_cantilever_under_a_tip_load():
    b = Beam(L, EI, (Support(0.0, uy="rigid", rz="rigid"),),
             point_loads=(PointLoad(L, P),))
    sol, dg = run(b)
    close(R(sol, 0).Fy, -P)
    close(R(sol, 0).Mz, -P * L)
    close(dg.M_at(0.0), P * L)
    close(dg.deflection_at(L), P * L ** 3 / (3 * EI))


def test_cantilever_under_uniform_load():
    b = Beam(L, EI, (Support(0.0, uy="rigid", rz="rigid"),),
             distributed=(DistributedLoad(0, L, W, W),))
    sol, dg = run(b)
    close(dg.M_at(0.0), W * L ** 2 / 2)
    close(dg.deflection_at(L), W * L ** 4 / (8 * EI))


def test_triangular_load_peaks_at_L_over_root_three():
    """The classic 0 -> w case. Both the peak and its station are non-obvious
    numbers, so this pins the cubic moment polynomial and its root finding."""
    b = Beam(L, EI, (Support(0.0), Support(L)),
             distributed=(DistributedLoad(0, L, 0.0, W),))
    sol, dg = run(b)
    close(R(sol, 0).Fy, -W * L / 6)
    close(R(sol, L).Fy, -W * L / 3)
    hi, _, _ = dg.extremes("M")
    close(hi.value, -W * L ** 2 / (9 * math.sqrt(3)))
    close(hi.x, L / math.sqrt(3))


def test_an_applied_moment_steps_the_diagram_by_its_own_magnitude():
    M0 = 50000.0
    b = Beam(L, EI, (Support(0.0), Support(L)),
             moments=(PointMoment(L / 2, M0),))
    sol, dg = run(b)
    close(R(sol, 0).Fy, M0 / L)
    close(R(sol, L).Fy, -M0 / L)
    left = dg.M_at(L / 2, side="left")
    right = dg.M_at(L / 2, side="right")
    close(left, M0 / 2)
    close(right, -M0 / 2)
    close(left - right, M0)
    # Shear is continuous across an applied couple.
    close(dg.V_at(L / 2, side="left"), dg.V_at(L / 2, side="right"))


# ==========================================================================
# Indeterminate -- these are the ones that catch a broken assembly
# ==========================================================================
def test_fixed_fixed_under_uniform_load():
    b = Beam(L, EI, (Support(0.0, uy="rigid", rz="rigid"),
                     Support(L, uy="rigid", rz="rigid")),
             distributed=(DistributedLoad(0, L, W, W),))
    sol, dg = run(b)
    close(dg.M_at(0.0), W * L ** 2 / 12)
    close(dg.M_at(L / 2), -W * L ** 2 / 24)
    close(dg.deflection_at(L / 2), W * L ** 4 / (384 * EI))


def test_propped_cantilever_under_uniform_load():
    b = Beam(L, EI, (Support(0.0, uy="rigid", rz="rigid"), Support(L)),
             distributed=(DistributedLoad(0, L, W, W),))
    sol, dg = run(b)
    close(R(sol, L).Fy, -3 * W * L / 8)
    close(R(sol, 0).Fy, -5 * W * L / 8)
    close(dg.M_at(0.0), W * L ** 2 / 8)
    hi, _, _ = dg.extremes("M")
    close(hi.value, -9 * W * L ** 2 / 128)
    close(hi.x, 5 * L / 8)


def test_two_equal_spans_under_uniform_load():
    b = Beam(2 * L, EI, (Support(0.0), Support(L), Support(2 * L)),
             distributed=(DistributedLoad(0, 2 * L, W, W),))
    sol, dg = run(b)
    close(R(sol, L).Fy, -1.25 * W * L)
    close(R(sol, 0).Fy, -0.375 * W * L)
    close(R(sol, 2 * L).Fy, -0.375 * W * L)
    close(dg.M_at(L), W * L ** 2 / 8)


def test_settlement_induces_moment_only_because_the_beam_is_indeterminate():
    """A support pushed down by delta on a two-span beam draws a real
    reaction out of nothing; the same settlement on a determinate beam draws
    none. Both halves are asserted, because getting only the first right is
    consistent with treating settlement as an applied load."""
    dlt = -0.25

    b = Beam(2 * L, EI,
             (Support(0.0), Support(L, dy=dlt), Support(2 * L)))
    sol, dg = run(b)
    close(R(sol, L).Fy, 6 * EI * dlt / L ** 3)
    close(R(sol, 0).Fy, -3 * EI * dlt / L ** 3)
    close(dg.deflection_at(L), dlt)

    det = Beam(L, EI, (Support(0.0), Support(L, dy=dlt)))
    sol2, dg2 = run(det)
    assert abs(R(sol2, L).Fy) < 1e-9
    assert abs(dg2.extremes("M")[2].value) < 1e-9
    # It still tilts -- rigid-body motion, no curvature.
    close(dg2.deflection_at(L), dlt)


# ==========================================================================
# Releases and elastic supports
# ==========================================================================
def test_a_hinge_holds_zero_moment_and_makes_the_beam_determinate():
    b = Beam(2 * L, EI, (Support(0.0, uy="rigid", rz="rigid"),
                         Support(2 * L)),
             point_loads=(PointLoad(1.5 * L, P),), hinges=(Hinge(L),))
    sol, dg = run(b)
    close(R(sol, 2 * L).Fy, -P / 2)
    close(R(sol, 0).Fy, -P / 2)
    close(dg.M_at(0.0), P * L / 2)
    close(dg.M_at(L), 0.0, scale=abs(P * L / 2))


def test_a_hinge_lets_the_rotation_be_discontinuous():
    b = Beam(2 * L, EI, (Support(0.0, uy="rigid", rz="rigid"),
                         Support(2 * L)),
             point_loads=(PointLoad(1.5 * L, P),), hinges=(Hinge(L),))
    sol, _ = run(b)
    i = sol.nodes.index(L)
    assert abs(sol.th_left[i] - sol.th_right[i]) > 1e-6, (
        "the two sides of a hinge must be free to rotate independently")


def test_a_guided_support_holds_rotation_and_carries_no_vertical_load():
    """Fixed at one end, guided (slider) at the other, under uniform load.
    The guided end takes no vertical reaction at all, so the fixed end carries
    the whole load while the slider supplies a moment. Closed form:
    M(0) = -wL^2/3, M(L) = +wL^2/6, delta(L) = -wL^4/(24EI), theta(L) = 0.
    """
    b = Beam(L, EI, (Support(0.0, uy="rigid", rz="rigid"),
                     Support(L, uy="none", rz="rigid")),
             distributed=(DistributedLoad(0, L, W, W),))
    sol, dg = run(b)
    assert abs(R(sol, L).Fy) < 1e-9, "a slider carries no vertical load"
    close(R(sol, 0).Fy, -W * L)
    close(dg.M_at(0.0), W * L ** 2 / 3)
    close(dg.M_at(L), -W * L ** 2 / 6)
    close(dg.deflection_at(L), W * L ** 4 / (24 * EI))
    assert abs(dg.theta_at(L)) < 1e-12, "rotation is restrained at a slider"


def test_spring_supports_add_a_rigid_body_sink_on_top_of_the_bending():
    k = 5000.0
    b = Beam(L, EI, (Support(0.0, uy="spring", ky=k),
                     Support(L, uy="spring", ky=k)),
             point_loads=(PointLoad(L / 2, P),))
    sol, dg = run(b)
    close(R(sol, 0).Fy, -P / 2)
    close(dg.deflection_at(0.0), P / (2 * k))
    close(dg.deflection_at(L / 2), P / (2 * k) + P * L ** 3 / (48 * EI))


def test_a_very_stiff_spring_reproduces_the_rigid_support():
    """The trust anchor for the elastic support: as k grows the answer has to
    walk onto the rigid result, which is what makes the spring a refinement of
    that case rather than a separate model."""
    rigid = Beam(L, EI, (Support(0.0, uy="rigid", rz="rigid"), Support(L)),
                 distributed=(DistributedLoad(0, L, W, W),))
    _, dg_r = run(rigid)
    soft = Beam(L, EI, (Support(0.0, uy="rigid", rz="rigid"),
                        Support(L, uy="spring", ky=1.0e14)),
                distributed=(DistributedLoad(0, L, W, W),))
    _, dg_s = run(soft)
    close(dg_s.M_at(0.0), dg_r.M_at(0.0))


# ==========================================================================
# Exactness and the validity gate
# ==========================================================================
def test_extra_nodes_cannot_change_the_answer():
    """There is no mesh parameter because refinement is a null operation:
    the elements are exact at the nodes and the interior is closed form.
    Zero-magnitude point loads are the cleanest way to force extra nodes."""
    base = Beam(L, EI, (Support(0.0), Support(L)),
                distributed=(DistributedLoad(0, L, W, W),))
    meshed = Beam(L, EI, (Support(0.0), Support(L)),
                  distributed=(DistributedLoad(0, L, W, W),),
                  point_loads=tuple(PointLoad(x, 0.0)
                                    for x in (13.7, 61.3, 88.1)))
    _, d1 = run(base)
    _, d2 = run(meshed)
    assert d1.extremes("M")[0].value == pytest.approx(
        d2.extremes("M")[0].value, rel=1e-12)
    assert d1.extremes("d")[2].value == pytest.approx(
        d2.extremes("d")[2].value, rel=1e-12)


def test_the_peak_moment_is_rooted_not_sampled():
    """A sampled peak would land on a sample station. The true peak of this
    case is at L/sqrt(3) = 57.735..., which is not on any regular grid."""
    b = Beam(L, EI, (Support(0.0), Support(L)),
             distributed=(DistributedLoad(0, L, 0.0, W),))
    _, dg = run(b)
    x = dg.extremes("M")[0].x
    assert abs(x - L / math.sqrt(3)) < 1e-9
    samples = dg.sample(per_piece=40)
    assert min(abs(float(s) - x) for s in samples["x"]) > 1e-6, (
        "the reported peak station coincided with a sample point, which "
        "suggests it was taken from the sample array rather than rooted")


def test_the_gate_is_not_vacuous():
    """Negative control. A gate that has never rejected anything is
    indistinguishable from no gate, so this corrupts a reaction by 1% and
    asserts the diagrams are refused and the message names what broke."""
    from dataclasses import replace

    from library.beam_line import build

    b = Beam(L, EI, (Support(0.0), Support(L)),
             distributed=(DistributedLoad(0, L, W, W),))
    sol = solve(b)
    assert sol.stable
    bad = replace(sol, reactions=tuple(
        replace(r, Fy=r.Fy * 1.01) if i == 0 else r
        for i, r in enumerate(sol.reactions)))
    dg = build(b, bad)
    assert not dg.valid
    assert "shear does not return to zero" in dg.message


def test_a_degenerate_diagram_is_not_judged_against_itself():
    """Two equal and opposite couples give V identically zero, so the peak
    shear IS its own rounding residue. Scaling the closure check by the peak
    then divides that residue by itself and rejects a perfectly good solve.
    The scale is floored at the applied-load magnitude to stop it.

    This shipped as a bug during the build: the beam solved correctly and the
    page showed no diagrams at all.
    """
    M0 = 9000.0
    b = Beam(240.0, 3.0e8, (Support(0.0), Support(240.0)),
             moments=(PointMoment(80.0, M0), PointMoment(160.0, -M0)))
    _, dg = run(b)
    assert abs(dg.extremes("V")[2].value) < 1e-9, "shear must be zero here"
    close(dg.M_at(80.0, side="right"), -M0)
    close(dg.M_at(160.0, side="right"), 0.0, scale=M0)


def test_load_scale_is_nonzero_whenever_anything_is_applied():
    """The shared definition of "how big is this problem". An applied couple
    has to contribute to the FORCE reference too, via M/L, or a beam loaded
    only by couples has a force scale of zero."""
    b = Beam(100.0, EI, (Support(0.0), Support(100.0)),
             moments=(PointMoment(50.0, 5000.0),))
    ref_F, ref_M = b.load_scale()
    assert ref_F == pytest.approx(50.0)
    assert ref_M == pytest.approx(5000.0)


def test_the_gate_tolerates_ordinary_floating_point_noise():
    """The other half of the control: a correct solve must clear the gate by
    orders, or the tolerance is set where a rounding difference decides."""
    b = Beam(2 * L, EI, (Support(0.0, uy="rigid", rz="rigid"),
                         Support(L), Support(2 * L)),
             distributed=(DistributedLoad(0, 2 * L, W, W),))
    _, dg = run(b)
    assert dg.closure_V < 1e-8
    assert dg.residual < 1e-10


def test_the_diagrams_close_and_the_integration_reproduces_the_solve():
    b = Beam(2 * L, EI, (Support(0.0, uy="rigid", rz="rigid"),
                         Support(L), Support(2 * L)),
             point_loads=(PointLoad(1.6 * L, P),),
             moments=(PointMoment(0.4 * L, 25000.0),),
             distributed=(DistributedLoad(0.0, L, -12.0, -4.0),))
    sol, dg = run(b)
    assert dg.closure_V < 1e-6
    assert dg.closure_M < 1e-6
    assert dg.residual < 1e-10
    total = b.total_applied_force + sum(r.Fy for r in sol.reactions)
    assert abs(total) < 1e-8


# ==========================================================================
# Mechanisms and malformed models
# ==========================================================================
@pytest.mark.parametrize("beam,why", [
    (Beam(L, EI, (), point_loads=(PointLoad(L / 2, P),)),
     "no supports at all"),
    (Beam(L, EI, (Support(L / 2),), point_loads=(PointLoad(0.0, P),)),
     "one vertical support leaves a rotation mode"),
    (Beam(2 * L, EI, (Support(0.0), Support(2 * L)), hinges=(Hinge(L),),
          point_loads=(PointLoad(L / 2, P),)),
     "a hinge releases more than two end supports can make up"),
])
def test_a_mechanism_is_detected_and_never_produces_a_diagram(beam, why):
    errs, sol, dg = analyse(beam)
    assert errs == []
    assert not sol.stable, why
    assert sol.message
    assert dg is not None and not dg.valid, (
        "an unstable beam must not yield drawable diagrams")


def test_the_singularity_verdict_is_not_a_marginal_judgement_call():
    """A real beam and a mechanism must sit orders apart on the same measure,
    or the threshold is doing the deciding rather than the physics."""
    mech = solve(Beam(L, EI, (Support(L / 2),),
                      point_loads=(PointLoad(0.0, P),)))
    real = solve(Beam(L, EI, (Support(0.0), Support(L)),
                      distributed=(DistributedLoad(0, L, W, W),)))
    soft = solve(Beam(L, EI, (Support(0.0, uy="spring", ky=0.01),
                              Support(L, uy="spring", ky=0.01)),
                      point_loads=(PointLoad(L / 2, P),)))
    assert mech.null_ratio < 1e-14
    assert real.null_ratio > 1e-6
    assert soft.stable and soft.null_ratio > 1e-12, (
        "a deliberately soft but real support must not read as a mechanism")


@pytest.mark.parametrize("beam,fragment", [
    (Beam(L, EI, (Support(0.0), Support(L)), hinges=(Hinge(0.0),)),
     "end of the span"),
    (Beam(L, EI, (Support(0.0), Support(L)), hinges=(Hinge(L / 2),),
          moments=(PointMoment(L / 2, 100.0),)),
     "no applied moment there can be equilibrated"),
    (Beam(L, EI, (Support(0.0), Support(L / 2, uy="rigid", rz="rigid"),
                  Support(L)), hinges=(Hinge(L / 2),)),
     "contradict each other"),
    (Beam(L, EI, (Support(0.0), Support(L)),
          distributed=(DistributedLoad(20.0, 20.0, W, W),)),
     "zero length"),
    (Beam(L, EI, (Support(0.0), Support(L * 3),)),
     "outside the span"),
    (Beam(L, EI, (Support(0.0), Support(L, uy="spring", ky=0.0),)),
     "no vertical stiffness"),
])
def test_a_malformed_model_is_rejected_with_an_actionable_message(beam,
                                                                  fragment):
    errs = validate(beam)
    assert any(fragment in e for e in errs), errs


def test_a_hinge_at_the_end_names_the_thing_to_do_instead():
    """Rejecting an input is only acceptable if the message says what to do
    instead; this one has an exact equivalent."""
    errs = validate(Beam(L, EI, (Support(0.0, uy="rigid", rz="rigid"),
                                 Support(L)), hinges=(Hinge(0.0),)))
    assert any("vertical-only" in e for e in errs), errs


# ==========================================================================
# Conventions
# ==========================================================================
def test_a_gravity_load_sags_and_a_cantilever_hogs():
    """The one convention error that would poison every downstream reading:
    a sign flip between sagging and hogging."""
    ss = Beam(L, EI, (Support(0.0), Support(L)),
              distributed=(DistributedLoad(0, L, W, W),))
    _, d1 = run(ss)
    assert d1.M_at(L / 2) > 0, "simply supported under gravity must sag"
    assert d1.deflection_at(L / 2) < 0, "and must deflect downward"

    cant = Beam(L, EI, (Support(0.0, uy="rigid", rz="rigid"),),
                point_loads=(PointLoad(L, P),))
    _, d2 = run(cant)
    assert d2.M_at(0.0) < 0, "a cantilever root under gravity must hog"


def test_pin_and_roller_are_the_same_restraint():
    """Documented in the Method section as an identity, not an approximation.
    If an axial DOF is ever added this test is the one that must change."""
    a = Beam(L, EI, (Support(0.0, uy="rigid"), Support(L, uy="rigid")),
             point_loads=(PointLoad(L / 3, P),))
    sol, dg = run(a)
    assert all(r.Mz == 0.0 for r in sol.reactions)
    close(R(sol, 0).Fy, -P * 2 / 3)


def test_overlapping_distributed_patches_add():
    """Two patches on the same stretch are a snow load on a dead load, not a
    modelling error."""
    one = Beam(L, EI, (Support(0.0), Support(L)),
               distributed=(DistributedLoad(0, L, 2 * W, 2 * W),))
    two = Beam(L, EI, (Support(0.0), Support(L)),
               distributed=(DistributedLoad(0, L, W, W),
                            DistributedLoad(0, L, W, W)))
    _, d1 = run(one)
    _, d2 = run(two)
    close(d2.extremes("M")[0].value, d1.extremes("M")[0].value)
