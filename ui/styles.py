"""
ui/styles.py

CSS injection for the Stress Toolkit. Called once at the top of any page.

Usage:
    from ui.styles import inject_css
    inject_css()
"""

import streamlit as st
from ui.theme import THEME


def inject_css() -> None:
    """Inject the toolkit's global CSS into the current Streamlit page."""
    t = THEME
    css = f"""<style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Serif:wght@400;500;600&display=swap');

    /* ── Root / canvas ──────────────────────────────────────────────── */
    html, body {{
        font-family: "IBM Plex Sans", system-ui, sans-serif !important;
        font-size: 14px;
        line-height: 1.45;
        -webkit-font-smoothing: antialiased;
        font-feature-settings: "ss01", "cv05", "cv11";
    }}
    html, body,
    [data-testid="stAppViewContainer"],
    [data-testid="stApp"],
    [data-testid="stMainBlockContainer"],
    .main {{
        background: {t.bg} !important;
        color: {t.text} !important;
    }}
    [data-testid="block-container"] {{
        background: transparent !important;
        padding-top: 24px !important;
    }}

    /* ── Sidebar ────────────────────────────────────────────────────── */
    [data-testid="stSidebar"] {{
        background: {t.sidebar} !important;
        border-right: 1px solid {t.border} !important;
    }}
    /* Font family only — let Streamlit light theme handle all colors */
    [data-testid="stSidebar"] input,
    [data-testid="stSidebar"] .stSelectbox,
    [data-testid="stSidebar"] .stNumberInput,
    [data-testid="stSidebar"] .stTextInput {{
        font-family: "IBM Plex Mono", monospace !important;
        font-size: 13px !important;
    }}
    [data-testid="stSidebar"] .tk-sec-hdr {{
        padding: 10px 0 6px !important;
        border-bottom: 1px solid {t.border} !important;
        margin-bottom: 8px !important;
    }}
    [data-testid="stSidebar"] .tk-sec-hdr__title {{
        font-size: 11px !important;
        letter-spacing: 0.08em !important;
        text-transform: uppercase !important;
        color: {t.accent} !important;
    }}

    /* ── Typography (main canvas) ───────────────────────────────────── */
    h1, h2, h3, h4, h5, h6 {{
        font-family: "IBM Plex Serif", Georgia, serif !important;
        color: {t.text} !important;
    }}
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] li {{
        color: {t.text} !important;
    }}

    /* ── Inputs — font only; colors handled by Streamlit light theme ── */
    .stNumberInput > div > div > input,
    .stTextInput > div > div > input,
    .stTextArea textarea {{
        font-family: "IBM Plex Mono", monospace !important;
        border-radius: 6px !important;
    }}

    /* ── Buttons ────────────────────────────────────────────────────── */
    .stButton > button {{
        background:    {t.accent} !important;
        color:         #ffffff !important;
        border:        none !important;
        border-radius: 6px !important;
        font-weight:   600 !important;
        font-family:   "IBM Plex Sans", system-ui, sans-serif !important;
        font-size:     13px !important;
        letter-spacing: 0.01em !important;
    }}
    .stButton > button:hover {{ background: {t.accent2} !important; }}

    /* ── Radio ──────────────────────────────────────────────────────── */
    .stRadio label,
    .stRadio > div > div {{ color: {t.text} !important; }}

    /* ── Expanders ──────────────────────────────────────────────────── */
    [data-testid="stExpander"] {{
        background:    {t.bg3} !important;
        border:        1px solid {t.border} !important;
        border-radius: 8px !important;
    }}
    [data-testid="stExpander"] summary {{ color: {t.text} !important; }}

    /* ── Native Streamlit tabs ──────────────────────────────────────── */
    [data-testid="stTabs"] button {{
        color: {t.muted} !important;
        font-family: "IBM Plex Sans", system-ui, sans-serif !important;
    }}
    [data-testid="stTabs"] button[aria-selected="true"] {{
        color: {t.accent} !important;
        border-bottom: 2px solid {t.accent} !important;
    }}

    /* ── Alerts / dividers ──────────────────────────────────────────── */
    [data-testid="stAlert"] {{
        background:   {t.bg3} !important;
        border-color: {t.border} !important;
        border-radius: 6px !important;
        color:        {t.text} !important;
    }}
    hr {{ border-color: {t.border} !important; margin: 12px 0 !important; }}

    /* ── Metrics ────────────────────────────────────────────────────── */
    [data-testid="stMetric"] {{
        background:    {t.bg3} !important;
        border:        1px solid {t.border} !important;
        border-radius: 8px !important;
        padding:       8px 12px !important;
    }}
    [data-testid="stMetricValue"] {{ color: {t.text} !important; }}
    [data-testid="stMetricLabel"] {{ color: {t.muted} !important; }}

    /* ════════════════════════════════════════════════════════════════
       TOOLKIT COMPONENTS
       ════════════════════════════════════════════════════════════════ */

    /* ── Page header ────────────────────────────────────────────────── */
    .tk-page-header {{
        padding-bottom: 16px;
        border-bottom: 1px solid {t.border};
        margin-bottom: 4px;
    }}
    .tk-page-title {{
        font-family: "IBM Plex Serif", Georgia, serif !important;
        font-size: 28px !important;
        font-weight: 500 !important;
        letter-spacing: -0.01em;
        color: {t.text} !important;
        margin: 0 0 8px !important;
        line-height: 1.15;
    }}
    .tk-page-title .sub {{
        font-style: italic;
        color: {t.muted} !important;
        font-size: 24px !important;
    }}
    .tk-page-meta {{
        font-family: "IBM Plex Mono", monospace !important;
        font-size: 11px !important;
        color: {t.muted} !important;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        display: flex;
        flex-wrap: wrap;
        gap: 6px 14px;
    }}
    .tk-page-meta b {{ color: {t.text2} !important; }}

    /* ── Section header ─────────────────────────────────────────────── */
    .tk-sec-hdr {{
        display: flex;
        align-items: baseline;
        gap: 10px;
        padding: 22px 0 10px;
        border-bottom: 1px solid {t.border};
        margin-bottom: 16px;
    }}
    .tk-sec-hdr__num {{
        font-family: "IBM Plex Mono", monospace !important;
        font-size: 11px !important;
        font-weight: 600 !important;
        color: {t.accent} !important;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        flex-shrink: 0;
    }}
    .tk-sec-hdr__title {{
        font-family: "IBM Plex Sans", system-ui, sans-serif !important;
        font-size: 15px !important;
        font-weight: 600 !important;
        color: {t.text} !important;
        flex: 1;
    }}
    .tk-sec-hdr__desc {{
        font-size: 12px !important;
        color: {t.muted} !important;
        font-style: italic;
    }}

    /* ── Stress card strip (5 stress cards + 1 combined = 6) ──────── */
    .tk-stress-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
        border: 1px solid {t.border};
        border-radius: 8px;
        overflow: hidden;
        background: {t.bg3};
        margin-bottom: 20px;
    }}
    .tk-stress-card {{
        padding: 14px 16px;
        border-right: 1px solid {t.border};
        display: flex;
        flex-direction: column;
        gap: 0;
        background: {t.bg3};
    }}
    .tk-stress-card:last-child {{ border-right: none; }}
    /* Combined MS card: accent left-border + subtle tint to stand apart */
    .tk-stress-card--combined {{
        background: {t.bg2};
        border-left: 3px solid {t.accent} !important;
    }}
    .tk-sc-label {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;
        gap: 4px;
    }}
    .tk-sc-name {{
        font-family: "IBM Plex Mono", monospace !important;
        font-size: 10px !important;
        font-weight: 600 !important;
        /* NO text-transform: Greek symbols like σ τ must stay lowercase */
        letter-spacing: 0.04em;
        color: {t.text2} !important;
    }}
    .tk-sc-val {{
        display: flex;
        align-items: baseline;
        gap: 4px;
        margin-bottom: 10px;
    }}
    .tk-sc-sign {{ color: {t.fail_fg} !important; font-size: 22px !important; line-height: 1; }}
    .tk-sc-num {{
        font-family: "IBM Plex Mono", monospace !important;
        font-size: 26px !important;
        font-weight: 500 !important;
        letter-spacing: -0.02em;
        color: {t.text} !important;
        line-height: 1;
        font-variant-numeric: tabular-nums;
    }}
    .tk-sc-unit {{
        font-family: "IBM Plex Mono", monospace !important;
        font-size: 12px !important;
        color: {t.muted} !important;
    }}
    .tk-sc-util-row {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 10px !important;
        color: {t.muted} !important;
        margin-bottom: 3px;
    }}
    .tk-sc-util-row b {{
        font-family: "IBM Plex Mono", monospace !important;
        font-size: 10px !important;
        font-weight: 600;
        color: {t.text2} !important;
    }}
    .tk-sc-bar {{
        height: 4px;
        background: {t.rule_soft};
        border-radius: 2px;
        overflow: hidden;
        margin: 2px 0 6px;
    }}
    .tk-sc-bar__fill {{ height: 100%; border-radius: 2px; transition: width 0.2s ease; }}
    .tk-sc-bar__fill.is-safe     {{ background: {t.pass_fg}; }}
    .tk-sc-bar__fill.is-caution  {{ background: {t.warn_fg}; }}
    .tk-sc-bar__fill.is-critical {{ background: {t.fail_fg}; }}
    .tk-sc-ms {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 10px !important;
        color: {t.muted} !important;
    }}
    .tk-sc-ms b {{
        font-family: "IBM Plex Mono", monospace !important;
        font-size: 10px !important;
        font-weight: 600;
        color: {t.text2} !important;
    }}

    /* ── Status badges ──────────────────────────────────────────────── */
    .tk-badge {{
        font-family: "IBM Plex Mono", monospace !important;
        font-size: 9px !important;
        font-weight: 600 !important;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        padding: 2px 6px;
        border-radius: 3px;
        white-space: nowrap;
        display: inline-block;
    }}
    .tk-badge.safe     {{ background: {t.pass_bg}; color: {t.pass_fg} !important; }}
    .tk-badge.caution  {{ background: {t.warn_bg}; color: {t.warn_fg} !important; }}
    .tk-badge.critical {{ background: {t.fail_bg}; color: {t.fail_fg} !important; }}

    /* ── Info card (horizontal key / value row) ─────────────────────── */
    .tk-icard {{
        background:    {t.bg3};
        border:        1px solid {t.border};
        border-radius: 6px;
        padding:       8px 12px;
        margin-bottom: 4px;
        display:       flex;
        align-items:   center;
        gap:           10px;
    }}
    .tk-icard-lbl {{
        font-family:  "IBM Plex Mono", monospace !important;
        font-size:    11px !important;
        font-weight:  600 !important;
        letter-spacing: 0.05em;
        color:        {t.muted} !important;
        min-width:    52px;
        flex-shrink:  0;
    }}
    .tk-icard-val {{
        font-family:         "IBM Plex Mono", monospace !important;
        font-size:           14px !important;
        font-weight:         500 !important;
        color:               {t.text} !important;
        flex:                1;
        font-variant-numeric: tabular-nums;
    }}
    .tk-icard-unit {{
        font-size:   10px !important;
        color:       {t.muted} !important;
        margin-left: 2px;
    }}
    .tk-icard-sub {{
        font-size:  10px !important;
        color:      {t.muted} !important;
        font-style: italic;
    }}

    /* ── Warning banner ─────────────────────────────────────────────── */
    .tk-warn {{
        background:    {t.warn_bg};
        border-left:   3px solid {t.warn_fg};
        border-radius: 0 6px 6px 0;
        padding:       10px 14px;
        margin:        8px 0;
        font-size:     12px;
        color:         {t.warn_fg} !important;
        font-weight:   500;
    }}

    /* ── Pass / fail chips ──────────────────────────────────────────── */
    .tk-chip-pass {{
        background:  {t.pass_bg};
        color:       {t.pass_fg} !important;
        font-family: "IBM Plex Mono", monospace !important;
        font-weight: 600;
        border-radius: 4px;
        padding:     3px 8px;
        font-size:   12px;
        display:     inline-block;
    }}
    .tk-chip-fail {{
        background:  {t.fail_bg};
        color:       {t.fail_fg} !important;
        font-family: "IBM Plex Mono", monospace !important;
        font-weight: 600;
        border-radius: 4px;
        padding:     3px 8px;
        font-size:   12px;
        display:     inline-block;
    }}
    .tk-chip-flag {{
        background:     {t.warn_bg};
        color:          {t.warn_fg} !important;
        font-family:    "IBM Plex Mono", monospace !important;
        font-size:      9px !important;
        font-weight:    700;
        border-radius:  3px;
        padding:        1px 5px;
        margin-left:    4px;
        display:        inline-block;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }}

    /* ── Formula reference block ────────────────────────────────────── */
    .tk-formulae {{
        border:        1px solid {t.border};
        border-radius: 8px;
        overflow:      hidden;
        background:    {t.bg3};
    }}
    .tk-frow {{
        display:        flex;
        align-items:    flex-start;
        gap:            14px;
        padding:        8px 14px;
        border-bottom:  1px solid {t.rule_soft};
        flex-wrap:      wrap;
    }}
    .tk-frow:last-child {{ border-bottom: none; }}
    .tk-fname {{
        font-size:   11px;
        font-weight: 700;
        color:       {t.accent2} !important;
        min-width:   190px;
        padding-top: 3px;
        flex-shrink: 0;
    }}
    .tk-fexpr {{
        font-family:   "IBM Plex Mono", monospace !important;
        font-size:     12px;
        color:         {t.text} !important;
        background:    {t.bg2};
        padding:       3px 8px;
        border-radius: 4px;
        min-width:     240px;
    }}
    .tk-fdesc {{
        font-size:   11px;
        color:       {t.muted} !important;
        font-style:  italic;
        padding-top: 3px;
        flex:        1;
        min-width:   200px;
    }}

    /* ── Responsive ─────────────────────────────────────────────────── */
    @media (max-width: 900px) {{
        .tk-stress-grid {{ grid-template-columns: repeat(2, 1fr); }}
        .tk-stress-card {{ border-bottom: 1px solid {t.border}; }}
    }}
    @media (max-width: 768px) {{
        .tk-sec-hdr  {{ flex-wrap: wrap; }}
        .tk-fname    {{ min-width: 120px; font-size: 10px; }}
        .tk-fexpr    {{ font-size: 10px; min-width: 140px; }}
        [data-testid="stDataFrame"],
        [data-testid="stTable"] {{
            overflow-x: auto !important;
            -webkit-overflow-scrolling: touch;
        }}
    }}
    @media (max-width: 480px) {{
        .tk-frow {{ flex-direction: column; gap: 4px; }}
        .tk-stress-grid {{ grid-template-columns: 1fr; }}
    }}

    /* ── Print ───────────────────────────────────────────────────────── */
    @media print {{
        [data-testid="stSidebar"], .stButton, footer {{ display: none !important; }}
        body {{ background: #fff !important; }}
    }}
    </style>"""

    st.markdown(css, unsafe_allow_html=True)
