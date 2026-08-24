"""
tests/tierod/test_allowables.py — Session 5 gate, allowables half.

Primary gate: **V9** — the Euler and Johnson branches must both return `Fcy/2`
at `lambda_crit`. A wrong `lambda_crit` produces a discontinuous allowable, and
a discontinuity in an allowable is worse than a wrong number: it puts a step in
the objective that a gradient optimizer will happily park itself against.

The rest of this file guards the parts of §6.1–6.3 that are easy to get subtly
wrong and impossible to notice downstream:

  * `L' = L / sqrt(c)` — dividing by `c` instead of `sqrt(c)` is a 2x error in
    the allowable at `c = 4` and nothing complains.
  * tension source selection: vendor rated is PRIMARY, `A_net * Ftu` is the
    fallback, and a rod with neither must be reported, not silently given an
    infinite allowable.
  * `P_comp_allow` falls as the rod lengthens. That coupling is the entire
    reason the objective is on load RATIO rather than load.
"""
from __future__ import annotations

import numpy as np
import pytest

from library.tierod import allowables as al
from library.tierod.model import Rod, RodEnd

E_STEEL = 29.0e6
FCY = 180.0e3


def _rod(**over) -> Rod:
    """A 0.375 dia alloy-steel rod, the demo assembly's section."""
    props = dict(
        E=E_STEEL, A=0.1104, I=9.71e-4, Fcy=FCY,
        Ftu=180.0e3, Fty=160.0e3, A_net=0.08,
    )
    props.update(over)
    return Rod(
        id="r",
        end_a=RodEnd(region_id="x", q=np.zeros(0)),
        end_b=RodEnd(region_id="y", q=np.zeros(0)),
        **props,
    )


def _L_at(lam: float, rod: Rod) -> float:
    """Rod length that produces slenderness `lam`."""
    rho = np.sqrt(rod.I / rod.A)
    return lam * rho * np.sqrt(rod.end_fixity)


# ======================================================================
# V9 — branch continuity at lambda_crit
# ======================================================================


def test_v9_both_branches_return_half_fcy_at_lambda_crit():
    rod = _rod()
    lam_c = al.lambda_crit(rod.E, rod.Fcy)

    johnson = al.johnson_stress(rod.E, rod.Fcy, lam_c)
    euler = al.euler_stress(rod.E, lam_c)

    assert johnson == pytest.approx(rod.Fcy / 2.0, rel=1e-12)
    assert euler == pytest.approx(rod.Fcy / 2.0, rel=1e-12)


def test_v9_the_dispatcher_is_continuous_across_the_branch_point():
    """Approach lambda_crit from both sides through the real entry point."""
    rod = _rod()
    lam_c = al.lambda_crit(rod.E, rod.Fcy)

    for eps in (1e-3, 1e-5, 1e-7):
        below = al.column_state(rod, _L_at(lam_c * (1 - eps), rod))
        above = al.column_state(rod, _L_at(lam_c * (1 + eps), rod))
        assert below.branch == "Johnson"
        assert above.branch == "Euler"
        assert below.F_c == pytest.approx(above.F_c, rel=10 * eps)
        assert below.F_c == pytest.approx(rod.Fcy / 2.0, rel=10 * eps)


def test_v9_the_branch_tangent_is_continuous_too():
    """Both curves share a slope at lambda_crit, not just a value.

    Value continuity alone would still pass with lambda_crit off by a factor
    that happens to cross the curves; a shared tangent pins it exactly.
    """
    rod = _rod()
    lam_c = al.lambda_crit(rod.E, rod.Fcy)
    h = lam_c * 1e-6

    slope_johnson = (
        al.johnson_stress(rod.E, rod.Fcy, lam_c) - al.johnson_stress(rod.E, rod.Fcy, lam_c - h)
    ) / h
    slope_euler = (
        al.euler_stress(rod.E, lam_c + h) - al.euler_stress(rod.E, lam_c)
    ) / h
    assert slope_johnson == pytest.approx(slope_euler, rel=1e-4)
    assert slope_johnson < 0.0


def test_lambda_crit_is_pi_root_two_e_over_fcy():
    assert al.lambda_crit(E_STEEL, FCY) == pytest.approx(
        np.pi * np.sqrt(2.0 * E_STEEL / FCY), rel=1e-14
    )


def test_johnson_returns_fcy_for_a_stub():
    """At zero slenderness the column allowable IS the material allowable."""
    assert al.johnson_stress(E_STEEL, FCY, 0.0) == pytest.approx(FCY)


# ======================================================================
# Column geometry — rho, effective length, the length coupling
# ======================================================================


def test_radius_of_gyration_is_root_i_over_a():
    rod = _rod()
    st = al.column_state(rod, 12.0)
    assert st.rho == pytest.approx(np.sqrt(rod.I / rod.A), rel=1e-14)
    assert st.lam == pytest.approx(st.L_eff / st.rho, rel=1e-14)


def test_end_fixity_divides_the_length_by_root_c():
    """L' = L / sqrt(c). Dividing by c instead is a silent 2x at c = 4."""
    L = 30.0
    pinned = al.column_state(_rod(end_fixity=1.0), L)
    fixed = al.column_state(_rod(end_fixity=4.0), L)

    assert pinned.L_eff == pytest.approx(L)
    assert fixed.L_eff == pytest.approx(L / 2.0)
    assert fixed.lam == pytest.approx(pinned.lam / 2.0)
    # both are Euler at 30 in, so the allowable goes as 1/lambda^2 -> 4x
    assert pinned.branch == fixed.branch == "Euler"
    assert fixed.F_c == pytest.approx(4.0 * pinned.F_c, rel=1e-12)


def test_euler_branch_reproduces_the_classical_critical_load():
    """P_comp_allow = F_c A must equal pi^2 E I / L'^2 exactly on the Euler
    branch — the same number by a different route."""
    rod = _rod()
    L = 30.0
    allow = al.compression_allowable(rod, L)
    assert allow.detail == "Euler"
    assert allow.value == pytest.approx(np.pi**2 * rod.E * rod.I / L**2, rel=1e-12)


def test_compression_allowable_falls_as_the_rod_lengthens():
    """The coupling §6.2 warns about: lengthening a rod to improve its
    direction degrades its own compression allowable."""
    rod = _rod()
    lengths = np.linspace(2.0, 60.0, 40)
    values = [al.compression_allowable(rod, float(L)).value for L in lengths]
    assert all(b < a for a, b in zip(values, values[1:]))


def test_compression_allowable_is_positive_and_capped_by_material_yield():
    rod = _rod()
    for L in (0.5, 5.0, 5.288, 20.0, 100.0):
        allow = al.compression_allowable(rod, L)
        assert 0.0 < allow.value <= rod.Fcy * rod.A + 1e-9


# ======================================================================
# §6.1 tension source selection
# ======================================================================


def test_vendor_rating_is_the_primary_tension_source():
    rod = _rod(P_tension_allow=7200.0)
    allow = al.tension_allowable(rod)
    assert allow.value == pytest.approx(7200.0)
    assert "vendor" in allow.source.lower()


def test_vendor_rating_wins_even_when_a_net_ftu_is_larger():
    """The spherical bearing is usually the weakest link, so the rated load
    governs regardless of how strong the shank calculates."""
    rod = _rod(P_tension_allow=3000.0, A_net=0.5, Ftu=200.0e3)
    assert al.tension_allowable(rod).value == pytest.approx(3000.0)


def test_tension_falls_back_to_a_net_times_ftu():
    rod = _rod(P_tension_allow=None)
    allow = al.tension_allowable(rod)
    assert allow.value == pytest.approx(0.08 * 180.0e3)
    assert "Ftu" in allow.source


def test_a_rod_with_no_tension_source_is_reported_not_guessed():
    rod = _rod(P_tension_allow=None, Ftu=None, A_net=None)
    allow = al.tension_allowable(rod)
    assert allow.value is None
    assert not allow.available
    assert "not specified" in allow.source.lower()


def test_a_net_alone_is_not_enough():
    rod = _rod(P_tension_allow=None, Ftu=None)
    assert al.tension_allowable(rod).value is None


def test_tension_yield_needs_fty_and_uses_the_gross_area():
    """Yield is a gross-section check; the net section is an ultimate check on
    the threaded shank."""
    rod = _rod()
    allow = al.tension_yield_allowable(rod)
    assert allow.value == pytest.approx(rod.A * rod.Fty)
    assert al.tension_yield_allowable(_rod(Fty=None)).value is None


# ======================================================================
# §6.3 load ratio, margin, safety factors
# ======================================================================


def test_margin_is_one_over_lr_minus_one():
    for lr in (0.1, 0.5, 1.0, 2.0):
        assert al.margin_of_safety(lr) == pytest.approx(1.0 / lr - 1.0)
    assert al.margin_of_safety(1.0) == pytest.approx(0.0)
    assert al.margin_of_safety(0.0) == float("inf")
    assert al.margin_of_safety(None) is None


def test_positive_load_is_checked_against_tension_negative_against_compression():
    ra = al.rod_allowables(_rod(P_tension_allow=5000.0), 30.0)
    sf = al.SafetyFactors(ultimate=1.0, yield_=1.0)

    t = al.load_ratio(+1000.0, ra, sf)
    c = al.load_ratio(-1000.0, ra, sf)
    assert t.sense == "T" and c.sense == "C"
    assert t.value == pytest.approx(1000.0 / 5000.0)
    assert c.value == pytest.approx(1000.0 / ra.compression_ult.value)


def test_the_safety_factor_scales_the_load_ratio_linearly():
    ra = al.rod_allowables(_rod(P_tension_allow=5000.0, Fty=None), 30.0)
    one = al.load_ratio(1000.0, ra, al.SafetyFactors(ultimate=1.0))
    ult = al.load_ratio(1000.0, ra, al.SafetyFactors(ultimate=1.5))
    assert ult.value == pytest.approx(1.5 * one.value)


def test_defaults_are_one_and_one_and_a_half_and_are_not_hardcoded():
    sf = al.SafetyFactors()
    assert (sf.yield_, sf.ultimate) == (1.0, 1.5)
    # and they are settable — the UI owns these numbers, not the library
    assert al.SafetyFactors(ultimate=2.0, yield_=1.15).ultimate == 2.0


def test_a_nonpositive_safety_factor_is_rejected():
    with pytest.raises(ValueError):
        al.SafetyFactors(ultimate=0.0)
    with pytest.raises(ValueError):
        al.SafetyFactors(yield_=-1.0)


def test_the_governing_check_is_the_smallest_effective_allowable():
    """LR is |P| over the *effective* allowable — the raw allowable divided by
    its own factor — so whichever check bites is simply the smallest of them."""
    rod = _rod(P_tension_allow=30000.0, Fty=20.0e3)   # deliberately weak yield
    ra = al.rod_allowables(rod, 30.0)
    sf = al.SafetyFactors(ultimate=1.5, yield_=1.0)

    lr = al.load_ratio(1000.0, ra, sf)
    assert lr.source.startswith("yield")
    assert lr.allowable == pytest.approx(rod.A * 20.0e3)
    assert lr.value == pytest.approx(1000.0 / (rod.A * 20.0e3))


def test_ultimate_governs_tension_for_ordinary_material_data():
    ra = al.rod_allowables(_rod(), 30.0)
    lr = al.load_ratio(1000.0, ra, al.SafetyFactors())
    assert lr.source.startswith("ultimate")
    assert lr.allowable == pytest.approx(0.08 * 180.0e3)


def test_compression_yield_is_available_even_without_fty():
    """Fcy is a required Rod field, so the compression side always has both a
    yield and an ultimate check regardless of what optional data is present."""
    ra = al.rod_allowables(_rod(Fty=None, Ftu=None, A_net=None), 30.0)
    assert ra.compression_yield.value == pytest.approx(0.1104 * FCY)
    assert ra.compression_ult.available


def test_a_rod_with_no_tension_data_yields_no_tension_ratio():
    ra = al.rod_allowables(_rod(P_tension_allow=None, Ftu=None, A_net=None, Fty=None), 30.0)
    lr = al.load_ratio(1000.0, ra, al.SafetyFactors())
    assert lr.value is None
    assert lr.margin is None
    assert "not specified" in lr.source.lower()
    # the compression side is unaffected
    assert al.load_ratio(-1000.0, ra, al.SafetyFactors()).value is not None


def test_zero_load_is_zero_ratio_and_infinite_margin():
    ra = al.rod_allowables(_rod(), 30.0)
    lr = al.load_ratio(0.0, ra, al.SafetyFactors())
    assert lr.value == 0.0
    assert lr.margin == float("inf")


def test_two_sided_ratio_uses_the_weaker_of_the_two_senses():
    """A symmetric orientation sweep drives every rod to +-|P|, so both senses
    reach full magnitude and only min(tension, compression) matters (§7.2).
    For a tie rod that is almost always compression."""
    ra = al.rod_allowables(_rod(P_tension_allow=50000.0), 30.0)
    sf = al.SafetyFactors()
    two = al.two_sided_load_ratio(4000.0, ra, sf)
    assert two.sense == "C"
    assert two.value == pytest.approx(
        4000.0 / (ra.compression_ult.value / sf.ultimate)
    )
    assert two.value >= al.load_ratio(4000.0, ra, sf).value


def test_two_sided_ratio_can_be_governed_by_tension_when_the_rod_is_stubby():
    """A short rod barely buckles, so a weak bearing rating governs instead."""
    ra = al.rod_allowables(_rod(P_tension_allow=800.0), 3.0)
    two = al.two_sided_load_ratio(500.0, ra, al.SafetyFactors())
    assert two.sense == "T"


# ======================================================================
# Input validation — bad data must fail loudly, at the source
# ======================================================================


@pytest.mark.parametrize(
    "over, L",
    [
        (dict(I=0.0), 10.0),
        (dict(I=-1e-4), 10.0),
        (dict(A=0.0), 10.0),
        (dict(end_fixity=0.0), 10.0),
        (dict(end_fixity=-1.0), 10.0),
        (dict(Fcy=0.0), 10.0),
        ({}, 0.0),
        ({}, -5.0),
    ],
)
def test_degenerate_column_inputs_raise(over, L):
    with pytest.raises(ValueError):
        al.column_state(_rod(**over), L)


def test_a_negative_vendor_rating_raises():
    with pytest.raises(ValueError):
        al.tension_allowable(_rod(P_tension_allow=-100.0))


# ======================================================================
# Rod specs — the editor's data, applied to the model
# ======================================================================


def test_a_rod_spec_writes_every_strength_field_it_owns():
    rod = _rod()
    spec = al.RodSpec(
        name="1/2-20 CRES", E=28.0e6, A=0.1963, I=3.07e-3,
        Fcy=140.0e3, Ftu=160.0e3, Fty=145.0e3, A_net=0.1419,
        P_tension_allow=12000.0,
    )
    spec.apply_to(rod)
    for field in ("E", "A", "I", "Fcy", "Ftu", "Fty", "A_net", "P_tension_allow"):
        assert getattr(rod, field) == getattr(spec, field)


def test_a_rod_spec_leaves_topology_and_end_fixity_alone():
    """A spec is section + material. Which regions a rod spans is a user
    input, and end fixity is a joint property, not a catalog property."""
    rod = _rod(end_fixity=4.0)
    before = (rod.end_a.region_id, rod.end_b.region_id, rod.end_fixity)
    al.ROD_SPECS[next(iter(al.ROD_SPECS))].apply_to(rod)
    assert (rod.end_a.region_id, rod.end_b.region_id, rod.end_fixity) == before


def test_the_starter_spec_list_is_self_consistent():
    for name, spec in al.ROD_SPECS.items():
        assert spec.name == name
        assert spec.A > 0.0 and spec.I > 0.0 and spec.E > 0.0 and spec.Fcy > 0.0
        if spec.A_net is not None:
            assert 0.0 < spec.A_net <= spec.A
        rod = _rod()
        spec.apply_to(rod)
        assert al.rod_allowables(rod, 20.0).compression_ult.available
