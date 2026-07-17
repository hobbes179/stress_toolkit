"""
apps/beam_section/plotting_interactive.py

Interactive stress contour (design handoff §6.2) — the Plotly working view
with a hover probe. Unlike the legacy matplotlib contour, the shear field
here is a REAL 2-D distribution: it comes from the FEM elasticity solution
(sectionproperties), so σ, τ, the principal stresses, σ_vm and the local
minimum margin are all correct at every interior point and readable on hover.

The matplotlib triangulated contour (plotting.draw_contour) is retained as
the print-quality "report figure".

Requires the FEM backend; callers should check fem_available() first and
fall back to the matplotlib view otherwise.
"""

from __future__ import annotations

import numpy as np

from library.materials import Material
from apps.beam_section.calculations import (
    Loads, neutral_axis_angle_deg, principal_axis_angle_deg, shear_center,
)


# Fields the user can display; the hover shows all of them regardless.
FIELD_LABELS = {
    "σ_x (axial+bending)": "sx",
    "τ (shear)":           "tau",
    "σ₁ (max principal)":  "s1",
    "σ₂ (min principal)":  "s2",
    "σ_vm (von Mises)":    "svm",
    "min MS":              "ms",
}


def _grid_mask(outer, voids, ys, zs):
    """Boolean (nz, ny) mask: True where a grid point is inside the section."""
    from matplotlib.path import Path
    Y, Z = np.meshgrid(ys, zs)
    pts = np.column_stack([Y.ravel(), Z.ravel()])
    inside = Path(np.asarray(outer)).contains_points(pts)
    for v in voids:
        inside &= ~Path(np.asarray(v)).contains_points(pts)
    return inside.reshape(Z.shape), Y, Z


def _min_ms_field(sig, tau, s1, s2, svm, material, sf_yield, sf_ult):
    """
    Vectorized local minimum margin over the §3.6 checks (for the hover probe).
    Operates on the whole grid at once — replaces the old per-point Python loop.
    NaN-masked points stay NaN (von-Mises term propagates the NaN).
    """
    Fty = material.Fty or 0.0
    Ftu = material.Ftu or 0.0
    Fcy = material.Fcy or 0.0
    Fsu = material.Fsu or 0.0

    def ms(allow, sf, applied):
        if allow <= 0:
            return np.full_like(applied, np.inf)
        return allow / (sf * np.maximum(np.abs(applied), 1e-9)) - 1.0

    out = ms(Fty, sf_yield, svm)                                      # vM yield
    out = np.minimum(out, np.where(s1 > 0, ms(Ftu, sf_ult, s1), np.inf))
    out = np.minimum(out, np.where(s2 < 0, ms(Fcy, sf_yield, s2), np.inf))
    out = np.minimum(out, ms(Fsu, sf_ult, tau))                      # shear ult
    return out


def compute_stress_field(section, loads: Loads, mesh_scale: float = 1.0,
                         n_grid: int = 160):
    """
    The expensive half of the interactive contour: the FEM elasticity solve
    over an n_grid × n_grid raster of the section. Returns (ys, zs, sig, tau)
    with σ, τ in ksi and points outside the section/mesh set to NaN.

    Pure and picklable — wrap in st.cache_data so overlay toggles and field
    switches (which don't change σ/τ) never re-trigger the FEM solve.
    """
    from library.analysis.fem_solver import fem_stress_at
    from apps.beam_section.calculations import fem_mesh_size_for

    geom = section.geometry()
    outer = np.asarray(geom.outer)
    voids = [np.asarray(v) for v in geom.voids]
    cy, cz = section.cy(), section.cz()

    ys = np.linspace(-cy, cy, n_grid)
    zs = np.linspace(-cz, cz, n_grid)
    mask, Y, Z = _grid_mask(outer, voids, ys, zs)
    pts = np.column_stack([Y.ravel(), Z.ravel()])

    ms = fem_mesh_size_for(section, mesh_scale)
    sig, tau = fem_stress_at(outer, voids, ms,
                             loads.P, loads.Vy, loads.Vz,
                             loads.My, loads.Mz, loads.T, pts)
    sig = sig.reshape(Y.shape)
    tau = tau.reshape(Y.shape)

    valid = mask & np.isfinite(sig) & np.isfinite(tau)
    sig = np.where(valid, sig, np.nan)
    tau = np.where(valid, tau, np.nan)
    return ys, zs, sig, tau


def _mesh_edge_segments(section, mesh_scale):
    """(xs, ys) polyline (NaN-separated per triangle) of the FEM element edges,
    in our (y, z) axes — for the optional 'mesh lines' contour overlay."""
    from library.analysis.fem_solver import fem_mesh
    from apps.beam_section.calculations import fem_mesh_size_for
    g = section.geometry()
    verts, tris = fem_mesh(g.outer, g.voids, fem_mesh_size_for(section, mesh_scale))
    xs: list = []
    ys: list = []
    for tri in tris:
        p = verts[tri]
        xs.extend([p[0, 0], p[1, 0], p[2, 0], p[0, 0], np.nan])
        ys.extend([p[0, 1], p[1, 1], p[2, 1], p[0, 1], np.nan])
    return xs, ys


def interactive_stress_contour(
    section, loads: Loads, material: Material,
    sf_yield: float, sf_ult: float, field_key: str,
    mesh_scale: float = 1.0, n_grid: int = 160,
    *,
    shear_app: tuple[float, float] | None = None,
    overlays: set[str] | None = None,
    show_mesh: bool = False,
    field: tuple | None = None,
):
    """
    Build the Plotly interactive stress contour for `field_key` (a value of
    FIELD_LABELS). Returns a plotly.graph_objects.Figure.

    Overlays are toggled via `overlays` (a subset of {"centroid",
    "shear_center", "neutral_axis", "shear_point"}); None = show all. The
    shear-application point is drawn when `shear_app=(y_app, z_app)` is given
    and "shear_point" is enabled. `show_mesh=True` overlays the FEM element
    edges.

    `field` may be a precomputed (ys, zs, sig, tau) tuple from
    compute_stress_field() — pass it (typically from an st.cache_data cache) to
    skip the expensive FEM solve when only overlays or the displayed field
    changed.
    """
    import plotly.graph_objects as go

    if overlays is None:
        overlays = {"centroid", "shear_center", "neutral_axis", "shear_point"}

    geom = section.geometry()
    outer = np.asarray(geom.outer)
    voids = [np.asarray(v) for v in geom.voids]
    cy, cz = section.cy(), section.cz()

    # Expensive FEM grid solve — reuse a cached field when the caller supplies
    # one; otherwise compute it here.
    if field is None:
        ys, zs, sig, tau = compute_stress_field(section, loads, mesh_scale, n_grid)
    else:
        ys, zs, sig, tau = field

    half = sig / 2.0
    radius = np.sqrt(half**2 + tau**2)
    s1 = half + radius
    s2 = half - radius
    svm = np.sqrt(np.clip(sig**2 + 3.0 * tau**2, 0, None))
    ms_field = _min_ms_field(sig, tau, s1, s2, svm, material, sf_yield, sf_ult)

    fields = {"sx": sig, "tau": tau, "s1": s1, "s2": s2, "svm": svm, "ms": ms_field}
    fkey = FIELD_LABELS.get(field_key, "svm")
    disp = fields[fkey]

    # customdata for the hover probe: every field at the cursor.
    customdata = np.dstack([sig, tau, s1, s2, svm, ms_field])
    hover = (
        "y = %{x:.3f} in<br>z = %{y:.3f} in<br>"
        "σ_x = %{customdata[0]:.3f} ksi<br>"
        "τ = %{customdata[1]:.3f} ksi<br>"
        "σ₁ = %{customdata[2]:.3f} ksi<br>"
        "σ₂ = %{customdata[3]:.3f} ksi<br>"
        "σ_vm = %{customdata[4]:.3f} ksi<br>"
        "min MS = %{customdata[5]:.2f}<extra></extra>"
    )

    # The stress fields use the classic Jet ramp (blue low → red high). The
    # MIN MS field is inverted in meaning — LOW margin is the concern — so it
    # gets a REVERSED ramp (red = low margin, blue = safe) and its top is
    # CAPPED at MS = 2.0 so one comfortably-high-margin (or infinite) point
    # never washes out the low-margin detail: everything ≥ 2.0 reads solid blue.
    heat_kwargs: dict = {}
    cbar_title = field_key
    if fkey == "ms":
        MS_CAP = 2.0
        disp = np.minimum(disp, MS_CAP)                # ≥ 2.0 → solid blue
        finite = disp[np.isfinite(disp)]
        zmin = float(np.min(finite)) if finite.size else 0.0
        if zmin >= MS_CAP:                             # whole section is safe
            zmin = 0.0
        heat_kwargs = dict(zmin=zmin, zmax=MS_CAP, reversescale=True)
        cbar_title = "min MS (≥2.0)"

    fig = go.Figure()
    fig.add_trace(go.Heatmap(
        x=ys, y=zs, z=disp, customdata=customdata,
        colorscale="Jet", connectgaps=False,   # classic blue→green→red stress plot
        hovertemplate=hover,
        colorbar=dict(title=cbar_title),
        **heat_kwargs,
    ))

    # Optional FEM mesh-line overlay (drawn under the outline/markers).
    if show_mesh:
        mxs, mys = _mesh_edge_segments(section, mesh_scale)
        fig.add_trace(go.Scatter(
            x=mxs, y=mys, mode="lines",
            line=dict(color="rgba(255,255,255,0.28)", width=0.5),
            name="mesh", hoverinfo="skip"))

    # Crisp boundary + void outlines.
    def _closed(loop):
        p = np.vstack([loop, loop[0]])
        return p[:, 0], p[:, 1]
    xo, yo = _closed(outer)
    fig.add_trace(go.Scatter(x=xo, y=yo, mode="lines",
                             line=dict(color="white", width=2),
                             hoverinfo="skip", showlegend=False))
    for v in voids:
        xv, yv = _closed(v)
        fig.add_trace(go.Scatter(x=xv, y=yv, mode="lines",
                                 line=dict(color="white", width=2),
                                 hoverinfo="skip", showlegend=False))

    # Overlays: centroid, shear centre, neutral axis, shear-application point.
    if "centroid" in overlays:
        fig.add_trace(go.Scatter(x=[0], y=[0], mode="markers",
                                 marker=dict(symbol="cross", size=9, color="white"),
                                 name="centroid", hoverinfo="name"))
    sc = shear_center(section)
    if "shear_center" in overlays and sc is not None and (
            abs(sc[0]) > 1e-4 or abs(sc[1]) > 1e-4):
        fig.add_trace(go.Scatter(x=[sc[0]], y=[sc[1]], mode="markers",
                                 marker=dict(symbol="x", size=10, color="#ff6d00"),
                                 name="shear center", hoverinfo="name"))
    if "neutral_axis" in overlays:
        na = neutral_axis_angle_deg(section, loads)
        if na is not None:
            L = max(cy, cz) * 1.3
            ang = np.radians(na)
            fig.add_trace(go.Scatter(
                x=[-L * np.cos(ang), L * np.cos(ang)],
                y=[-L * np.sin(ang), L * np.sin(ang)],
                mode="lines", line=dict(color="white", width=1.2, dash="dot"),
                name="neutral axis", hoverinfo="name"))
    if "shear_point" in overlays and shear_app is not None:
        ya, za = shear_app
        # Distinct from the shear CENTER (orange ✕): the point where transverse
        # shear is actually applied (yellow diamond). Offset from SC ⇒ torsion.
        fig.add_trace(go.Scatter(
            x=[ya], y=[za], mode="markers",
            marker=dict(symbol="diamond", size=11, color="#ffd60a",
                        line=dict(color="black", width=1)),
            name="shear applied", hoverinfo="name"))
    if "principal_axes" in overlays:
        # Two perpendicular principal centroidal axes (cyan). Coincide with
        # Y/Z for symmetric sections; rotated for L/Z (Iyz ≠ 0).
        pa = np.radians(principal_axis_angle_deg(section))
        L = max(cy, cz) * 1.25
        for off, nm in [(0.0, "principal 1"), (np.pi / 2, "principal 2")]:
            a = pa + off
            fig.add_trace(go.Scatter(
                x=[-L * np.cos(a), L * np.cos(a)],
                y=[-L * np.sin(a), L * np.sin(a)],
                mode="lines", line=dict(color="#00d5ff", width=1.1, dash="dashdot"),
                name=nm, hoverinfo="name"))
    if "load_arrows" in overlays:
        # In-plane load-direction arrows from the shear-application point
        # (or centroid): transverse shears Vy/Vz, plus a torsion spin glyph.
        ya, za = shear_app if shear_app is not None else (0.0, 0.0)
        Larr = max(cy, cz) * 0.55
        red = "#ff1744"

        def _arrow(dx, dy, label):
            fig.add_annotation(
                x=ya + dx, y=za + dy, ax=ya, ay=za,
                xref="x", yref="y", axref="x", ayref="y",
                showarrow=True, arrowhead=3, arrowsize=1.3, arrowwidth=2.2,
                arrowcolor=red, text=label, font=dict(color=red, size=11),
                standoff=1,
            )

        if abs(loads.Vy) > 1e-9:
            _arrow(np.sign(loads.Vy) * Larr, 0.0, "V_y")
        if abs(loads.Vz) > 1e-9:
            _arrow(0.0, np.sign(loads.Vz) * Larr, "V_z")
        if abs(loads.T) > 1e-9:
            # ↺ = +T (CCW about +X out of page), ↻ = −T.
            spin = "↺ T" if loads.T > 0 else "↻ T"
            fig.add_annotation(x=cy * 0.72, y=cz * 0.72, text=spin,
                               showarrow=False,
                               font=dict(color=red, size=16))

    pad = max(cy, cz) * 0.12
    fig.update_xaxes(title="y (in)", range=[-cy - pad, cy + pad],
                     constrain="domain", zeroline=False)
    fig.update_yaxes(title="z (in)", range=[-cz - pad, cz + pad],
                     scaleanchor="x", scaleratio=1, zeroline=False)
    fig.update_layout(
        template="plotly_dark", height=520,
        margin=dict(l=40, r=10, t=30, b=40),
        title=f"{field_key} — {section.name}  (FEM field, hover to probe)",
        legend=dict(orientation="h", y=-0.12),
    )
    return fig
