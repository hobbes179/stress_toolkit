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
    Loads, neutral_axis_angle_deg, shear_center,
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


def _point_min_ms(sx, tau, s1, s2, svm, material, sf_yield, sf_ult, fbu):
    """Local minimum margin over the §3.6 checks (for the hover probe)."""
    Fty = material.Fty or 0.0
    Ftu = material.Ftu or 0.0
    Fcy = material.Fcy or 0.0
    Fsu = material.Fsu or 0.0

    def ms(allow, sf, applied):
        a = max(abs(applied), 1e-9)
        return allow / (sf * a) - 1 if allow > 0 else np.inf

    checks = [
        ms(Fty, sf_yield, svm),                       # von Mises yield
        ms(Ftu, sf_ult, s1) if s1 > 0 else np.inf,    # ultimate (tension)
        ms(Fcy, sf_yield, s2) if s2 < 0 else np.inf,  # compression yield
        ms(Fsu, sf_ult, tau),                         # shear ultimate
    ]
    return min(checks)


def interactive_stress_contour(
    section, loads: Loads, material: Material,
    sf_yield: float, sf_ult: float, field_key: str,
    mesh_scale: float = 1.0, n_grid: int = 160,
):
    """
    Build the Plotly interactive stress contour for `field_key` (a value of
    FIELD_LABELS). Returns a plotly.graph_objects.Figure.
    """
    import plotly.graph_objects as go
    from library.analysis.fem_solver import fem_stress_at, default_mesh_size
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

    # Only keep points that are both inside the polygon and inside the mesh.
    valid = mask & np.isfinite(sig) & np.isfinite(tau)
    sig = np.where(valid, sig, np.nan)
    tau = np.where(valid, tau, np.nan)

    half = sig / 2.0
    radius = np.sqrt(half**2 + tau**2)
    s1 = half + radius
    s2 = half - radius
    svm = np.sqrt(np.clip(sig**2 + 3.0 * tau**2, 0, None))

    fbu = section.effective_f_cozzone * (material.Ftu or 0.0)
    ms_field = np.full(sig.shape, np.nan)
    ii = np.where(valid)
    for i, j in zip(*ii):
        ms_field[i, j] = _point_min_ms(sig[i, j], tau[i, j], s1[i, j], s2[i, j],
                                       svm[i, j], material, sf_yield, sf_ult, fbu)

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

    fig = go.Figure()
    fig.add_trace(go.Heatmap(
        x=ys, y=zs, z=disp, customdata=customdata,
        colorscale="Jet", connectgaps=False,   # classic blue→green→red stress plot
        hovertemplate=hover,
        colorbar=dict(title=field_key),
    ))

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

    # Overlays: centroid, shear centre, neutral axis (bending), principal axes.
    fig.add_trace(go.Scatter(x=[0], y=[0], mode="markers",
                             marker=dict(symbol="cross", size=9, color="white"),
                             name="centroid", hoverinfo="name"))
    sc = shear_center(section)
    if sc is not None and (abs(sc[0]) > 1e-4 or abs(sc[1]) > 1e-4):
        fig.add_trace(go.Scatter(x=[sc[0]], y=[sc[1]], mode="markers",
                                 marker=dict(symbol="x", size=10, color="#ff6d00"),
                                 name="shear center", hoverinfo="name"))
    na = neutral_axis_angle_deg(section, loads)
    if na is not None:
        L = max(cy, cz) * 1.3
        ang = np.radians(na)
        fig.add_trace(go.Scatter(
            x=[-L * np.cos(ang), L * np.cos(ang)],
            y=[-L * np.sin(ang), L * np.sin(ang)],
            mode="lines", line=dict(color="white", width=1.2, dash="dot"),
            name="neutral axis", hoverinfo="name"))

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
