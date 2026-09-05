"""
library/beam_line/diagrams.py

Shear, moment, slope and deflection along the span -- as EXACT piecewise
polynomials, not as a sampled grid.

WHY POLYNOMIALS RATHER THAN SAMPLES
-----------------------------------
Under a trapezoidal load the quantities are polynomial in x:

    w  degree 1        V  degree 2        M  degree 3
    th degree 4        d  degree 5

so between two feature stations each one is exactly representable. Carrying
the coefficients instead of a sample array buys three things that matter for a
stress report:

  * `M_max` is found by rooting V, so it is the true peak and its station is
    exact -- not "the largest of 500 samples", which is wrong by up to half a
    sample interval and silently mesh-dependent.
  * A discontinuity is represented as a discontinuity. V steps at a point load
    and M steps at an applied moment; a sampled curve smears both.
  * The deflection is obtained by integrating M/EI in closed form, so it does
    not inherit a quadrature error on top of the solve.

HOW THE INTEGRATION CONSTANTS ARE SET, AND WHY THAT IS ALSO THE CHECK
---------------------------------------------------------------------
V and M are built from statics alone: marching left to right, accumulating
applied loads and the solver's reactions. Slope and deflection are then
integrated forward from `th(0)` and `d(0)` taken from the stiffness solve, and
reset only at hinges (where rotation is genuinely discontinuous).

That makes the nodal deflections a real cross-check rather than a restatement:
the integration never looks at the solved deflection anywhere except x = 0, so
if the reactions were wrong the integrated curve would miss the prescribed
value at the far supports. `Diagrams.residual` measures exactly that, and
`closure_V` / `closure_M` confirm both diagrams return to zero past the last
support. `SUM P = 0` is necessary but not sufficient; the integrated diagrams
are the gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from library.beam_line.model import POSITION_TOL, Beam
from library.beam_line.solver import SolveResult, intensity_at

# Fractions of the peak value. A correct solve lands many orders below these;
# they are set to catch a wrong one, not to grade a right one.
CLOSURE_TOL = 1.0e-6
RESIDUAL_TOL = 1.0e-6


# ---------------------------------------------------------------------------
# Small ascending-order polynomial helpers. c[0] + c[1]*u + c[2]*u^2 + ...
# ---------------------------------------------------------------------------

def _polyval(c: Sequence[float], u: float) -> float:
    acc = 0.0
    for coef in reversed(c):
        acc = acc * u + coef
    return acc


def _polyint(c: Sequence[float], const: float) -> list[float]:
    return [const] + [ci / (i + 1) for i, ci in enumerate(c)]


def _polyder(c: Sequence[float]) -> list[float]:
    return [i * ci for i, ci in enumerate(c)][1:] or [0.0]


def _roots_in(c: Sequence[float], hi: float) -> list[float]:
    """Real roots of the ascending-order polynomial `c` in (0, hi)."""
    arr = np.asarray(c, dtype=float)
    scale = float(np.max(np.abs(arr))) if arr.size else 0.0
    if scale <= 0.0:
        return []
    # Trim negligible high-order terms before rooting; np.roots on a leading
    # coefficient of ~1e-18 manufactures enormous spurious roots.
    keep = len(arr)
    while keep > 1 and abs(arr[keep - 1]) <= 1.0e-13 * scale:
        keep -= 1
    if keep < 2:
        return []
    r = np.roots(arr[:keep][::-1])
    out = []
    for z in r:
        if abs(z.imag) <= 1.0e-9 * max(1.0, abs(z.real)):
            u = float(z.real)
            if POSITION_TOL < u < hi - POSITION_TOL:
                out.append(u)
    return sorted(out)


# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Extremum:
    """A located extreme value."""

    x: float
    value: float


@dataclass(frozen=True)
class Piece:
    """One element's closed-form diagrams, in the local variable u = x - x0."""

    x0: float
    x1: float
    EI: float
    V: tuple[float, ...]
    M: tuple[float, ...]
    th: tuple[float, ...]
    d: tuple[float, ...]

    @property
    def length(self) -> float:
        return self.x1 - self.x0


@dataclass(frozen=True)
class Diagrams:
    """The complete set of diagrams plus the quality gate.

    `valid` is the single flag the app should key off. It is False when the
    diagrams do not close or the integrated deflection does not reproduce the
    supports -- in which case no peak or reaction should be displayed.
    """

    pieces: tuple[Piece, ...]
    stations: tuple[float, ...]
    closure_V: float
    closure_M: float
    residual: float
    valid: bool
    message: str = ""

    # -- evaluation ------------------------------------------------------

    def _piece_at(self, x: float, side: str = "right") -> Piece:
        """The piece to evaluate at station `x`.

        At a station that is a piece boundary the answer is genuinely
        two-valued -- V steps at a point load and M steps at an applied
        couple -- so `side` says which one is wanted rather than leaving it to
        a floating-point tie-break. Asking for a station outside the span
        clamps to the nearest end instead of extrapolating the polynomial,
        which would produce a confident and meaningless number.
        """
        ps = self.pieces
        if side == "left":
            for p in ps:
                if x <= p.x1:
                    return p
            return ps[-1]
        for p in reversed(ps):
            if x >= p.x0:
                return p
        return ps[0]

    def _eval(self, field: str, x: float, side: str) -> float:
        p = self._piece_at(x, side)
        u = min(max(x - p.x0, 0.0), p.length)
        return _polyval(getattr(p, field), u)

    def V_at(self, x: float, side: str = "right") -> float:
        return self._eval("V", x, side)

    def M_at(self, x: float, side: str = "right") -> float:
        return self._eval("M", x, side)

    def theta_at(self, x: float, side: str = "right") -> float:
        return self._eval("th", x, side)

    def deflection_at(self, x: float, side: str = "right") -> float:
        return self._eval("d", x, side)

    # -- sampling for plotting -------------------------------------------

    def sample(self, per_piece: int = 24) -> dict[str, np.ndarray]:
        """Dense polyline for drawing.

        Emits both the left and the right value at every interior station, at
        the same x, so a step in V or M renders as a vertical line instead of
        a steep ramp.
        """
        xs: list[float] = []
        V: list[float] = []
        M: list[float] = []
        th: list[float] = []
        d: list[float] = []
        for p in self.pieces:
            n = max(2, per_piece)
            for k in range(n + 1):
                u = p.length * k / n
                xs.append(p.x0 + u)
                V.append(_polyval(p.V, u))
                M.append(_polyval(p.M, u))
                th.append(_polyval(p.th, u))
                d.append(_polyval(p.d, u))
        return {
            "x": np.asarray(xs), "V": np.asarray(V), "M": np.asarray(M),
            "theta": np.asarray(th), "delta": np.asarray(d),
        }

    # -- peaks -----------------------------------------------------------

    def _candidates(self, field: str) -> list[tuple[float, float]]:
        """Every station where the field can be extreme: both ends of every
        piece, plus the interior roots of its derivative."""
        out: list[tuple[float, float]] = []
        for p in self.pieces:
            c = getattr(p, field)
            out.append((p.x0, _polyval(c, 0.0)))
            out.append((p.x1, _polyval(c, p.length)))
            for u in _roots_in(_polyder(c), p.length):
                out.append((p.x0 + u, _polyval(c, u)))
        return out

    def extremes(self, field: str) -> tuple[Extremum, Extremum, Extremum]:
        """(most positive, most negative, largest magnitude)."""
        cands = self._candidates(field)
        hi = max(cands, key=lambda t: t[1])
        lo = min(cands, key=lambda t: t[1])
        mag = max(cands, key=lambda t: abs(t[1]))
        return (Extremum(*hi), Extremum(*lo), Extremum(*mag))

    def zero_crossings(self, field: str = "V") -> list[float]:
        """Stations where the field passes through zero, for annotation.

        The shear zeros are where the moment peaks, so marking them makes the
        two panels readable together.
        """
        out: list[float] = []
        for p in self.pieces:
            c = getattr(p, field)
            for u in _roots_in(c, p.length):
                out.append(p.x0 + u)
        return sorted(out)


def build(beam: Beam, sol: SolveResult) -> Diagrams:
    """Recover the diagrams from the solved reactions and the applied loads."""
    if not sol.stable or len(sol.nodes) < 2:
        return Diagrams((), tuple(sol.nodes), 0.0, 0.0, 0.0, False,
                        sol.message or "No stable solution.")

    nodes = list(sol.nodes)
    n = len(nodes)

    # Concentrated force and moment landing at each node, applied plus reaction.
    node_F = [0.0] * n
    node_M = [0.0] * n
    for p in beam.point_loads:
        node_F[_nearest(nodes, p.x)] += p.P
    for m in beam.moments:
        node_M[_nearest(nodes, m.x)] += m.M
    for r in sol.reactions:
        i = _nearest(nodes, r.x)
        node_F[i] += r.Fy
        node_M[i] += r.Mz

    hinge_nodes = {_nearest(nodes, h.x) for h in beam.hinges}

    pieces: list[Piece] = []
    V0 = node_F[0]
    M0 = -node_M[0]
    th0 = sol.th_right[0]
    d0 = sol.v[0]

    for e in range(n - 1):
        x0, x1 = nodes[e], nodes[e + 1]
        Le = x1 - x0
        EI = sol.element_EI[e]
        w1 = intensity_at(beam, x0, side="right")
        w2 = intensity_at(beam, x1, side="left")
        s = (w2 - w1) / Le if Le > 0 else 0.0

        Vc = [V0, w1, 0.5 * s]
        Mc = [M0, V0, 0.5 * w1, s / 6.0]
        thc = _polyint([c / EI for c in Mc], th0)
        dc = _polyint(thc, d0)

        pieces.append(Piece(x0, x1, EI, tuple(Vc), tuple(Mc),
                            tuple(thc), tuple(dc)))

        # March to the right-hand node, then apply what sits on it.
        V0 = _polyval(Vc, Le) + node_F[e + 1]
        M0 = _polyval(Mc, Le) - node_M[e + 1]
        d0 = _polyval(dc, Le)
        th0 = (sol.th_right[e + 1] if (e + 1) in hinge_nodes
               else _polyval(thc, Le))

    # ---- gate -----------------------------------------------------------
    # The scale for the closure ratio has to be the TRUE peak of each diagram,
    # taken over the interior as well as the ends. Using only the piece
    # endpoints looks equivalent and is not: a simply supported beam has
    # M = 0 at both ends, so the endpoint scale collapses onto the closure
    # residue itself and every such beam reports a closure ratio of 1.
    probe = Diagrams(tuple(pieces), tuple(nodes), 0.0, 0.0, 0.0, True)
    peak_V = abs(probe.extremes("V")[2].value)
    peak_M = abs(probe.extremes("M")[2].value)

    # ...and the scale is floored at the size of the applied loading, because
    # the peak of a diagram can itself be zero. Two equal and opposite couples
    # give V == 0 to rounding, so dividing the shear residue by the peak shear
    # divides it by itself. `Beam.load_scale()` is the shared definition of
    # "how big is this problem"; the reaction magnitudes join it so a beam
    # loaded only by an imposed settlement still has a reference.
    ref_F, ref_M = beam.load_scale()
    ref_F = max([ref_F] + [abs(r.Fy) for r in sol.reactions])
    ref_M = max([ref_M] + [abs(r.Mz) for r in sol.reactions])
    scale_V = max(peak_V, ref_F)
    scale_M = max(peak_M, ref_M)

    closure_V = abs(V0)
    closure_M = abs(M0)
    cV = closure_V / scale_V if scale_V > 0 else closure_V
    cM = closure_M / scale_M if scale_M > 0 else closure_M

    # Integrated deflection must reproduce the solved nodal values. It only
    # ever used the solve at x = 0, so agreement at the far supports is
    # genuine confirmation that the reactions are right.
    #
    # The scale is the peak of the deflection FIELD, not of the nodal values.
    # On a beam whose nodes all sit at supports -- a stiff spring, a propped
    # cantilever -- every nodal deflection is at or near zero while the span
    # deflects perfectly normally, and normalising by those turns a 1e-16
    # rounding difference into an apparent 1e-5 error.
    scale = max(abs(probe.extremes("d")[2].value),
                max((abs(v) for v in sol.v), default=0.0))
    worst = 0.0
    for i in range(1, len(nodes)):
        p = pieces[i - 1]
        worst = max(worst, abs(_polyval(p.d, p.length) - sol.v[i]))
    residual = worst / scale if scale > 0 else worst

    ok = (cV <= CLOSURE_TOL and cM <= CLOSURE_TOL
          and residual <= RESIDUAL_TOL)
    msg = ""
    if not ok:
        bits = []
        if cV > CLOSURE_TOL:
            bits.append(f"shear does not return to zero (V(L) = {V0:,.3g} lb)")
        if cM > CLOSURE_TOL:
            bits.append(f"moment does not return to zero (M(L) = {M0:,.3g} lb·in)")
        if residual > RESIDUAL_TOL:
            bits.append("the integrated deflection does not reproduce the "
                        "supported stations")
        msg = ("The diagrams do not close: " + "; ".join(bits)
               + ". Results are suppressed.")

    return Diagrams(tuple(pieces), tuple(nodes), closure_V, closure_M,
                    residual, ok, msg)


def _nearest(nodes: Sequence[float], x: float) -> int:
    best, best_d = 0, float("inf")
    for i, xn in enumerate(nodes):
        d = abs(xn - x)
        if d < best_d:
            best, best_d = i, d
    return best
