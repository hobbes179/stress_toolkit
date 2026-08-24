"""
tests/tierod/test_ui_scene.py — Session 4 gate (the testable half).

Session 4's formal gate is a manual checklist in a browser, but most of what
can go wrong is structural and does not need eyes:

  * `uirevision` constant, or the camera resets on every slider tick and the
    tool is unusable — the single most common way Streamlit + Plotly 3D fails
  * `aspectmode='data'`, or geometry renders distorted and rod angles look
    wrong, which is exactly what the engineer judges by eye
  * static traces separated from rod traces, so only rods rebuild per rerun
  * the mesh fed to the renderer comes from the SAME `region.point()` that
    feeds the optimizer — never a second geometry definition
  * animation frames move bodies rigidly along a mode with rods still attached

`ui_scene` must not import Streamlit: it maps library objects to Plotly
figures, so it stays testable on its own.
"""
from __future__ import annotations

import numpy as np
import pytest

from tests.tierod.legacy_demo import collinear_plate, mixed_region_assembly, two_tank_demo

from apps.tierod import examples, ui_scene
from conftest import make_hexapod, make_line_supported
from library.tierod import mechanisms as mech
from library.tierod.kernel import assemble


# ======================================================================
# Layout invariants that make the tool usable at all
# ======================================================================


def test_ui_scene_does_not_import_streamlit():
    """The figure layer stays pure so it can be tested and reused."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    code = (
        "import sys; import apps.tierod.ui_scene; "
        "sys.exit(1 if any(m == 'streamlit' or m.startswith('streamlit.') "
        "for m in sys.modules) else 0)"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"ui_scene pulled in Streamlit\n{r.stdout}{r.stderr}"


def test_uirevision_is_constant_across_rebuilds():
    """Streamlit reruns the whole script on every widget change. Without a
    CONSTANT uirevision the camera resets on every slider tick."""
    a = two_tank_demo()
    f1 = ui_scene.build_figure(a)
    # move a rod end, exactly as a slider would
    a.rods["rod_a0"].end_a.q = np.array([1.0, 20.0])
    f2 = ui_scene.build_figure(a)
    assert f1.layout.uirevision == f2.layout.uirevision
    assert f1.layout.uirevision == ui_scene.UIREVISION
    assert f1.layout.scene.uirevision == f2.layout.scene.uirevision


def test_aspectmode_is_data_so_geometry_is_not_distorted():
    f = ui_scene.build_figure(two_tank_demo())
    assert f.layout.scene.aspectmode == "data"


def test_static_traces_are_separated_from_rod_traces():
    """Bodies, regions and CG markers never move while the optimizer runs;
    only rod traces are rebuilt per rerun."""
    a = two_tank_demo()
    static = ui_scene.static_traces(a)
    rods = ui_scene.rod_traces(a)
    assert len(static) > 0 and len(rods) == len(a.rods)
    assert all(t.name not in {r.name for r in rods} for t in static)
    # and the split is exhaustive: the figure is exactly static + rods
    f = ui_scene.build_figure(a)
    assert len(f.data) == len(static) + len(rods)


# ======================================================================
# Geometry is never written twice
# ======================================================================


def test_region_traces_come_from_region_point():
    """The renderer must sample `region.point(q)` — the same function the
    optimizer differentiates — not a parallel geometry implementation."""
    a = two_tank_demo()
    traces = ui_scene.region_traces(a)
    assert traces, "regions must render"

    by_name = {t.name: t for t in traces}
    region = a.regions["band_a"]
    body = a.bodies[region.body_id]
    trace = by_name["band_a"]

    pts = np.column_stack(
        [np.asarray(trace.x).ravel(), np.asarray(trace.y).ravel(), np.asarray(trace.z).ravel()]
    ).T
    finite = pts[:, np.all(np.isfinite(pts), axis=0)]
    assert finite.shape[1] > 10

    # every rendered point must be reproducible by region.point() on the body
    (lo_t, hi_t), (lo_z, hi_z) = region.bounds()
    for j in range(0, finite.shape[1], 7):
        p_local = body.R.T @ (finite[:, j] - body.origin)
        # invert the band parameterization and check point() reproduces it
        th = np.arctan2(p_local[1], p_local[0]) % (2.0 * np.pi)
        q = np.array([th, p_local[2]])
        assert np.allclose(body.to_global(region.point(q)), finite[:, j], atol=1e-9)


def test_region_trace_dimension_matches_the_primitive():
    """2-D regions render as a surface, 1-D as a swept line, 0-D as a marker —
    generated from `ndim`, with no per-type branching in the caller."""
    a = mixed_region_assembly()
    kinds = {t.name: t.type for t in ui_scene.region_traces(a)}
    assert kinds["patch2d"] == "surface"
    assert kinds["arc1d"] == "scatter3d"
    assert kinds["fixed0d"] == "scatter3d"


def test_body_meshes_come_from_the_clearance_primitives():
    a = two_tank_demo()
    meshes = ui_scene.body_mesh_traces(a)
    assert len(meshes) == 3          # plate + two tanks
    for t in meshes:
        assert t.type == "mesh3d"
        assert 0.0 < t.opacity < 1.0, "bodies must be translucent"
        assert len(t.i) > 0


def test_a_body_without_a_clearance_primitive_is_skipped_not_crashed():
    a = two_tank_demo()
    a.bodies["tank_a"].clearance = None
    meshes = ui_scene.body_mesh_traces(a)
    assert len(meshes) == 2


def test_cg_markers_are_placed_for_free_bodies_only():
    a = two_tank_demo()
    traces = ui_scene.cg_traces(a)
    pts = np.column_stack([np.array([t.x[0], t.y[0], t.z[0]]) for t in traces])
    assert pts.shape[1] == 2, "the grounded plate carries no inertial load"
    for body_id in ("tank_a", "tank_b"):
        body = a.bodies[body_id]
        assert any(np.allclose(pts[:, j], body.to_global(body.cg)) for j in range(2))


# ======================================================================
# Rods
# ======================================================================


def test_rod_traces_span_the_actual_endpoints():
    a = two_tank_demo()
    for trace in ui_scene.rod_traces(a):
        rod = a.rods[trace.name]
        p, q, *_ = a.rod_endpoints(rod)
        assert np.allclose([trace.x[0], trace.y[0], trace.z[0]], p)
        assert np.allclose([trace.x[1], trace.y[1], trace.z[1]], q)


def test_rods_are_coloured_by_load_ratio():
    a = two_tank_demo()
    lr = {rod_id: 0.1 + 0.8 * (i / 11.0) for i, rod_id in enumerate(a.rods)}
    traces = {t.name: t for t in ui_scene.rod_traces(a, load_ratios=lr)}
    low = traces[min(lr, key=lr.get)].line.color
    high = traces[max(lr, key=lr.get)].line.color
    assert low != high, "load ratio must drive rod colour"
    # colour must increase monotonically with load, not jump around
    ramp = [ui_scene.load_ratio_color(x) for x in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert len(set(ramp)) == 5, "the ramp must actually vary"

    # and OVER the allowable must be distinct from exactly AT it — otherwise a
    # rod with no margin left looks identical to one that is just fully used
    assert ui_scene.load_ratio_color(1.01) != ui_scene.load_ratio_color(1.00)
    assert ui_scene.load_ratio_color(2.5) == ui_scene.load_ratio_color(1.01)
    assert ui_scene.load_ratio_color(None) == ui_scene.ROD_NEUTRAL


def test_rod_traces_survive_missing_load_ratios():
    """Before a solve there are no ratios; the scene must still draw."""
    traces = ui_scene.rod_traces(two_tank_demo(), load_ratios=None)
    assert len(traces) == 12
    assert all(t.line.color is not None for t in traces)


# ======================================================================
# Mechanism animation (§5.3) — the highest-value output
# ======================================================================


def test_mechanism_figure_has_frames_and_a_play_control():
    a = collinear_plate()
    asm = assemble(a)
    mode = mech.null_modes(asm)[0]
    fig = ui_scene.mechanism_figure(a, mode, n_frames=16)
    assert len(fig.frames) == 16
    assert fig.layout.uirevision == ui_scene.UIREVISION
    assert fig.layout.scene.aspectmode == "data"
    assert fig.layout.updatemenus, "needs a play control"


def test_animation_moves_bodies_rigidly_and_keeps_rods_attached():
    """A mode animation that detaches a rod from its body is worse than no
    animation: it shows a motion the layout does not permit."""
    a = collinear_plate()
    asm = assemble(a)
    mode = mech.null_modes(asm)[0]

    amp = 1.5
    for phase in (0.0, 0.25, 0.5, 1.0):
        moved = ui_scene.displaced_endpoints(a, mode, amplitude=amp, phase=phase)
        for rod_id, (p, q) in moved.items():
            rod = a.rods[rod_id]
            p0, q0, body_a, body_b = a.rod_endpoints(rod)
            for body_id, base, now in ((body_a, p0, p), (body_b, q0, q)):
                if a.bodies[body_id].is_ground:
                    assert np.allclose(now, base), "ground must not move"
                else:
                    expected = base + mode.displace(
                        body_id, base.reshape(3, 1), amplitude=amp * np.sin(2 * np.pi * phase)
                    ).ravel()
                    assert np.allclose(now, expected)


def test_animation_amplitude_zero_is_the_undeformed_layout():
    a = collinear_plate()
    mode = mech.null_modes(assemble(a))[0]
    moved = ui_scene.displaced_endpoints(a, mode, amplitude=0.0, phase=0.3)
    for rod_id, (p, q) in moved.items():
        p0, q0, *_ = a.rod_endpoints(a.rods[rod_id])
        assert np.allclose(p, p0) and np.allclose(q, q0)


def test_the_collinear_plate_animates_rotation_about_the_plate_line():
    """The Session 4 gate case. The motion shown must be rotation about the
    ground line, and the cause must be named in words."""
    a = collinear_plate()
    report = mech.check(a)
    assert not report.ok
    assert report.nullity == 1

    axis = report.modes[0].common_axis()
    assert axis is not None
    point, direction = axis
    assert abs(abs(float(direction @ np.array([1.0, 0.0, 0.0]))) - 1.0) < 1e-7

    assert any("collinear" in m.lower() for m in report.messages)
    assert any(f.kind == "collinear_ground" for f in report.findings)

    # and the animation actually turns the body about that line: every point
    # keeps its distance to the axis, to first order
    mode = report.modes[0]
    asm = assemble(a)

    def worst_radius_error(amplitude, phase=0.25):
        moved = ui_scene.displaced_endpoints(a, mode, amplitude=amplitude, phase=phase)
        worst = 0.0
        for j, rod_id in enumerate(asm.rod_ids):
            before, after = asm.points_a[:, j], moved[rod_id][0]
            r0 = np.linalg.norm(np.cross(before - point, direction))
            r1 = np.linalg.norm(np.cross(after - point, direction))
            worst = max(worst, abs(r1 - r0) / max(r0, 1e-9))
        return worst

    for phase in (0.2, 0.6):
        assert worst_radius_error(0.4, phase) < 1e-3, "must turn about the axis"

    # A mode is a LINEARIZED rigid motion, so points travel along tangents and
    # the radius grows second order — the same small-displacement assumption
    # the kernel makes. Prove the discrepancy is exactly that by halving the
    # amplitude and watching the error fall roughly fourfold, rather than
    # papering over it with a loose tolerance.
    e1 = worst_radius_error(0.4)
    e2 = worst_radius_error(0.2)
    assert e1 > 0.0 and 3.2 < e1 / e2 < 4.8, (
        f"radius error should be quadratic in amplitude, got ratio {e1 / e2:.2f}"
    )


def test_mechanism_figure_handles_a_multi_body_mode():
    a = two_tank_demo()
    del a.rods["rod_a0"]
    del a.rods["rod_b0"]
    modes = mech.null_modes(assemble(a))
    assert modes
    fig = ui_scene.mechanism_figure(a, modes[0], n_frames=8)
    assert len(fig.frames) == 8


# ======================================================================
# Example assemblies used by the app and the gate checklist
# ======================================================================


def test_demo_assembly_is_valid_and_solvable():
    a = two_tank_demo()
    a.validate()
    report = mech.check(a)
    assert report.graph.ok
    assert len(a.rods) == 12
    assert len(a.bodies) == 3


def test_collinear_plate_is_the_documented_failure_case():
    a = collinear_plate()
    a.validate()
    assert mech.check(a).nullity >= 1


def test_every_example_builds_a_figure():
    for name, factory in examples.EXAMPLES.items():
        a = factory()
        a.validate()
        fig = ui_scene.build_figure(a)
        assert len(fig.data) > 0, name
        assert fig.layout.scene.aspectmode == "data", name


# ======================================================================
# Session 5 — the worst-direction cone
# ======================================================================


def test_the_cone_sits_at_the_rod_midpoint_and_points_along_n_hat():
    a = two_tank_demo()
    d = np.array([0.0, 0.6, -0.8])
    (cone,) = ui_scene.worst_direction_traces(a, "rod_a0", d)

    p, q, *_ = a.rod_endpoints(a.rods["rod_a0"])
    mid = 0.5 * (p + q)
    assert (cone.x[0], cone.y[0], cone.z[0]) == pytest.approx(tuple(mid))

    vec = np.array([cone.u[0], cone.v[0], cone.w[0]], dtype=float)
    assert np.allclose(vec / np.linalg.norm(vec), d)
    assert cone.anchor == "tail"


def test_the_cone_direction_is_normalized_before_scaling():
    """An unnormalized n_hat would make the glyph length report the load
    magnitude, which it is not — the cone shows a DIRECTION."""
    a = two_tank_demo()
    short = ui_scene.worst_direction_traces(a, "rod_a0", [0.0, 0.0, 1.0])[0]
    long = ui_scene.worst_direction_traces(a, "rod_a0", [0.0, 0.0, 900.0])[0]
    assert short.w[0] == pytest.approx(long.w[0])


def test_a_rod_with_no_worst_direction_gets_no_cone():
    a = two_tank_demo()
    assert ui_scene.worst_direction_traces(a, "rod_a0", np.zeros(3)) == []
    assert ui_scene.worst_direction_traces(a, "not_a_rod", [0, 0, 1.0]) == []


def test_the_cone_is_only_added_when_asked_for():
    a = two_tank_demo()
    plain = ui_scene.build_figure(a)
    with_cone = ui_scene.build_figure(
        a, worst_direction=("rod_a0", np.array([0.0, 0.0, 1.0]))
    )
    assert len(with_cone.data) == len(plain.data) + 1
    assert any(t.type == "cone" for t in with_cone.data)
    assert not any(t.type == "cone" for t in plain.data)


def test_the_cone_does_not_disturb_the_camera_revision():
    a = two_tank_demo()
    fig = ui_scene.build_figure(
        a, worst_direction=("rod_a0", np.array([1.0, 0.0, 0.0]))
    )
    assert fig.layout.uirevision == ui_scene.UIREVISION
    assert fig.layout.scene.uirevision == ui_scene.UIREVISION
