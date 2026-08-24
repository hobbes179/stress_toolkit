"""
tests/tierod/test_ui_build.py — Session 9 gate: the construction UI.

Almost every test here is on the PURE half of `ui_build`. That is the point of
the split: the rules that can lose a user's work — clipping an attachment,
reseeding one, cascading a delete, converting an angle — are functions, so they
can be pinned without driving a browser.

The end of the file drives the real page through `AppTest`, which is the only
thing that catches a stale widget key handed back to Streamlit outside its own
range. That failure mode is invisible to unit tests by construction.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from apps.tierod import ui_build as ub
from library.tierod import serialize
from library.tierod.clearance import CLEARANCE_TYPES, Box, Cylinder, Sphere
from library.tierod.model import (
    REGION_TYPES,
    Annulus,
    Assembly,
    Body,
    CircleArc,
    PlanarPatch,
    Removed,
    Segment,
    frame_from_axis,
    new_region,
    new_rod,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


@pytest.fixture
def two_body() -> Assembly:
    """Ground disc + free plate, one arc and one annulus, one rod between.

    Chosen because both regions have DIMENSIONAL bounds (an arc's theta range,
    an annulus's radii). A `PlanarPatch` normalizes q to [0, 1] regardless of
    its width, so shrinking one can never strand an attachment — it is the
    wrong shape to test the clipping rule with.
    """
    asm = Assembly({"g": Body("g", is_ground=True), "p": Body("p")}, {}, {})
    asm.add_region(
        new_region("CircleArc", "arc", "g", axis="Z", radius=8.0,
                   theta_min=0.0, theta_max=2.0 * np.pi)
    )
    asm.add_region(
        new_region("Annulus", "ann", "p", axis="Z", origin=[0.0, 0.0, 6.0],
                   r_inner=2.0, r_outer=9.0)
    )
    asm.add_rod(
        new_rod(asm, "r1", "arc", "ann",
                q_a=[np.radians(170.0)], q_b=[8.0, np.radians(30.0)])
    )
    return asm


def _qr_triad() -> np.ndarray:
    """A right-handed orthonormal frame that is not any axis dropdown value."""
    Q, _ = np.linalg.qr(np.array([[1.0, 2.0, 3.0], [0.0, 1.0, 4.0], [5.0, 6.0, 0.0]]))
    if np.linalg.det(Q) < 0:
        Q[:, 0] *= -1.0
    return Q


# ----------------------------------------------------------------------
# Units — degrees in, radians stored
# ----------------------------------------------------------------------


def test_angles_are_edited_in_degrees_and_stored_in_radians():
    assert ub.display_to_stored("angle", 180.0) == pytest.approx(np.pi)
    assert ub.stored_to_display("angle", np.pi) == pytest.approx(180.0)


def test_lengths_pass_through_untouched():
    assert ub.display_to_stored("length", 2.5) == 2.5
    assert ub.stored_to_display("length", 2.5) == 2.5


def test_vec3_survives_the_round_trip_as_three_numbers():
    out = ub.display_to_stored("vec3", np.array([1.0, 2.0, 3.0]))
    assert out == (1.0, 2.0, 3.0)
    assert ub.stored_to_display("vec3", (4.0, 5.0, 6.0)) == (4.0, 5.0, 6.0)


def test_the_units_round_trip_for_every_declared_parameter():
    """Every kind any primitive declares must survive display -> stored -> display."""
    for cls in (*REGION_TYPES.values(), *CLEARANCE_TYPES.values()):
        for f in ub.param_fields(cls):
            back = ub.stored_to_display(f.kind, ub.display_to_stored(f.kind, f.value))
            assert np.allclose(np.asarray(back, dtype=float),
                               np.asarray(f.value, dtype=float)), (cls, f.attr)


def test_a_full_circle_reads_as_360_not_as_two_pi():
    """The whole reason `kind` exists. 6.28 in a degree box is a silent lie."""
    fields = {f.attr: f.value for f in ub.param_fields(CircleArc)}
    assert fields["theta_max"] == pytest.approx(360.0)


# ----------------------------------------------------------------------
# param_fields — self-generating from PARAMS
# ----------------------------------------------------------------------


def test_param_fields_on_a_class_gives_the_declared_defaults():
    fields = ub.param_fields(PlanarPatch)
    assert [f.attr for f in fields] == ["width", "height"]
    assert [f.value for f in fields] == [1.0, 1.0]


def test_param_fields_on_an_instance_gives_that_instance_s_values(two_body):
    fields = {f.attr: f.value for f in ub.param_fields(two_body.regions["ann"])}
    assert fields == {"r_inner": 2.0, "r_outer": 9.0,
                      "theta_min": pytest.approx(0.0),
                      "theta_max": pytest.approx(360.0)}


@pytest.mark.parametrize("cls", list(REGION_TYPES.values()) + list(CLEARANCE_TYPES.values()))
def test_every_primitive_is_editable_without_a_line_of_ui_code(cls):
    """Adding a primitive must never require touching this file or ui_build.

    The builder reads `PARAMS` and nothing else, so this asserts the contract
    holds rather than that any particular primitive is present.
    """
    fields = ub.param_fields(cls)
    assert all(f.kind in {"length", "angle", "vec3"} for f in fields)
    assert all(f.step > 0 for f in fields)
    assert len({f.attr for f in fields}) == len(fields)


def test_the_box_half_extents_render_as_one_vec3_field_not_three_lengths():
    fields = ub.param_fields(Box)
    assert len(fields) == 1 and fields[0].kind == "vec3"


# ----------------------------------------------------------------------
# apply_params — clearance shells only
# ----------------------------------------------------------------------


def test_apply_params_writes_a_clearance_shell_in_stored_units():
    prim = Cylinder(origin=np.zeros(3), **dict(zip(("e1", "e2", "e3"),
                                                   frame_from_axis("Z"))))
    ub.apply_params(prim, {"radius": 3.0, "z_min": -1.0, "z_max": 4.0})
    assert (prim.radius, prim.z_min, prim.z_max) == (3.0, -1.0, 4.0)


def test_apply_params_revalidates_so_a_bad_number_is_refused_at_the_edit():
    prim = Box(origin=np.zeros(3), **dict(zip(("e1", "e2", "e3"),
                                              frame_from_axis("Z"))))
    with pytest.raises(ValueError):
        ub.apply_params(prim, {"half_extents": (1.0, -1.0, 1.0)})


def test_apply_params_rejects_a_parameter_the_primitive_does_not_declare():
    prim = Sphere(origin=np.zeros(3), **dict(zip(("e1", "e2", "e3"),
                                                 frame_from_axis("Z"))))
    with pytest.raises(KeyError):
        ub.apply_params(prim, {"height": 2.0})


# ----------------------------------------------------------------------
# axis_name
# ----------------------------------------------------------------------


@pytest.mark.parametrize("axis", ["X", "Y", "Z"])
def test_axis_name_recovers_the_dropdown_value_that_built_the_triad(axis):
    region = new_region("PlanarPatch", "r", "b", axis=axis)
    assert ub.axis_name(region) == axis


def test_an_arbitrary_triad_reports_custom_rather_than_claiming_an_axis(two_body):
    """Re-selecting 'Z' on a region that is not on Z would rotate real geometry."""
    Q = _qr_triad()
    region = two_body.regions["ann"]
    region.e1, region.e2, region.e3 = Q[:, 0], Q[:, 1], Q[:, 2]
    assert ub.axis_name(region) == ub.CUSTOM_AXIS


# ----------------------------------------------------------------------
# unique_id
# ----------------------------------------------------------------------


def test_unique_id_returns_the_stem_when_it_is_free():
    assert ub.unique_id([], "body") == "body"


def test_unique_id_skips_names_already_taken():
    assert ub.unique_id(["body", "body_2"], "body") == "body_3"


def test_unique_id_never_collides_over_repeated_adds():
    taken: list[str] = []
    for _ in range(25):
        name = ub.unique_id(taken, "rod")
        assert name not in taken
        taken.append(name)


# ----------------------------------------------------------------------
# replace_region — the attachment repair
# ----------------------------------------------------------------------


def test_shrinking_a_region_drags_its_attachments_inside_and_says_so(two_body):
    """Rule 1. Without the clip, `validate()` refuses the whole model."""
    report = ub.replace_region(two_body, "arc", params={"theta_max": 90.0})
    assert report.clipped == ("r1.a",)
    assert np.degrees(two_body.rods["r1"].end_a.q[0]) == pytest.approx(90.0)
    two_body.validate()


def test_the_clipped_attachment_is_named_not_just_counted(two_body):
    report = ub.replace_region(two_body, "ann", params={"r_outer": 4.0})
    assert "r1.b" in report.message()


def test_shrinking_without_the_repair_would_have_been_invalid(two_body):
    """Pins WHY the clip exists: the un-repaired model is a hard failure."""
    two_body.regions["arc"].theta_max = np.radians(90.0)   # the naive edit
    with pytest.raises(ValueError, match="outside the bounds"):
        two_body.validate()


def test_changing_a_region_s_type_reseeds_its_attachments(two_body):
    """Rule 2. ndim changed, so every q on it is now the wrong length."""
    report = ub.replace_region(two_body, "ann", type_name="Segment")
    assert report.reseeded == ("r1.b",)
    assert two_body.rods["r1"].end_b.q.size == Segment.ndim
    two_body.validate()


def test_a_retype_that_keeps_ndim_clips_rather_than_reseeds(two_body):
    """CircleArc and Segment are both 1-D, so no `q` is the wrong length.

    The VALUE still moves: 170 means degrees-of-arc on one type and inches
    along a rail on the other, and 2.97 rad is outside a 1 in segment. Nothing
    could carry that number across meaningfully, so it is clipped into the new
    domain and reported — which is the honest outcome, not a preserved number.
    """
    report = ub.replace_region(two_body, "arc", type_name="Segment")
    assert report.reseeded == ()
    assert report.clipped == ("r1.a",)
    assert two_body.regions["arc"].in_bounds(two_body.rods["r1"].end_a.q)
    two_body.validate()


def test_parameters_carry_across_a_retype_by_name(two_body):
    """A theta range the user set must not be thrown away by a type change."""
    ub.replace_region(two_body, "arc", params={"theta_min": 30.0, "theta_max": 150.0})
    ub.replace_region(two_body, "arc", type_name="Annulus")
    arc = two_body.regions["arc"]
    assert np.degrees(arc.theta_min) == pytest.approx(30.0)
    assert np.degrees(arc.theta_max) == pytest.approx(150.0)


def test_a_parameter_with_no_counterpart_falls_back_to_the_new_default(two_body):
    """CircleArc.radius has no name in Annulus — it is defaulted, not guessed."""
    ub.replace_region(two_body, "arc", params={"radius": 8.0})
    ub.replace_region(two_body, "arc", type_name="Annulus")
    assert two_body.regions["arc"].r_outer == Annulus.r_outer


def test_replace_region_keeps_an_arbitrary_triad_when_no_axis_is_given(two_body):
    """A JSON-loaded frame must survive an unrelated parameter edit."""
    Q = _qr_triad()
    region = two_body.regions["ann"]
    region.e1, region.e2, region.e3 = Q[:, 0], Q[:, 1], Q[:, 2]
    ub.replace_region(two_body, "ann", params={"r_outer": 5.0})
    after = two_body.regions["ann"]
    assert np.allclose(np.column_stack([after.e1, after.e2, after.e3]), Q)
    assert after.r_outer == 5.0


def test_naming_an_axis_does_rebuild_the_triad(two_body):
    ub.replace_region(two_body, "ann", axis="X")
    assert ub.axis_name(two_body.regions["ann"]) == "X"


def test_replace_region_preserves_the_body_the_region_belongs_to(two_body):
    ub.replace_region(two_body, "ann", type_name="Segment")
    assert two_body.regions["ann"].body_id == "p"


def test_replace_region_preserves_the_origin_when_none_is_given(two_body):
    before = two_body.regions["ann"].origin.copy()
    ub.replace_region(two_body, "ann", params={"r_outer": 5.0})
    assert np.allclose(two_body.regions["ann"].origin, before)


def test_replace_region_preserves_keepouts(two_body):
    two_body.regions["ann"].keepouts = ["sentinel"]
    ub.replace_region(two_body, "ann", params={"r_outer": 5.0})
    assert two_body.regions["ann"].keepouts == ["sentinel"]


def test_replace_region_leaves_attachments_on_other_regions_alone(two_body):
    before = two_body.rods["r1"].end_b.q.copy()
    ub.replace_region(two_body, "arc", params={"theta_max": 45.0})
    assert np.allclose(two_body.rods["r1"].end_b.q, before)


def test_replace_region_rejects_an_unknown_region(two_body):
    with pytest.raises(KeyError):
        ub.replace_region(two_body, "nope", params={})


def test_replace_region_rejects_an_unknown_type(two_body):
    with pytest.raises(ValueError, match="unknown region type"):
        ub.replace_region(two_body, "arc", type_name="Trapezoid")


def test_replace_region_rejects_a_parameter_the_type_does_not_declare(two_body):
    with pytest.raises(KeyError):
        ub.replace_region(two_body, "arc", params={"width": 3.0})


def test_an_edit_that_moves_nothing_reports_nothing_moved(two_body):
    report = ub.replace_region(two_body, "arc", params={"radius": 9.0})
    assert not report
    assert "no attachment moved" in report.message()


# ----------------------------------------------------------------------
# region_changed — the guard that keeps the sliders usable
# ----------------------------------------------------------------------


def test_region_changed_is_false_when_nothing_differs(two_body):
    region = two_body.regions["arc"]
    params = {f.attr: f.value for f in ub.param_fields(region)}
    assert not ub.region_changed(region, type_name="CircleArc", axis="Z",
                                 origin=region.origin, params=params)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"type_name": "Segment"},
        {"axis": "X"},
        {"origin": [1.0, 0.0, 0.0]},
        {"params": {"radius": 99.0}},
        {"params": {"theta_max": 90.0}},
    ],
)
def test_region_changed_notices_each_kind_of_edit(two_body, kwargs):
    assert ub.region_changed(two_body.regions["arc"], **kwargs)


def test_region_changed_compares_angles_in_display_units(two_body):
    """theta_max is 2*pi stored and 360 displayed. Comparing raw would say
    'changed' on every rerun and purge the sliders continuously."""
    assert not ub.region_changed(two_body.regions["arc"],
                                 params={"theta_max": 360.0})


# ----------------------------------------------------------------------
# stale_keys — rule 3
# ----------------------------------------------------------------------


def test_stale_keys_selects_the_rod_scoped_widget_state():
    keys = ["tierod::q::r1::a::0", "tierod::topo::r1::b", "tierod::rodprop::r1::A",
            "tierod::qrod", "tierod::spec_targets"]
    assert ub.stale_keys(keys) == sorted(keys)


def test_stale_keys_leaves_the_model_bearing_state_alone():
    """Purging these would throw away the user's actual model or their example
    choice — the cache is disposable, the model is not."""
    keys = ["tierod::assembly", "tierod::example", "tierod::loaded",
            "tierod::sf_ult", "tierod::sf_yield", "tierod::b::rp::arc::radius"]
    assert ub.stale_keys(keys) == []


def test_the_design_slider_key_format_is_the_one_stale_keys_purges():
    """Couples the two modules: if `ui_inputs` renames its slider key, this
    fails instead of the purge silently becoming a no-op."""
    from apps.tierod import ui_inputs

    asm = Assembly({"g": Body("g", is_ground=True), "p": Body("p")}, {}, {})
    asm.add_region(new_region("CircleArc", "arc", "g", axis="Z"))
    asm.add_region(new_region("Annulus", "ann", "p", axis="Z"))
    asm.add_rod(new_rod(asm, "r1", "arc", "ann"))
    keys = [s.key for s in ui_inputs.slider_specs(asm)]
    assert keys and ub.stale_keys(keys) == sorted(keys)


# ----------------------------------------------------------------------
# removal_message
# ----------------------------------------------------------------------


def test_removal_message_names_everything_the_cascade_took(two_body):
    message = ub.removal_message(two_body.remove_body("g"))
    assert "g" in message and "arc" in message and "r1" in message


def test_removal_message_counts_and_pluralizes():
    message = ub.removal_message(Removed(regions=["a"], rods=["x", "y"]))
    assert "1 region" in message and "2 rods" in message


def test_removal_message_is_honest_about_an_empty_cascade():
    assert ub.removal_message(Removed()) == "Removed nothing."


def test_deleting_a_region_reports_the_rods_that_went_with_it(two_body):
    message = ub.removal_message(two_body.remove_region("arc"))
    assert "r1" in message
    assert "r1" not in two_body.rods


# ----------------------------------------------------------------------
# Build -> serialize -> analyse, end to end on the pure layer
# ----------------------------------------------------------------------


def test_a_model_built_entirely_through_the_helpers_solves(two_body):
    """The whole point: geometry created here reaches the kernel intact."""
    from library.tierod.kernel import assemble

    asm = Assembly({}, {}, {})
    asm.add_body(Body("base", is_ground=True))
    asm.add_body(Body("top", mass=100.0, origin=np.array([0.0, 0.0, 10.0])))
    asm.add_region(new_region("CircleArc", "base_r", "base", axis="Z", radius=10.0))
    asm.add_region(new_region("CircleArc", "top_r", "top", axis="Z", radius=6.0))
    for i in range(8):
        asm.add_rod(
            new_rod(asm, f"rod_{i}", "base_r", "top_r",
                    q_a=[2.0 * np.pi * i / 8.0],
                    q_b=[2.0 * np.pi * (i + 0.5) / 8.0])
        )
    asm.validate()
    built = assemble(asm)
    assert built.n_dof == 6
    assert len(built.rod_ids) == 8


def test_a_built_model_round_trips_through_json(two_body):
    ub.replace_region(two_body, "ann", axis="X", params={"r_outer": 5.5})
    back = serialize.loads(serialize.dumps(two_body))
    back.validate()
    assert ub.axis_name(back.regions["ann"]) == "X"
    assert back.regions["ann"].r_outer == 5.5


def test_a_truncated_file_raises_rather_than_loading_half_a_model(two_body):
    text = serialize.dumps(two_body)
    with pytest.raises(Exception):
        serialize.loads(text[: len(text) // 2])


def test_a_wrong_schema_file_is_refused(two_body):
    payload = serialize.to_dict(two_body)
    payload["schema"] = serialize.SCHEMA_VERSION + 1
    with pytest.raises(ValueError):
        serialize.loads(json.dumps(payload))


# ----------------------------------------------------------------------
# The running page
# ----------------------------------------------------------------------

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

PAGE = "pages/3_Tie_Rod_Layout.py"
TIMEOUT = 120


def _run(**session_state):
    at = AppTest.from_file(PAGE, default_timeout=TIMEOUT)
    for key, value in session_state.items():
        at.session_state[key] = value
    return at.run()


def _with_model(assembly):
    """Session state that installs `assembly` instead of an example.

    The example name must be a REAL one. A sentinel there is silently reset by
    the selectbox and the page rebuilds the example over the injected model —
    the test then passes for the wrong reason.
    """
    from apps.tierod import examples

    return {
        "tierod::assembly": assembly,
        "tierod::loaded": examples.DEFAULT_EXAMPLE,
        "tierod::example": examples.DEFAULT_EXAMPLE,
    }


def test_the_build_tab_renders_on_the_default_example():
    at = _run()
    assert not at.exception, [e.value for e in at.exception]


def test_an_empty_model_says_what_to_do_instead_of_crashing():
    """Mid-build the model has no rods. Every analysis tab must survive it —
    a traceback there takes the builder tab down with it."""
    at = _run(**_with_model(Assembly({}, {}, {})))
    assert not at.exception, [e.value for e in at.exception]
    assert any("no rods yet" in str(i.value).lower() for i in at.info)


def test_a_model_with_bodies_but_no_rods_survives():
    asm = Assembly({"g": Body("g", is_ground=True), "p": Body("p")}, {}, {})
    asm.add_region(new_region("CircleArc", "arc", "g", axis="Z"))
    at = _run(**_with_model(asm))
    assert not at.exception, [e.value for e in at.exception]


def _stale_slider_model() -> Assembly:
    """A 90-degree arc carrying a rod, ready for a 170-degree stale key."""
    asm = Assembly({"g": Body("g", is_ground=True), "p": Body("p")}, {}, {})
    asm.add_region(new_region("CircleArc", "arc", "g", axis="Z", radius=8.0,
                              theta_min=0.0, theta_max=np.radians(90.0)))
    asm.add_region(new_region("Annulus", "ann", "p", origin=[0.0, 0.0, 6.0],
                              axis="Z", r_inner=2.0, r_outer=9.0))
    asm.add_rod(new_rod(asm, "r1", "arc", "ann"))
    return asm


def test_streamlit_does_not_clamp_a_session_value_to_a_slider_s_range():
    """The measured behaviour the clipping rule exists for.

    If a future Streamlit starts clamping, this fails and the guard in
    `apply_rod_q` can be reconsidered — rather than the guard quietly becoming
    dead code nobody dares remove.
    """
    def page():
        # `from_function` re-executes the source without this module's imports.
        import streamlit as st

        st.write(f"value={st.slider('x', 0.0, 1.0, 0.5, key='k')}")

    at = AppTest.from_function(page, default_timeout=TIMEOUT)
    at.session_state["k"] = 9.0
    at.run()
    assert not at.exception
    assert any("value=9.0" in str(m.value) for m in at.markdown)


def test_a_stale_slider_value_never_reaches_the_model():
    """Rule 3, stated as the invariant that actually matters.

    A slider key holding 170 deg while its region now stops at 90 deg is NOT
    refused by Streamlit — it is handed back verbatim. Unclipped it lands in
    the model, and the next rerun refuses the whole assembly.
    """
    asm = _stale_slider_model()
    at = _run(**_with_model(asm),
              **{"tierod::q::r1::a::0": np.radians(170.0)})  # from a wider arc
    assert not at.exception, [e.value for e in at.exception]
    assert asm.regions["arc"].in_bounds(asm.rods["r1"].end_a.q)
    asm.validate()


def test_a_stale_slider_does_not_poison_the_next_rerun():
    """The failure as the user meets it: the page dies one interaction later,
    naming a rod they never touched, with Reset as the only way out."""
    asm = _stale_slider_model()
    at = _run(**_with_model(asm),
              **{"tierod::q::r1::a::0": np.radians(170.0)})
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert not any("inconsistent" in str(e.value).lower() for e in at.error)


def test_the_builder_does_not_disturb_a_healthy_layout():
    """Adding the Build tab must not change any number the module reports."""
    at = _run()
    assert not at.exception
    assert any("no mechanism" in str(s.value).lower() for s in at.success)


# ----------------------------------------------------------------------
# The live builder scene (added after the owner asked to see what is being
# built — before this the Build tab had no view at all and you had to
# switch tabs to find out what your numbers made)
# ----------------------------------------------------------------------


def test_the_scene_caption_counts_what_is_on_screen(two_body):
    text = ub.scene_caption(two_body)
    assert "2 bodies" in text and "2 region(s)" in text and "1 rod(s)" in text


def test_the_scene_caption_says_how_many_bodies_are_ground(two_body):
    assert "(1 ground)" in ub.scene_caption(two_body)


def test_the_scene_caption_handles_a_single_body():
    asm = Assembly({"only": Body("only")}, {}, {})
    assert "1 body" in ub.scene_caption(asm)


def test_the_scene_caption_says_there_is_nothing_to_draw_yet():
    assert "nothing to draw" in ub.scene_caption(Assembly({}, {}, {})).lower()


def test_the_caption_tracks_a_cascade(two_body):
    """The commonest build surprise is a rod that quietly went with a region.
    The counts are what make that visible."""
    two_body.remove_region("arc")
    assert "0 rod(s)" in ub.scene_caption(two_body)


def test_the_build_tab_draws_the_model_it_is_editing():
    """An exact count, because `>= 2` passed with the builder scene deleted.

    A healthy default page renders exactly three Plotly charts:
      1. the builder scene          (ui_build)
      2. the layout scene           (render, Layout tab)
      3. the results chart          (ui_results)
    The mechanism animation is a fourth, rendered only when there are modes.
    If you add or remove a chart, update this number deliberately — that is
    the point of pinning it.
    """
    at = _run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.get("plotly_chart")) == 3
