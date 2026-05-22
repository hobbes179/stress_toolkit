"""
apps/beam_section/app.py

Streamlit page for the Beam Section Stress module.
Exports render() — called from pages/1_Beam_Section_Stress.py.
"""

from __future__ import annotations

import streamlit as st
import matplotlib.pyplot as plt

from ui.styles import inject_css
from ui.components import (
    section_header, info_card,
    html_table, ms_chip, render_formulae, estimated_flag,
    stress_card_strip,
)
from ui.theme import THEME

from library.materials import MATERIALS, names_grouped
from library.shapes import SHAPE_NAMES, make_section, SHAPE_REGISTRY

from apps.beam_section.calculations import (
    Loads, calc_stress_at_points, calc_margin_table, find_governing,
)
from apps.beam_section.plotting import draw_section, draw_contour


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

FORMULAE = [
    ("Axial Normal Stress",
     "σ_axial = P / A",
     "Uniform. Positive = tension (+X).",
     None),

    ("Bending Normal Stress",
     "σ_bend = (My·z)/Iy + (Mz·y)/Iz",
     "Flexure formula. Bending axes through centroid.",
     None),

    ("Total Normal Stress",
     "σ = σ_axial + σ_bend",
     "Superposition. Linear-elastic, small deformation.",
     None),

    ("Shear — Vy",
     "τ_Vy = Vy·Q_y / (Iy·t_w)",
     "VQ/It. Q = 1st moment of area above neutral axis.",
     None),

    ("Shear — Vz",
     "τ_Vz = Vz·Q_z / (Iz·t_w)",
     "Analogous for horizontal shear about Z axis.",
     None),

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

    ("Total Shear",
     "τ_total = √(τ_Vy² + τ_Vz² + τ_T²)",
     "RSS combination at each key point.",
     None),

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

    ("MMPDS Interaction",
     "MS = 1/√(Rc² + Rb² + Rs²) − 1",
     "Rc = σ_ax/Ftu,  Rb = σ_bend/Fbu,  Rs = τ/Fsu.",
     None),

    ("Cozzone Fbu",
     "Fbu = f · Ftu",
     "f = shape factor (simplified constant per section class). "
     "See library/shapes/shapes.py for table.",
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

        section_header("Applied Loads")
        P  = st.number_input("P — Axial (lb)",         value=0.0,    step=100., format="%.1f")
        Vy = st.number_input("Vy — Shear Y (lb)",      value=0.0,    step=100., format="%.1f")
        Vz = st.number_input("Vz — Shear Z (lb)",      value=500.0,  step=100., format="%.1f")
        My = st.number_input("My — Bending Y (lb·in)", value=1000.0, step=100., format="%.1f")
        Mz = st.number_input("Mz — Bending Z (lb·in)", value=0.0,    step=100., format="%.1f")
        T_locked = (section.category == "Open thin-walled")
        T = st.number_input(
            "T — Torsion (lb·in)",
            value=0.0,
            step=100.,
            format="%.1f",
            disabled=T_locked,
        )
        if T_locked:
            T = 0.0
            st.markdown(
                f"<div style='background:{t.amber_bg};border-left:3px solid {t.amber};"
                f"border-radius:4px;padding:10px 12px;margin-top:4px;font-size:11px;"
                f"color:{t.muted};line-height:1.6;'>"
                f"<b style='color:{t.amber};'>Torsion locked to zero.</b> "
                f"St. Venant torsion (τ = T·t/J) omits warping stresses, which can "
                f"dominate for short members with restrained ends — a potentially "
                f"non-conservative error. For torsion-critical members, use a closed "
                f"section (Rect Tube or Circular Tube)."
                f"</div>",
                unsafe_allow_html=True,
            )

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

    # ── Calculations ─────────────────────────────────────────────────────
    try:
        df_stress = calc_stress_at_points(section, loads)
        df_ms     = calc_margin_table(df_stress, material, section,
                                      sf_yield, sf_ult, loads)
        govs      = find_governing(df_stress)
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
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    # ── 01 — Governing Stress Summary ────────────────────────────────────
    section_header("Governing Stress Summary", number="01",
                   desc="extreme-fiber results across the section")

    fbu = section.f_cozzone * (material.Ftu or 0.0)
    stress_allowables = [
        (material.Fty or 0.0, "Fty", sf_yield),
        (material.Fcy or 0.0, "Fcy", sf_yield),
        (material.Ftu or 0.0, "Ftu", sf_ult),
        (material.Fsu or 0.0, "Fsu", sf_ult),
        (fbu,                 "Fbu", sf_ult),
    ]
    combined_ms_rows = df_ms[df_ms["Check"].str.contains("MMPDS", na=False)]
    combined_ms = float(combined_ms_rows.iloc[0]["MS"]) if not combined_ms_rows.empty else None
    stress_card_strip(govs, stress_allowables, combined_ms=combined_ms)

    # ── 02 — Section Geometry & Key Points ───────────────────────────────
    section_header("Section Geometry & Key Points", number="02",
                   desc="KP positions and per-fiber stress state")

    col_left, col_right = st.columns([2, 1], gap="large")

    with col_left:
        tab_sec, tab_con = st.tabs(["Section Diagram", "Stress Contour"])

        with tab_sec:
            kps = section.key_points(loads.My, loads.Mz)
            fig_sec = draw_section(section, kps)
            st.pyplot(fig_sec, use_container_width=True)
            plt.close(fig_sec)

            rows = [(kp.id, kp.description, f"{kp.y:.4f}", f"{kp.z:.4f}")
                    for kp in kps]
            html_table(
                ["KP", "Description", "y (in)", "z (in)"],
                rows,
                col_aligns=["center", "left", "center", "center"],
            )

        with tab_con:
            _FIELD_LABELS = [
                "Max Principal (σ₁)",
                "Min Principal (σ₂)",
                "Axial + Bending (σ_total)",
                "Shear (τ_total)",
                "Equivalent (σ_vm)",
            ]
            _FIELD_KEYS = {
                "Max Principal (σ₁)":         "σ1",
                "Min Principal (σ₂)":         "σ2",
                "Axial + Bending (σ_total)":  "σ_total",
                "Shear (τ_total)":            "τ_total",
                "Equivalent (σ_vm)":          "σ_vm",
            }
            field_label = st.radio(
                "Stress field",
                _FIELD_LABELS,
                horizontal=True,
                key="contour_choice",
            )
            field_choice = _FIELD_KEYS[field_label]
            with st.spinner("Computing stress field…"):
                fig_con = draw_contour(section, loads, field_choice)
            st.pyplot(fig_con, use_container_width=True)
            plt.close(fig_con)
            st.caption(
                "Smooth contour from Delaunay triangulation. "
                "Inner voids excluded automatically."
            )

    with col_right:
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
                      sub=f"= f·Ftu  (f = {section.f_cozzone:.2f})")
        st.caption(material.source)

        section_header("Applied Loads")
        for label, val, unit in [
            ("P", P, "lb"), ("Vy", Vy, "lb"), ("Vz", Vz, "lb"),
            ("My", My, "lb·in"), ("Mz", Mz, "lb·in"), ("T", T, "lb·in"),
        ]:
            value_color = t.accent if val != 0 else t.muted
            info_card(label, f"{val:,.1f}", unit, value_color=value_color)

        section_header("Section Properties")
        for label, val, unit in [
            ("A",  section.area(),      "in²"),
            ("Iy", section.Iy(),        "in⁴"),
            ("Iz", section.Iz(),        "in⁴"),
            ("J",  section.J_torsion(), "in⁴"),
            ("Sy", section.Sy(),        "in³"),
            ("Sz", section.Sz(),        "in³"),
            ("f",  section.f_cozzone,   "shape factor"),
        ]:
            info_card(label, f"{val:.4f}", unit)

    # ── 03 — Stress Results ───────────────────────────────────────────────
    section_header("Stress Results at Key Points", number="03",
                   desc="all stresses in ksi")

    num_cols = ["σ_axial", "σ_bend", "σ_total",
                "τ_Vy", "τ_Vz", "τ_T", "τ_total",
                "σ1", "σ2", "σ_vm"]

    # Find ALL rows that share the maximum absolute value for each column.
    # Ties due to symmetry are highlighted together rather than just the first.
    gov_max  = {c: df_stress[c].abs().max() for c in num_cols}
    gov_mask = {c: df_stress[c].abs() >= gov_max[c] - 1e-9 for c in num_cols}
    def _kp_label(c: str) -> str:
        # gov_max uses abs(), so this correctly catches zero for all columns
        # including σ2 which can be negative.
        if gov_max[c] < 1e-9:
            return "---"
        if gov_mask[c].all():
            return "ALL"
        return ", ".join(df_stress.loc[gov_mask[c], "KP"].tolist())

    gov_kps  = {c: _kp_label(c) for c in num_cols}
    gov_vals = {c: df_stress.loc[gov_mask[c], c].iloc[0] for c in num_cols}

    hdrs = ["KP", "Description"] + num_cols
    rows_html: list[list[str]] = []
    for i, row in df_stress.iterrows():
        cells = [row["KP"], row["Description"]]
        for c in num_cols:
            v = row[c]
            if gov_mask[c].loc[i]:
                cell = (
                    f"<span style='background:{t.amber_bg};"
                    f"color:{t.amber};font-weight:700;"
                    f"padding:1px 4px;border-radius:3px;'>"
                    f"{v:.2f}</span>"
                )
            else:
                cell = f"{v:.2f}"
            cells.append(cell)
        rows_html.append(cells)

    # Bottom row: all tied governing KPs + their value
    gov_row: list[str] = ["↑ max |val|", "—"]
    for c in num_cols:
        v = gov_vals[c]
        gov_row.append(
            f"<span style='color:{t.accent};font-size:10px;font-weight:700;'>"
            f"{gov_kps[c]}<br>{v:.2f}</span>"
        )
    rows_html.append(gov_row)

    html_table(
        hdrs, rows_html,
        col_aligns=["center", "left"] + ["center"] * len(num_cols),
    )
    st.caption(
        "Amber = governing (max-absolute) value per column. "
        "Bottom row: governing KP and value."
    )

    # ── 04 — Margin of Safety ─────────────────────────────────────────────
    section_header("Margin of Safety", number="04",
                   desc="MS = Allow / (SF × Applied) − 1")

    all_ms  = [float(v) for v in df_ms["MS"]
               if isinstance(v, (int, float)) and v < 999]
    min_ms  = min(all_ms) if all_ms else 999.0

    if min_ms >= 0:
        st.success(f"✓  ALL MARGINS POSITIVE  |  Minimum MS = {min_ms:.3f}")
    else:
        st.error(f"✗  NEGATIVE MARGIN DETECTED  |  Minimum MS = {min_ms:.3f}")

    ms_rows: list[list[str]] = []
    for _, row in df_ms.iterrows():
        allow = row["Allow"]
        allow_str = f"{allow:.1f}" if isinstance(allow, (int, float)) else str(allow)

        applied = row["Applied"]
        applied_str = (f"{float(applied):.2f}"
                       if isinstance(applied, (int, float)) else str(applied))

        ms_rows.append([
            row["Check"],
            allow_str,
            f"{row['SF']:.2f}",
            applied_str,
            ms_chip(row["MS"]),
        ])

    html_table(
        ["Check", "Allowable (ksi)", "SF", "Applied (ksi)", "MS"],
        ms_rows,
        col_aligns=["left", "center", "center", "center", "center"],
    )
    st.caption(
        "+HIGH indicates MS > 10 — substantial reserve; exact value not shown."
    )

    # ── 05 — Formulae Reference ───────────────────────────────────────────
    with st.expander("First-Principles Formulae Reference", expanded=False):
        st.markdown(
            f"<p style='font-size:11px;color:{t.muted};margin-bottom:10px;'>"
            f"Showing formulae applicable to <b>{shape_name}</b>. "
            "Ref: MMPDS-01 §1.3, Roark's Formulas for Stress &amp; Strain, "
            "Timoshenko &amp; Goodier Theory of Elasticity. "
            "Bending evaluated on geometric axes (valid when section is "
            "constrained by adjacent structure)."
            "</p>",
            unsafe_allow_html=True,
        )
        applicable_formulae = [
            (name, expr, desc)
            for name, expr, desc, shapes in FORMULAE
            if shapes is None or shape_name in shapes
        ]
        render_formulae(applicable_formulae)

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
