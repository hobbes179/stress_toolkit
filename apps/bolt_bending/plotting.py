"""
apps/bolt_bending/plotting.py

Joint elevation and the shear / moment diagrams, as a hand-built SVG string.
No Streamlit imports — `joint_diagram_svg()` is pure and takes a
`BoltAnalysis`, so it can be rendered to a file, a page, or a test.

Why SVG and not matplotlib
──────────────────────────
The rest of the toolkit draws with matplotlib, but this figure is not a plot
of a function — it is a schematic elevation of the joint with the bearing
distribution drawn on it, sitting beside two diagrams that share its vertical
axis. That composition was already solved in the standalone tool this module
was ported from (`docs/bolt_bending/index.html`), so the SVG is carried over
essentially unchanged and only the palette is swapped for the toolkit tokens
in `ui.theme.BOLT_PALETTE`.

⚠️ ASSUMPTION — the joint elevation is schematic in the HORIZONTAL direction
only: bolt width and plate reach are fixed pixel values. The vertical
(station) axis is dimensionally true and shared by all three panels. Do not
"fix" the horizontal scale to be dimensionally true — a real diameter-to-grip
ratio makes the elevation unreadable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from xml.sax.saxutils import escape

from library.bolt_bending.kernel import BoltAnalysis
from ui.theme import BOLT_PALETTE

# ── Canvas geometry (user units; the SVG scales to its container) ─────────
# Height allows for the three-line caption block below the diagrams (see the
# end of joint_diagram_svg); the last line sits at BOT + 104.
VIEW_W, VIEW_H = 820, 584
TOP, BAND_H = 76, 384
BOT = TOP + BAND_H
CX, BW, PL = 210, 26, 126          # centreline, bolt width, plate reach
PANEL_W = 198
PANEL_V_X, PANEL_M_X = 352, 596
BEARING_W = 92                     # full-scale width of a bearing block

# Minimum horizontal gap between two axis tick labels, in user units. A label
# like "-1,057" is about 34 wide at font-size 11; below this they overprint.
TICK_MIN_SEP = 36


# ══════════════════════════════════════════════════════════════════════════
# Number formatting — matches the original tool so screenshots compare
# ══════════════════════════════════════════════════════════════════════════
def fmt(v: float, dp: int) -> str:
    """Fixed-decimal with thousands separators."""
    return f"{v:,.{dp}f}"


def whole(v: float) -> str:
    """Whole units above 1, `sig` below it.

    For reaction and couple annotations, where decimals on a ~57 lbf
    idealisation imply a precision the number does not have. The fallback
    keeps a small value from printing as a bare "0".
    """
    return fmt(v, 0) if abs(v) >= 1.0 else sig(v)


def sig(v: float) -> str:
    """Magnitude-adaptive precision: fewer decimals as the number grows."""
    a = abs(v)
    if a == 0:
        return "0"
    if a >= 1000:
        return fmt(v, 0)
    if a >= 100:
        return fmt(v, 1)
    if a >= 1:
        return fmt(v, 2)
    return fmt(v, 3)


# ══════════════════════════════════════════════════════════════════════════
# Tiny SVG element builders
# ══════════════════════════════════════════════════════════════════════════
def _attrs(d: dict) -> str:
    return " ".join(f'{k}="{v}"' for k, v in d.items())


def _el(tag: str, **kw) -> str:
    """Self-closing element. Trailing underscores in kwargs become hyphens
    (stroke_width -> stroke-width)."""
    return f"<{tag} {_attrs({k.replace('_', '-'): v for k, v in kw.items()})}/>"


def _text(x: float, y: float, s: str, **kw) -> str:
    base = {"x": x, "y": y, "font-size": 11, "fill": BOLT_PALETTE["muted"]}
    base.update({k.replace("_", "-"): v for k, v in kw.items()})
    return f"<text {_attrs(base)}>{escape(str(s))}</text>"


# ══════════════════════════════════════════════════════════════════════════
# The figure
# ══════════════════════════════════════════════════════════════════════════
def _hatch_band(x: float, y: float, w: float, h: float,
                spacing: float = 6.0, opacity: float = 1.0) -> str:
    """A diagonal-hatched rectangle, drawn as explicit clipped line segments.

    Deliberately NOT an SVG `<pattern>` fill. Patterns need `<defs>` plus a
    `url(#id)` reference, which ties the figure to a sanitizer that preserves
    both, and to ids being unique across everything else on the page. Solving
    the clip analytically instead keeps the figure a self-contained bag of
    primitives that renders anywhere — inline, in a file, in a PDF.

    Lines run at 45 degrees along constant (x - y). For each such line the
    entry and exit points on the rectangle are found directly, so no clipPath
    is needed either.
    """
    c = BOLT_PALETTE
    parts = [_el("rect", x=x, y=y, width=w, height=h, fill=c["hatch_bg"],
                 fill_opacity=opacity, stroke=c["ink"], stroke_width=1,
                 stroke_opacity=min(1.0, opacity + 0.25))]

    step = spacing * 1.4142135623730951      # perpendicular spacing -> x offset
    k0 = math.floor((x - (y + h)) / step)
    k1 = math.ceil((x + w - y) / step)
    for k in range(k0, k1 + 1):
        const = k * step                      # the line is x - y = const
        y_a = max(y, x - const)               # enters at the top or left edge
        y_b = min(y + h, x + w - const)       # leaves at the bottom or right
        if y_b - y_a <= 0.01:
            continue
        parts.append(_el("line", x1=round(const + y_a, 2), y1=round(y_a, 2),
                         x2=round(const + y_b, 2), y2=round(y_b, 2),
                         stroke=c["hatch_line"], stroke_width=1.4,
                         stroke_opacity=opacity))
    return "".join(parts)


@dataclass(frozen=True)
class Group:
    """A physical layer, for a figure whose segments are subdivisions of it.

    The refined bearing solve splits each plate into ~24 strips so the varying
    distribution can be drawn. Those strips are the right thing for the
    bearing blocks and the diagrams, but the WRONG thing for station ticks,
    labels and panel rules — 24 ticks per plate is noise, not information. So
    the caller passes the original layers here and the annotation is drawn
    from them while the segments still drive the distribution.
    """

    x0: float
    x1: float
    kind: str
    index: int          # 1-based plate number, 0 for a gap
    P: float


def joint_diagram_svg(a: BoltAnalysis,
                      groups: list[Group] | None = None) -> str:
    """Build the three-panel figure for one analysis.

    Left panel is the joint elevation — bolt, head and nut, plates and
    spacers, and each plate's bearing intensity drawn as a block whose width
    is proportional to |w| = |P/t| against the largest in the stack. Centre
    and right panels are V(x) and M(x) on the same vertical station axis.

    Args:
        a: Result of `library.bolt_bending.analyse()`.
        groups: Optional physical layers, when `a`'s segments are subdivisions
            of them (the refined bearing view). Station ticks, plate labels
            and panel rules are drawn from these instead of from every
            segment. Omit for the baseline, where segments ARE the layers.

    Returns:
        A complete `<svg>...</svg>` string, scaling to its container. Render it
        with `st.markdown(..., unsafe_allow_html=True)` — **not** `st.html()`,
        which sanitises with an HTML-only profile and drops SVG silently.
        `svg_document()` wraps it as a standalone page for writing to a file.
    """
    c = BOLT_PALETTE
    out: list[str] = []

    if groups is None:
        n = 0
        groups = []
        for sg in a.segments:
            if sg.kind == "plate":
                n += 1
            groups.append(Group(sg.x0, sg.x1, sg.kind,
                                n if sg.kind == "plate" else 0, sg.P))

    if a.L <= 0 or not a.stations:
        out.append(_text(24, 90, "Add a layer with thickness to see the diagrams.",
                         font_size=14))
        return _svg("".join(out))

    def sy(x: float) -> float:
        """Station (in) to y (user units). Shared by all three panels."""
        return TOP + BAND_H * x / a.L

    out.append(_text(CX, 30, "Joint and bearing", text_anchor="middle",
                     font_size=12, fill=c["ink"], font_weight=500))

    # ── bolt, head, nut ───────────────────────────────────────────────
    out.append(_el("line", x1=CX, y1=TOP - 34, x2=CX, y2=BOT + 34,
                   stroke=c["ink"], stroke_width=1,
                   stroke_dasharray="7 4", opacity=0.3))
    out.append(_el("rect", x=CX - BW / 2, y=TOP, width=BW, height=BAND_H,
                   fill=c["bolt_fill"], stroke=c["ink"], stroke_width=1))
    for y, label in ((TOP - 17, "head"), (BOT, "nut")):
        out.append(_el("rect", x=CX - BW / 2 - 11, y=y, width=BW + 22, height=17,
                       fill=c["cap_fill"], stroke=c["ink"], stroke_width=1))
        out.append(_text(CX - BW / 2 - 16, y + 12, label, text_anchor="end"))

    # ── plates, spacers, bearing intensity ────────────────────────────
    # Bodies, spacers and labels are drawn per GROUP (the physical layers);
    # the bearing blocks are drawn per SEGMENT, so a subdivided plate shows
    # its varying distribution instead of one averaged block.
    w_max = max((abs(sg.P / sg.t) for sg in a.segments
                 if sg.kind == "plate" and sg.t > 0), default=0.0)

    # Every layer is drawn to its FULL width, both sides of the bolt — a plate
    # exists on both sides of its hole, and showing only the bearing side made
    # the stack read as a set of half-plates. The two sides are distinguished
    # by weight rather than by presence: the bearing side is solid and carries
    # the bearing block and its arrows, the unloaded side is pale and carries
    # the load-direction arrow and the labels. That also stops the labels
    # competing with the bearing graphics for the same space.
    for g in groups:
        y0, h = sy(g.x0), sy(g.x1) - sy(g.x0)
        if h <= 0:
            continue
        if g.kind == "gap":
            # Full width too, so a spacer reads as the same kind of object as
            # a plate rather than a narrow band floating on the bolt.
            # Lightened now that it spans the full width: at the old density
            # a full-width hatch was the heaviest thing in the stack, which
            # reads as importance when a spacer is the one layer that carries
            # nothing. Wider spacing, lower opacity — present but inert.
            out.append(_hatch_band(CX - BW / 2 - PL, y0, BW + 2 * PL, h,
                                   spacing=9.0, opacity=0.45))
            if h >= 12:
                # Kept INSIDE the band — just outside it would land on the
                # shear panel at PANEL_V_X. A backing rect stops the hatching
                # running through the lettering.
                lx = CX + BW / 2 + PL - 7
                out.append(_el("rect", x=lx - 42, y=y0 + h / 2 - 8,
                               width=46, height=15, fill=c["background"],
                               fill_opacity=0.85, stroke="none"))
                out.append(_text(lx, y0 + h / 2 + 4, "spacer",
                                 text_anchor="end"))
            continue
        loaded = -1 if g.P >= 0 else 1   # side the plate bears against the bolt
        for s_ in (loaded, -loaded):
            strong = s_ == loaded
            out.append(_el(
                "rect", x=min(CX + s_ * BW / 2, CX + s_ * (BW / 2 + PL)),
                y=y0, width=PL, height=h, fill=c["plate_fill"],
                fill_opacity=1.0 if strong else 0.38,
                stroke=c["ink"], stroke_width=1,
                stroke_opacity=1.0 if strong else 0.35))

    for sg in a.segments:
        if sg.kind != "plate" or sg.t <= 0:
            continue
        y0, h = sy(sg.x0), sy(sg.x1) - sy(sg.x0)
        if h <= 0:
            continue
        w = sg.P / sg.t
        side = -1 if sg.P >= 0 else 1
        x_in = CX + side * BW / 2        # face bearing on the bolt
        bw = BEARING_W * abs(w) / w_max if w_max > 0 else 0.0
        if bw <= 1.5:
            continue
        out.append(_el("rect", x=min(x_in, x_in + side * bw), y=y0,
                       width=bw, height=h, fill=c["shear"], opacity=0.17))
        out.append(_el("line", x1=x_in + side * bw, y1=y0,
                       x2=x_in + side * bw, y2=y0 + h,
                       stroke=c["shear"], stroke_width=1.6))
        n = max(1, min(7, round(h / 13)))
        for k in range(n):
            ay = y0 + h * (k + 0.5) / n
            tail, head = x_in + side * bw, x_in
            out.append(_el(
                "path",
                d=(f"M{tail} {ay} H{head} "
                   f"M{head - side * 6} {ay - 4} L{head} {ay} "
                   f"L{head - side * 6} {ay + 4}"),
                stroke=c["shear"], stroke_width=1.3, fill="none",
                stroke_linecap="round", stroke_linejoin="round"))

    # ── unloaded side: load direction and labels ──────────────────────
    # Both live on the pale side, where nothing else is drawn. The direction
    # arrow shows the EXTERNAL load on the layer — the load entered in the
    # sidebar — which acts in the same sense as that layer's bearing arrows
    # and therefore always points outward from the bolt on this side. The
    # label carries the entered load rather than the intensity P/t: the
    # intensity is already shown graphically by the bearing block's width,
    # whereas the total is what was typed, so the figure doubles as a check
    # on data entry.
    for g in groups:
        if g.kind != "plate":
            continue
        y0, h = sy(g.x0), sy(g.x1) - sy(g.x0)
        if h <= 0:
            continue
        quiet = 1 if g.P >= 0 else -1    # opposite the bearing side
        anchor = "end" if quiet > 0 else "start"
        lx = CX + quiet * (BW / 2 + PL) - quiet * 7

        if h >= 18:
            ax0 = CX + quiet * (BW / 2 + 10)
            ax1 = ax0 + quiet * 30
            ay = y0 + h / 2
            out.append(_el(
                "path",
                d=(f"M{ax0} {ay} H{ax1} "
                   f"M{ax1 - quiet * 7} {ay - 4.5} L{ax1} {ay} "
                   f"L{ax1 - quiet * 7} {ay + 4.5}"),
                stroke=c["ink"], stroke_width=1.4, fill="none",
                stroke_opacity=0.55,
                stroke_linecap="round", stroke_linejoin="round"))

        if h >= 30:
            out.append(_text(lx, y0 + h / 2 - 2, f"plate {g.index}",
                             text_anchor=anchor))
            out.append(_text(lx, y0 + h / 2 + 12, f"{sig(g.P)} lbf",
                             text_anchor=anchor, font_size=10.5,
                             opacity=0.72))
        elif h >= 13:
            out.append(_text(lx, y0 + h / 2 + 4, f"plate {g.index}",
                             text_anchor=anchor))

    # ── head and nut reactions ────────────────────────────────────────
    # These are the R_0 / R_L pair that closes the residual moment. They are
    # drawn as lateral arrows because that IS what the model applies — it is
    # why V(0) = R_0 ≠ 0 in the shear panel — but the shafts are DASHED to
    # mark them as a statically equivalent idealisation rather than a contact
    # force. A solid arrow pushing sideways on the head reads as the head
    # bearing sideways, which it cannot do: nothing at the underside of a head
    # has a surface to push against. The couple is really supplied by clamp
    # pressure shifting across the head and nut undersides. See the caption,
    # kernel.py "Closing the residual moment", and Method §3.
    for y, R, tag in ((TOP - 30, a.R0, "R₀"), (BOT + 32, a.RL, "Rₗ")):
        if abs(R) < 0.5:
            continue
        s_ = 1 if R >= 0 else -1
        x0 = CX + s_ * (BW / 2 + 6)
        x1 = x0 + s_ * 46
        out.append(_el(
            "path", d=f"M{x0} {y} H{x1}",
            stroke=c["moment"], stroke_width=1.5, fill="none",
            stroke_dasharray="4 3", stroke_linecap="round"))
        out.append(_el(
            "path",
            d=f"M{x1 - s_ * 7} {y - 4} L{x1} {y} L{x1 - s_ * 7} {y + 4}",
            stroke=c["moment"], stroke_width=1.5, fill="none",
            stroke_linecap="round", stroke_linejoin="round"))
        out.append(_text(x1 + s_ * 6, y + 4, f"{tag} {whole(abs(R))} lbf",
                         text_anchor="start" if s_ > 0 else "end",
                         fill=c["moment"], font_size=10.5))

    # ── station scale ─────────────────────────────────────────────────
    last_y = [-99.0]     # list so the closure can write to it

    def station_tick(x: float, label: str) -> None:
        y = sy(x)
        if abs(y - last_y[0]) < 12:
            return
        last_y[0] = y
        out.append(_el("line", x1=CX - BW / 2 - PL - 6, y1=y,
                       x2=CX - BW / 2 - PL, y2=y,
                       stroke=c["ink"], stroke_width=1, opacity=0.5))
        out.append(_text(CX - BW / 2 - PL - 10, y + 4, label, text_anchor="end"))

    station_tick(0, "0")
    for g in groups:
        if 1e-9 < g.x1 < a.L - 1e-9:
            station_tick(g.x1, fmt(g.x1, 3))
    last_y[0] = -99.0            # the nut label always wins its slot
    station_tick(a.L, fmt(a.L, 3))

    out.append(
        f'<text transform="translate(18,{(TOP + BOT) / 2}) rotate(-90)" '
        f'text-anchor="middle" font-size="11.5" fill="{c["muted"]}">'
        f"Distance along bolt from head, in</text>"
    )

    # ── shear and moment panels, sharing the station axis ─────────────
    panels = (
        ("V", PANEL_V_X, c["shear"], "Shear V, lbf"),
        ("M", PANEL_M_X, c["moment"], "Moment M, in·lbf"),
    )
    for key, x0p, color, label in panels:
        vals = [getattr(q, key) for q in a.stations]
        lo, hi = min(0.0, *vals), max(0.0, *vals)
        if hi - lo < 1e-9:
            lo, hi = -1.0, 1.0
        pad = (hi - lo) * 0.16
        hi, lo = hi + pad, lo - pad

        def px(v: float, _x0=x0p, _lo=lo, _hi=hi) -> float:
            return _x0 + PANEL_W * (v - _lo) / (_hi - _lo)

        out.append(_text(x0p + PANEL_W / 2, 30, label, text_anchor="middle",
                         font_size=12, fill=color, font_weight=500))

        # gap bands, segment rules, frame, zero line
        for g in groups:
            if g.kind == "gap" and g.x1 > g.x0:
                out.append(_el("rect", x=x0p, y=sy(g.x0), width=PANEL_W,
                               height=sy(g.x1) - sy(g.x0),
                               fill=c["ink"], opacity=0.05))
        for g in groups:
            if g.x0 > 0:
                out.append(_el("line", x1=x0p, y1=sy(g.x0), x2=x0p + PANEL_W,
                               y2=sy(g.x0), stroke=c["rule"], stroke_width=1))
        for y in (TOP, BOT):
            out.append(_el("line", x1=x0p, y1=y, x2=x0p + PANEL_W, y2=y,
                           stroke=c["ink"], stroke_width=1))
        out.append(_el("line", x1=px(0), y1=TOP, x2=px(0), y2=BOT,
                       stroke=c["ink"], stroke_width=1, opacity=0.55))

        # Axis ticks at the two data extremes plus zero. The extremes go down
        # first because they carry the scale; zero is dropped if it would
        # overprint one of them, which happens whenever a diagram barely
        # crosses zero (the default stack dips to M = -0.4 against a 278.7
        # peak, so its "-0.400" and "0" labels land on the same pixel). The
        # zero line itself is already drawn, so losing its label costs little.
        span = hi - lo
        placed: list[float] = []
        for v in (lo + pad, hi - pad, 0.0):
            v = 0.0 if abs(v) < span * 1e-9 else v
            if any(abs(px(v) - px(u)) < TICK_MIN_SEP for u in placed):
                continue
            placed.append(v)
        for v in sorted(placed):
            out.append(_el("line", x1=px(v), y1=BOT, x2=px(v), y2=BOT + 4,
                           stroke=c["ink"], stroke_width=1, opacity=0.6))
            out.append(_text(px(v), BOT + 17, sig(v), text_anchor="middle"))

        # filled area then the curve on top
        fill_d = [f"M{px(0)} {sy(a.stations[0].x)}"]
        fill_d += [f" L{px(getattr(q, key))} {sy(q.x)}" for q in a.stations]
        fill_d.append(f" L{px(0)} {sy(a.stations[-1].x)} Z")
        out.append(_el("path", d="".join(fill_d), fill=color, opacity=0.13))

        line_d = [f"M{px(getattr(a.stations[0], key))} {sy(a.stations[0].x)}"]
        line_d += [f" L{px(getattr(q, key))} {sy(q.x)}" for q in a.stations[1:]]
        out.append(_el("path", d="".join(line_d), fill="none", stroke=color,
                       stroke_width=2, stroke_linejoin="round"))

        if key == "M" and abs(a.M_max.M) > 1e-9:
            s2 = 1 if a.M_max.M >= 0 else -1
            out.append(_el("circle", cx=px(a.M_max.M), cy=sy(a.M_max.x), r=4,
                           fill=color))
            out.append(_text(px(a.M_max.M) + s2 * 8, sy(a.M_max.x) - 8,
                             sig(a.M_max.M),
                             text_anchor="start" if s2 > 0 else "end",
                             fill=color, font_size=12, font_weight=500))

    # Caption block. Lines are broken by hand and kept under ~125 characters:
    # at font-size 11 the drawable width is about 750 user units, or ~135
    # characters, and an over-long line is silently clipped at the viewBox
    # edge rather than wrapping. Bump VIEW_H if a line is added.
    caption = [
        "Shaded blocks are bearing intensity P/t on the bearing side. The pale "
        "half is the unloaded side; its arrow is that layer's load.",
    ]
    if abs(a.R0) >= 0.5:
        # The arrows are FORCES (lbf); their MOMENT closes the residual
        # (lb·in). An earlier caption called the pair itself "a couple of N
        # lb·in", which conflates a force pair with its moment and put two
        # units on one object. R·L is given symbolically because the displayed
        # R is rounded to whole lbf and would not multiply out to the stated
        # moment on the page.
        caption += [
            f"Dashed R₀ and Rₗ are equal and opposite forces of "
            f"{whole(abs(a.R0))} lbf, L apart. They add no net force.",
            f"Only their moment, R·L = {whole(abs(a.moment_residual))} lb·in, "
            f"closes the diagram — not sideways bearing on the head. Method §3.",
        ]
    for i, line in enumerate(caption):
        out.append(_text(CX - BW / 2 - PL, BOT + 72 + i * 16, line,
                         font_size=11, opacity=1.0 if i == 0 else 0.78))

    return _svg("".join(out))

    def sy(x: float) -> float:
        """Station (in) to y (user units). Shared by all three panels."""
        return TOP + BAND_H * x / a.L

    out.append(_text(CX, 30, "Joint and bearing", text_anchor="middle",
                     font_size=12, fill=c["ink"], font_weight=500))

    # ── bolt, head, nut ───────────────────────────────────────────────
    out.append(_el("line", x1=CX, y1=TOP - 34, x2=CX, y2=BOT + 34,
                   stroke=c["ink"], stroke_width=1,
                   stroke_dasharray="7 4", opacity=0.3))
    out.append(_el("rect", x=CX - BW / 2, y=TOP, width=BW, height=BAND_H,
                   fill=c["bolt_fill"], stroke=c["ink"], stroke_width=1))
    for y, label in ((TOP - 17, "head"), (BOT, "nut")):
        out.append(_el("rect", x=CX - BW / 2 - 11, y=y, width=BW + 22, height=17,
                       fill=c["cap_fill"], stroke=c["ink"], stroke_width=1))
        out.append(_text(CX - BW / 2 - 16, y + 12, label, text_anchor="end"))

    # ── plates, spacers, bearing intensity ────────────────────────────
    # Bodies, spacers and labels are drawn per GROUP (the physical layers);
    # the bearing blocks are drawn per SEGMENT, so a subdivided plate shows
    # its varying distribution instead of one averaged block.
    w_max = max((abs(sg.P / sg.t) for sg in a.segments
                 if sg.kind == "plate" and sg.t > 0), default=0.0)

    # Every layer is drawn to its FULL width, both sides of the bolt — a plate
    # exists on both sides of its hole, and showing only the bearing side made
    # the stack read as a set of half-plates. The two sides are distinguished
    # by weight rather than by presence: the bearing side is solid and carries
    # the bearing block and its arrows, the unloaded side is pale and carries
    # the load-direction arrow and the labels. That also stops the labels
    # competing with the bearing graphics for the same space.
    for g in groups:
        y0, h = sy(g.x0), sy(g.x1) - sy(g.x0)
        if h <= 0:
            continue
        if g.kind == "gap":
            # Full width too, so a spacer reads as the same kind of object as
            # a plate rather than a narrow band floating on the bolt.
            # Lightened now that it spans the full width: at the old density
            # a full-width hatch was the heaviest thing in the stack, which
            # reads as importance when a spacer is the one layer that carries
            # nothing. Wider spacing, lower opacity — present but inert.
            out.append(_hatch_band(CX - BW / 2 - PL, y0, BW + 2 * PL, h,
                                   spacing=9.0, opacity=0.45))
            if h >= 12:
                # Kept INSIDE the band — just outside it would land on the
                # shear panel at PANEL_V_X. A backing rect stops the hatching
                # running through the lettering.
                lx = CX + BW / 2 + PL - 7
                out.append(_el("rect", x=lx - 42, y=y0 + h / 2 - 8,
                               width=46, height=15, fill=c["background"],
                               fill_opacity=0.85, stroke="none"))
                out.append(_text(lx, y0 + h / 2 + 4, "spacer",
                                 text_anchor="end"))
            continue
        loaded = -1 if g.P >= 0 else 1   # side the plate bears against the bolt
        for s_ in (loaded, -loaded):
            strong = s_ == loaded
            out.append(_el(
                "rect", x=min(CX + s_ * BW / 2, CX + s_ * (BW / 2 + PL)),
                y=y0, width=PL, height=h, fill=c["plate_fill"],
                fill_opacity=1.0 if strong else 0.38,
                stroke=c["ink"], stroke_width=1,
                stroke_opacity=1.0 if strong else 0.35))

    for sg in a.segments:
        if sg.kind != "plate" or sg.t <= 0:
            continue
        y0, h = sy(sg.x0), sy(sg.x1) - sy(sg.x0)
        if h <= 0:
            continue
        w = sg.P / sg.t
        side = -1 if sg.P >= 0 else 1
        x_in = CX + side * BW / 2        # face bearing on the bolt
        bw = BEARING_W * abs(w) / w_max if w_max > 0 else 0.0
        if bw <= 1.5:
            continue
        out.append(_el("rect", x=min(x_in, x_in + side * bw), y=y0,
                       width=bw, height=h, fill=c["shear"], opacity=0.17))
        out.append(_el("line", x1=x_in + side * bw, y1=y0,
                       x2=x_in + side * bw, y2=y0 + h,
                       stroke=c["shear"], stroke_width=1.6))
        n = max(1, min(7, round(h / 13)))
        for k in range(n):
            ay = y0 + h * (k + 0.5) / n
            tail, head = x_in + side * bw, x_in
            out.append(_el(
                "path",
                d=(f"M{tail} {ay} H{head} "
                   f"M{head - side * 6} {ay - 4} L{head} {ay} "
                   f"L{head - side * 6} {ay + 4}"),
                stroke=c["shear"], stroke_width=1.3, fill="none",
                stroke_linecap="round", stroke_linejoin="round"))

    # ── unloaded side: load direction and labels ──────────────────────
    # Both live on the pale side, where nothing else is drawn. The direction
    # arrow shows the EXTERNAL load on the layer — the load entered in the
    # sidebar — which acts in the same sense as that layer's bearing arrows
    # and therefore always points outward from the bolt on this side. The
    # label carries the entered load rather than the intensity P/t: the
    # intensity is already shown graphically by the bearing block's width,
    # whereas the total is what was typed, so the figure doubles as a check
    # on data entry.
    for g in groups:
        if g.kind != "plate":
            continue
        y0, h = sy(g.x0), sy(g.x1) - sy(g.x0)
        if h <= 0:
            continue
        quiet = 1 if g.P >= 0 else -1    # opposite the bearing side
        anchor = "end" if quiet > 0 else "start"
        lx = CX + quiet * (BW / 2 + PL) - quiet * 7

        if h >= 18:
            ax0 = CX + quiet * (BW / 2 + 10)
            ax1 = ax0 + quiet * 30
            ay = y0 + h / 2
            out.append(_el(
                "path",
                d=(f"M{ax0} {ay} H{ax1} "
                   f"M{ax1 - quiet * 7} {ay - 4.5} L{ax1} {ay} "
                   f"L{ax1 - quiet * 7} {ay + 4.5}"),
                stroke=c["ink"], stroke_width=1.4, fill="none",
                stroke_opacity=0.55,
                stroke_linecap="round", stroke_linejoin="round"))

        if h >= 30:
            out.append(_text(lx, y0 + h / 2 - 2, f"plate {g.index}",
                             text_anchor=anchor))
            out.append(_text(lx, y0 + h / 2 + 12, f"{sig(g.P)} lbf",
                             text_anchor=anchor, font_size=10.5,
                             opacity=0.72))
        elif h >= 13:
            out.append(_text(lx, y0 + h / 2 + 4, f"plate {g.index}",
                             text_anchor=anchor))

    # ── head and nut reactions ────────────────────────────────────────
    # These are the R_0 / R_L pair that closes the residual moment. They are
    # drawn as lateral arrows because that IS what the model applies — it is
    # why V(0) = R_0 ≠ 0 in the shear panel — but the shafts are DASHED to
    # mark them as a statically equivalent idealisation rather than a contact
    # force. A solid arrow pushing sideways on the head reads as the head
    # bearing sideways, which it cannot do: nothing at the underside of a head
    # has a surface to push against. The couple is really supplied by clamp
    # pressure shifting across the head and nut undersides. See the caption,
    # kernel.py "Closing the residual moment", and Method §3.
    for y, R, tag in ((TOP - 30, a.R0, "R₀"), (BOT + 32, a.RL, "Rₗ")):
        if abs(R) < 0.5:
            continue
        s_ = 1 if R >= 0 else -1
        x0 = CX + s_ * (BW / 2 + 6)
        x1 = x0 + s_ * 46
        out.append(_el(
            "path", d=f"M{x0} {y} H{x1}",
            stroke=c["moment"], stroke_width=1.5, fill="none",
            stroke_dasharray="4 3", stroke_linecap="round"))
        out.append(_el(
            "path",
            d=f"M{x1 - s_ * 7} {y - 4} L{x1} {y} L{x1 - s_ * 7} {y + 4}",
            stroke=c["moment"], stroke_width=1.5, fill="none",
            stroke_linecap="round", stroke_linejoin="round"))
        out.append(_text(x1 + s_ * 6, y + 4, f"{tag} {whole(abs(R))} lbf",
                         text_anchor="start" if s_ > 0 else "end",
                         fill=c["moment"], font_size=10.5))

    # ── station scale ─────────────────────────────────────────────────
    last_y = [-99.0]     # list so the closure can write to it

    def station_tick(x: float, label: str) -> None:
        y = sy(x)
        if abs(y - last_y[0]) < 12:
            return
        last_y[0] = y
        out.append(_el("line", x1=CX - BW / 2 - PL - 6, y1=y,
                       x2=CX - BW / 2 - PL, y2=y,
                       stroke=c["ink"], stroke_width=1, opacity=0.5))
        out.append(_text(CX - BW / 2 - PL - 10, y + 4, label, text_anchor="end"))

    station_tick(0, "0")
    for g in groups:
        if 1e-9 < g.x1 < a.L - 1e-9:
            station_tick(g.x1, fmt(g.x1, 3))
    last_y[0] = -99.0            # the nut label always wins its slot
    station_tick(a.L, fmt(a.L, 3))

    out.append(
        f'<text transform="translate(18,{(TOP + BOT) / 2}) rotate(-90)" '
        f'text-anchor="middle" font-size="11.5" fill="{c["muted"]}">'
        f"Distance along bolt from head, in</text>"
    )

    # ── shear and moment panels, sharing the station axis ─────────────
    panels = (
        ("V", PANEL_V_X, c["shear"], "Shear V, lbf"),
        ("M", PANEL_M_X, c["moment"], "Moment M, in·lbf"),
    )
    for key, x0p, color, label in panels:
        vals = [getattr(q, key) for q in a.stations]
        lo, hi = min(0.0, *vals), max(0.0, *vals)
        if hi - lo < 1e-9:
            lo, hi = -1.0, 1.0
        pad = (hi - lo) * 0.16
        hi, lo = hi + pad, lo - pad

        def px(v: float, _x0=x0p, _lo=lo, _hi=hi) -> float:
            return _x0 + PANEL_W * (v - _lo) / (_hi - _lo)

        out.append(_text(x0p + PANEL_W / 2, 30, label, text_anchor="middle",
                         font_size=12, fill=color, font_weight=500))

        # gap bands, segment rules, frame, zero line
        for g in groups:
            if g.kind == "gap" and g.x1 > g.x0:
                out.append(_el("rect", x=x0p, y=sy(g.x0), width=PANEL_W,
                               height=sy(g.x1) - sy(g.x0),
                               fill=c["ink"], opacity=0.05))
        for g in groups:
            if g.x0 > 0:
                out.append(_el("line", x1=x0p, y1=sy(g.x0), x2=x0p + PANEL_W,
                               y2=sy(g.x0), stroke=c["rule"], stroke_width=1))
        for y in (TOP, BOT):
            out.append(_el("line", x1=x0p, y1=y, x2=x0p + PANEL_W, y2=y,
                           stroke=c["ink"], stroke_width=1))
        out.append(_el("line", x1=px(0), y1=TOP, x2=px(0), y2=BOT,
                       stroke=c["ink"], stroke_width=1, opacity=0.55))

        # Axis ticks at the two data extremes plus zero. The extremes go down
        # first because they carry the scale; zero is dropped if it would
        # overprint one of them, which happens whenever a diagram barely
        # crosses zero (the default stack dips to M = -0.4 against a 278.7
        # peak, so its "-0.400" and "0" labels land on the same pixel). The
        # zero line itself is already drawn, so losing its label costs little.
        span = hi - lo
        placed: list[float] = []
        for v in (lo + pad, hi - pad, 0.0):
            v = 0.0 if abs(v) < span * 1e-9 else v
            if any(abs(px(v) - px(u)) < TICK_MIN_SEP for u in placed):
                continue
            placed.append(v)
        for v in sorted(placed):
            out.append(_el("line", x1=px(v), y1=BOT, x2=px(v), y2=BOT + 4,
                           stroke=c["ink"], stroke_width=1, opacity=0.6))
            out.append(_text(px(v), BOT + 17, sig(v), text_anchor="middle"))

        # filled area then the curve on top
        fill_d = [f"M{px(0)} {sy(a.stations[0].x)}"]
        fill_d += [f" L{px(getattr(q, key))} {sy(q.x)}" for q in a.stations]
        fill_d.append(f" L{px(0)} {sy(a.stations[-1].x)} Z")
        out.append(_el("path", d="".join(fill_d), fill=color, opacity=0.13))

        line_d = [f"M{px(getattr(a.stations[0], key))} {sy(a.stations[0].x)}"]
        line_d += [f" L{px(getattr(q, key))} {sy(q.x)}" for q in a.stations[1:]]
        out.append(_el("path", d="".join(line_d), fill="none", stroke=color,
                       stroke_width=2, stroke_linejoin="round"))

        if key == "M" and abs(a.M_max.M) > 1e-9:
            s2 = 1 if a.M_max.M >= 0 else -1
            out.append(_el("circle", cx=px(a.M_max.M), cy=sy(a.M_max.x), r=4,
                           fill=color))
            out.append(_text(px(a.M_max.M) + s2 * 8, sy(a.M_max.x) - 8,
                             sig(a.M_max.M),
                             text_anchor="start" if s2 > 0 else "end",
                             fill=color, font_size=12, font_weight=500))

    out.append(_text(
        CX - BW / 2 - PL, BOT + 72,
        "Shaded blocks are bearing intensity P/t, on the side each layer bears "
        "against. The pale half is the unloaded side; its arrow is the load "
        "applied to that layer.",
        font_size=11))

    # Say what the dashed pair is, right where it is drawn. Without this the
    # arrows read as the head and nut bearing sideways.
    #
    # The arrows are FORCES (lbf); their MOMENT is what closes the residual
    # (lb·in). An earlier caption said the pair "are one couple of N lb·in",
    # which conflates a pair of forces with its moment and left the figure
    # labelling the same thing in two different units. State both quantities
    # and the relation between them, and give R·L symbolically rather than
    # numerically — the displayed R is rounded to whole lbf, so spelling out
    # the multiplication would not visibly come to the stated moment.
    if abs(a.R0) >= 0.5:
        out.append(_text(
            CX - BW / 2 - PL, BOT + 88,
            f"Dashed R₀ and Rₗ are equal and opposite forces of "
            f"{whole(abs(a.R0))} lbf, L apart. They add no net force — only "
            f"their moment, R·L = {whole(abs(a.moment_residual))} lb·in, which "
            f"closes the diagram. Not sideways bearing on the head; Method §3.",
            font_size=11, opacity=0.78))

    return _svg("".join(out))


def _svg(body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VIEW_W} {VIEW_H}" '
        f'preserveAspectRatio="xMidYMid meet" role="img" '
        f'style="width:100%;height:auto;display:block" '
        f'aria-label="Joint elevation with bearing distribution, and shear and '
        f'moment diagrams along the bolt" '
        f'font-family="IBM Plex Sans, ui-sans-serif, -apple-system, Segoe UI, '
        f'Roboto, sans-serif">{body}</svg>'
    )


def svg_document(svg: str) -> str:
    """Wrap an SVG as a standalone HTML page.

    Not used by the Streamlit page, which renders the SVG inline. This is for
    writing the figure to a file — a report attachment, or a visual diff
    against the archived original tool.
    """
    c = BOLT_PALETTE
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>"
        f"html,body{{margin:0;padding:0;height:100%;background:{c['background']};}}"
        "body{display:flex;align-items:center;justify-content:center;}"
        "svg{width:100%;height:100%;display:block;}"
        "</style></head><body>" + svg + "</body></html>"
    )
