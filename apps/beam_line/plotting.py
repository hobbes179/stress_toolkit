"""
apps/beam_line/plotting.py

The beam elevation and the shear / moment / deflection diagrams, as a
hand-built SVG string. No Streamlit imports -- `figure_svg()` is pure and
takes the model plus its solution, so it can be rendered to a file, a page,
or a test.

Why SVG and not matplotlib
--------------------------
Same reason as the bolt module: the top panel is a schematic elevation, not a
plot of a function, and it has to share an x axis with three real plots below
it. Matplotlib can be made to do that, but the support symbols, the load
arrows and the reaction callouts are all hand-placed anyway, so there is
nothing left for it to contribute.

Unlike the bolt figure, the horizontal axis here IS dimensionally true -- it
is the span, and every station on every panel lines up with it. Only the
vertical extents are schematic: beam depth, arrow lengths and diagram heights
are pixel values chosen for legibility, not scaled section depths.

NO <defs>, NO url(#id)
----------------------
Arrowheads are explicit polygons and hatching is explicit line segments, not
SVG `<pattern>` or `<marker>` fills. Those need a `<defs>` block plus id
references that survive the page's sanitiser and stay unique against
everything else rendered on the page. The bolt module learned this; the same
rule applies here.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from library.beam_line.diagrams import Diagrams
from library.beam_line.envelope import Envelope
from library.beam_line.model import Beam
from library.beam_line.solver import SolveResult
from ui.theme import BEAM_PALETTE as C

# ---- Canvas geometry (user units; the SVG scales to its container) --------
VIEW_W = 920
LEFT, RIGHT = 74, 30
PLOT_W = VIEW_W - LEFT - RIGHT

ELEV_TOP = 26              # top of the load-arrow zone
BEAM_Y = 112               # beam centreline
BEAM_H = 13                # drawn beam depth
ELEV_BOT = 228             # below the support symbols and reaction labels

PANEL_TITLE_H = 17
PANEL_H = 104              # plot band height per diagram panel
PANEL_GAP = 30             # room for the panel title and breathing space
AXIS_H = 34                # station axis under the last panel

# Minimum horizontal gap between two station tick labels, in user units.
TICK_MIN_SEP = 46

# Fraction of the panel half-height the largest value is drawn at, so a peak
# label has room above the curve.
BAND_FILL = 0.86


# ==========================================================================
# Number formatting
# ==========================================================================
def fmt(v: float, dp: int) -> str:
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
    if a >= 0.001:
        return fmt(v, 4)
    return f"{v:.2e}"


def station(v: float) -> str:
    """Station label. Stations are user-entered dimensions, so they keep more
    decimals than a computed force does."""
    if abs(v - round(v)) < 1.0e-9:
        return f"{v:,.0f}"
    return f"{v:,.3f}".rstrip("0").rstrip(".")


# ==========================================================================
# Tiny SVG element builders
# ==========================================================================
def _attrs(d: dict) -> str:
    return " ".join(f'{k}="{v}"' for k, v in d.items())


def _el(tag: str, **kw) -> str:
    return f"<{tag} {_attrs({k.replace('_', '-'): v for k, v in kw.items()})}/>"


def _text(x: float, y: float, s: str, **kw) -> str:
    base = {"x": round(x, 2), "y": round(y, 2), "font-size": 11,
            "fill": C["muted"], "font-family": "inherit"}
    base.update({k.replace("_", "-"): v for k, v in kw.items()})
    return f"<text {_attrs(base)}>{escape(str(s))}</text>"


def _line(x1: float, y1: float, x2: float, y2: float, **kw) -> str:
    base = {"x1": round(x1, 2), "y1": round(y1, 2),
            "x2": round(x2, 2), "y2": round(y2, 2),
            "stroke": C["ink"], "stroke-width": 1}
    base.update({k.replace("_", "-"): v for k, v in kw.items()})
    return f"<line {_attrs(base)}/>"


def _poly(pts: list[tuple[float, float]], **kw) -> str:
    s = " ".join(f"{round(x, 2)},{round(y, 2)}" for x, y in pts)
    base = {"points": s, "fill": "none"}
    base.update({k.replace("_", "-"): v for k, v in kw.items()})
    return f"<polygon {_attrs(base)}/>"


def _polyline(pts: list[tuple[float, float]], **kw) -> str:
    s = " ".join(f"{round(x, 2)},{round(y, 2)}" for x, y in pts)
    base = {"points": s, "fill": "none", "stroke": C["ink"],
            "stroke-width": 1.6, "stroke-linejoin": "round"}
    base.update({k.replace("_", "-"): v for k, v in kw.items()})
    return f"<polyline {_attrs(base)}/>"


def _arrow_v(x: float, y_tail: float, y_head: float, color: str,
             width: float = 1.6, head: float = 7.0) -> str:
    """Vertical arrow with an explicit triangular head at `y_head`."""
    d = 1.0 if y_head > y_tail else -1.0
    shaft_end = y_head - d * head
    out = [_line(x, y_tail, x, shaft_end, stroke=color, stroke_width=width)]
    out.append(_poly([(x, y_head), (x - head * 0.46, shaft_end),
                      (x + head * 0.46, shaft_end)], fill=color))
    return "".join(out)


def _hatch(x: float, y: float, w: float, h: float, spacing: float = 7.0,
           color: str | None = None) -> str:
    """Diagonal hatching inside a rectangle, as explicit clipped segments."""
    col = color or C["support"]
    out = []
    n = int((w + h) / spacing) + 1
    for i in range(n + 1):
        # 45-degree lines, clipped to the box by parameterising the entry and
        # exit edges directly rather than relying on a clip path.
        off = i * spacing
        x1, y1 = x + off, y
        x2, y2 = x, y + off
        if x1 > x + w:
            over = x1 - (x + w)
            x1, y1 = x + w, y + over
        if y2 > y + h:
            over = y2 - (y + h)
            x2, y2 = x + over, y + h
        if y1 > y + h or x2 > x + w:
            continue
        out.append(_line(x1, y1, x2, y2, stroke=col, stroke_width=0.8,
                         stroke_opacity=0.7))
    return "".join(out)


# ==========================================================================
# The figure
# ==========================================================================
def figure_svg(beam: Beam, sol: SolveResult | None,
               dg: Diagrams | None, ghost: Beam | None = None,
               env: Envelope | None = None) -> str:
    """Full figure. Falls back to the elevation alone when there is no valid
    solution, because the elevation is still the user's own input and hiding
    it would leave them nothing to correct.

    `ghost` carries the supports, loads and hinges the user has switched OFF.
    They are drawn faint and dashed in the elevation rather than omitted: an
    item that vanishes entirely is one you forget you excluded, and this
    figure gets screenshotted into stress reports. The library never sees
    them -- "disabled" is a UI idea, and `beam` is always the real model that
    was solved.

    `env` locks the diagram scales to the envelope of every load combination,
    so switching a load off shrinks the curve instead of rescaling the axis
    under it. Without it each panel is scaled to its own current peak and two
    screenshots of different subsets cannot be compared by eye.
    """
    show_diagrams = bool(dg is not None and dg.valid and dg.pieces)
    n_panels = 3 if show_diagrams else 0
    height = ELEV_BOT + n_panels * (PANEL_H + PANEL_GAP) + (
        AXIS_H if show_diagrams else 12)

    L = beam.L or 1.0

    def X(x: float) -> float:
        return LEFT + (x / L) * PLOT_W

    body: list[str] = [
        _el("rect", x=0, y=0, width=VIEW_W, height=height,
            fill=C["background"]),
    ]

    # Station gridlines run the full height so a peak can be read across
    # panels without a ruler.
    grid_bottom = height - (AXIS_H if show_diagrams else 6)
    for xs in beam.feature_stations():
        body.append(_line(X(xs), ELEV_TOP - 6, X(xs), grid_bottom,
                          stroke=C["rule_soft"], stroke_width=1))

    body.append(_elevation(beam, sol, X, ghost))

    if show_diagrams:
        assert dg is not None
        samp = dg.sample(per_piece=40)
        y0 = ELEV_BOT
        ref_F, ref_M = beam.load_scale()
        panels = [
            ("Shear   V (lb)", samp["V"], C["shear"], "V", 0, ref_F),
            ("Moment   M (lb·in)", samp["M"], C["moment"], "M", 0, ref_M),
            # Deflection has no load-based reference, so only an exact zero
            # counts as degenerate there. A genuinely tiny deflection is a
            # real answer worth plotting.
            ("Deflection   δ (in)", samp["delta"], C["deflect"], "d", 4, 0.0),
        ]
        for i, (title, ys, col, field, dp, zref) in enumerate(panels):
            top = y0 + PANEL_GAP + i * (PANEL_H + PANEL_GAP)
            body.append(_panel(dg, samp["x"], ys, title, col, field, X,
                               top, L, dp, zref, env))
        body.append(_station_axis(beam, X, height - AXIS_H + 14))

    return (f'<svg viewBox="0 0 {VIEW_W} {height}" width="100%" '
            f'role="img" xmlns="http://www.w3.org/2000/svg" '
            f'style="font-family:inherit">{"".join(body)}</svg>')


# --------------------------------------------------------------------------
# Elevation
# --------------------------------------------------------------------------
def _elevation(beam: Beam, sol: SolveResult | None, X,
               ghost: Beam | None = None) -> str:
    out: list[str] = []
    top = BEAM_Y - BEAM_H / 2
    bot = BEAM_Y + BEAM_H / 2

    out.append(_el("rect", x=X(0.0), y=top, width=X(beam.L) - X(0.0),
                   height=BEAM_H, fill=C["beam_fill"],
                   stroke=C["beam_edge"], stroke_width=1.2))

    # Switched-off items go down first, so an active item at the same station
    # draws over its ghost rather than under it. The distributed-load scale is
    # shared between the two layers, or a ghosted 100 lb/in patch would be
    # drawn the same height as an active 1 lb/in one and read as comparable.
    k = _load_scale(beam, ghost)
    if ghost is not None:
        inner = (_distributed(ghost, X, top, k)
                 + _point_loads(ghost, X, top)
                 + _applied_moments(ghost, X, top)
                 + _supports(ghost, X, bot)
                 + _hinges(ghost, X))
        if inner:
            out.append(f'<g opacity="0.3" stroke-dasharray="4 3">{inner}</g>')

    out.append(_distributed(beam, X, top, k))
    out.append(_point_loads(beam, X, top))
    out.append(_applied_moments(beam, X, top))
    out.append(_supports(beam, X, bot))
    out.append(_hinges(beam, X))
    if sol is not None and sol.stable:
        out.append(_reactions(beam, sol, X, bot))

    out.append(_text(LEFT, ELEV_TOP - 12, "Elevation", font_size=11.5,
                     font_weight=600, fill=C["ink"]))
    return "".join(out)


def _load_scale(beam: Beam, ghost: Beam | None = None) -> float:
    """Pixels per unit intensity for the distributed-load profile.

    Taken over the active AND the switched-off patches together so the two
    layers are drawn to one scale and can be compared by eye.
    """
    patches = list(beam.distributed)
    if ghost is not None:
        patches += list(ghost.distributed)
    peak = max((max(abs(d.w1), abs(d.w2)) for d in patches), default=0.0)
    return (46.0 / peak) if peak > 0 else 0.0


def _distributed(beam: Beam, X, beam_top: float,
                 k: float | None = None) -> str:
    """Distributed patches, drawn above the beam with height proportional to
    |w| and arrow direction showing the sign.

    Height is |w| rather than signed w so an upward patch is not drawn
    underneath the support symbols. The arrows and the printed values carry
    the sign, and a patch that changes sign is split at its zero crossing so
    the two halves get opposite arrows.
    """
    if not beam.distributed:
        return ""
    if k is None:
        k = _load_scale(beam)
    out: list[str] = []
    for d in beam.distributed:
        parts = [(d.x1, d.x2, d.w1, d.w2)]
        if d.w1 * d.w2 < 0.0:
            xc = d.x1 + d.length * abs(d.w1) / (abs(d.w1) + abs(d.w2))
            parts = [(d.x1, xc, d.w1, 0.0), (xc, d.x2, 0.0, d.w2)]
        for (xa, xb, wa, wb) in parts:
            ya = beam_top - abs(wa) * k
            yb = beam_top - abs(wb) * k
            out.append(_poly(
                [(X(xa), beam_top), (X(xa), ya), (X(xb), yb),
                 (X(xb), beam_top)],
                fill=C["load"], fill_opacity=0.16,
                stroke=C["load"], stroke_width=1.3))
            sign = wa if abs(wa) >= abs(wb) else wb
            span_px = X(xb) - X(xa)
            n = max(2, min(11, int(span_px / 34)))
            for i in range(n + 1):
                f = i / n
                xx = X(xa) + f * span_px
                yy = ya + f * (yb - ya)
                if abs(yy - beam_top) < 4:
                    continue
                if sign < 0:
                    out.append(_arrow_v(xx, yy, beam_top - 1, C["load"],
                                        width=1.0, head=5.0))
                else:
                    out.append(_arrow_v(xx, beam_top - 1, yy, C["load"],
                                        width=1.0, head=5.0))
        lab = (f"w = {sig(d.w1)}" if abs(d.w1 - d.w2) < 1e-12
               else f"w {sig(d.w1)} → {sig(d.w2)}") + " lb/in"
        ymid = max(beam_top - max(abs(d.w1), abs(d.w2)) * k - 7,
                   ELEV_TOP - 4)
        cx = (X(d.x1) + X(d.x2)) / 2
        # Opaque backing: a point load elsewhere in the same patch draws its
        # arrow straight through this label, and the two are the same colour.
        out.append(_el("rect", x=cx - 3.1 * len(lab) - 4, y=ymid - 9,
                       width=6.2 * len(lab) + 8, height=13,
                       fill=C["background"], rx=2))
        out.append(_text(cx, ymid, lab, text_anchor="middle",
                         fill=C["load"], font_size=10.5, font_weight=600))
    return "".join(out)


def _point_loads(beam: Beam, X, beam_top: float) -> str:
    """Concentrated forces, drawn above the beam.

    The arrow always points the way the force acts: a downward load has its
    head on the beam, an upward load has its head above. Both are drawn in the
    zone above the beam so they never collide with the support symbols.
    """
    out: list[str] = []
    tail = ELEV_TOP + 16
    for p in beam.point_loads:
        if p.P == 0.0:
            continue
        x = X(p.x)
        if p.P < 0:
            out.append(_arrow_v(x, tail, beam_top - 1, C["load"]))
        else:
            out.append(_arrow_v(x, beam_top - 1, tail, C["load"]))
        out.append(_text(x, tail - 6, f"{sig(abs(p.P))} lb",
                         text_anchor="middle", fill=C["load"],
                         font_size=10.5, font_weight=600))
    return "".join(out)


def _applied_moments(beam: Beam, X, beam_top: float) -> str:
    """Applied couples, as a semicircular arc with a head showing the sense."""
    out: list[str] = []
    r = 15.0
    for m in beam.moments:
        if m.M == 0.0:
            continue
        x, cy = X(m.x), beam_top - r - 4
        ccw = m.M > 0
        # A semicircle over the top of the station, drawn with an explicit arc
        # command. Sweep 1 is always the arc that goes OVER the top -- SVG's y
        # axis points down, so sweep 1 traverses left-top-right, which reads
        # as clockwise on screen.
        out.append(f'<path d="M {round(x - r, 2)} {round(cy, 2)} '
                   f'A {r} {r} 0 0 1 {round(x + r, 2)} {round(cy, 2)}" '
                   f'fill="none" stroke="{C["load"]}" stroke-width="1.7"/>')
        # The sense is carried entirely by WHICH END the head sits on, and it
        # is the left end for counterclockwise. Putting the head on the right
        # for a positive (CCW) moment draws it backwards -- the arc is the
        # same curve either way, so the head is the only thing saying which
        # direction it is travelled.
        hx = x - r if ccw else x + r
        out.append(_poly([(hx, cy + 7), (hx - 5.5, cy - 2),
                          (hx + 5.5, cy - 2)], fill=C["load"]))
        out.append(_text(x, cy - r - 4, f"{sig(abs(m.M))} lb·in",
                         text_anchor="middle", fill=C["load"],
                         font_size=10.5, font_weight=600))
    return "".join(out)


def _supports(beam: Beam, X, beam_bot: float) -> str:
    out: list[str] = []
    for s in beam.supports:
        x = X(s.x)
        y = beam_bot
        if s.uy == "rigid":
            out.append(_poly([(x, y), (x - 10, y + 17), (x + 10, y + 17)],
                             fill=C["background"], stroke=C["support"],
                             stroke_width=1.4))
            out.append(_line(x - 15, y + 17, x + 15, y + 17,
                             stroke=C["support"], stroke_width=1.4))
            out.append(_hatch(x - 15, y + 17, 30, 7, spacing=6))
        elif s.uy == "spring":
            out.append(_spring(x, y, y + 24))
            out.append(_line(x - 13, y + 24, x + 13, y + 24,
                             stroke=C["support"], stroke_width=1.4))
            out.append(_hatch(x - 13, y + 24, 26, 7, spacing=6))
        if s.rz == "rigid":
            # Fixity: a hatched wall face against the beam end.
            out.append(_line(x, beam_bot - BEAM_H - 12, x,
                             beam_bot + 12, stroke=C["support"],
                             stroke_width=2.2))
            side = -12 if s.x > beam.L / 2 else 0
            out.append(_hatch(x + side, beam_bot - BEAM_H - 12, 12, 24,
                              spacing=6))
        elif s.rz == "spring":
            out.append(f'<path d="M {round(x - 9, 2)} {round(beam_bot + 4, 2)} '
                       f'A 9 9 0 1 1 {round(x + 9, 2)} '
                       f'{round(beam_bot + 4, 2)}" fill="none" '
                       f'stroke="{C["support"]}" stroke-width="1.4"/>')
        label = s.kind if s.kind != "Vertical (pin/roller)" else "Pin/roller"
        out.append(_text(x, beam_bot + 40, label, text_anchor="middle",
                         font_size=9.5, fill=C["muted"]))
        if s.dy != 0.0 or s.drz != 0.0:
            bits = []
            if s.dy:
                bits.append(f"Δ {sig(s.dy)} in")
            if s.drz:
                bits.append(f"φ {sig(s.drz)} rad")
            out.append(_text(x, beam_bot + 51, " / ".join(bits),
                             text_anchor="middle", font_size=9.5,
                             fill=C["load"]))
    return "".join(out)


def _spring(x: float, y_top: float, y_bot: float) -> str:
    """Zigzag coil between two stations."""
    n, w = 5, 7.0
    pts = [(x, y_top)]
    span = y_bot - y_top - 4
    for i in range(n):
        f = (i + 0.5) / n
        pts.append((x + (w if i % 2 == 0 else -w), y_top + 2 + f * span))
    pts.append((x, y_bot))
    return _polyline(pts, stroke=C["support"], stroke_width=1.4)


def _hinges(beam: Beam, X) -> str:
    out: list[str] = []
    for h in beam.hinges:
        out.append(_el("circle", cx=X(h.x), cy=BEAM_Y, r=4.6,
                       fill=C["hinge"], stroke=C["ink"], stroke_width=1.5))
        out.append(_text(X(h.x), BEAM_Y - 12, "hinge", text_anchor="middle",
                         font_size=9.5, fill=C["muted"]))
    return "".join(out)


def _reactions(beam: Beam, sol: SolveResult, X, beam_bot: float) -> str:
    """Reaction arrows and values below each support.

    Drawn as an arrow rather than a captioned number: the arrow says which way
    the support pushes without a legend, and a legend placed at the left edge
    collides with the reaction of a support that sits at x = 0 -- which is
    where a support usually is.

    A component that is zero to rounding is suppressed rather than printed. A
    fixed end whose applied resultant happens to act through it carries a
    genuine zero moment reaction, and printing that as "1.82e-12 lb·in" reads
    as a real number with a strange exponent instead of as nothing.
    """
    out: list[str] = []
    y_head = beam_bot + 58
    y_tail = beam_bot + 80
    # Judged against the size of the loading, never against the largest
    # reaction: a beam under a self-cancelling pair of couples has every
    # reaction at the rounding floor, and a self-relative test would then
    # print all of them.
    ref_F, ref_M = beam.load_scale()
    ref_F = max([ref_F] + [abs(r.Fy) for r in sol.reactions])
    ref_M = max([ref_M] + [abs(r.Mz) for r in sol.reactions])
    tol_F = 1.0e-9 * ref_F
    tol_M = 1.0e-9 * ref_M
    for r in sol.reactions:
        x = X(r.x)
        if abs(r.Fy) > tol_F:
            # Arrow points the way the support pushes on the beam.
            if r.Fy > 0:
                out.append(_arrow_v(x, y_tail, y_head, C["reaction"],
                                    width=1.5, head=6.5))
            else:
                out.append(_arrow_v(x, y_head, y_tail, C["reaction"],
                                    width=1.5, head=6.5))
        bits = []
        if abs(r.Fy) > tol_F:
            bits.append(f"{sig(r.Fy)} lb")
        if abs(r.Mz) > tol_M:
            bits.append(f"{sig(r.Mz)} lb·in")
        if not bits:
            continue
        out.append(_text(x, y_tail + 13, "  ".join(bits),
                         text_anchor="middle", font_size=10.5,
                         font_weight=600, fill=C["reaction"]))
    return "".join(out)


# --------------------------------------------------------------------------
# Diagram panels
# --------------------------------------------------------------------------
def _panel(dg: Diagrams, xs, ys, title: str, color: str, field: str, X,
           top: float, L: float, dp: int, zero_ref: float = 0.0,
           env: Envelope | None = None) -> str:
    out: list[str] = []
    mid = top + PANEL_H / 2
    peak = float(max(abs(float(v)) for v in ys)) if len(ys) else 0.0

    out.append(_text(LEFT, top - 7, title, font_size=11.5, font_weight=600,
                     fill=C["ink"]))

    # Degenerate panel: the quantity is zero. Say so rather than rendering a
    # meaningless full-scale flat line.
    #
    # "Zero" has to be judged against the size of the LOADING, not against
    # zero exactly. Two self-cancelling couples give a shear of 1e-13, which
    # is zero in every sense that matters but is not `<= 0.0` -- and drawing
    # it against its own peak magnifies pure rounding to full scale, which is
    # the most misleading thing this figure could do.
    if peak <= max(0.0, 1.0e-9 * zero_ref):
        out.append(_line(LEFT, mid, LEFT + PLOT_W, mid, stroke=C["rule"],
                         stroke_width=1.2))
        out.append(_text(LEFT + PLOT_W / 2, mid - 7, "zero throughout",
                         text_anchor="middle", font_size=10.5,
                         fill=C["muted"], font_style="italic"))
        return "".join(out)

    # Locked scale: the envelope over every load combination, floored by what
    # is actually being drawn. The floor is not decoration -- the envelope is
    # sampled on a grid, and a curve must never be allowed to run outside its
    # own panel because the grid missed its peak by a hair.
    locked = max(peak, env.peak(field)) if env is not None else peak
    scale = (PANEL_H / 2 * BAND_FILL) / locked

    def Y(v: float) -> float:
        return mid - v * scale

    pts = [(X(float(x)), Y(float(v))) for x, v in zip(xs, ys)]
    out.append(_poly([(pts[0][0], mid)] + pts + [(pts[-1][0], mid)],
                     fill=color, fill_opacity=0.15))
    out.append(_polyline(pts, stroke=color, stroke_width=1.7))
    out.append(_line(LEFT, mid, LEFT + PLOT_W, mid, stroke=C["rule"],
                     stroke_width=1.1))

    hi, lo, _ = dg.extremes(field)
    for ex, above in ((hi, True), (lo, False)):
        if abs(ex.value) < 1.0e-12 * peak:
            continue
        px, py = X(ex.x), Y(ex.value)
        out.append(_el("circle", cx=px, cy=py, r=3.1, fill=color))
        # Place the label clear of the marker, then keep it inside the band.
        # A peak sitting near the top of the panel would otherwise put its
        # label straight through the panel title, and one near the bottom
        # through the station axis; both flip to the other side instead.
        ty = py - 11 if above else py + 15
        if ty < top + 11:
            ty = py + 15
        elif ty > top + PANEL_H - 2:
            ty = py - 11
        ta = ("start" if px < LEFT + 60 else
              "end" if px > LEFT + PLOT_W - 60 else "middle")
        out.append(_text(px, ty, f"{fmt(ex.value, dp) if dp else sig(ex.value)}"
                         f"  @ x = {station(ex.x)}", text_anchor=ta,
                         font_size=10.5, font_weight=600, fill=color))

    # Reference rules at the envelope, drawn only when the current subset does
    # not reach it -- that gap IS the contribution of whatever is switched
    # off, and showing it is the point of locking the scale.
    if env is not None and locked > peak * 1.02:
        e_hi, e_lo = env.bounds(field)
        for v in (e_hi, e_lo):
            if abs(v) <= 1.0e-12 * locked:
                continue
            out.append(_line(LEFT, Y(v), LEFT + PLOT_W, Y(v), stroke=color,
                             stroke_width=1, stroke_opacity=0.42,
                             stroke_dasharray="3 4"))
        # Anchored to the upper rule when there is one, not to whichever is
        # larger: the lower rule shares the bottom of the panel with the
        # negative peak callout, and the two collide there.
        anchor_v = e_hi if abs(e_hi) > 1.0e-12 * locked else e_lo
        out.append(_text(LEFT + PLOT_W, Y(anchor_v) - 4,
                         "load envelope", text_anchor="end", font_size=9.5,
                         fill=color, fill_opacity=0.75))

    out.append(_text(LEFT - 8, mid + 3.5, "0", text_anchor="end",
                     font_size=10, fill=C["muted"]))
    return "".join(out)


def _station_axis(beam: Beam, X, y: float) -> str:
    """Shared station axis. Feature stations are the ticks, thinned so labels
    never overprint, with the two ends always kept."""
    out = [_line(LEFT, y - 12, LEFT + PLOT_W, y - 12, stroke=C["ink"],
                 stroke_width=1.1)]
    xs = beam.feature_stations()
    keep: list[float] = []
    for v in xs:
        if v in (xs[0], xs[-1]):
            keep.append(v)
            continue
        if all(abs(X(v) - X(k)) >= TICK_MIN_SEP for k in keep + [xs[-1]]):
            keep.append(v)
    for v in sorted(keep):
        px = X(v)
        out.append(_line(px, y - 12, px, y - 7, stroke=C["ink"],
                         stroke_width=1.1))
        anchor = ("start" if v == xs[0] else
                  "end" if v == xs[-1] else "middle")
        out.append(_text(px, y + 3, station(v), text_anchor=anchor,
                         font_size=10))
    out.append(_text(LEFT + PLOT_W / 2, y + 17, "Station x (in)",
                     text_anchor="middle", font_size=10.5, fill=C["muted"]))
    return "".join(out)
