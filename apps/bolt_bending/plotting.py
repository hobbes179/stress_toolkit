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
from xml.sax.saxutils import escape

from library.bolt_bending.kernel import BoltAnalysis
from ui.theme import BOLT_PALETTE

# ── Canvas geometry (user units; the SVG scales to its container) ─────────
VIEW_W, VIEW_H = 820, 552
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
                spacing: float = 6.0) -> str:
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
                 stroke=c["ink"], stroke_width=1)]

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
                         stroke=c["hatch_line"], stroke_width=1.4))
    return "".join(parts)


def joint_diagram_svg(a: BoltAnalysis) -> str:
    """Build the three-panel figure for one analysis.

    Left panel is the joint elevation — bolt, head and nut, plates and
    spacers, and each plate's bearing intensity drawn as a block whose width
    is proportional to |w| = |P/t| against the largest in the stack. Centre
    and right panels are V(x) and M(x) on the same vertical station axis.

    Args:
        a: Result of `library.bolt_bending.analyse()`.

    Returns:
        A complete `<svg>...</svg>` string, scaling to its container. Render it
        with `st.markdown(..., unsafe_allow_html=True)` — **not** `st.html()`,
        which sanitises with an HTML-only profile and drops SVG silently.
        `svg_document()` wraps it as a standalone page for writing to a file.
    """
    c = BOLT_PALETTE
    out: list[str] = []

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
    w_max = max((abs(s.P / s.t) for s in a.segments
                 if s.kind == "plate" and s.t > 0), default=0.0)

    plate_i = 0
    for s in a.segments:
        y0 = sy(s.x0)
        h = sy(s.x1) - y0
        if h <= 0:
            continue

        if s.kind == "gap":
            out.append(_hatch_band(CX - BW / 2 - 32, y0, BW + 64, h))
            if h >= 12:
                out.append(_text(CX + BW / 2 + 38, y0 + h / 2 + 4, "spacer"))
            continue

        plate_i += 1
        w = s.P / s.t
        side = -1 if s.P >= 0 else 1     # plate body sits opposite the load it applies
        x_in = CX + side * BW / 2        # face bearing on the bolt
        x_out = x_in + side * PL

        out.append(_el("rect", x=min(x_in, x_out), y=y0, width=PL, height=h,
                       fill=c["plate_fill"], stroke=c["ink"], stroke_width=1))

        # bearing block, width proportional to intensity w = P/t
        bw = BEARING_W * abs(w) / w_max if w_max > 0 else 0.0
        if bw > 1.5:
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

        anchor = "start" if side < 0 else "end"
        lx = x_out - side * 7
        if h >= 30:
            out.append(_text(lx, y0 + h / 2 - 2, f"plate {plate_i}",
                             text_anchor=anchor))
            out.append(_text(lx, y0 + h / 2 + 12, f"{sig(w)} lbf/in",
                             text_anchor=anchor, font_size=10.5, opacity=0.72))
        elif h >= 13:
            out.append(_text(lx, y0 + h / 2 + 4, f"plate {plate_i}",
                             text_anchor=anchor))

    # ── head and nut reactions ────────────────────────────────────────
    for y, R in ((TOP - 30, a.R0), (BOT + 32, a.RL)):
        if abs(R) < 0.5:
            continue
        s_ = 1 if R >= 0 else -1
        x0 = CX + s_ * (BW / 2 + 6)
        x1 = x0 + s_ * 46
        out.append(_el(
            "path",
            d=(f"M{x0} {y} H{x1} "
               f"M{x1 - s_ * 7} {y - 4} L{x1} {y} L{x1 - s_ * 7} {y + 4}"),
            stroke=c["moment"], stroke_width=1.5, fill="none",
            stroke_linecap="round", stroke_linejoin="round"))
        out.append(_text(x1 + s_ * 6, y + 4, f"{sig(abs(R))} lbf",
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
    for s in a.segments:
        if 1e-9 < s.x1 < a.L - 1e-9:
            station_tick(s.x1, fmt(s.x1, 3))
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
        for s in a.segments:
            if s.kind == "gap" and s.x1 > s.x0:
                out.append(_el("rect", x=x0p, y=sy(s.x0), width=PANEL_W,
                               height=sy(s.x1) - sy(s.x0),
                               fill=c["ink"], opacity=0.05))
        for s in a.segments:
            if s.x0 > 0:
                out.append(_el("line", x1=x0p, y1=sy(s.x0), x2=x0p + PANEL_W,
                               y2=sy(s.x0), stroke=c["rule"], stroke_width=1))
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
        "Shaded blocks are bearing intensity P/t. Positive load acts to the right.",
        font_size=11))

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
