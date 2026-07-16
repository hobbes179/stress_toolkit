"""
apps/beam_section/app.py

Streamlit page for the Beam Section Stress module.
Exports render() — called from pages/1_Beam_Section_Stress.py.
"""

from __future__ import annotations

from dataclasses import astuple

import numpy as np
import streamlit as st
import matplotlib.pyplot as plt

from ui.styles import inject_css
from ui.components import (
    section_header, info_card,
    html_table, render_formulae, estimated_flag,
    stress_card_strip, governing_banner, table_export_controls,
)
from ui.theme import THEME, ms_status

from library.materials import MATERIALS, names_grouped
from library.shapes import SHAPE_NAMES, make_section, SHAPE_REGISTRY

from apps.beam_section.calculations import (
    Loads, calc_stress_at_points, calc_margin_table, find_governing,
    neutral_axis_angle_deg, shear_center, induced_torsion,
    warping_characteristic_length, fem_mesh_size_for, governing_summary,
)
from apps.beam_section.plotting import (
    draw_section, draw_contour, draw_report_contour, draw_fem_mesh,
)


# ──────────────────────────────────────────────────────────────────────────
# Caching layer (Phase 6B)
# Streamlit reruns the whole script on every widget change. These wrappers key
# the expensive FEM work on the geometry + loads + mesh so it is computed once
# and reused: a full mesh+warping solve is ~4.5 s and the contour grid ~0.8 s,
# but toggling an overlay or switching the displayed field changes neither.
# Object args are passed underscore-prefixed so st.cache_data does NOT try to
# hash them; the plain args form the cache key.
# ──────────────────────────────────────────────────────────────────────────
def _section_key(section) -> tuple:
    """Hashable identity of a section for cache keys."""
    if getattr(section, "is_imported", False):
        import hashlib
        g = section.geometry()
        parts = [np.ascontiguousarray(np.round(g.outer, 9)).tobytes()]
        for v in g.voids:
            parts.append(np.ascontiguousarray(np.round(np.asarray(v), 9)).tobytes())
        return ("imported", hashlib.md5(b"|".join(parts)).hexdigest())
    return (section.name, tuple(section.dims))


@st.cache_data(show_spinner=False, max_entries=32)
def _cached_results(section_key, loads_key, mat_name, solver, mesh_scale,
                    sf_yield, sf_ult, _section, _loads, _material):
    """Stress table + margin table + governing rows (the sidebar-driven path)."""
    df_stress = calc_stress_at_points(_section, _loads, solver=solver,
                                      mesh_scale=mesh_scale)
    df_ms = calc_margin_table(df_stress, _material, _section,
                              sf_yield, sf_ult, _loads)
    govs = find_governing(df_stress)
    return df_stress, df_ms, govs


@st.cache_data(show_spinner=False, max_entries=32)
def _cached_stress_field(section_key, loads_key, mesh_scale, n_grid,
                         _section, _loads):
    """The interactive-contour FEM grid solve (ys, zs, sig, tau)."""
    from apps.beam_section.plotting_interactive import compute_stress_field
    return compute_stress_field(_section, _loads, mesh_scale, n_grid)


@st.cache_data(show_spinner=False, max_entries=32)
def _cached_jconv(section_key, mesh_size, _section):
    """Coarse-vs-fine J-convergence delta for the FEM Mesh tab."""
    from library.analysis.fem_solver import fem_j_convergence
    g = _section.geometry()
    return fem_j_convergence(g.outer, g.voids, mesh_size)


def _render_validation(section, mesh_scale) -> None:
    """
    Validation tab: a lightweight FEM-vs-closed-form section-property
    cross-check (A, Iy, Iz, J). Previews the full per-shape validation page
    that lands in Phase 7 (§7.4); the FEM solve here reuses the cached mesh.
    """
    from library.analysis.fem_solver import fem_available
    section_header("Validation", desc="independent cross-checks")
    if not fem_available():
        st.info("Install the FEM backend (sectionproperties) for cross-solver "
                "validation. The full per-shape validation page arrives in "
                "Phase 7.")
        return

    from library.analysis.fem_solver import fem_properties
    g = section.geometry()
    ms = fem_mesh_size_for(section, mesh_scale)
    try:
        fp = fem_properties(g.outer, g.voids, ms)   # cached mesh → cheap
    except Exception as e:                            # noqa: BLE001
        st.warning(f"FEM property solve unavailable: {e}")
        return

    t = THEME

    def _chip(pct: float) -> str:
        if pct < 2.0:
            bg, fg, lab = t.pass_bg, t.pass_fg, "✓"
        elif pct < 5.0:
            bg, fg, lab = t.warn_bg, t.warn_fg, "~"
        else:
            bg, fg, lab = t.fail_bg, t.fail_fg, "✗"
        return (f"<span style='background:{bg};color:{fg};font-weight:700;"
                f"padding:1px 6px;border-radius:3px;'>{lab} {pct:.2f}%</span>")

    rows: list[list[str]] = []
    for lbl, cls_val, fem_val, unit in [
        ("A",  section.area(),      fp["A"],  "in²"),
        ("Iy", section.Iy(),        fp["Iy"], "in⁴"),
        ("Iz", section.Iz(),        fp["Iz"], "in⁴"),
        ("J",  section.J_torsion(), fp["J"],  "in⁴"),
    ]:
        pct = abs(fem_val - cls_val) / abs(cls_val) * 100 if cls_val else 0.0
        rows.append([lbl, f"{cls_val:.4f}", f"{fem_val:.4f}", unit, _chip(pct)])

    html_table(
        ["Property", "Closed-form", "FEM", "unit", "Δ"], rows,
        col_aligns=["center", "right", "right", "center", "center"],
    )
    st.caption(
        "Section-property cross-check: the FEM (sectionproperties) solve vs the "
        "shape's analytic closed form. Small Δ confirms the mesh and the axis "
        "mapping. A larger Δ on J for open sections reflects FEM corner "
        "resolution vs the ΣLt³/3 thin-wall idealization — expected, not an "
        "error. The full validation page (classical | FEM | reference | %Δ per "
        "shape) arrives in Phase 7."
    )


# ──────────────────────────────────────────────────────────────────────────
# Formulae reference data
# Each entry: (display name, formula, description, applicable shapes)
# shapes = None        → shown for every section
# shapes = frozenset   → shown only when shape_name is in the set
# ──────────────────────────────────────────────────────────────────────────
_OPEN_SECTIONS = frozenset({
    "I-Beam / W-Shape", "T-Beam", "L-Beam / Angle",
    "C-Beam / Channel", "Z-Beam", "Plus / Cross",
})
_SOLID_CLOSED = frozenset({
    "Rectangle", "Circle", "Ellipse",
    "Rect Tube (HSS)", "Circular Tube",
})

FORMULAE = [
    ("Axial Normal Stress",
     "σ_axial = P / A",
     "Uniform. Positive = tension (+X).",
     None),

    ("Bending Normal Stress",
     "σ_bend = [(My·Iz − Mz·Iyz)·z + (Mz·Iy − My·Iyz)·y] / Δ,  Δ = Iy·Iz − Iyz²",
     "Unsymmetric-bending tensor. Accounts for the product of inertia Iyz "
     "exactly, so L and Z sections are valid with no geometric-axis "
     "constraint assumption. Reduces to (My·z)/Iy + (Mz·y)/Iz when Iyz = 0 "
     "(symmetric sections).",
     None),

    ("Total Normal Stress",
     "σ = σ_axial + σ_bend",
     "Superposition. Linear-elastic, small deformation.",
     None),

    ("Transverse Shear — open sections (midline shear flow)",
     "q(s) = −[(Vy·Iy − Vz·Iyz)·∫y·t ds + (Vz·Iz − Vy·Iyz)·∫z·t ds] / Δ,   τ_V = q/t",
     "Bruhn open-section shear flow, integrated from a free edge along the "
     "wall midline. Correct axis pairing Vy↔(Iz,∫y), Vz↔(Iy,∫z); includes "
     "the product of inertia Iyz. Reduces to −Vy·Qz/Iz − Vz·Qy/Iy when Iyz=0.",
     _OPEN_SECTIONS),

    ("Transverse Shear — solids / tubes (VQ/It)",
     "τ_V = V·Q / (I·t)",
     "First-moment (VQ/It) form. NOTE: still on the legacy axis pairing — "
     "corrected for these shapes in Phase 3 (ExactSolid / closed-cell solvers).",
     _SOLID_CLOSED),

    ("Torsion — Rect Tube (Bredt-Batho)",
     "τ_T = T / (2·Am·t_min)",
     "Am = median-line enclosed area. t_min = thinnest wall governs.",
     frozenset({"Rect Tube (HSS)"})),

    ("Torsion — Circle (exact)",
     "τ_T = 16·T / (π·d³)",
     "Exact closed-form. Max at outer surface.",
     frozenset({"Circle"})),

    ("Torsion — Circular Tube (exact)",
     "τ_T = T·r_o / J,  J = π(d_o⁴ − d_i⁴)/32",
     "Exact. Max at outer surface.",
     frozenset({"Circular Tube"})),

    ("Torsion — Ellipse (exact)",
     "τ_T = 2·T / (π·a·b²)",
     "Exact. Max at end of minor axis (b).",
     frozenset({"Ellipse"})),

    ("Torsion — Rectangle (solid)",
     "τ_T = T·t_min / J,  J = a·b³/3·(1 − 0.63·b/a),  a ≥ b",
     "Timoshenko approximation. Accurate to ~10 % for a/b ≥ 3; conservative at lower ratios.",
     frozenset({"Rectangle"})),

    ("Torsion — Open thin-walled",
     "τ_T = 0  (locked)",
     "St. Venant omits warping stresses — non-conservative for short restrained members. "
     "Torsion is excluded for all open thin-walled sections.",
     _OPEN_SECTIONS),

    ("Combined Wall Shear — open sections (§3.3)",
     "τ_wall = |τ_Vy + τ_Vz| + |τ_T|",
     "Exact algebraic combination: the two transverse-shear flows share the "
     "wall tangent (add signed); torsion adds in magnitude. Evaluated per "
     "point along the midline (design handoff §3.2–3.3).",
     _OPEN_SECTIONS),

    ("Combined Shear — solids / tubes (interim, v1.1.0)",
     "τ_total = √(τ_Vy² + τ_Vz²) + |τ_T|",
     "Conservative interim combination pending the Phase-3 solvers for these "
     "shapes. Still stricter than RSS, which is unconservative (see CHANGELOG.md).",
     _SOLID_CLOSED),

    ("Principal Stresses",
     "σ₁,₂ = σ/2 ± √[(σ/2)² + τ²]",
     "2D plane-stress transformation.",
     None),

    ("Von Mises",
     "σ_vm = √(σ₁² − σ₁·σ₂ + σ₂²)",
     "Distortion energy criterion.",
     None),

    ("Margin of Safety",
     "MS = Allow / (SF · Applied) − 1",
     "MS ≥ 0 PASS,  MS < 0 FAIL.",
     None),

    ("Combined Interaction (v1.1.0)",
     "MS = 2 / [(Ra+Rb) + √((Ra+Rb)² + 4·Rs²)] − 1",
     "Curve: (Ra+Rb) + Rs² = 1. Ra = SF_ult·|σ_axial|/Fa (Fa=Ftu tension, "
     "Fcy compression), Rb = SF_ult·|σ_bend|/Fbu, Rs = SF_ult·τ_wall/Fsu. "
     "Replaces the RSS-style 1/√(Rc²+Rb²+Rs²)−1 form, which was "
     "unconservative (see CHANGELOG.md).",
     None),

    ("Cozzone Fbu",
     "Fbu = f_eff · Ftu",
     "f_eff = shape factor, gated to 1.0 for thin-walled open sections "
     "(plastic-bending credit unsubstantiated without a crippling check). "
     "Solid/closed shapes keep their table value. See library/shapes/shapes.py.",
     None),
]


# ──────────────────────────────────────────────────────────────────────────
# RENDER
# ──────────────────────────────────────────────────────────────────────────
def render() -> None:
    inject_css()
    t = THEME

    # ── Sidebar inputs (processed first so variables are available) ──────
    with st.sidebar:
        section_header("Load Case")
        lc_id   = st.text_input("Load Case ID", value="LC-01")
        analyst = st.text_input("Analyst", value="")
        project = st.text_input("Project / Component", value="")

        section_header("Material")
        mat_name = st.selectbox("Material", names_grouped())
        material = MATERIALS[mat_name]

        c1, c2 = st.columns(2)
        sf_yield = c1.number_input("SF Yield", value=1.00,
                                   min_value=1.0, step=0.05, format="%.2f")
        sf_ult   = c2.number_input("SF Ult",   value=1.50,
                                   min_value=1.0, step=0.05, format="%.2f")

        with st.expander("Material allowables"):
            for prop, label, unit in [
                ("Fty",  "Fty",  "ksi"),
                ("Ftu",  "Ftu",  "ksi"),
                ("Fcy",  "Fcy",  "ksi"),
                ("Fsu",  "Fsu",  "ksi"),
                ("Fbru", "Fbru", "ksi"),
                ("Fbry", "Fbry", "ksi"),
            ]:
                val = getattr(material, prop)
                val_str = f"{val:.1f}" if val is not None else "—"
                info_card(
                    label, val_str, unit,
                    flag=estimated_flag(prop, material.estimated_fields),
                )
            st.caption(material.source)

        section_header("Cross-Section")
        from library.analysis.fem_solver import fem_available, FEMSolver
        geom_source = st.radio("Geometry source",
                               ["Catalog shape", "Custom import"],
                               horizontal=True)

        if geom_source == "Catalog shape":
            is_imported = False
            shape_name = st.selectbox("Section Shape", SHAPE_NAMES)
            cls      = SHAPE_REGISTRY[shape_name]
            labels   = cls.dim_labels
            defaults = cls.dim_defaults
            dims: list = []
            for slot, (lbl_pair, dflt) in enumerate(zip(labels, defaults)):
                if lbl_pair is None:
                    dims.append(None)
                else:
                    sym, desc = lbl_pair
                    v = st.number_input(
                        f"{sym} — {desc} (in)",
                        value=float(dflt),
                        min_value=1e-6, step=0.0625,
                        format="%.4f",
                        key=f"dim_{slot}_{shape_name}",
                    )
                    dims.append(v)
            section = make_section(shape_name, dims)
            dim_error = section.validate_dims()
            if dim_error:
                st.error(dim_error)
                st.stop()
        else:
            # ── Custom section import (design handoff §5) ────────────────
            is_imported = True
            shape_name = "Custom (imported)"
            from library.shapes.import_section import (
                parse_vertex_text, parse_dxf, make_imported_section,
                GeometryImportError,
            )
            if not fem_available():
                st.error("Custom import needs the FEM backend "
                         "(sectionproperties), which is not installed.")
                st.stop()

            import_mode = st.radio("Input", ["Paste vertices", "Upload DXF"],
                                   horizontal=True)
            loops = None
            try:
                if import_mode == "Paste vertices":
                    txt = st.text_area(
                        "Vertices — 'y, z' per line; blank line separates "
                        "loops (first loop = outer boundary)",
                        value="0, 0\n4, 0\n4, 2\n0, 2",
                        height=170,
                    )
                    if txt.strip():
                        loops = parse_vertex_text(txt)
                else:
                    up = st.file_uploader("DXF file (units assumed inches)",
                                          type=["dxf"])
                    if up is not None:
                        loops, skipped = parse_dxf(up.getvalue())
                        if skipped:
                            st.caption("Skipped: " + "; ".join(skipped))
                if loops is None:
                    st.info("Enter vertices or upload a DXF to build a "
                            "custom section.")
                    st.stop()
                section, _res = make_imported_section(loops)
            except GeometryImportError as e:
                st.error(f"Import error: {e}")
                st.stop()

            b, h = _res.bbox
            st.success(
                f"Imported ✓  bbox {b:.3f} × {h:.3f} in · A = {_res.area:.4f} in²"
            )
            st.caption("⚠️ Drawing units assumed INCHES — confirm the bounding "
                       "box above matches your part before trusting results.")
            for _n in _res.notes:
                st.caption(_n)

        def _box(body_html: str, accent: str, bg: str) -> None:
            st.markdown(
                f"<div style='background:{bg};border-left:3px solid {accent};"
                f"border-radius:4px;padding:10px 12px;margin-top:4px;font-size:11px;"
                f"color:{t.muted};line-height:1.6;'>{body_html}</div>",
                unsafe_allow_html=True,
            )

        # Solver override (design handoff §2.3). Imported polygons are always
        # FEM; catalog shapes offer Auto/Classical/FEM (FEM if backend present).
        if is_imported:
            solver_choice = "FEM"
            st.caption("Solver: **sectionproperties FEM** (imported section)")
        else:
            _solver_opts = (["Auto", "Classical", "FEM"] if fem_available()
                            else ["Auto", "Classical"])
            solver_choice = st.selectbox(
                "Solver", _solver_opts,
                help="Auto: classical midline for open sections, VQ/It for "
                     "solids/tubes. FEM: sectionproperties — for cross-checks "
                     "and arbitrary polygons.",
            )
        mesh_scale = 1.0
        if solver_choice == "FEM":
            _mesh_choice = st.selectbox(
                "FEM mesh refinement",
                ["Standard (2 elem / thickness)", "Fine", "Very fine"],
                help="Standard already puts ≥2 elements through every wall "
                     "thickness (no element bridges a wall). Finer = more "
                     "accurate, slower (the warping solve is the slow step).",
            )
            mesh_scale = {"Standard (2 elem / thickness)": 1.0,
                          "Fine": 0.5, "Very fine": 0.25}[_mesh_choice]

        section_header("Applied Loads")
        P  = st.number_input("P — Axial (lb)",         value=0.0,    step=100., format="%.1f")
        Vy = st.number_input("Vy — Shear Y (lb)",      value=0.0,    step=100., format="%.1f")
        Vz = st.number_input("Vz — Shear Z (lb)",      value=500.0,  step=100., format="%.1f")
        My = st.number_input("My — Bending Y (lb·in)", value=1000.0, step=100., format="%.1f")
        Mz = st.number_input("Mz — Bending Z (lb·in)", value=0.0,    step=100., format="%.1f")
        T_applied = st.number_input("T — Torsion (lb·in)", value=0.0,
                                    step=100., format="%.1f")

        # ── Shear application point → induced torsion (§3.4) ──────────────
        sc = shear_center(section)
        y_sc, z_sc = sc if sc is not None else (0.0, 0.0)
        app_mode = st.selectbox(
            "Shear applied at",
            ["Shear center", "Centroid", "Custom (y, z)"],
            help="Transverse shear applied off the shear center induces "
                 "torsion T = Vz·(y_app−y_sc) − Vy·(z_app−z_sc) (§3.4).",
        )
        if app_mode == "Shear center":
            y_app, z_app = y_sc, z_sc
        elif app_mode == "Centroid":
            y_app, z_app = 0.0, 0.0
        else:
            y_app = st.number_input("y_app (in)", value=float(y_sc),
                                    step=0.1, format="%.3f")
            z_app = st.number_input("z_app (in)", value=float(z_sc),
                                    step=0.1, format="%.3f")

        T_induced = induced_torsion(Vy, Vz, y_app, z_app, y_sc, z_sc)
        T = T_applied + T_induced

        if abs(T_induced) > 1e-9:
            _box(
                f"<b style='color:{t.accent};'>Induced torsion "
                f"{T_induced:+,.1f} lb·in.</b> Shear applied off the shear "
                f"center (SC = {y_sc:.3f}, {z_sc:.3f}). "
                f"T_total = T_applied {T_applied:+,.1f} + induced "
                f"{T_induced:+,.1f} = <b>{T:,.1f}</b> lb·in.",
                t.accent, t.amber_bg,
            )

        # ── Warping screen (§3.5) for open sections under torsion ────────
        if section.category == "Open thin-walled" and abs(T) > 1e-9:
            Cw = section.Cw()
            J = section.J_torsion()
            if Cw is None:
                _box(
                    "<b style='color:{c};'>St-Venant torsion applied "
                    "(τ = T·t/J).</b> Warping constant Cw is not tabulated "
                    "for this section, so the warping screen cannot run — "
                    "for short members with restrained ends, warping normal "
                    "stresses (not computed) may make this unconservative. "
                    "Apply engineering judgment.".format(c=t.amber),
                    t.amber, t.amber_bg,
                )
            elif Cw == 0.0:
                _box(
                    "<b>Warping-free section (Cw ≈ 0).</b> St-Venant torsion "
                    "governs; there is no warping magnification to screen for.",
                    t.muted, t.amber_bg,
                )
            else:
                lam = warping_characteristic_length(material.E, material.G, Cw, J)
                L_member = st.number_input(
                    "Member length L (in) — warping screen",
                    value=0.0, min_value=0.0, step=1.0, format="%.2f",
                    help="0 = skip. Screens L/λ: ≳10 St-Venant OK, ≲2 warping dominates.",
                )
                if lam and L_member > 0:
                    ratio = L_member / lam
                    if ratio >= 10:
                        _box(f"<b style='color:#2ecc71;'>L/λ = {ratio:.1f} ≳ 10.</b> "
                             f"St-Venant-only torsion is reasonable (λ = {lam:.2f} in).",
                             "#2ecc71", t.amber_bg)
                    elif ratio <= 2:
                        _box(f"<b style='color:#e74c3c;'>L/λ = {ratio:.1f} ≲ 2.</b> "
                             f"Warping dominates for restrained ends — St-Venant-only "
                             f"results are UNCONSERVATIVE (λ = {lam:.2f} in). Warping "
                             f"normal stresses are not computed.",
                             "#e74c3c", t.amber_bg)
                    else:
                        _box(f"<b style='color:{t.amber};'>L/λ = {ratio:.1f}.</b> "
                             f"Intermediate — include warping if the ends are "
                             f"restrained (λ = {lam:.2f} in).",
                             t.amber, t.amber_bg)
                elif lam:
                    _box(f"Enter member length L to screen warping "
                         f"(λ = {lam:.2f} in).", t.muted, t.amber_bg)

        if shape_name == "Rectangle" and T != 0:
            _a = max(section.d1, section.d2)
            _b = min(section.d1, section.d2)
            if _b > 0 and _a / _b < 3:
                st.markdown(
                    f"<div style='background:{t.amber_bg};border-left:3px solid {t.amber};"
                    f"border-radius:4px;padding:10px 12px;margin-top:4px;font-size:11px;"
                    f"color:{t.muted};line-height:1.6;'>"
                    f"<b style='color:{t.amber};'>Low aspect ratio (a/b = {_a/_b:.2f}).</b> "
                    f"The Timoshenko torsion approximation is accurate to ~10% for a/b ≥ 3. "
                    f"At this ratio the formula overestimates τ_T — conservative, "
                    f"but margins may be unnecessarily tight."
                    f"</div>",
                    unsafe_allow_html=True,
                )

    loads = Loads(P=P, Vy=Vy, Vz=Vz, My=My, Mz=Mz, T=T)

    # ── Solver identity (traceability — acceptance #7) ───────────────────
    if solver_choice == "FEM":
        solver_name = FEMSolver().name + (" (imported)" if is_imported else "")
        solver_cite = FEMSolver().method_citation
    elif section.category == "Open thin-walled" and solver_choice in ("Auto", "Classical"):
        solver_name = "Classical midline (Bruhn)"
        solver_cite = "Bruhn open-section shear flow; St-Venant open torsion J=ΣLt³/3"
    else:
        solver_name = "Exact / VQ-It closed form"
        solver_cite = "Documented closed forms (Bredt for tubes)"

    # ── Calculations (cached — see the caching layer above) ──────────────
    section_key = _section_key(section)
    loads_key   = astuple(loads)
    try:
        df_stress, df_ms, govs = _cached_results(
            section_key, loads_key, mat_name, solver_choice, mesh_scale,
            sf_yield, sf_ult, section, loads, material)
    except Exception as e:
        st.error(f"Calculation error: {e}")
        import traceback
        st.code(traceback.format_exc())
        return

    # ── Page header ──────────────────────────────────────────────────────
    st.markdown(
        "<div class='tk-page-header'>"
        f"<h1 class='tk-page-title'>Beam Section Stress "
        f"<span class='sub'>— {shape_name.lower()}</span></h1>"
        "<div class='tk-page-meta'>"
        f"<span><b>{lc_id or 'LC-??'}</b></span>"
        "<span>Linear-elastic</span>"
        "<span>IPS units</span>"
        "<span>MMPDS-01 allowables</span>"
        "<span>X = beam axis</span>"
        "<span>Y = horiz. right</span>"
        "<span>Z = vert. up</span>"
        + (f"<span style='color:{t.amber};font-weight:700;'>IMPORTED — FEM</span>"
           if is_imported else "")
        + f"<span title='{solver_cite}'>Solver: <b>{solver_name}</b></span>"
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.caption(f"Method: {solver_cite}")

    # ── Governing banner (persistent, above the tabs — §6.3) ─────────────
    _min_ms, _gov_check, _gov_loc = governing_summary(df_stress, df_ms)
    governing_banner(_min_ms, _gov_check, _gov_loc, solver_name)

    if solver_choice == "FEM":
        st.warning(
            "**FEM captures stress concentrations at sharp re-entrant corners** "
            "(web–flange junctions, void corners) that the classical "
            "nominal-stress method omits — this is why FEM can read higher than "
            "Classical near junctions. At a perfectly sharp inside corner the "
            "torsion stress is theoretically **singular**, so the FEM peak there "
            "**grows as the mesh refines** (try the mesh selector) and is *not* a "
            "converged design value — model a fillet radius for real corner "
            "stresses. Away from corners the two solvers agree (see the "
            "Validation tab).",
            icon="⚠️",
        )

    fbu = section.effective_f_cozzone * (material.Ftu or 0.0)
    cozzone_gated = section.effective_f_cozzone != section.f_cozzone

    tab_geo, tab_load, tab_res, tab_marg, tab_form, tab_val = st.tabs(
        ["Geometry", "Loads", "Results", "Margins", "Formulas", "Validation"])

    # ═══════════════════════════ GEOMETRY ═══════════════════════════════
    with tab_geo:
        section_header("Section Geometry & Key Points", number="01",
                       desc="section diagram, key points, and properties")
        col_left, col_right = st.columns([2, 1], gap="large")

        with col_left:
            _glabels = ["Section Diagram"] + (
                ["FEM Mesh"] if solver_choice == "FEM" else [])
            _gtabs = st.tabs(_glabels)
            with _gtabs[0]:
                _show_dims = st.checkbox("Dimension leaders", value=True,
                                         key="geo_dims")
                kps = section.key_points(loads.My, loads.Mz)
                fig_sec = draw_section(section, kps, show_dims=_show_dims)
                st.pyplot(fig_sec, use_container_width=True)
                plt.close(fig_sec)
                rows = [(kp.id, kp.description, f"{kp.y:.4f}", f"{kp.z:.4f}")
                        for kp in kps]
                html_table(
                    ["KP", "Description", "y (in)", "z (in)"], rows,
                    col_aligns=["center", "left", "center", "center"],
                )
            if solver_choice == "FEM":
                with _gtabs[1]:
                    ms = fem_mesh_size_for(section, mesh_scale)
                    with st.spinner("Meshing…"):
                        fig_m = draw_fem_mesh(section, ms)
                    st.pyplot(fig_m, use_container_width=True)
                    plt.close(fig_m)
                    jc, jf, pct = _cached_jconv(section_key, ms, section)
                    flag = "✓" if pct < 2.0 else "⚠"
                    st.caption(
                        f"{flag} Coarse-vs-fine J sanity: J = {jc:.4f} in⁴ at "
                        f"this mesh vs {jf:.4f} in⁴ at 4× finer → Δ = {pct:.1f}% "
                        f"(mesh converged if small; refine if large)."
                    )

        with col_right:
            section_header("Section Properties")
            iyz_val = section.Iyz()
            for label, val, unit in [
                ("A",   section.area(),      "in²"),
                ("Iy",  section.Iy(),        "in⁴"),
                ("Iz",  section.Iz(),        "in⁴"),
                ("Iyz", iyz_val,             "in⁴"),
                ("J",   section.J_torsion(), "in⁴"),
                ("Sy",  section.Sy(),        "in³"),
                ("Sz",  section.Sz(),        "in³"),
                ("f",   section.effective_f_cozzone, "shape factor"),
            ]:
                info_card(label, f"{val:.2f}", unit)
            if abs(iyz_val) > 1e-4:
                na_angle = neutral_axis_angle_deg(section, loads)
                if na_angle is not None:
                    info_card("NA angle", f"{na_angle:.1f}", "deg",
                              sub="neutral axis vs +Y (unsymmetric bending)")
            if cozzone_gated:
                st.caption(
                    f"f = 1.0 (plastic bending gated pending crippling check — "
                    f"table value {section.f_cozzone:.2f} not used)"
                )
            sc = shear_center(section)
            if sc is not None:
                info_card("SC", f"({sc[0]:.3f}, {sc[1]:.3f})", "in",
                          sub="shear center (y, z) from centroid")
                if abs(sc[0]) > 1e-3 or abs(sc[1]) > 1e-3:
                    st.caption(
                        "Transverse shear applied through the centroid induces "
                        "torsion about the shear center — see §3.4 (Phase 3)."
                    )

    # ═══════════════════════════ LOADS ═════════════════════════════════
    with tab_load:
        section_header("Applied Loads & Material", number="02",
                       desc="load case (entered in the sidebar) and allowables")
        col_a, col_b = st.columns(2, gap="large")
        with col_a:
            section_header("Applied Loads")
            for label, val, unit in [
                ("P", P, "lb"), ("Vy", Vy, "lb"), ("Vz", Vz, "lb"),
                ("My", My, "lb·in"), ("Mz", Mz, "lb·in"),
                ("T (total)", T, "lb·in"),
            ]:
                value_color = t.accent if val != 0 else t.muted
                info_card(label, f"{val:,.1f}", unit, value_color=value_color)
            if abs(T_induced) > 1e-9:
                info_card("T induced", f"{T_induced:,.1f}", "lb·in",
                          value_color=t.accent,
                          sub="from shear off the shear center (§3.4)")
        with col_b:
            section_header("Material")
            for prop, label, unit in [
                ("Fty", "Fty", "ksi"), ("Ftu", "Ftu", "ksi"),
                ("Fcy", "Fcy", "ksi"), ("Fsu", "Fsu", "ksi"),
            ]:
                val = getattr(material, prop)
                val_str = f"{val:.1f}" if val is not None else "—"
                info_card(
                    label, val_str, unit,
                    flag=estimated_flag(prop, material.estimated_fields),
                )
            if material.Ftu is not None:
                info_card("Fbu", f"{fbu:.1f}", "ksi",
                          sub=f"= f·Ftu  (f = {section.effective_f_cozzone:.2f})",
                          flag="GATED" if cozzone_gated else None)
            st.caption(material.source)

    # ═══════════════════════════ RESULTS ═══════════════════════════════
    with tab_res:
        section_header("Governing Stress Summary", number="03",
                       desc="extreme-fiber results across the section")
        # Order tracks find_governing() (σ1, σ2, σ_vm, τ_total, σ_bend); each
        # paired with the allowable its §3.6 check uses (σ1↔Ftu, σ2↔Fcy,
        # σ_vm↔Fty, τ↔Fsu; σ_bend↔Fbu for display continuity only).
        stress_allowables = [
            (material.Ftu or 0.0, "Ftu", sf_ult),
            (material.Fcy or 0.0, "Fcy", sf_yield),
            (material.Fty or 0.0, "Fty", sf_yield),
            (material.Fsu or 0.0, "Fsu", sf_ult),
            (fbu,                 "Fbu", sf_ult),
        ]
        combined_ms_rows = df_ms[df_ms["Check"].str.contains(
            "Combined interaction", na=False)]
        combined_ms = (float(combined_ms_rows.iloc[0]["MS"])
                       if not combined_ms_rows.empty else None)
        stress_card_strip(govs, stress_allowables, combined_ms=combined_ms)

        section_header("Stress Contour",
                       desc="interactive FEM field — hover to probe")
        if fem_available():
            # Interactive Plotly view with a real 2-D FEM stress field (correct
            # shear) and a hover probe (design handoff §6.2). Wrapped in a
            # fragment so toggling an overlay or switching the displayed field
            # reruns ONLY this block (hitting the cached field) — the rest of
            # the page and the FEM solve don't re-fire.
            #
            # NOTE: this contour is ALWAYS an FEM field, independent of the
            # solver dropdown. The classical/exact solvers produce values only
            # at key points and along the wall midline — not a continuous 2-D
            # field — so FEM is used purely as the field visualizer. The table
            # and margins still use the selected solver.
            if solver_choice != "FEM":
                st.info(
                    f"**The contour below is an FEM field** "
                    f"(sectionproperties), shown only to visualize the 2-D "
                    f"stress distribution — the classical solver gives values "
                    f"at discrete key points / along the midline, not a full "
                    f"field. Your **results table and margins use "
                    f"{solver_name}** (no finite elements). Away from sharp "
                    f"re-entrant corners the FEM field and the classical values "
                    f"agree; at a sharp inside corner the FEM field can read "
                    f"higher (mesh-dependent — model a fillet for real corner "
                    f"stress).",
                    icon="ℹ️",
                )
            from apps.beam_section.plotting_interactive import (
                interactive_stress_contour, FIELD_LABELS,
            )

            @st.fragment
            def _contour_fragment():
                field_label = st.radio(
                    "Stress field", list(FIELD_LABELS.keys()),
                    horizontal=True, key="contour_choice",
                )
                _ov = set()
                _oc = st.columns(4)
                if _oc[0].checkbox("Centroid", value=True, key="ov_centroid"):
                    _ov.add("centroid")
                if _oc[1].checkbox("Shear center", value=True, key="ov_sc"):
                    _ov.add("shear_center")
                if _oc[2].checkbox("Neutral axis", value=True, key="ov_na"):
                    _ov.add("neutral_axis")
                if _oc[3].checkbox("Shear point", value=True, key="ov_shearpt"):
                    _ov.add("shear_point")
                _oc2 = st.columns(4)
                if _oc2[0].checkbox("Principal axes", value=False, key="ov_pa"):
                    _ov.add("principal_axes")
                if _oc2[1].checkbox("Load arrows", value=False, key="ov_load"):
                    _ov.add("load_arrows")
                _show_mesh = _oc2[2].checkbox("Mesh lines", value=False,
                                              key="ov_mesh")
                with st.spinner("Computing FEM stress field…"):
                    field = _cached_stress_field(
                        section_key, loads_key, mesh_scale, 160,
                        section, loads)
                fig_i = interactive_stress_contour(
                    section, loads, material, sf_yield, sf_ult,
                    field_label, mesh_scale=mesh_scale,
                    shear_app=(y_app, z_app), overlays=_ov,
                    show_mesh=_show_mesh, field=field)
                st.plotly_chart(fig_i, use_container_width=True)
                st.caption(
                    "FEM elasticity field — σ, τ, σ₁/σ₂, σ_vm and min-MS are "
                    "correct at every interior point (hover to probe). Peaks "
                    "at sharp re-entrant corners are mesh-dependent (see "
                    "warning)."
                )

            _contour_fragment()

            with st.expander("Report figure (matplotlib, print-quality)"):
                rlabel = st.radio(
                    "Field", ["σ_total", "σ_vm", "σ1", "σ2", "τ_total"],
                    horizontal=True, key="report_field")
                # Render from the SAME cached FEM field as the interactive view
                # (cache hit → instant) so shear varies correctly rather than
                # showing the legacy uniform VQ/It value.
                ys_r, zs_r, sig_r, tau_r = _cached_stress_field(
                    section_key, loads_key, mesh_scale, 160, section, loads)
                fig_con = draw_report_contour(
                    section, ys_r, zs_r, sig_r, tau_r, rlabel)
                st.pyplot(fig_con, use_container_width=True)
                plt.close(fig_con)
                st.caption("Print-quality figure from the FEM elasticity field "
                           "— matches the interactive contour above.")
        else:
            # FEM backend absent → matplotlib fallback (shear approximate).
            _FIELD_KEYS = {"Max Principal (σ₁)": "σ1", "Min Principal (σ₂)": "σ2",
                           "Axial + Bending (σ_total)": "σ_total",
                           "Shear (τ_total)": "τ_total", "Equivalent (σ_vm)": "σ_vm"}
            field_label = st.radio("Stress field", list(_FIELD_KEYS.keys()),
                                   horizontal=True, key="contour_choice")
            fig_con = draw_contour(section, loads, _FIELD_KEYS[field_label])
            st.pyplot(fig_con, use_container_width=True)
            plt.close(fig_con)
            st.caption("Install the FEM backend (sectionproperties) for the "
                       "interactive contour with a correct shear field.")

        section_header("Stress Results at Key Points",
                       desc="all stresses in ksi — sortable; ⬇ to export")

        num_cols = ["σ_axial", "σ_bend", "σ_total",
                    "τ_Vy", "τ_Vz", "τ_T", "τ_total",
                    "σ1", "σ2", "σ_vm"]

        # Per-column governing value (max |val|); its cell(s) get an amber
        # highlight in the Styler. Ties (symmetry) highlight together.
        gov_max = {c: float(df_stress[c].abs().max()) for c in num_cols}

        disp = df_stress[["KP", "Description"] + num_cols].copy()

        def _hl_gov(col):
            m = gov_max[col.name]
            if m < 1e-9:
                return [""] * len(col)
            css = f"background-color:{t.amber_bg};color:{t.amber};font-weight:700;"
            return [css if abs(v) >= m - 1e-9 else "" for v in col]

        sty = (disp.style
               .format({c: "{:.2f}" for c in num_cols})
               .apply(_hl_gov, subset=num_cols, axis=0))
        st.dataframe(
            sty, use_container_width=True, hide_index=True,
            column_config={
                "KP": st.column_config.TextColumn(width="small"),
                "Description": st.column_config.TextColumn(width="medium"),
            },
        )
        st.caption(
            "Amber = governing (max-|value|) cell per column. Click a column "
            "header to sort."
        )

        exp = disp.copy()
        for c in num_cols:
            exp[c] = exp[c].map(lambda v: f"{v:.2f}")
        table_export_controls(exp, "stress_results.csv", "stress")

    # ═══════════════════════════ MARGINS ═══════════════════════════════
    with tab_marg:
        section_header("Margin of Safety", number="04",
                       desc="MS = Allow / (SF × Applied) − 1")

        all_ms  = [float(v) for v in df_ms["MS"]
                   if isinstance(v, (int, float)) and v < 999]
        min_ms  = min(all_ms) if all_ms else 999.0

        if min_ms >= 0:
            st.success(f"✓  ALL MARGINS POSITIVE  |  Minimum MS = {min_ms:.3f}")
        else:
            st.error(f"✗  NEGATIVE MARGIN DETECTED  |  Minimum MS = {min_ms:.3f}")

        disp_ms = df_ms.rename(columns={
            "Allow": "Allowable (ksi)", "Applied": "Applied (ksi)"}).copy()

        def _fmt_num(v):
            return f"{v:.1f}" if isinstance(v, (int, float)) else str(v)

        def _fmt_applied(v):
            return f"{float(v):.2f}" if isinstance(v, (int, float)) else str(v)

        def _fmt_ms(v):
            if isinstance(v, (int, float)):
                return "+HIGH" if v > 10 else f"{v:+.3f}"
            return str(v)

        def _color_ms(col):
            out = []
            for v in col:
                if isinstance(v, (int, float)) and v < 999:
                    bg, fg, _ = ms_status(v)
                    out.append(f"background-color:{bg};color:{fg};font-weight:700;")
                else:
                    out.append("")
            return out

        sty_ms = (disp_ms.style
                  .format({"Allowable (ksi)": _fmt_num, "SF": "{:.2f}",
                           "Applied (ksi)": _fmt_applied, "MS": _fmt_ms})
                  .apply(_color_ms, subset=["MS"]))
        st.dataframe(sty_ms, use_container_width=True, hide_index=True)
        st.caption(
            "MS cell color: red < 0 (fail), amber < 0.25 (marginal), green ≥ "
            "0.25 (pass) — thresholds from ui.theme. +HIGH = MS > 10."
        )

        exp_ms = disp_ms.copy()
        exp_ms["Allowable (ksi)"] = exp_ms["Allowable (ksi)"].map(_fmt_num)
        exp_ms["Applied (ksi)"]   = exp_ms["Applied (ksi)"].map(_fmt_applied)
        exp_ms["SF"]              = exp_ms["SF"].map(lambda v: f"{v:.2f}")
        exp_ms["MS"]              = exp_ms["MS"].map(_fmt_ms)
        table_export_controls(exp_ms, "margins.csv", "margins")

    # ═══════════════════════════ FORMULAS ══════════════════════════════
    with tab_form:
        section_header("First-Principles Formulae", number="05",
                       desc=f"equations applicable to {shape_name}")
        st.markdown(
            f"<p style='font-size:11px;color:{t.muted};margin-bottom:10px;'>"
            "Ref: MMPDS-01 §1.3, Roark's Formulas for Stress &amp; Strain, "
            "Timoshenko &amp; Goodier Theory of Elasticity. "
            "Bending uses the full unsymmetric-bending tensor — valid for "
            "unsymmetric sections (L, Z) without any constraint assumption."
            "</p>",
            unsafe_allow_html=True,
        )
        applicable_formulae = [
            (name, expr, desc)
            for name, expr, desc, shapes in FORMULAE
            if shapes is None or shape_name in shapes
        ]
        render_formulae(applicable_formulae)

    # ═══════════════════════════ VALIDATION ════════════════════════════
    with tab_val:
        _render_validation(section, mesh_scale)

    # ── Footer ────────────────────────────────────────────────────────────
    st.divider()
    st.markdown(
        f"<p style='font-family:\"IBM Plex Mono\",monospace;"
        f"font-size:11px;color:{t.muted};text-align:center;'>"
        f"{lc_id or '—'} · {project or '—'} · Analyst: {analyst or '—'} · "
        f"{shape_name} · {mat_name} · "
        f"SF_y={sf_yield:.2f}  SF_u={sf_ult:.2f} · "
        f"Linear-elastic only · Not for buckling, fatigue, or non-linear analysis"
        f"</p>",
        unsafe_allow_html=True,
    )
