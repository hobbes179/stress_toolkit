"""
ui/theme.py

Central theme token system for the Stress Toolkit.

All colors, spacing, typography are defined here. Other modules import THEME
and never hardcode colors. A single unified light theme is used throughout —
warm off-white canvas, light sidebar, IBM Plex type family.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    """A complete theme definition. All values are hex color strings."""
    # ── Base surfaces ─────────────────────────────────────
    bg:           str   # main page / sidebar background
    bg2:          str   # raised surface (cards, section headers)
    bg3:          str   # paper / card surface (white)
    sidebar:      str   # sidebar background

    # ── Typography ────────────────────────────────────────
    text:         str   # primary text (ink)
    text2:        str   # secondary text (ink-2)
    muted:        str   # tertiary / metadata text (ink-3)

    # ── Accents ───────────────────────────────────────────
    accent:       str   # primary accent (signal blue)
    accent2:      str   # deep accent
    border:       str   # card borders, dividers
    rule_soft:    str   # subtle table row dividers

    # ── Status colors ─────────────────────────────────────
    pass_bg:      str   # safe background
    pass_fg:      str   # safe foreground
    fail_bg:      str   # critical background
    fail_fg:      str   # critical foreground
    warn_bg:      str   # caution background
    warn_fg:      str   # caution foreground
    amber:        str   # governing value highlight text
    amber_bg:     str   # governing value highlight background

    # ── Component-specific ────────────────────────────────
    hdr:          str   # section header background
    inp:          str   # input field background
    inp_border:   str   # input field border
    row_alt:      str   # alternating row background
    row_base:     str   # base row background
    tbl_hdr_bg:   str   # table header background
    tbl_hdr_fg:   str   # table header text
    tbl_border:   str   # table border


# ──────────────────────────────────────────────────────────────────────────
# Unified light theme — warm engineering-report aesthetic
# Warm off-white canvas, clean type, signal-blue accent.
# ──────────────────────────────────────────────────────────────────────────
THEME = Theme(
    bg          = "#f5f3ee",   # warm off-white
    bg2         = "#efece4",   # subtle raised surface
    bg3         = "#ffffff",   # paper / card white
    sidebar     = "#f5f3ee",   # sidebar matches canvas
    text        = "#15181d",   # primary ink
    text2       = "#2c323b",   # secondary ink
    muted       = "#5b6472",   # tertiary / labels
    accent      = "#1d4ed8",   # signal blue
    accent2     = "#0b2a7a",   # deep blue
    border      = "#d8d3c7",   # card borders
    rule_soft   = "#e7e2d4",   # table row dividers
    pass_bg     = "#d9ecdf",
    pass_fg     = "#1f7a4a",
    fail_bg     = "#f4d5d3",
    fail_fg     = "#b3231c",
    warn_bg     = "#f6e8c8",
    warn_fg     = "#b67400",
    amber       = "#b67400",
    amber_bg    = "#fffaed",
    hdr         = "#efece4",
    inp         = "#ffffff",
    inp_border  = "#d8d3c7",
    row_alt     = "#efece4",
    row_base    = "#ffffff",
    tbl_hdr_bg  = "#efece4",
    tbl_hdr_fg  = "#15181d",
    tbl_border  = "#d8d3c7",
)


# ──────────────────────────────────────────────────────────────────────────
# Margin-of-safety color thresholds (design handoff §6.3)
# MS < MS_FAIL → fail (red); MS_FAIL ≤ MS < MS_WARN → caution (amber);
# MS ≥ MS_WARN → pass (green). Kept here as constants — never inline in pages.
# ──────────────────────────────────────────────────────────────────────────
MS_FAIL = 0.0
MS_WARN = 0.25


def ms_status(ms: float) -> tuple[str, str, str]:
    """Map an MS value to (background, foreground, label) using THEME status
    colors and the MS_FAIL / MS_WARN thresholds above."""
    if ms < MS_FAIL:
        return THEME.fail_bg, THEME.fail_fg, "FAIL"
    if ms < MS_WARN:
        return THEME.warn_bg, THEME.warn_fg, "MARGINAL"
    return THEME.pass_bg, THEME.pass_fg, "PASS"


# ──────────────────────────────────────────────────────────────────────────
# Engineering plot palette — used by matplotlib figures.
# Always white background for print-friendly output.
# ──────────────────────────────────────────────────────────────────────────
PLOT_PALETTE = dict(
    section_fill     = "#BDD7EE",   # section material fill
    section_edge     = "#1A5496",   # section outline
    kp_marker        = "#E84A00",   # key-point dot
    kp_edge          = "#8B2500",   # key-point edge
    centroid         = "#1F3864",   # centroid crosshair
    axis             = "#9DC3E6",   # neutral-axis lines
    grid             = "#dddddd",   # gridlines
    text             = "#333333",   # plot text
    tick             = "#555555",   # tick labels
    spine            = "#cccccc",   # axis spine
    background       = "#ffffff",   # plot background (always white)
    contour_cmap     = "jet",        # blue→cyan→green→yellow→red (traditional stress)
)


# ──────────────────────────────────────────────────────────────────────────
# Bolt-diagram palette — used by the hand-built SVG in
# apps/bolt_bending/plotting.py. Kept here for the same reason as
# PLOT_PALETTE: no page or plotting module hardcodes a hex value.
#
# Shear and moment need to stay separable in colour, in print, and in
# greyscale, so they are a blue/oxblood pair rather than two hues of one
# family. White ground throughout, matching the matplotlib figures.
# ──────────────────────────────────────────────────────────────────────────
BOLT_PALETTE = dict(
    shear        = THEME.accent,     # shear diagram, bearing arrows
    moment       = "#8c2f39",        # moment diagram, head/nut reactions
    ink          = THEME.text,       # outlines, axis rules
    muted        = THEME.muted,      # tick labels, annotations
    rule         = THEME.border,     # panel dividers
    rule_soft    = THEME.rule_soft,  # segment boundary lines
    bolt_fill    = "#edf2f3",        # bolt shank body
    cap_fill     = "#d7e0e3",        # head and nut blocks
    plate_fill   = "#e4ebee",        # plate bodies
    hatch_bg     = "#f7f9f9",        # spacer hatch ground
    hatch_line   = "#c9d4d8",        # spacer hatch strokes
    background   = "#ffffff",        # figure ground (always white, like PLOT_PALETTE)
)
