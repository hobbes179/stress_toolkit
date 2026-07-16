"""
Home.py
TEST
Top-level entry point for the Stress Toolkit on Streamlit Cloud.

Landing page — module cards in the main content area link to each analysis
module. Streamlit also auto-discovers pages/ files and adds them to the
sidebar navigation, so both paths reach the same destinations.

Module entry points live in pages/ and are thin wrappers that call into
apps/<module>/app.py::render().
"""

import streamlit as st

from ui.styles import inject_css
from ui.components import section_header
from ui.theme import THEME

st.set_page_config(
    page_title="Stress Toolkit",
    page_icon="🛠️",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_css()
t = THEME


# Each entry: (icon, title, description, page_path)
MODULES = [
    (
        "📐",
        "Beam Section Stress",
        "Calculate normal, shear, principal, and von Mises stresses on a beam "
        "cross-section under combined axial, shear, bending, and torsion loads. "
        "Supports 11 standard shapes — rectangular, circular, hollow tubes, "
        "I / T / L / C / Z rolled profiles, and more. Outputs margins of safety "
        "against MMPDS-01 allowables and a smooth filled stress contour.",
        "pages/1_Beam_Section_Stress.py",
    ),
    (
        "📋",
        "Material Library",
        "Browse all 24 metallic alloys in the toolkit across four categories: "
        "aluminium, steel, titanium, and stainless. Tabulates room-temperature "
        "minimum allowables (Fty, Ftu, Fcy, Fsu, Fbru, Fbry) and physical "
        "properties (E, G, ν, α, T_max, ρ) sourced from MMPDS-01 with "
        "citations. Estimated values are flagged.",
        "pages/2_Material_Library.py",
    ),
]


# ── Header ────────────────────────────────────────────────────────────────
st.markdown(
    f"<div style='margin-bottom:4px;'>"
    f"<h1 style='font-size:30px;font-weight:800;color:{t.accent2};margin:0;'>"
    f"🛠️  Stress Toolkit</h1>"
    f"<p style='font-size:13px;color:{t.muted};margin:8px 0 0;line-height:1.6;'>"
    f"A collection of structural-analysis tools for metallic airframe design. "
    f"Built on MMPDS-01 allowables, classical elasticity, and clean Python."
    f"</p></div>",
    unsafe_allow_html=True,
)
st.divider()


# ── Module cards ──────────────────────────────────────────────────────────
section_header("Available Modules")

cols = st.columns(len(MODULES), gap="large")

for col, (icon, title, desc, page_path) in zip(cols, MODULES):
    with col:
        # Description block — rounded top, open bottom border so the
        # page_link button below reads as part of the same card unit.
        st.markdown(
            f"<div style='"
            f"background:{t.bg3};"
            f"border:1px solid {t.border};"
            f"border-bottom:none;"
            f"border-radius:8px 8px 0 0;"
            f"padding:24px 24px 20px;'>"
            f"<div style='font-size:36px;line-height:1;margin-bottom:14px;'>{icon}</div>"
            f"<div style='font-size:16px;font-weight:700;color:{t.accent2};"
            f"margin-bottom:10px;'>{title}</div>"
            f"<div style='font-size:12px;color:{t.muted};line-height:1.7;'>{desc}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        # Navigation button — sits flush against the card above.
        # use_container_width spans the full column width.
        try:
            st.page_link(
                page_path,
                label=f"Open  {title}",
                use_container_width=True,
            )
        except Exception:
            st.caption(f"Select **{title}** from the sidebar to open this module.")


# ── Footer ────────────────────────────────────────────────────────────────
from version import version_string
st.divider()
st.markdown(
    f"<p style='font-size:11px;color:{t.muted};text-align:center;'>"
    f"Stress Toolkit {version_string()} · Built with Python and Streamlit"
    f"</p>",
    unsafe_allow_html=True,
)
