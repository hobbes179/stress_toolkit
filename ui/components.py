"""
ui/components.py

Reusable UI components for the Stress Toolkit.

All HTML is built as single-line concatenated strings to prevent Streamlit's
Markdown parser from inserting unwanted <p> tags or interpreting indentation
as code blocks inside unsafe_allow_html blocks.

IMPORTANT — Greek symbols (σ, τ, etc.):
    Never apply CSS text-transform:uppercase to any element that may contain
    Greek stress symbols. CSS uppercase turns σ → Σ and τ → Τ. All classes
    that display engineering labels intentionally omit text-transform.

Usage:
    from ui.components import (
        section_header, info_card, warning_banner,
        html_table, ms_chip, render_formulae, estimated_flag,
        stress_card_strip,
    )
"""

from __future__ import annotations
from typing import Iterable, Sequence

import streamlit as st

from ui.theme import THEME


# ──────────────────────────────────────────────────────────────────────────
# Section header
# ──────────────────────────────────────────────────────────────────────────
def section_header(
    text: str,
    number: str | None = None,
    desc: str | None = None,
) -> None:
    """
    Render a section header.

    Args:
        text:   Title text.
        number: Optional short label in accent color (e.g. "01", "02").
                Omit for sidebar section headers.
        desc:   Optional short italic descriptor after the title.
    """
    num_html  = f"<span class='tk-sec-hdr__num'>{number}</span>" if number else ""
    desc_html = f"<span class='tk-sec-hdr__desc'>{desc}</span>" if desc else ""
    html = (
        "<div class='tk-sec-hdr'>"
        + num_html
        + f"<span class='tk-sec-hdr__title'>{text}</span>"
        + desc_html
        + "</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────
# Info card  (horizontal key / value row)
# ──────────────────────────────────────────────────────────────────────────
def info_card(
    label: str,
    value: str,
    unit: str = "",
    *,
    sub: str | None = None,
    value_color: str | None = None,
    flag: str | None = None,
) -> None:
    """
    Render a horizontal key/value info card.

    Args:
        label:       Short key shown in mono at the left.
        value:       Main value text (pre-formatted string).
        unit:        Optional unit suffix (smaller, muted).
        sub:         Optional italic sub-line to the right.
        value_color: Optional CSS color override for the value.
        flag:        Optional small badge appended to value (e.g. "EST").
    """
    val_style = f"color:{value_color};" if value_color else ""
    flag_html = f"<span class='tk-chip-flag'>{flag}</span>" if flag else ""
    sub_html  = f"<span class='tk-icard-sub'>{sub}</span>" if sub else ""
    html = (
        "<div class='tk-icard'>"
        f"<div class='tk-icard-lbl'>{label}</div>"
        f"<div class='tk-icard-val' style='{val_style}'>{value}"
        f"<span class='tk-icard-unit'>{unit}</span>{flag_html}</div>"
        + sub_html
        + "</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────
# Stress card strip  (5-card governing summary)
# ──────────────────────────────────────────────────────────────────────────
def stress_card_strip(
    govs: list,
    allowables: list[tuple[float, str, float]],
    combined_ms: float | None = None,
) -> None:
    """
    Render the horizontal governing stress summary strip.

    5 stress cards (one per GoverningStress) plus an optional 6th card
    for the MMPDS combined interaction margin. The 6th card is visually
    distinguished with an accent left-border and a subtle background tint.

    Args:
        govs:        List of GoverningStress objects (from find_governing).
        allowables:  List of (allowable_value, allowable_label, sf) tuples,
                     parallel to govs. Example: (42.0, "Fty", 1.0).
        combined_ms: MMPDS combined interaction MS value (optional).
    """
    def _status(util: float) -> str:
        if util > 0.9:
            return "critical"
        if util > 0.5:
            return "caution"
        return "safe"

    def _status_label(s: str) -> str:
        return {"safe": "Safe", "caution": "Watch", "critical": "Critical"}[s]

    cards: list[str] = []

    # ── Individual stress cards ───────────────────────────────────────
    for gov, (allow, allow_label, sf) in zip(govs, allowables):
        val      = abs(gov.value)
        util     = val / allow if allow > 0 else 0.0
        ms       = allow / (sf * val) - 1 if val > 1e-10 else 999.0
        pct      = min(100.0, util * 100.0)
        status   = _status(util)
        ms_str   = "+∞" if ms > 99 else (f"+{ms:.1f}" if ms >= 0 else f"{ms:.1f}")
        sign_html = "<span class='tk-sc-sign'>−</span>" if gov.value < -1e-10 else ""

        cards.append(
            "<div class='tk-stress-card'>"
            "<div class='tk-sc-label'>"
            f"<span class='tk-sc-name'>{gov.label}</span>"
            f"<span class='tk-badge {status}'>{_status_label(status)}</span>"
            "</div>"
            f"<div class='tk-sc-val'>{sign_html}"
            f"<span class='tk-sc-num'>{val:.2f}</span>"
            "<span class='tk-sc-unit'>ksi</span>"
            "</div>"
            "<div class='tk-sc-util-row'>"
            f"<span>vs {allow_label}</span>"
            f"<b>{pct:.1f}%</b>"
            "</div>"
            "<div class='tk-sc-bar'>"
            f"<div class='tk-sc-bar__fill is-{status}' style='width:{pct:.1f}%'></div>"
            "</div>"
            "<div class='tk-sc-ms'>"
            "<span>Margin of Safety</span>"
            f"<b>MS = {ms_str}</b>"
            "</div>"
            "</div>"
        )

    # ── Combined MS card (distinct: accent border + tinted bg) ───────
    if combined_ms is not None:
        ms = combined_ms
        # Utilization = 1/(1 + MS); when MS=0 → 100%, MS=1 → 50%
        util = 1.0 / (1.0 + ms) if ms > -1 + 1e-6 else 2.0
        pct  = min(100.0, util * 100.0)
        status  = _status(util)
        ms_str  = f"+{ms:.2f}" if ms >= 0 else f"{ms:.2f}"

        cards.append(
            "<div class='tk-stress-card tk-stress-card--combined'>"
            "<div class='tk-sc-label'>"
            "<span class='tk-sc-name'>Combined Interaction</span>"
            f"<span class='tk-badge {status}'>{_status_label(status)}</span>"
            "</div>"
            "<div class='tk-sc-val'>"
            f"<span class='tk-sc-num'>{ms_str}</span>"
            "<span class='tk-sc-unit'>MS</span>"
            "</div>"
            "<div class='tk-sc-util-row'>"
            "<span>(Ra+Rb) + Rs² = 1</span>"
            f"<b>{pct:.1f}%</b>"
            "</div>"
            "<div class='tk-sc-bar'>"
            f"<div class='tk-sc-bar__fill is-{status}' style='width:{pct:.1f}%'></div>"
            "</div>"
            "<div class='tk-sc-ms'>"
            "<span>Combined margin</span>"
            f"<b>MS = {ms_str}</b>"
            "</div>"
            "</div>"
        )

    html = "<div class='tk-stress-grid'>" + "".join(cards) + "</div>"
    st.markdown(html, unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────
# Warning banner
# ──────────────────────────────────────────────────────────────────────────
def warning_banner(text_html: str) -> None:
    """Render an amber warning bar. text_html may contain inline HTML."""
    st.markdown(f"<div class='tk-warn'>{text_html}</div>", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────
# Themed HTML table
# ──────────────────────────────────────────────────────────────────────────
def html_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    col_aligns: Sequence[str] | None = None,
) -> None:
    """
    Render a themed HTML table. Cell contents may include inline HTML.

    Header text-transform is intentionally omitted so that column names
    containing Greek symbols (σ, τ) render in the correct case.

    Args:
        headers:    Column header strings.
        rows:       Row sequences; each row length must match headers.
        col_aligns: CSS text-align per column. Defaults to left then center.
    """
    t = THEME
    if col_aligns is None:
        col_aligns = ["left"] + ["center"] * (len(headers) - 1)

    # No text-transform here — σ/τ column names must stay lowercase.
    th_style = (
        f"background:{t.tbl_hdr_bg};color:{t.tbl_hdr_fg};"
        f"padding:8px 10px;font-size:11px;font-weight:700;"
        f"font-family:'IBM Plex Mono',monospace;letter-spacing:0.03em;"
        f"border:1px solid {t.tbl_border};white-space:nowrap;"
    )

    parts: list[str] = [
        '<div style="overflow-x:auto;-webkit-overflow-scrolling:touch;">',
        f'<table style="width:100%;border-collapse:collapse;font-size:12px;'
        f"font-family:'IBM Plex Mono',monospace;\">",
        "<thead><tr>",
    ]
    for h in headers:
        parts.append(f"<th style='{th_style}'>{h}</th>")
    parts.append("</tr></thead><tbody>")

    for ri, row in enumerate(rows):
        bg = t.row_alt if ri % 2 else t.row_base
        parts.append(f"<tr style='background:{bg};'>")
        for ci, cell in enumerate(row):
            align = col_aligns[ci] if ci < len(col_aligns) else "center"
            parts.append(
                f"<td style='padding:7px 10px;"
                f"border:1px solid {t.tbl_border};"
                f"color:{t.text};text-align:{align};'>{cell}</td>"
            )
        parts.append("</tr>")
    parts.append("</tbody></table></div>")

    st.markdown("".join(parts), unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────
# Margin-of-safety chip
# ──────────────────────────────────────────────────────────────────────────
def ms_chip(value) -> str:
    """
    Return HTML for a pass/fail margin chip (does not write to page).

    Pass (MS ≥ 0): green chip.
    Fail (MS < 0): red chip.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)

    if v > 10:
        return "<span class='tk-chip-pass'>+HIGH</span>"
    if v >= 0:
        return f"<span class='tk-chip-pass'>✓ +{v:.2f}</span>"
    return f"<span class='tk-chip-fail'>✗ {v:.2f}</span>"


# ──────────────────────────────────────────────────────────────────────────
# Formula reference rows
# ──────────────────────────────────────────────────────────────────────────
def render_formulae(formulae: Iterable[tuple[str, str, str]]) -> None:
    """
    Render all (name, expr, desc) tuples as a single batched HTML block.
    Batching prevents Streamlit element spacing from fragmenting the rows.
    """
    rows: list[str] = []
    for name, expr, desc in formulae:
        rows.append(
            "<div class='tk-frow'>"
            f"<div class='tk-fname'>{name}</div>"
            f"<div class='tk-fexpr'>{expr}</div>"
            f"<div class='tk-fdesc'>{desc}</div>"
            "</div>"
        )
    html = "<div class='tk-formulae'>" + "".join(rows) + "</div>"
    st.markdown(html, unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────
# Estimated-value flag
# ──────────────────────────────────────────────────────────────────────────
def estimated_flag(field_name: str, estimated_fields: Iterable[str]) -> str:
    """Return 'EST' if field_name is in estimated_fields, else empty string."""
    return "EST" if field_name in (estimated_fields or ()) else ""
