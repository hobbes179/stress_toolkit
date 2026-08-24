"""
Plotly scene for the tie-rod module (build prompt §10).

**Imports Plotly and numpy but NOT Streamlit**, so the whole figure layer is
unit-testable and reusable outside the app.

Three implementation details that otherwise bite, all asserted in the tests:

* **`uirevision` is mandatory and must be constant.** Streamlit reruns the
  entire script on every widget change; without it the camera resets on every
  slider tick and the tool is unusable. This is the most common way
  Streamlit + Plotly 3D goes wrong.
* **`scene.aspectmode = 'data'`.** Otherwise the axes normalize independently,
  geometry renders distorted and rod angles look wrong — which is exactly what
  the engineer is judging by eye.
* **Static traces are split from rod traces.** Bodies, regions and CG markers
  never move while the optimizer runs; only the rods are rebuilt per rerun.
  The solve is microseconds, figure serialization is the only real cost.

Geometry is never written twice: 2-D and 1-D regions are meshed by sampling
`region.point(q)`, the same function the optimizer differentiates, and body
shells come from `Body.clearance.surface_mesh()`.
"""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from library.tierod.model import Assembly

UIREVISION = "tierod-scene"

BODY_COLOR = "#7C8DA6"
BODY_OPACITY = 0.22
REGION_COLOR = "#2E86DE"
CG_COLOR = "#E67E22"
ROD_NEUTRAL = "#4A5568"
AXIS_COLOR = "#C0392B"
WORST_DIR_COLOR = "#8E44AD"
GRID_N = 24


# ----------------------------------------------------------------------
# Load-ratio colouring
# ----------------------------------------------------------------------


def load_ratio_color(lr: float | None) -> str:
    """Green through amber to red, saturating past LR = 1 (no margin left)."""
    if lr is None:
        return ROD_NEUTRAL
    x = float(np.clip(lr, 0.0, 1.0))
    if lr > 1.0:
        return "#8E0B0B"          # over the allowable: distinct, not just dark red
    if x < 0.5:
        t = x / 0.5
        r, g, b = (int(46 + t * (241 - 46)), int(160 + t * (196 - 160)), int(67 + t * (15 - 67)))
    else:
        t = (x - 0.5) / 0.5
        r, g, b = (int(241 + t * (192 - 241)), int(196 + t * (57 - 196)), int(15 + t * (43 - 15)))
    return f"#{r:02X}{g:02X}{b:02X}"


# ----------------------------------------------------------------------
# Static traces: bodies, regions, CG markers
# ----------------------------------------------------------------------


def body_mesh_traces(assembly: Assembly, opacity: float = BODY_OPACITY) -> list:
    """Translucent shells from each body's clearance primitive.

    A body with no clearance primitive is skipped rather than treated as an
    error — the primitive drives non-penetration, and a model can be perfectly
    valid without one.
    """
    traces = []
    for body in assembly.bodies.values():
        if body.clearance is None:
            continue
        v_local, faces = body.clearance.surface_mesh()
        v = body.origin[:, None] + body.R @ v_local
        traces.append(
            go.Mesh3d(
                x=v[0],
                y=v[1],
                z=v[2],
                i=faces[:, 0],
                j=faces[:, 1],
                k=faces[:, 2],
                color=BODY_COLOR,
                opacity=opacity,
                flatshading=True,
                hoverinfo="name",
                name=body.id,
                showlegend=False,
            )
        )
    return traces


def region_traces(assembly: Assembly, n: int = GRID_N) -> list:
    """Attachment regions, sampled from `region.point(q)`.

    Dispatch is on `region.ndim` alone — 2-D becomes a surface, 1-D a swept
    line, 0-D a marker — so a new region primitive needs no code here.
    """
    traces = []
    for region in assembly.regions.values():
        body = assembly.bodies[region.body_id]
        bounds = region.bounds()

        if region.ndim == 2:
            (lo0, hi0), (lo1, hi1) = bounds
            u = np.linspace(lo0, hi0, n)
            v = np.linspace(lo1, hi1, n)
            X = np.zeros((n, n))
            Y = np.zeros((n, n))
            Z = np.zeros((n, n))
            for i, ui in enumerate(u):
                for j, vj in enumerate(v):
                    p = body.to_global(region.point(np.array([ui, vj])))
                    X[i, j], Y[i, j], Z[i, j] = p
            traces.append(
                go.Surface(
                    x=X, y=Y, z=Z,
                    surfacecolor=np.zeros((n, n)),
                    colorscale=[[0.0, REGION_COLOR], [1.0, REGION_COLOR]],
                    opacity=0.45, showscale=False, hoverinfo="name",
                    name=region.id, showlegend=False,
                )
            )
        elif region.ndim == 1:
            (lo, hi) = bounds[0]
            pts = np.column_stack(
                [body.to_global(region.point(np.array([t])))
                 for t in np.linspace(lo, hi, 4 * n)]
            )
            traces.append(
                go.Scatter3d(
                    x=pts[0], y=pts[1], z=pts[2], mode="lines",
                    line=dict(color=REGION_COLOR, width=6),
                    hoverinfo="name", name=region.id, showlegend=False,
                )
            )
        else:
            p = body.to_global(region.point(np.zeros(0)))
            traces.append(
                go.Scatter3d(
                    x=[p[0]], y=[p[1]], z=[p[2]], mode="markers",
                    marker=dict(size=5, color=REGION_COLOR, symbol="diamond"),
                    hoverinfo="name", name=region.id, showlegend=False,
                )
            )
    return traces


def cg_traces(assembly: Assembly) -> list:
    """CG markers for FREE bodies. A ground body carries no inertial load, so
    marking its CG would imply a load path that does not exist."""
    traces = []
    for body in assembly.bodies.values():
        if body.is_ground:
            continue
        p = body.to_global(body.cg)
        traces.append(
            go.Scatter3d(
                x=[p[0]], y=[p[1]], z=[p[2]], mode="markers+text",
                marker=dict(size=7, color=CG_COLOR, symbol="x"),
                text=[f"  cg {body.id}"], textposition="middle right",
                textfont=dict(size=10, color=CG_COLOR),
                hovertext=f"{body.id}: {body.mass:g} lb x {body.g_factor:g} g",
                hoverinfo="text", name=f"cg::{body.id}", showlegend=False,
            )
        )
    return traces


def static_traces(assembly: Assembly) -> list:
    """Everything that does not move while rod ends are being dragged."""
    return body_mesh_traces(assembly) + region_traces(assembly) + cg_traces(assembly)


# ----------------------------------------------------------------------
# Rods — the only traces rebuilt per rerun
# ----------------------------------------------------------------------


def rod_traces(assembly: Assembly, load_ratios=None, selected=None) -> list:
    """One line per rod, coloured by load ratio when a solve has been run."""
    traces = []
    for rod_id, rod in assembly.rods.items():
        a, b, *_ = assembly.rod_endpoints(rod)
        lr = None if load_ratios is None else load_ratios.get(rod_id)
        label = f"{rod_id}" if lr is None else f"{rod_id}  LR {lr:.3f}"
        traces.append(
            go.Scatter3d(
                x=[a[0], b[0]], y=[a[1], b[1]], z=[a[2], b[2]],
                mode="lines",
                line=dict(
                    color=load_ratio_color(lr),
                    width=10 if rod_id == selected else 6,
                ),
                hovertext=label, hoverinfo="text",
                name=rod_id, showlegend=False,
            )
        )
    return traces


# ----------------------------------------------------------------------
# Figures
# ----------------------------------------------------------------------


def _scene_layout(**extra) -> dict:
    return dict(
        scene=dict(
            aspectmode="data",          # never let the axes normalize separately
            uirevision=UIREVISION,
            xaxis_title="X (in)",
            yaxis_title="Y (in)",
            zaxis_title="Z (in)",
            **extra,
        ),
        uirevision=UIREVISION,          # constant: the camera must survive reruns
        margin=dict(l=0, r=0, t=28, b=0),
        height=620,
        showlegend=False,
    )


def worst_direction_traces(assembly: Assembly, rod_id: str, direction,
                           scale: float | None = None) -> list:
    """A cone at the selected rod's midpoint, along that rod's worst load
    direction `n_hat*`.

    `n_hat*_i = row_i(T)/||row_i(T)||` is the closed-form answer to "which way
    would you have to load this assembly to break THIS rod", and it is the
    diagnostic that explains why a rod governs. Drawn on one rod at a time: 12
    cones at 12 different angles is noise.

    A rod that carries no load has no worst direction; it gets no cone rather
    than an arbitrary one.
    """
    d = np.asarray(direction, dtype=float).reshape(3)
    n = float(np.linalg.norm(d))
    if rod_id not in assembly.rods or n < 1e-12:
        return []
    d = d / n
    a, b, *_ = assembly.rod_endpoints(assembly.rods[rod_id])
    mid = 0.5 * (a + b)
    size = float(scale if scale is not None else 0.25 * _model_extent(assembly))
    return [
        go.Cone(
            x=[mid[0]], y=[mid[1]], z=[mid[2]],
            u=[d[0] * size], v=[d[1] * size], w=[d[2] * size],
            anchor="tail", sizemode="absolute", sizeref=size,
            colorscale=[[0.0, WORST_DIR_COLOR], [1.0, WORST_DIR_COLOR]],
            showscale=False, hovertext=f"{rod_id} worst direction",
            hoverinfo="text", name=f"worst::{rod_id}", showlegend=False,
        )
    ]


def build_figure(assembly: Assembly, load_ratios=None, selected=None,
                 static=None, worst_direction=None) -> go.Figure:
    """The main scene. Pass `static` to reuse cached static traces.

    `worst_direction` is `(rod_id, n_hat)` for the cone glyph, or None.
    """
    traces = list(static if static is not None else static_traces(assembly))
    traces += rod_traces(assembly, load_ratios, selected)
    if worst_direction is not None:
        traces += worst_direction_traces(assembly, *worst_direction)
    fig = go.Figure(data=traces)
    fig.update_layout(**_scene_layout())
    return fig


# ----------------------------------------------------------------------
# Mechanism animation (§5.3) — the highest-value output the tool produces
# ----------------------------------------------------------------------


def _phase_amplitude(amplitude: float, phase: float) -> float:
    """Sinusoidal sweep, so the animation eases through the neutral position
    and reverses instead of snapping back."""
    return amplitude * float(np.sin(2.0 * np.pi * phase))


def displaced_endpoints(assembly: Assembly, mode, amplitude: float = 1.0,
                        phase: float = 0.25) -> dict:
    """`{rod_id: (a, b)}` with each end carried by ITS OWN body.

    Ground bodies do not appear in a mode, so their ends stay put; this is what
    keeps the rods attached during the animation instead of drifting off the
    geometry.
    """
    amp = _phase_amplitude(amplitude, phase)
    out = {}
    for rod_id, rod in assembly.rods.items():
        a, b, body_a, body_b = assembly.rod_endpoints(rod)
        moved = []
        for body_id, p in ((body_a, a), (body_b, b)):
            if body_id in mode.per_body:
                p = p + mode.displace(body_id, p.reshape(3, 1), amplitude=amp).ravel()
            moved.append(p)
        out[rod_id] = (moved[0], moved[1])
    return out


def _displaced_body_mesh(assembly: Assembly, body, mode, amp: float):
    v_local, faces = body.clearance.surface_mesh()
    v = body.origin[:, None] + body.R @ v_local
    if body.id in mode.per_body:
        v = v + mode.displace(body.id, v, amplitude=amp)
    return v, faces


def mechanism_figure(assembly: Assembly, mode, n_frames: int = 24,
                     amplitude: float | None = None) -> go.Figure:
    """Animate the assembly along one null mode, rods drawn in.

    Do not report "singular" — show the motion the layout permits. Amplitude
    defaults to a visible fraction of the model size; modes are normalized so
    that a unit amplitude is roughly a real displacement in inches.
    """
    if amplitude is None:
        amplitude = 0.12 * _model_extent(assembly)

    bodies = [b for b in assembly.bodies.values() if b.clearance is not None]
    rod_ids = list(assembly.rods)

    def frame_data(phase: float) -> list:
        amp = _phase_amplitude(amplitude, phase)
        data = []
        for body in bodies:
            v, faces = _displaced_body_mesh(assembly, body, mode, amp)
            data.append(
                go.Mesh3d(
                    x=v[0], y=v[1], z=v[2],
                    i=faces[:, 0], j=faces[:, 1], k=faces[:, 2],
                    color=BODY_COLOR, opacity=BODY_OPACITY, flatshading=True,
                    name=body.id, showlegend=False, hoverinfo="name",
                )
            )
        moved = displaced_endpoints(assembly, mode, amplitude, phase)
        for rod_id in rod_ids:
            a, b = moved[rod_id]
            data.append(
                go.Scatter3d(
                    x=[a[0], b[0]], y=[a[1], b[1]], z=[a[2], b[2]],
                    mode="lines", line=dict(color=ROD_NEUTRAL, width=6),
                    name=rod_id, showlegend=False, hoverinfo="name",
                )
            )
        return data

    phases = np.linspace(0.0, 1.0, n_frames, endpoint=False)
    frames = [
        go.Frame(
            data=frame_data(float(p)),
            name=f"{i:03d}",
            traces=list(range(len(bodies) + len(rod_ids))),
        )
        for i, p in enumerate(phases)
    ]

    fig = go.Figure(data=frame_data(0.0), frames=frames)

    # the rotation axis, when the mode has one — the named cause, drawn
    axis = mode.common_axis()
    if axis is not None:
        point, direction = axis
        span = _model_extent(assembly)
        ends = np.column_stack([point - direction * span, point + direction * span])
        fig.add_trace(
            go.Scatter3d(
                x=ends[0], y=ends[1], z=ends[2], mode="lines",
                line=dict(color=AXIS_COLOR, width=4, dash="dash"),
                name="rotation axis", hoverinfo="name", showlegend=False,
            )
        )

    fig.update_layout(
        **_scene_layout(),
        updatemenus=[
            dict(
                type="buttons",
                showactive=False,
                x=0.02, y=0.04, xanchor="left", yanchor="bottom",
                buttons=[
                    dict(
                        label="▶ Play",
                        method="animate",
                        args=[
                            None,
                            dict(
                                frame=dict(duration=70, redraw=True),
                                fromcurrent=True,
                                transition=dict(duration=0),
                                mode="immediate",
                            ),
                        ],
                    ),
                    dict(
                        label="❚❚ Pause",
                        method="animate",
                        args=[
                            [None],
                            dict(
                                frame=dict(duration=0, redraw=False),
                                mode="immediate",
                            ),
                        ],
                    ),
                ],
            )
        ],
    )
    return fig


def _model_extent(assembly: Assembly) -> float:
    """Rough overall size, used to scale the animation and the axis glyph."""
    pts = []
    for rod in assembly.rods.values():
        a, b, *_ = assembly.rod_endpoints(rod)
        pts.extend([a, b])
    if not pts:
        return 1.0
    P = np.column_stack(pts)
    extent = float(np.max(P.max(axis=1) - P.min(axis=1)))
    return extent if extent > 0.0 else 1.0


__all__ = [
    "UIREVISION",
    "load_ratio_color",
    "body_mesh_traces",
    "region_traces",
    "cg_traces",
    "static_traces",
    "rod_traces",
    "worst_direction_traces",
    "build_figure",
    "displaced_endpoints",
    "mechanism_figure",
]
