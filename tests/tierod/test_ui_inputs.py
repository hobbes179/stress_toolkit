"""
tests/tierod/test_ui_inputs.py — Session 4 gate, input-layer half.

Two things here are worth real tests:

  * the design-variable sliders GENERATE THEMSELVES from `region.bounds()` via
    the design-vector layout. A PlanarPatch end gets two, a CircleArc one, a
    FixedPoint none, with no per-type UI code — so adding a region primitive
    never touches the UI.
  * the ground toggle GRAYS mass / cg / g_factor rather than clearing them.
    Losing a body's mass because someone toggled ground to check something is
    a data-loss bug, and it is the kind that goes unnoticed.
"""
from __future__ import annotations

import numpy as np
import pytest

from apps.tierod import examples, ui_inputs
from library.tierod import allowables as al
from library.tierod import sweep as sw
from library.tierod.model import Body


# ======================================================================
# Sliders generate themselves from the model
# ======================================================================


def test_slider_specs_follow_the_design_vector_layout():
    a = examples.demo_assembly()
    specs = ui_inputs.slider_specs(a)
    assert len(specs) == a.n_design_vars() == 48
    layout_ends = [(rod_id, tag) for rod_id, tag, _ in a.design_vector_layout()]
    assert [(s.rod_id, s.end) for s in specs][::2] == layout_ends


def test_slider_bounds_are_the_region_bounds():
    a = examples.demo_assembly()
    for spec in ui_inputs.slider_specs(a):
        region = a.regions[spec.region_id]
        lo, hi = region.bounds()[spec.axis]
        assert (spec.lo, spec.hi) == (lo, hi)
        assert lo <= spec.value <= hi
        assert spec.step > 0.0


def test_slider_count_per_end_is_the_region_dimension():
    a = examples.mixed_region_assembly()
    per_end: dict[tuple[str, str], int] = {}
    for s in ui_inputs.slider_specs(a):
        per_end[(s.rod_id, s.end)] = per_end.get((s.rod_id, s.end), 0) + 1
    assert per_end[("r_patch", "a")] == 2      # PlanarPatch
    assert per_end[("r_patch", "b")] == 1      # CircleArc
    assert ("r_fixed", "a") not in per_end     # FixedPoint contributes nothing


def test_no_per_type_ui_code_is_needed_for_a_new_primitive():
    """The generator must read ndim/bounds only, never a type name."""
    import inspect

    src = inspect.getsource(ui_inputs.slider_specs)
    for type_name in (
        "PlanarPatch", "CircleArc", "Annulus", "CylindricalBand",
        "SphericalPatch", "Segment", "FixedPoint",
    ):
        assert type_name not in src, f"slider_specs branches on {type_name}"


def test_design_vector_round_trips_through_the_sliders():
    a = examples.demo_assembly()
    x0 = a.design_vector()
    assert x0.shape == (48,)
    x1 = x0 + 0.01
    a.set_design_vector(x1)
    assert np.allclose(a.design_vector(), x1)
    # and the sliders now report the new values
    assert np.allclose([s.value for s in ui_inputs.slider_specs(a)], x1)


def test_set_design_vector_rejects_a_wrong_length():
    a = examples.demo_assembly()
    with pytest.raises(ValueError):
        a.set_design_vector(np.zeros(3))


def test_slider_labels_identify_the_rod_end_and_parameter():
    a = examples.demo_assembly()
    labels = [s.label for s in ui_inputs.slider_specs(a)]
    assert len(set(labels)) == len(labels), "labels must be unique widget keys"
    assert any("rod_a0" in lbl and "a" in lbl for lbl in labels)


# ======================================================================
# Ground toggle grays, never clears
# ======================================================================


def test_ground_toggle_disables_mass_fields_without_clearing_them():
    body = Body(id="b", mass=137.0, cg=np.array([1.0, 2.0, 3.0]), g_factor=4.5)

    spec = ui_inputs.body_form_spec(body)
    assert not spec.mass_disabled

    body.is_ground = True
    spec = ui_inputs.body_form_spec(body)
    assert spec.mass_disabled, "grounded bodies gray their inertial inputs"
    assert body.mass == 137.0
    assert np.allclose(body.cg, [1.0, 2.0, 3.0])
    assert body.g_factor == 4.5


def test_ground_toggle_round_trips_without_data_loss():
    """Toggle on and back off: every inertial value must survive."""
    body = Body(id="b", mass=137.0, cg=np.array([1.0, 2.0, 3.0]), g_factor=4.5)
    before = (body.mass, body.cg.copy(), body.g_factor)

    for is_ground in (True, False, True, False):
        ui_inputs.apply_body_edits(body, is_ground=is_ground)

    assert body.mass == before[0]
    assert np.allclose(body.cg, before[1])
    assert body.g_factor == before[2]
    assert body.is_ground is False


def test_apply_body_edits_updates_what_it_is_given():
    body = Body(id="b", mass=10.0, cg=np.zeros(3), g_factor=1.0)
    ui_inputs.apply_body_edits(body, mass=25.0, cg=[0.0, 0.0, 4.0], g_factor=6.0)
    assert body.mass == 25.0
    assert np.allclose(body.cg, [0.0, 0.0, 4.0])
    assert body.g_factor == 6.0
    # and leaves alone what it is not given
    ui_inputs.apply_body_edits(body, is_ground=True)
    assert body.mass == 25.0 and body.g_factor == 6.0


def test_grounded_body_reports_no_sweep_block_but_keeps_its_data():
    body = Body(id="b", mass=99.0, cg=np.array([0.0, 0.0, 5.0]), is_ground=True)
    with pytest.raises(ValueError):
        body.sweep_block()
    assert body.mass == 99.0


# ======================================================================
# Topology editing — rods span a pair of regions, chosen by the user
# ======================================================================


def test_region_choices_are_grouped_by_body():
    a = examples.demo_assembly()
    choices = ui_inputs.region_choices(a)
    assert set(choices) == {"plate", "tank_a", "tank_b"}
    assert "band_a" in choices["tank_a"]
    assert "foot_a" in choices["plate"]


def test_retargeting_a_rod_end_resets_q_into_the_new_region_bounds():
    """Topology is a user input; moving an end to a different region must
    leave a valid q, not a stale one of the wrong length."""
    a = examples.mixed_region_assembly()
    ui_inputs.set_rod_end_region(a, "r_patch", "a", "arc1d")
    a.validate()
    rod = a.rods["r_patch"]
    assert rod.end_a.region_id == "arc1d"
    assert rod.end_a.q.size == a.regions["arc1d"].ndim
    assert a.regions["arc1d"].in_bounds(rod.end_a.q)


def test_retargeting_to_a_fixed_point_leaves_an_empty_q():
    a = examples.mixed_region_assembly()
    ui_inputs.set_rod_end_region(a, "r_patch", "a", "fixed0d")
    assert a.rods["r_patch"].end_a.q.size == 0
    a.validate()


def test_ui_inputs_pure_helpers_do_not_need_streamlit_state():
    """These helpers are called from tests and from the app alike; they must
    not reach into st.session_state."""
    import inspect

    for fn in (
        ui_inputs.slider_specs,
        ui_inputs.body_form_spec,
        ui_inputs.apply_body_edits,
        ui_inputs.region_choices,
        ui_inputs.rods_with_design_vars,
        ui_inputs.apply_rod_q,
        ui_inputs.set_rod_end_region,
    ):
        assert "session_state" not in inspect.getsource(fn)


# ======================================================================
# One rod at a time — clutter, and accidental drags on the wrong rod
# ======================================================================


def test_rods_with_design_vars_skips_fully_fixed_rods():
    a = examples.mixed_region_assembly()
    # r_fixed spans a FixedPoint and a PlanarPatch, so it still has 2 vars
    assert ui_inputs.rods_with_design_vars(a) == ["r_fixed", "r_patch"]

    # pin both ends of one rod to fixed points and it drops out entirely
    ui_inputs.set_rod_end_region(a, "r_fixed", "b", "fixed0d")
    assert ui_inputs.rods_with_design_vars(a) == ["r_patch"]


def test_apply_rod_q_writes_only_the_named_rod():
    a = examples.demo_assembly()
    before = a.design_vector().copy()
    ui_inputs.apply_rod_q(a, "rod_a0", [1.0, 20.0, 8.0, 1.0])

    assert np.allclose(a.rods["rod_a0"].end_a.q, [1.0, 20.0])
    assert np.allclose(a.rods["rod_a0"].end_b.q, [8.0, 1.0])
    # every other rod is untouched — the whole point of editing one at a time
    after = a.design_vector()
    assert not np.allclose(after[:4], before[:4])
    assert np.allclose(after[4:], before[4:])


def test_apply_rod_q_rejects_a_wrong_length():
    a = examples.demo_assembly()
    with pytest.raises(ValueError):
        ui_inputs.apply_rod_q(a, "rod_a0", [1.0, 2.0])


# ======================================================================
# Rod specs — grouped strength data, because nobody builds twelve
# individually-sized rods
# ======================================================================


def test_every_rod_reports_which_spec_it_matches():
    a = examples.demo_assembly()
    spec = al.ROD_SPECS['1/2" alloy steel']
    ui_inputs.assign_spec(a, spec, list(a.rods))
    assert ui_inputs.spec_assignments(a) == {r: spec.name for r in a.rods}


def test_a_rod_that_matches_no_spec_reads_as_custom():
    a = examples.demo_assembly()
    ui_inputs.assign_spec(a, al.ROD_SPECS['1/2" alloy steel'], list(a.rods))
    a.rods["rod_a0"].A *= 1.37
    assert ui_inputs.spec_assignments(a)["rod_a0"] == ui_inputs.CUSTOM
    assert ui_inputs.spec_assignments(a)["rod_a1"] == '1/2" alloy steel'


def test_assigning_a_spec_touches_only_the_named_rods():
    a = examples.demo_assembly()
    before = {r: a.rods[r].A for r in a.rods}
    ui_inputs.assign_spec(a, al.ROD_SPECS['5/8" alloy steel'], ["rod_a0", "rod_b2"])
    for rod_id, rod in a.rods.items():
        if rod_id in ("rod_a0", "rod_b2"):
            assert rod.A == al.ROD_SPECS['5/8" alloy steel'].A
        else:
            assert rod.A == before[rod_id]


def test_assigning_a_spec_gives_the_rod_a_tension_allowable():
    """The point of the editor: without Ftu/A_net a rod is checked in
    compression only, and that looks identical to a complete margin."""
    a = examples.demo_assembly()
    for rod in a.rods.values():
        rod.Ftu = rod.A_net = rod.P_tension_allow = None
    assert sw.run_sweep(a).incomplete_rods
    ui_inputs.assign_spec(a, al.ROD_SPECS['3/8" alloy steel'], list(a.rods))
    assert sw.run_sweep(a).incomplete_rods == []


def test_assigning_an_unknown_rod_raises():
    a = examples.demo_assembly()
    with pytest.raises(KeyError):
        ui_inputs.assign_spec(a, al.ROD_SPECS['3/8" alloy steel'], ["nope"])


def test_manual_overrides_write_only_what_they_are_given():
    a = examples.demo_assembly()
    rod = a.rods["rod_a0"]
    before = (rod.E, rod.I, rod.Fcy)
    ui_inputs.apply_rod_properties(rod, A=0.25, P_tension_allow=9000.0)
    assert rod.A == 0.25 and rod.P_tension_allow == 9000.0
    assert (rod.E, rod.I, rod.Fcy) == before


def test_a_manual_override_can_clear_an_optional_allowable():
    """Clearing a vendor rating must fall back to A_net*Ftu, not keep a stale
    number that no longer reflects what the engineer entered."""
    a = examples.demo_assembly()
    rod = a.rods["rod_a0"]
    ui_inputs.apply_rod_properties(rod, P_tension_allow=9000.0)
    assert al.tension_allowable(rod).value == 9000.0
    ui_inputs.apply_rod_properties(rod, P_tension_allow=None)
    assert al.tension_allowable(rod).value == pytest.approx(rod.A_net * rod.Ftu)


def test_the_rod_editor_helpers_are_streamlit_free():
    import inspect

    for fn in (ui_inputs.spec_assignments, ui_inputs.assign_spec,
               ui_inputs.apply_rod_properties):
        assert "session_state" not in inspect.getsource(fn)
        assert "st." not in inspect.getsource(fn)
