"""
apps/beam_section/plotting.py

Plotting for the Beam Section module.

Two figure types:
  * draw_section()  — proportional section diagram with key points
  * draw_contour()  — smooth filled contour of a stress field over the
                      section interior, using constrained triangulation
                      so the boundary follows the section outline exactly
                      and inner voids are excluded.

Both figures always render on a white background regardless of UI theme,
for print-friendliness.
"""

from __future__ import annotations
import math
from typing import Sequence

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.tri as mtri
from matplotlib.patches import Polygon as MplPolygon, PathPatch
from matplotlib.path import Path

from library.shapes import Section, KeyPoint
from ui.theme import PLOT_PALETTE


# ──────────────────────────────────────────────────────────────────────────
# Helpers — point-in-polygon, ray casting
# ──────────────────────────────────────────────────────────────────────────
def _point_in_poly(y: float, z: float, poly: np.ndarray) -> bool:
    """Ray-casting point-in-polygon test. poly is (N, 2) array."""
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        yi, zi = poly[i]
        yj, zj = poly[j]
        if ((zi > z) != (zj > z)) and (y < (yj - yi) * (z - zi) / (zj - zi + 1e-30) + yi):
            inside = not inside
        j = i
    return inside


def _point_in_section(y: float, z: float, polys: list[np.ndarray]) -> bool:
    """True if point is inside outer polygon AND outside any inner voids."""
    if not polys:
        return False
    if not _point_in_poly(y, z, polys[0]):
        return False
    # Any subsequent polygon is a void
    for hole in polys[1:]:
        if _point_in_poly(y, z, hole):
            return False
    return True


# ──────────────────────────────────────────────────────────────────────────
# Section diagram (proportional, key points labelled)
# ──────────────────────────────────────────────────────────────────────────
def draw_section(section: Section, kps: Sequence[KeyPoint]):
    """
    Draw the section outline with key points labelled. Returns the figure.
    """
    P = PLOT_PALETTE
    fig, ax = plt.subplots(figsize=(6, 6), facecolor=P["background"])
    ax.set_facecolor(P["background"])

    polys = section.polygon_vertices()

    if len(polys) == 1:
        ax.add_patch(MplPolygon(
            polys[0], closed=True,
            facecolor=P["section_fill"],
            edgecolor=P["section_edge"],
            linewidth=2, zorder=2,
        ))
    elif len(polys) >= 2:
        # Outer polygon filled, holes punched out using compound path
        outer = polys[0]
        path_verts = list(map(tuple, outer)) + [tuple(outer[0])]
        codes = [Path.MOVETO] + [Path.LINETO] * (len(outer) - 1) + [Path.CLOSEPOLY]
        for hole in polys[1:]:
            # Reverse hole vertex order so the fill rule punches it out
            h = hole[::-1] if not _is_clockwise(hole) else hole
            path_verts += list(map(tuple, h)) + [tuple(h[0])]
            codes += [Path.MOVETO] + [Path.LINETO] * (len(h) - 1) + [Path.CLOSEPOLY]
        compound = Path(path_verts, codes)
        ax.add_patch(PathPatch(
            compound,
            facecolor=P["section_fill"],
            edgecolor=P["section_edge"],
            linewidth=2, zorder=2,
        ))

    cy = section.cy()
    cz = section.cz()

    # Centroid crosshair
    cs = max(cy, cz) * 0.10
    ax.plot([-cs, cs], [0, 0], color=P["centroid"], lw=1.2, ls="--", alpha=0.5, zorder=4)
    ax.plot([0, 0], [-cs, cs], color=P["centroid"], lw=1.2, ls="--", alpha=0.5, zorder=4)

    # Key points
    for kp in kps:
        ax.plot(kp.y, kp.z, "o",
                color=P["kp_marker"], ms=8,
                mec=P["kp_edge"], mew=1, zorder=6)
        offset_y = 0.06 * cy + 0.06 * abs(kp.y)
        offset_z = 0.06 * cz + 0.06 * abs(kp.z)
        if kp.y < 0:
            offset_y = -offset_y
        if kp.z < 0:
            offset_z = -offset_z
        if abs(kp.y) < 1e-6 and abs(kp.z) < 1e-6:
            offset_y = 0.10 * cy
            offset_z = 0.10 * cz
        ax.annotate(
            kp.id,
            (kp.y, kp.z),
            xytext=(kp.y + offset_y, kp.z + offset_z),
            fontsize=7, color=P["kp_marker"], fontweight="bold",
            ha="center", va="center", zorder=7,
            bbox=dict(boxstyle="circle,pad=0.15",
                      fc="white", ec=P["kp_marker"], lw=0.8),
        )

    pad = max(cy, cz) * 0.45
    ax.set_xlim(-cy - pad, cy + pad * 1.4)
    ax.set_ylim(-cz - pad, cz + pad)
    ax.set_xlabel("y  (in)", fontsize=9, color=P["text"])
    ax.set_ylabel("z  (in)", fontsize=9, color=P["text"])
    ax.set_aspect("equal", "datalim")
    ax.tick_params(labelsize=8, colors=P["tick"])
    for sp in ax.spines.values():
        sp.set_edgecolor(P["spine"])
    ax.grid(True, alpha=0.2, color=P["grid"])

    title = (f"{section.name}  |  A={section.area():.4f} in²  "
             f"Iy={section.Iy():.4f} in⁴  Sy={section.Sy():.4f} in³")
    ax.set_title(title, fontsize=8, color=P["text"], pad=8)
    fig.tight_layout()
    return fig


def _is_clockwise(verts: np.ndarray) -> bool:
    """Shoelace formula sign — True if vertices are clockwise ordered."""
    s = 0.0
    n = len(verts)
    for i in range(n):
        x1, y1 = verts[i]
        x2, y2 = verts[(i + 1) % n]
        s += (x2 - x1) * (y2 + y1)
    return s > 0


# ──────────────────────────────────────────────────────────────────────────
# Stress field at arbitrary (y, z) point
# ──────────────────────────────────────────────────────────────────────────
def _stress_at(section: Section, loads, y: float, z: float) -> dict:
    """Compute σ₁, σ₂, σ_vm, τ_total, σ_total at a single (y, z)."""
    A   = section.area()
    Iy  = section.Iy()
    Iz  = section.Iz()
    Qy  = section.Qy()
    Qz  = section.Qz()
    tw_y = section.tw_y()
    tw_z = section.tw_z()
    tau_T = section.tau_T(loads.T)

    sa = loads.P / A / 1000 if A > 0 else 0.0
    sb = ((loads.My * z / Iy if Iy > 0 else 0.0) +
          (loads.Mz * y / Iz if Iz > 0 else 0.0)) / 1000
    sn = sa + sb

    tvy = loads.Vy * Qy / (Iy * tw_y) / 1000 if (Iy > 0 and tw_y > 0) else 0.0
    tvz = loads.Vz * Qz / (Iz * tw_z) / 1000 if (Iz > 0 and tw_z > 0) else 0.0
    tau = math.sqrt(tvy**2 + tvz**2 + tau_T**2)

    half = sn / 2
    radius = math.sqrt(half**2 + tau**2)
    s1 = half + radius
    s2 = half - radius
    svm = math.sqrt(s1**2 - s1 * s2 + s2**2)

    return dict(σ1=s1, σ2=s2, σ_vm=svm, τ_total=tau, σ_total=sn)


# ──────────────────────────────────────────────────────────────────────────
# Smooth contour using triangulation
# ──────────────────────────────────────────────────────────────────────────
def draw_contour(
    section: Section,
    loads,
    field_key: str,
    *,
    n_interior: int = 800,
):
    """
    Draw a filled stress contour over the section.

    Method:
      1. Collect boundary points from the polygon vertices (outer + inner).
      2. Generate interior sample points on a regular grid inside the
         section (rejection-sampled via point-in-section test).
      3. Build a Delaunay triangulation of all points.
      4. Mask triangles whose centroids fall outside the section (handles
         both the outer boundary AND interior voids cleanly).
      5. Evaluate the stress field at each node.
      6. Render via tricontourf for smooth interpolation.

    Args:
        section:    Section instance
        loads:      Loads instance
        field_key:  one of "σ1", "σ2", "σ_vm", "τ_total", "σ_total"
        n_interior: target number of interior sample points

    Returns:
        matplotlib Figure
    """
    P = PLOT_PALETTE
    fig, ax = plt.subplots(figsize=(6, 6), facecolor=P["background"])
    ax.set_facecolor(P["background"])

    polys = section.polygon_vertices()
    if not polys:
        ax.text(0.5, 0.5, "Section has no geometry",
                ha="center", va="center", transform=ax.transAxes,
                fontsize=11, color=P["text"])
        return fig

    cy = section.cy()
    cz = section.cz()

    # ── Step 1: boundary points (outer + any holes) ──────────────────────
    boundary_y: list[float] = []
    boundary_z: list[float] = []
    for poly in polys:
        # Densify long edges so contour boundary is smooth on straight edges
        densified = _densify(poly, max_edge_length=max(cy, cz) * 0.05)
        boundary_y.extend(densified[:, 0])
        boundary_z.extend(densified[:, 1])

    # ── Step 2: interior grid sample points ──────────────────────────────
    # Choose grid spacing so we get roughly n_interior points inside the section.
    bbox_area = (2 * cy) * (2 * cz)
    sec_area = section.area()
    if sec_area <= 0:
        sec_area = bbox_area * 0.3
    density = n_interior / sec_area
    spacing = 1.0 / math.sqrt(density) if density > 0 else 0.1

    ny = max(int((2 * cy) / spacing), 8)
    nz = max(int((2 * cz) / spacing), 8)
    ys_grid = np.linspace(-cy, cy, ny)
    zs_grid = np.linspace(-cz, cz, nz)

    interior_y: list[float] = []
    interior_z: list[float] = []
    margin = spacing * 0.5  # don't place interior points too close to boundary
    for yg in ys_grid:
        for zg in zs_grid:
            if _point_in_section(yg, zg, polys):
                # Reject points within `margin` of any boundary edge
                if _dist_to_any_polygon(yg, zg, polys) > margin:
                    interior_y.append(yg)
                    interior_z.append(zg)

    all_y = np.array(boundary_y + interior_y)
    all_z = np.array(boundary_z + interior_z)

    if len(all_y) < 4:
        ax.text(0.5, 0.5, "Insufficient mesh nodes",
                ha="center", va="center", transform=ax.transAxes,
                fontsize=11, color=P["text"])
        return fig

    # ── Step 3: Delaunay triangulation ───────────────────────────────────
    try:
        triang = mtri.Triangulation(all_y, all_z)
    except (RuntimeError, ValueError):
        ax.text(0.5, 0.5, "Triangulation failed",
                ha="center", va="center", transform=ax.transAxes,
                fontsize=11, color=P["text"])
        return fig

    # ── Step 4: mask triangles whose centroid is outside the section ─────
    tri_centers_y = all_y[triang.triangles].mean(axis=1)
    tri_centers_z = all_z[triang.triangles].mean(axis=1)
    mask = np.array([
        not _point_in_section(yc, zc, polys)
        for yc, zc in zip(tri_centers_y, tri_centers_z)
    ])
    triang.set_mask(mask)

    # ── Step 5: stress at each node ──────────────────────────────────────
    field_values = np.array([
        _stress_at(section, loads, y, z)[field_key]
        for y, z in zip(all_y, all_z)
    ])

    # ── Step 6: render ───────────────────────────────────────────────────
    vmin = float(np.nanmin(field_values))
    vmax = float(np.nanmax(field_values))
    span = vmax - vmin
    rel_span = span / max(abs(vmin), abs(vmax), 1e-6)
    is_uniform = rel_span < 1e-6 or span < 1e-8
    uniform_val = (vmin + vmax) / 2  # only meaningful when is_uniform

    if is_uniform:
        # Flat fill using the colormap midpoint colour.
        # The uniform value is placed in the figure title (outside the axes)
        # so it can never overlap the section geometry regardless of section size.
        cmap = plt.get_cmap(P["contour_cmap"])
        flat_color = cmap(0.5)
        for poly in polys[:1]:
            ax.add_patch(MplPolygon(
                poly, closed=True,
                facecolor=flat_color, edgecolor=P["section_edge"],
                linewidth=2, zorder=2, alpha=0.85,
            ))
        for hole in polys[1:]:
            ax.add_patch(MplPolygon(
                hole, closed=True,
                facecolor="white", edgecolor=P["section_edge"],
                linewidth=2, zorder=3,
            ))
    else:
        # 9 boundary lines → 8 discrete colour bands (≥7 as requested)
        levels = np.linspace(vmin, vmax, 9)
        cf = ax.tricontourf(triang, field_values,
                            levels=levels,
                            cmap=P["contour_cmap"],
                            vmin=vmin, vmax=vmax)
        # Thin white contour lines at each band boundary
        ax.tricontour(triang, field_values,
                      levels=levels,
                      colors="white", linewidths=0.5, alpha=0.6)
        cb = fig.colorbar(cf, ax=ax, fraction=0.04, pad=0.04)
        cb.set_label(f"{field_key}  (ksi)", fontsize=9, color=P["text"])
        cb.ax.tick_params(labelsize=8, colors=P["text"])

    # Section boundary overlay (so outline is always crisp)
    for poly in polys[:1]:
        ax.add_patch(MplPolygon(
            poly, closed=True,
            fill=False, edgecolor=P["section_edge"],
            linewidth=2.0, zorder=8,
        ))
    for hole in polys[1:]:
        ax.add_patch(MplPolygon(
            hole, closed=True,
            fill=False, edgecolor=P["section_edge"],
            linewidth=2.0, zorder=8,
        ))

    # Fixed axis limits — identical for every field so the section always
    # appears at the same scale. adjustable="box" means matplotlib shrinks
    # the axes box (not the data limits) to maintain equal aspect, which
    # guarantees our xlim/ylim are honoured exactly and the section size is
    # consistent whether or not the uniform annotation is present.
    pad = max(cy, cz) * 0.45
    ax.set_xlim(-cy - pad, cy + pad)
    ax.set_ylim(-cz - pad, cz + pad)
    ax.set_xlabel("y  (in)", fontsize=9, color=P["text"])
    ax.set_ylabel("z  (in)", fontsize=9, color=P["text"])
    ax.set_aspect("equal", adjustable="box")
    ax.tick_params(labelsize=8, colors=P["tick"])
    for sp in ax.spines.values():
        sp.set_edgecolor(P["spine"])

    # Title — uniform value shown here so it is always outside the axes area
    uniform_suffix = f"  |  Uniform: {uniform_val:.4f} ksi" if is_uniform else ""
    ax.set_title(
        f"{field_key} field  —  {section.name}{uniform_suffix}",
        fontsize=9, color=P["text"], pad=8,
    )
    fig.tight_layout()
    return fig


# ──────────────────────────────────────────────────────────────────────────
# Polygon densification and distance helpers
# ──────────────────────────────────────────────────────────────────────────
def _densify(poly: np.ndarray, max_edge_length: float) -> np.ndarray:
    """Subdivide polygon edges so no edge exceeds max_edge_length."""
    if max_edge_length <= 0:
        return poly
    out: list[np.ndarray] = []
    n = len(poly)
    for i in range(n):
        p0 = poly[i]
        p1 = poly[(i + 1) % n]
        out.append(p0)
        edge_len = np.linalg.norm(p1 - p0)
        if edge_len > max_edge_length:
            n_sub = int(np.ceil(edge_len / max_edge_length))
            for k in range(1, n_sub):
                t = k / n_sub
                out.append(p0 * (1 - t) + p1 * t)
    return np.array(out)


def _dist_to_segment(py: float, pz: float,
                     a: np.ndarray, b: np.ndarray) -> float:
    """Shortest distance from point (py, pz) to segment a→b."""
    ab = b - a
    ap = np.array([py, pz]) - a
    ab_len_sq = ab @ ab
    if ab_len_sq < 1e-30:
        return float(np.linalg.norm(ap))
    t = max(0.0, min(1.0, (ap @ ab) / ab_len_sq))
    closest = a + t * ab
    return float(np.linalg.norm(np.array([py, pz]) - closest))


def _dist_to_any_polygon(y: float, z: float, polys: list[np.ndarray]) -> float:
    """Min distance from (y, z) to any edge across all polygons."""
    md = float("inf")
    for poly in polys:
        n = len(poly)
        for i in range(n):
            d = _dist_to_segment(y, z, poly[i], poly[(i + 1) % n])
            if d < md:
                md = d
    return md
