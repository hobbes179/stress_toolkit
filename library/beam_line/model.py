"""
library/beam_line/model.py

Data model for the line-beam module: a straight, prismatic beam loaded
transversely, with arbitrary supports, releases and loads along the span.

Pure data + validation. Nothing here imports Streamlit, numpy or the solver.

SIGN CONVENTIONS (used identically by the solver, the diagrams and the figure)
-----------------------------------------------------------------------------
    x   runs left to right along the span, 0 at the left end, L at the right.
    v   transverse displacement, POSITIVE UP (in).
    th  rotation dv/dx, POSITIVE COUNTERCLOCKWISE (rad).

    P   point force, POSITIVE UP (lb).  A gravity load is negative.
    w   distributed intensity, POSITIVE UP (lb/in).
    M   applied point moment, POSITIVE COUNTERCLOCKWISE (lb-in).

    V(x) = sum of all transverse forces to the LEFT of x, positive up.
    M(x) = sum F*(x - a) - sum M_applied, both over everything left of x.
           This is the ordinary SAGGING-POSITIVE bending moment: a simply
           supported beam under gravity has M > 0 throughout.

Note that `V = dM/dx` holds everywhere except across an applied point moment,
where M steps by -M_applied and V is continuous.

WHY PIN AND ROLLER ARE THE SAME THING HERE
------------------------------------------
This is a transverse-only (Euler-Bernoulli) beam model: each node carries a
vertical DOF and a rotation, and there is no axial DOF. A pin and a roller
therefore impose the identical restraint -- vertical translation -- and
produce identical reactions, diagrams and deflections. The module offers one
"vertical" restraint rather than two symbols that compute the same answer.
Axial force, and with it the pin/roller distinction, would need a third DOF
and a different module.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, Sequence

# How close two stations must be before they are treated as the same point.
# Also the tolerance on "is this feature inside the span".
POSITION_TOL = 1.0e-9

Restraint = Literal["none", "rigid", "spring"]


@dataclass(frozen=True)
class Support:
    """A support at station `x`.

    Each of the two DOFs is independently free, rigidly held, or held by an
    elastic spring:

        uy  vertical translation   -- "spring" uses `ky`  (lb/in)
        rz  rotation               -- "spring" uses `krz` (lb-in/rad)

    `dy` / `drz` are PRESCRIBED MOVEMENTS of the support itself (settlement,
    jig misalignment, thermal growth of the structure it sits on):

      * against a rigid restraint they force the beam to that value;
      * against a spring they move the far end of the spring, so the force
        delivered to the beam is `ky * (dy - v)`.

    On a statically determinate beam a settlement induces no internal load; on
    an indeterminate one it induces real moments, which is the point of having
    it.
    """

    x: float
    uy: Restraint = "rigid"
    rz: Restraint = "none"
    ky: float = 0.0
    krz: float = 0.0
    dy: float = 0.0
    drz: float = 0.0
    label: str = ""

    @property
    def restrains_anything(self) -> bool:
        return self.uy != "none" or self.rz != "none"

    @property
    def kind(self) -> str:
        """Short human name for the restraint combination."""
        u, r = self.uy, self.rz
        if u == "rigid" and r == "rigid":
            return "Fixed"
        if u == "rigid" and r == "none":
            return "Vertical (pin/roller)"
        if u == "none" and r == "rigid":
            return "Guided"
        if u == "none" and r == "none":
            return "Free"
        return "Spring"


@dataclass(frozen=True)
class PointLoad:
    """Concentrated transverse force. `P` positive up (lb)."""

    x: float
    P: float
    label: str = ""


@dataclass(frozen=True)
class PointMoment:
    """Concentrated applied moment. `M` positive counterclockwise (lb-in)."""

    x: float
    M: float
    label: str = ""


@dataclass(frozen=True)
class DistributedLoad:
    """Linearly varying transverse load from `x1` to `x2`.

    `w1` and `w2` are intensities (lb/in, positive up) at `x1` and `x2`.
    A rectangular (uniform) load is w1 == w2; a triangular load sets one end
    to zero; a trapezoid is the general case. There is no separate load type
    for those three -- they are the same object.
    """

    x1: float
    x2: float
    w1: float
    w2: float
    label: str = ""

    @property
    def length(self) -> float:
        return self.x2 - self.x1

    @property
    def total(self) -> float:
        """Resultant force, lb (positive up)."""
        return 0.5 * (self.w1 + self.w2) * self.length

    @property
    def centroid(self) -> float:
        """Station of the resultant, in. Midspan of the patch when uniform."""
        a, b = self.w1, self.w2
        if abs(a + b) < 1.0e-30:
            return 0.5 * (self.x1 + self.x2)
        return self.x1 + self.length * (a + 2.0 * b) / (3.0 * (a + b))

    def intensity_at(self, x: float) -> float:
        if self.length <= 0.0:
            return 0.0
        f = (x - self.x1) / self.length
        return self.w1 + (self.w2 - self.w1) * f

    @property
    def shape(self) -> str:
        if abs(self.w1 - self.w2) < 1.0e-12:
            return "uniform"
        if abs(self.w1) < 1.0e-12 or abs(self.w2) < 1.0e-12:
            return "triangular"
        return "trapezoidal"


@dataclass(frozen=True)
class Hinge:
    """An internal moment release at station `x`.

    Transmits shear but not moment, so the rotation is discontinuous there.
    This is the Gerber / cantilever-suspended-span device, and it is also how
    a real splice with no moment capacity is modelled.
    """

    x: float
    label: str = ""


@dataclass(frozen=True)
class Beam:
    """The complete problem statement.

    `EI` is in lb-in^2 -- E in psi times I in in^4. The app works in Msi and
    in^4 and multiplies out; the library never sees Msi.
    """

    L: float
    EI: float
    supports: tuple[Support, ...] = ()
    point_loads: tuple[PointLoad, ...] = ()
    moments: tuple[PointMoment, ...] = ()
    distributed: tuple[DistributedLoad, ...] = ()
    hinges: tuple[Hinge, ...] = ()

    def with_EI(self, EI: float) -> "Beam":
        return replace(self, EI=EI)

    @property
    def total_applied_force(self) -> float:
        """Sum of every applied transverse force, lb (positive up)."""
        return (sum(p.P for p in self.point_loads)
                + sum(d.total for d in self.distributed))

    def total_applied_moment_about(self, x0: float = 0.0) -> float:
        """Sum of applied moments about station `x0`, lb-in (CCW positive).

        Used by the equilibrium gate: this plus the reaction moments must
        vanish.
        """
        m = sum(mm.M for mm in self.moments)
        m += sum(p.P * (p.x - x0) for p in self.point_loads)
        m += sum(d.total * (d.centroid - x0) for d in self.distributed)
        return m

    def load_scale(self) -> tuple[float, float]:
        """(force, moment) reference magnitudes for this problem, in lb and
        lb-in.

        Used wherever a residue has to be judged against "the size of the
        problem" rather than against the size of the answer. Normalising by
        the answer fails exactly when the answer is zero: a beam carrying two
        equal and opposite couples has `V` identically zero, so its peak shear
        IS its own rounding residue and the ratio comes out at 2 instead of
        1e-15. An applied couple contributes `M/L` to the force reference,
        because that is the shear it would take to carry it.
        """
        L = self.L if self.L > 0 else 1.0
        F = max([0.0]
                + [abs(p.P) for p in self.point_loads]
                + [abs(d.total) for d in self.distributed]
                + [abs(m.M) / L for m in self.moments])
        M = max([0.0] + [abs(m.M) for m in self.moments] + [F * L])
        return F, M

    def feature_stations(self) -> list[float]:
        """Every station the mesh must place a node at.

        Nodes go at the ends, at every support, at every hinge, at every point
        load and moment, and at both ends of every distributed patch. Meshing
        this way means that inside an element the only load is a single linear
        function, which is what makes the recovered diagrams exact rather than
        interpolated.
        """
        xs: list[float] = [0.0, self.L]
        xs += [s.x for s in self.supports]
        xs += [h.x for h in self.hinges]
        xs += [p.x for p in self.point_loads]
        xs += [m.x for m in self.moments]
        for d in self.distributed:
            xs += [d.x1, d.x2]
        return _unique_sorted(xs, POSITION_TOL)


def _unique_sorted(xs: Sequence[float], tol: float) -> list[float]:
    """Sort and collapse values closer together than `tol`."""
    out: list[float] = []
    for x in sorted(xs):
        if not out or (x - out[-1]) > tol:
            out.append(float(x))
    return out


def validate(beam: Beam) -> list[str]:
    """Return a list of human-readable problems. Empty means the model is
    well-formed -- it does NOT mean the beam is stable; that is the solver's
    job (`solve()` reports a mechanism).
    """
    errs: list[str] = []
    L = beam.L

    if not (L > 0.0):
        return ["Span must be greater than zero."]
    if not (beam.EI > 0.0):
        errs.append("EI must be greater than zero - check E and I.")

    def _inside(x: float, what: str) -> None:
        if x < -POSITION_TOL or x > L + POSITION_TOL:
            errs.append(
                f"{what} at x = {x:g} in is outside the span (0 to {L:g} in)."
            )

    for s in beam.supports:
        _inside(s.x, "Support")
        if s.uy == "spring" and not (s.ky > 0.0):
            errs.append(
                f"Spring support at x = {s.x:g} in has no vertical stiffness."
            )
        if s.rz == "spring" and not (s.krz > 0.0):
            errs.append(
                f"Spring support at x = {s.x:g} in has no rotational stiffness."
            )
        if s.uy == "none" and s.rz == "none":
            errs.append(
                f"Support at x = {s.x:g} in restrains nothing - "
                "delete it or give it a restraint."
            )

    for h in beam.hinges:
        _inside(h.x, "Hinge")
        # A release at the very end has no continuity to release -- there is
        # only one element touching that node. What the user means is a
        # support that does not hold moment, which is expressible directly.
        if h.x <= POSITION_TOL or h.x >= L - POSITION_TOL:
            errs.append(
                f"Hinge at x = {h.x:g} in is at the end of the span, where "
                "there is no moment continuity to release. If the intent is "
                "an end that carries no moment, set that support to "
                "vertical-only instead."
            )
        for m in beam.moments:
            if abs(m.x - h.x) <= POSITION_TOL:
                errs.append(
                    f"An applied moment sits exactly on the hinge at "
                    f"x = {h.x:g} in. A hinge holds M = 0 on both sides, so "
                    "no applied moment there can be equilibrated. Move one of "
                    "them clear of the other."
                )
        for s in beam.supports:
            if abs(s.x - h.x) <= POSITION_TOL and s.rz != "none":
                errs.append(
                    f"The support at x = {s.x:g} in restrains rotation at the "
                    "same station as a hinge. Those contradict each other — "
                    "keep the rotational restraint or keep the hinge."
                )

    for p in beam.point_loads:
        _inside(p.x, "Point load")
    for m in beam.moments:
        _inside(m.x, "Applied moment")

    for d in beam.distributed:
        _inside(d.x1, "Distributed load start")
        _inside(d.x2, "Distributed load end")
        if d.length <= POSITION_TOL:
            errs.append(
                f"Distributed load from x = {d.x1:g} to {d.x2:g} in has zero "
                "length - use a point load instead."
            )

    # Two hinges at the same station is a beam cut through, not a release.
    hs = sorted(h.x for h in beam.hinges)
    for a, b in zip(hs, hs[1:]):
        if (b - a) <= POSITION_TOL:
            errs.append(
                f"Two hinges at the same station (x = {a:g} in) - "
                "the beam is cut through."
            )

    return errs
