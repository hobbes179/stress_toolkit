"""
apps/material_library/app.py

Material Library — browse all MMPDS-01 allowables and physical properties.
Exports render() — called from pages/2_Material_Library.py.

Read-only reference view; no user inputs or calculations.
"""

from __future__ import annotations

import streamlit as st

from ui.styles import inject_css
from ui.components import section_header, warning_banner, html_table
from ui.theme import THEME

from library.materials import MATERIALS, list_by_category


# ──────────────────────────────────────────────────────────────────────────
# Citation links
# MMPDS-01 is a purchased document (CINDAS LLC). Direct section links are
# not publicly accessible; these point to the publishers' root pages.
# ──────────────────────────────────────────────────────────────────────────
_LINK_MMPDS = "https://cindasdata.com"
_LINK_AISC  = "https://www.aisc.org"
_LINK_ASTM  = "https://www.astm.org"


def _source_link(source: str) -> str:
    """Wrap a source string with appropriate hyperlinks to the publisher."""
    t = THEME
    a = f"style='color:{t.accent};text-decoration:none;'"
    if "MMPDS" in source:
        return (
            f"<a href='{_LINK_MMPDS}' target='_blank' rel='noopener noreferrer' {a}>"
            f"{source}</a>"
        )
    if "AISC" in source and "A36" in source:
        return (
            f"<a href='{_LINK_AISC}' target='_blank' rel='noopener noreferrer' {a}>AISC</a>"
            f" / "
            f"<a href='{_LINK_ASTM}/a0036_a0036m' target='_blank' rel='noopener noreferrer' {a}>ASTM A36</a>"
        )
    if "AISC" in source and "A572" in source:
        return (
            f"<a href='{_LINK_AISC}' target='_blank' rel='noopener noreferrer' {a}>AISC</a>"
            f" / "
            f"<a href='{_LINK_ASTM}/a0572_a0572m' target='_blank' rel='noopener noreferrer' {a}>ASTM A572</a>"
        )
    return source


# ──────────────────────────────────────────────────────────────────────────
# Formatting helpers
# ──────────────────────────────────────────────────────────────────────────
def _fmt(val: float | None, fmt: str) -> str:
    """Format a numeric value or return an em-dash if absent."""
    return format(val, fmt) if val is not None else "—"


def _cell(mat, prop: str, fmt: str) -> str:
    """Formatted cell; appends EST badge when the value is estimated."""
    val = getattr(mat, prop)
    text = _fmt(val, fmt)
    if val is not None and mat.is_estimated(prop):
        text += " <span class='tk-chip-flag'>EST</span>"
    return text


# ──────────────────────────────────────────────────────────────────────────
# Table renderers
# ──────────────────────────────────────────────────────────────────────────
def _strength_table(materials) -> None:
    """Render the strength allowables table for a list of Material objects."""
    headers = [
        "Material",
        "Fty (ksi)", "Ftu (ksi)", "Fcy (ksi)",
        "Fsu (ksi)", "Fbru (ksi)", "Fbry (ksi)",
        "Source",
    ]
    rows = [
        [
            f"<b>{mat.name}</b>",
            _cell(mat, "Fty",  ".0f"),
            _cell(mat, "Ftu",  ".0f"),
            _cell(mat, "Fcy",  ".0f"),
            _cell(mat, "Fsu",  ".0f"),
            _cell(mat, "Fbru", ".0f"),
            _cell(mat, "Fbry", ".0f"),
            _source_link(mat.source),
        ]
        for mat in materials
    ]
    html_table(
        headers, rows,
        col_aligns=["left"] + ["center"] * 6 + ["left"],
    )


def _props_table(materials) -> None:
    """Render the elastic and physical properties table."""
    headers = [
        "Material",
        "E (Msi)", "Ec (Msi)", "G (Msi)", "ν",
        "α (µin/in/°F)", "T_max (°F)", "ρ (lb/in³)",
        "Notes",
    ]
    rows = [
        [
            f"<b>{mat.name}</b>",
            _fmt(mat.E,     ".1f"),
            _fmt(mat.Ec,    ".1f"),
            _fmt(mat.G,     ".1f"),
            _fmt(mat.nu,    ".2f"),
            _fmt(mat.alpha, ".1f"),
            _fmt(mat.T_max, ".0f"),
            _fmt(mat.rho,   ".3f"),
            mat.notes if mat.notes else "—",
        ]
        for mat in materials
    ]
    html_table(
        headers, rows,
        col_aligns=["left"] + ["center"] * 7 + ["left"],
    )


# ──────────────────────────────────────────────────────────────────────────
# RENDER
# ──────────────────────────────────────────────────────────────────────────
def render() -> None:
    inject_css()
    t = THEME

    grouped  = list_by_category()
    cats     = [c for c in ("Aluminum", "Steel", "Titanium", "Stainless") if c in grouped]
    all_mats = [m for cat in cats for m in grouped[cat]]
    n_mats   = len(all_mats)

    # ── Sidebar ───────────────────────────────────────────────────────────
    with st.sidebar:
        section_header("About")
        st.markdown(
            f"<p style='font-size:12px;color:{t.muted};line-height:1.6;'>"
            "Room-temperature minimum allowables for the dominant grain direction "
            "unless otherwise noted. Strength values in <b>ksi</b>; "
            "modulus values in <b>Msi</b>."
            "</p>",
            unsafe_allow_html=True,
        )

        section_header("Property Legend")
        rows_html = (
            f"<b style='color:{t.text2};'>Fty</b>"
            f"<span style='color:{t.muted};'> — Tensile yield strength</span><br>"
            f"<b style='color:{t.text2};'>Ftu</b>"
            f"<span style='color:{t.muted};'> — Tensile ultimate strength</span><br>"
            f"<b style='color:{t.text2};'>Fcy</b>"
            f"<span style='color:{t.muted};'> — Compressive yield strength</span><br>"
            f"<b style='color:{t.text2};'>Fsu</b>"
            f"<span style='color:{t.muted};'> — Shear ultimate strength</span><br>"
            f"<b style='color:{t.text2};'>Fbru</b>"
            f"<span style='color:{t.muted};'> — Bearing ultimate (e/D = 1.5)</span><br>"
            f"<b style='color:{t.text2};'>Fbry</b>"
            f"<span style='color:{t.muted};'> — Bearing yield (e/D = 1.5)</span><br>"
            f"<b style='color:{t.text2};'>E / Ec</b>"
            f"<span style='color:{t.muted};'> — Tension / compression modulus</span><br>"
            f"<b style='color:{t.text2};'>G</b>"
            f"<span style='color:{t.muted};'> — Shear modulus</span><br>"
            f"<b style='color:{t.text2};'>ν</b>"
            f"<span style='color:{t.muted};'> — Poisson's ratio</span><br>"
            f"<b style='color:{t.text2};'>α</b>"
            f"<span style='color:{t.muted};'> — Thermal expansion coeff.</span><br>"
            f"<b style='color:{t.text2};'>T_max</b>"
            f"<span style='color:{t.muted};'> — Max service temperature</span><br>"
            f"<b style='color:{t.text2};'>ρ</b>"
            f"<span style='color:{t.muted};'> — Density</span><br>"
            f"<span class='tk-chip-flag'>EST</span>"
            f"<span style='color:{t.muted};'> — Estimated; not from MMPDS-01</span>"
        )
        st.markdown(
            f"<div style='font-size:12px;line-height:2.1;'>{rows_html}</div>",
            unsafe_allow_html=True,
        )

    # ── Page header ───────────────────────────────────────────────────────
    st.markdown(
        "<div class='tk-page-header'>"
        "<h1 class='tk-page-title'>Material Library</h1>"
        "<div class='tk-page-meta'>"
        f"<span><b>{n_mats} alloys</b></span>"
        "<span>4 categories</span>"
        "<span>MMPDS-01 allowables</span>"
        "<span>IPS units</span>"
        "<span>Room temperature</span>"
        "<span>Minimum properties</span>"
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    warning_banner(
        "⚠ For preliminary sizing only. Always verify allowables against the applicable "
        "procurement specification and material certification before use in a formal stress report."
    )

    # ── Category tabs ─────────────────────────────────────────────────────
    tabs = st.tabs(["All"] + cats)

    # All tab
    with tabs[0]:
        section_header("Strength Allowables", number="01",
                       desc="room-temperature minimums")
        _strength_table(all_mats)
        st.caption(
            "Fbru / Fbry at edge-distance-to-diameter ratio e/D = 1.5.  "
            "EST = estimated value not sourced from MMPDS-01."
        )

        section_header("Elastic & Physical Properties", number="02")
        _props_table(all_mats)

    # Per-category tabs
    for i, cat in enumerate(cats):
        with tabs[i + 1]:
            mats = grouped[cat]
            section_header("Strength Allowables",
                           desc=f"{cat} — room-temperature minimums")
            _strength_table(mats)
            st.caption(
                "Fbru / Fbry at e/D = 1.5.  "
                "EST = estimated value not sourced from MMPDS-01."
            )

            section_header("Elastic & Physical Properties")
            _props_table(mats)

    # ── Footer ────────────────────────────────────────────────────────────
    st.divider()
    st.markdown(
        f"<p style='font-family:\"IBM Plex Mono\",monospace;"
        f"font-size:11px;color:{t.muted};text-align:center;'>"
        "Primary source: MMPDS-01 (Metallic Materials Properties Development and Standardization, CINDAS LLC).  "
        "Structural steels A36 / A572 from AISC / ASTM.  "
        "Not a substitute for project-specific material qualification."
        "</p>",
        unsafe_allow_html=True,
    )
