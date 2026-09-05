"""
Home.py

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
        "Combined-loading stress analysis of a cross-section — normal, shear, "
        "principal, and von Mises — with margins of safety to MMPDS-01. "
        "11 catalog shapes plus custom polygon / DXF import, an interactive FEM "
        "stress contour, and a built-in validation page.",
        "pages/1_Beam_Section_Stress.py",
    ),
    (
        "📋",
        "Material Library",
        "24 metallic alloys — aluminium, steel, titanium, stainless — with "
        "room-temperature MMPDS-01 allowables (Fty, Ftu, Fcy, Fsu, Fbru, Fbry) "
        "and physical properties (E, G, ν, α, T_max, ρ). Estimated values "
        "flagged with citations.",
        "pages/2_Material_Library.py",
    ),
    (
        "🔩",
        "Tie-Rod Layout",
        "Rigid bodies on two-force members with spherical bearings both ends. "
        "Build the assembly, then search for a rod layout that restrains it "
        "and survives losing any one rod. Multi-body load extraction from the "
        "screw matrix, margins under a closed-form orientation envelope, "
        "animated mechanism modes, and a rod-count/slenderness trade curve.",
        "pages/3_Tie_Rod_Layout.py",
    ),
    (
        "🔧",
        "Bolt Bending",
        "Shear and moment diagrams along a bolt in a multi-layer joint. "
        "Uniform bearing per layer, spacers that add arm with no support, "
        "and the head/nut couple that closes the moment. Margins on bending, "
        "shear, and a combined interaction scanned station by station rather "
        "than pairing the two maxima.",
        "pages/4_Bolt_Bending.py",
    ),
    (
        "📉",
        "Beam Diagrams",
        "Shear, moment and deflection along a line beam. Any arrangement of "
        "end conditions and interior supports — rigid, elastic or settling — "
        "plus internal hinges and point, moment and trapezoidal loads. "
        "Statically indeterminate beams are solved by direct stiffness; the "
        "diagrams come back as exact polynomials, so the peak moment and its "
        "station are found by rooting the shear rather than by sampling.",
        "pages/5_Beam_Diagrams.py",
    ),
]

# Cards per row. Four modules in one row squeezes every description into a
# narrow column; two rows of two keeps them readable. Rows wrap automatically
# as modules are added.
CARDS_PER_ROW = 2


# ── Header ────────────────────────────────────────────────────────────────
st.markdown(
    f"<div style='margin-bottom:6px;'>"
    f"<h1 style='font-size:32px;font-weight:800;color:{t.accent2};margin:0;"
    f"letter-spacing:-0.01em;'>🛠️  Stress Toolkit</h1>"
    f"<p style='font-size:14px;color:{t.text2};margin:10px 0 14px;"
    f"line-height:1.65;max-width:64ch;'>"
    f"Cross-section stress analysis for metallic airframe design — combined "
    f"axial, shear, bending, and torsion, with margins of safety to MMPDS-01. "
    f"Built for the rigor of a formal stress report.</p>"
    f"<div class='tk-page-meta'>"
    f"<span>MMPDS-01 allowables</span>"
    f"<span>Classical + FEM solvers</span>"
    f"<span>11 shapes + custom import</span>"
    f"<span>Interactive stress contour</span>"
    f"<span>Bolt-bending diagrams</span>"
    f"<span>Validation built in</span>"
    f"</div></div>",
    unsafe_allow_html=True,
)
st.divider()


# ── Module cards ──────────────────────────────────────────────────────────
section_header("Available Modules")

for row_start in range(0, len(MODULES), CARDS_PER_ROW):
    row = MODULES[row_start:row_start + CARDS_PER_ROW]
    # Pad the final row so a lone card keeps the same width as a full row's.
    cols = st.columns(CARDS_PER_ROW, gap="large")
    for col, (icon, title, desc, page_path) in zip(cols, row):
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
                    label=f"Open {title}  →",
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
