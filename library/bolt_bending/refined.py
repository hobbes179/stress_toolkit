"""
library/bolt_bending/refined.py

Refined bearing distribution — the pencil-sharpening pass over the uniform
bearing baseline in `kernel.py`. Pure engineering math; nothing here imports
Streamlit.

═══════════════════════════════════════════════════════════════════════════
WHAT THIS REFINES, AND WHAT IT DELIBERATELY DOES NOT
═══════════════════════════════════════════════════════════════════════════
The baseline spreads each plate's load **uniformly over its own thickness**.
That is equivalent to assuming the bolt is **rigid across each plate's
thickness** — it cannot bend or tilt within the hole, so it presses evenly.
On a long grip that is measurably conservative: a real bolt bends, bearing
concentrates toward the shear planes, and the effective moment arm shortens.

This module lets the bolt bend. It refines **where within each plate's
thickness the load acts** — nothing else.

It does **NOT**:
  • determine the load split between plates. `P_i` stays an INPUT, exactly as
    in the baseline; the split is statically indeterminate and remains the
    engineer's call. It is enforced here as a constraint (see below).
  • model bolt–hole clearance, one-sided contact, or plastic bearing. The
    foundation is linear and two-sided, so a negative reaction means the bolt
    bearing on the far side of the hole — real for a close-fit bolt, wrong
    for a sloppy clearance fit.
  • iterate. One linear solve.

═══════════════════════════════════════════════════════════════════════════
FORMULATION
═══════════════════════════════════════════════════════════════════════════
Each plate i is given an unknown rigid offset `d_i`. Between bolt and plate
sits a Winkler bed of modulus `k` [lb/in per in], so the reaction per unit
length is

    q(x) = k · (d_i − w(x))

and the beam equation over that plate becomes  EI·w'''' + k·w = k·d_i.

The offsets are fixed by requiring each plate to transfer exactly the load the
engineer entered:

    ∫ k·(d_i − w) dx = P_i          over plate i

That is one extra equation per plate for one extra unknown per plate, so the
whole thing is a single linear solve — no iteration, and the load split is
honoured exactly.

**End conditions.** Lateral deflection is pinned at the head and nut faces.
This is not a convenience: without it the system is singular, because
translating or rotating the bolt while shifting every `d_i` to match leaves
the constraints satisfied — two rigid-body null modes. Pinning `w` at both
ends removes exactly those two modes.

Those pins are a **deflection boundary condition on the shape solve only** —
they are the same idealisation as the baseline's end pair (see kernel.py,
"Closing the residual moment"), but their reactions are not carried forward
and are not asserted to equal `R_0`/`R_L`. The refined distribution is handed
back to `kernel.analyse()` as strips, and the kernel recomputes `M_res` from
that strip layout and closes it with its own end pair. On the shipped default
the refined layout still leaves `M_res` = −78.9 lb·in, closed at 74.5 lbf, so
the two are related but distinct numbers. Do not conflate them.

⚠️ An earlier draft left the system singular and leaned on a least-squares
minimum-norm solution. It looked plausible and converged to the wrong answer
at coarse mesh (239.4 vs the correct 235.1 lb·in). Do not reintroduce that.

**Rigid-bolt limit.** Pinned at both ends and straight ⇒ `w ≡ 0` ⇒ `q = k·d_i`,
uniform over each plate. So the refined model reduces to the baseline
*exactly* as `k → 0` (bolt stiff relative to the foundation). That is the
validation gate, asserted in `tests/bolt_bending/test_refined.py`.

═══════════════════════════════════════════════════════════════════════════
REUSING THE BASELINE KERNEL
═══════════════════════════════════════════════════════════════════════════
The refined distribution is delivered to `kernel.analyse()` by subdividing
each plate into thin strips, each a `Layer` carrying its share of `P_i`. The
kernel is therefore used **completely unchanged** — same integration, same
peak finding, same margins, same diagrams. The strips are normalised so they
sum to `P_i`, so `ΣP` and the equilibrium gate behave identically.

═══════════════════════════════════════════════════════════════════════════
UNITS
═══════════════════════════════════════════════════════════════════════════
Inches, pounds. Moduli are taken in **Msi** at the API boundary (matching the
material library) and converted to psi internally.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from library.bolt_bending.kernel import BoltAnalysis, Layer, analyse

# Default discretisation. Peak moment is converged to 4 significant figures at
# 200 el/in and 24 strips, and stable to at least 1600 el/in — see
# test_refined.py, which pins both.
ELEMENTS_PER_INCH = 200
STRIPS_PER_PLATE = 24

# Solution-quality thresholds, both set from measured behaviour rather than
# picked as round numbers. They replaced a `np.linalg.cond` gate that measured
# the beam matrix's intrinsic conditioning rather than solution quality (see
# `_solve` for why it was wrong).
#
# `residual` — relative residual of the linear solve. Observed 1.6e-10 (100
# el/in) to 3.8e-6 (1600 el/in); it grows with mesh through float64
# accumulation, not through anything physical. A genuinely failed solve is
# O(1), so the threshold sits two decades above the worst legitimate value.
RESIDUAL_WARN = 1.0e-4

# `load_error` — how far the STRIP discretisation lands from each plate's
# entered load, before the strips are normalised onto it. Measured to scale as
# 1/strips², i.e. it is the midpoint-quadrature error of sampling the solved
# distribution, and it grows with β·t because a peakier distribution has more
# curvature for the strips to miss. Observed 3e-8 (near-uniform bearing) to
# 4e-3 (an absurd 1000 Msi plate); 3e-4 on the shipped default.
#
# It matters because the strips ARE renormalised onto the entered load, which
# forces the right total onto whatever shape came out. Checking after that
# would always pass. This is the pre-normalisation number, so it says how much
# work the normalisation is doing — and therefore how well the strip count
# resolves the distribution it is representing.
LOAD_ERROR_WARN = 1.0e-2


# ══════════════════════════════════════════════════════════════════════════
# Foundation modulus — the documented basis
# ══════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class FoundationBasis:
    """The foundation modulus `k` plus the citation that justifies it.

    The basis string travels with the result into any export or printout —
    a less-conservative option must never appear without its justification.
    """

    k: float                 # lb/in per in of bolt length
    E_plate: float           # psi, the plate modulus it was derived from
    citation: str
    note: str

    @property
    def k_msi(self) -> float:
        return self.k / 1.0e6


def tate_rosenfeld_k(E_plate_msi: float) -> FoundationBasis:
    """Foundation modulus from the Tate & Rosenfeld bearing term.

    NACA TN 1051 (1946) decomposes fastener flexibility into bending, shear,
    and **bearing** contributions. Only the bearing term belongs here: this
    model already computes bolt bending explicitly from EI, so folding a
    lumped joint compliance into `k` would double-count it.

    The bearing compliance of a plate of thickness t is `δ = P/(E·t)`. In the
    Winkler bed, `P = ∫q dx = k·δ·t`, hence `δ = P/(k·t)`. Equating the two:

        k = E_plate

    So the modulus is the plate's Young's modulus, and it is a *derived*
    quantity rather than a fitted one — which is why Tate & Rosenfeld is the
    basis used for `k` here and Huth is kept as an independent cross-check
    (see `huth_compliance`).

    Args:
        E_plate_msi: Plate Young's modulus, Msi.
    """
    E = E_plate_msi * 1.0e6
    return FoundationBasis(
        k=E,
        E_plate=E,
        citation="Tate & Rosenfeld, NACA TN 1051 (1946) — bearing term",
        note=(
            "k = E_plate, from the plate bearing compliance δ = P/(E·t). "
            "Bearing term only: bolt bending is computed explicitly from EI, "
            "so a lumped joint compliance would double-count it."
        ),
    )


def huth_compliance(
    d: float, t1: float, t2: float,
    E1_msi: float, E2_msi: float, Ef_msi: float,
    n_shear_planes: int = 2,
) -> float:
    """Huth fastener compliance, in/lb — an INDEPENDENT cross-check on `k`.

    ⚠️ VERIFY — the exponent `a` and coefficient `b` below are the commonly
    quoted bolted-metallic constants (a = 2/3, b = 3.0) from Huth, "Influence
    of Fastener Flexibility on the Prediction of Load Transfer and Fatigue
    Life for Multiple-Row Joints", ASTM STP 927 (1986). They are reproduced
    from memory and MUST be checked against the paper before this number is
    quoted in a released stress report.

    This is a **lumped joint** compliance: it bundles bolt bending, bolt
    shear, and the bearing of both plates into one empirical number. It is
    therefore NOT usable directly as `k` (that is the double-counting trap
    described in `tate_rosenfeld_k`). It is used only to sanity-check the
    relative plate displacement the refined model predicts.

    Args:
        d:  Fastener diameter, in.
        t1, t2: Plate thicknesses, in.
        E1_msi, E2_msi: Plate moduli, Msi.
        Ef_msi: Fastener modulus, Msi.
        n_shear_planes: 1 for single shear, 2 for double shear.

    Returns:
        Compliance C in in/lb, such that relative plate displacement = C · P.
    """
    a, b = 2.0 / 3.0, 3.0          # ⚠️ VERIFY — bolted metallic
    n = float(n_shear_planes)
    E1, E2, Ef = E1_msi * 1e6, E2_msi * 1e6, Ef_msi * 1e6
    if min(d, t1, t2, E1, E2, Ef) <= 0:
        return math.inf
    return (
        ((t1 + t2) / (2.0 * d)) ** a
        * (b / n)
        * (1.0 / (t1 * E1) + 1.0 / (n * t2 * E2)
           + 1.0 / (2.0 * t1 * Ef) + 1.0 / (2.0 * n * t2 * Ef))
    )


# ══════════════════════════════════════════════════════════════════════════
# Result
# ══════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class PlateBearing:
    """Per-plate diagnostics for the refined solve."""

    index: int               # 1-based plate number, as labelled on the figure
    t: float
    P: float
    beta: float              # (k/4EI)^(1/4), 1/in
    offset: float            # the solved rigid offset d_i, in
    k: float = 0.0           # this plate's own foundation modulus, lb/in/in
    material: str = ""       # what it was taken from, for the printout

    @property
    def k_msi(self) -> float:
        return self.k / 1.0e6

    @property
    def beta_t(self) -> float:
        """The dimensionless number that says whether refinement matters.

        β·t < ~1 → bearing is near-uniform, the baseline is already right.
        β·t > ~2 → bearing peaks hard toward the shear plane.
        """
        return self.beta * self.t

    @property
    def characteristic_length(self) -> float:
        """1/β, in — the distance over which bolt deflection decays."""
        return 1.0 / self.beta if self.beta > 0 else math.inf


@dataclass(frozen=True)
class RefinedResult:
    """Baseline and refined analyses side by side, plus the basis."""

    baseline: BoltAnalysis
    refined: BoltAnalysis
    strips: list[Layer]
    basis: FoundationBasis
    plates: list[PlateBearing]
    residual: float               # ||Ax-b||/||b|| of the linear solve
    load_error: float             # worst |Σstrips − P_i|/|P_i| BEFORE normalising
                                  # — a strip-resolution measure, see the
                                  # module constants
    huth_C: float | None = field(default=None)
    model_C: float | None = field(default=None)

    @property
    def moment_ratio(self) -> float:
        """Refined peak moment / baseline peak moment."""
        b = abs(self.baseline.M_max.M)
        return abs(self.refined.M_max.M) / b if b > 1e-12 else 1.0

    @property
    def conservatism_recovered(self) -> float:
        """Fractional reduction in peak moment, e.g. 0.156 for −15.6%."""
        return 1.0 - self.moment_ratio

    @property
    def refinement_is_material(self) -> bool:
        """True when the refinement actually changes the answer enough to
        care. Below this the baseline is already the right model and the
        refined view is noise."""
        return self.conservatism_recovered > 0.02

    @property
    def max_beta_t(self) -> float:
        return max((p.beta_t for p in self.plates), default=0.0)

    @property
    def mixed_stack(self) -> bool:
        """True when the plates do not all share one foundation modulus.

        A mixed stack has no single `k`, so the display must show the
        per-plate column rather than one headline number.
        """
        return len({round(p.k, 6) for p in self.plates}) > 1

    @property
    def trustworthy(self) -> bool:
        """False when the solve did not actually satisfy what it was given.

        Two direct measures rather than a condition number: the linear
        residual of the solve, and how far the strip discretisation sat from
        each plate's entered load before being normalised onto it. See
        `RESIDUAL_WARN` / `LOAD_ERROR_WARN` for what each one actually
        measures and where the thresholds came from.
        """
        return (self.residual < RESIDUAL_WARN
                and self.load_error < LOAD_ERROR_WARN)

    @property
    def cross_check_ratio(self) -> float | None:
        """model_C / huth_C. Near 1 means the derived k reproduces the
        published lumped compliance; far from 1 warrants a look."""
        if not self.huth_C or not self.model_C:
            return None
        return self.model_C / self.huth_C


# ══════════════════════════════════════════════════════════════════════════
# The solve
# ══════════════════════════════════════════════════════════════════════════
def _bolt_EI(d_bolt: float, E_bolt_msi: float) -> float:
    return E_bolt_msi * 1.0e6 * math.pi * d_bolt**4 / 64.0


def _solve(layers, ks, EI, elements_per_inch, strips_per_plate):
    """Assemble and solve.

    Returns `(strip layers, plate offsets, residual, load_error)`.

    Args:
        ks: Foundation modulus per LAYER index, lb/in per in. Each plate
            may sit on its own bed — a steel doubler and an aluminium
            skin in one stack have genuinely different bearing stiffness,
            and averaging them would smear the peaking onto the wrong
            plate. Gap entries are ignored.
    """
    segs, x = [], 0.0
    for ly in layers:
        segs.append((ly, x, x + ly.thickness))
        x += ly.thickness
    L = x
    if L <= 0:
        return [Layer(ly.kind, ly.thickness, ly.load) for ly in layers], {}, 0.0, 0.0

    plates = [(i, a, b) for i, (ly, a, b) in enumerate(segs)
              if ly.kind == "plate" and ly.thickness > 0]
    if not plates:
        return [Layer(ly.kind, ly.thickness, ly.load) for ly in layers], {}, 0.0, 0.0

    ne = max(60, int(elements_per_inch * L))
    Le = L / ne
    xn = np.linspace(0.0, L, ne + 1)
    nd = 2 * (ne + 1)
    npl = len(plates)

    ke = (EI / Le**3) * np.array([
        [12, 6*Le, -12, 6*Le],
        [6*Le, 4*Le*Le, -6*Le, 2*Le*Le],
        [-12, -6*Le, 12, -6*Le],
        [6*Le, 2*Le*Le, -6*Le, 4*Le*Le]])
    # Consistent Winkler foundation matrix and load vector, per unit k. The
    # plate's own k multiplies them at assembly time.
    kf1 = (Le / 420) * np.array([
        [156, 22*Le, 54, -13*Le],
        [22*Le, 4*Le*Le, 13*Le, -3*Le*Le],
        [54, 13*Le, 156, -22*Le],
        [-13*Le, -3*Le*Le, -22*Le, 4*Le*Le]])
    fv1 = (Le / 12) * np.array([6.0, Le, 6.0, -Le])

    n = nd + npl
    A = np.zeros((n, n))
    rhs = np.zeros(n)

    centres = 0.5 * (xn[:-1] + xn[1:])
    owner = np.full(ne, -1, dtype=int)
    for j, (_, a, b) in enumerate(plates):
        owner[(centres > a) & (centres < b)] = j

    for e in range(ne):
        dofs = [2*e, 2*e+1, 2*e+2, 2*e+3]
        A[np.ix_(dofs, dofs)] += ke
        j = owner[e]
        if j >= 0:
            k = ks[plates[j][0]]
            A[np.ix_(dofs, dofs)] += k * kf1
            A[np.ix_(dofs, [nd + j])] -= (k * fv1).reshape(-1, 1)
            A[nd + j, dofs] -= k * fv1          # ∫k(d_i − w)dx = P_i
            A[nd + j, nd + j] += k * Le
    for j, (i, _a, _b) in enumerate(plates):
        rhs[nd + j] = segs[i][0].load

    # Pin lateral deflection at head and nut: removes the two rigid-body null
    # modes. A boundary condition on the SHAPE solve only — these reactions
    # are not R_0/R_L, which the kernel recomputes from the strips. Module doc.
    for dof in (0, 2 * ne):
        A[dof, :] = 0.0
        A[:, dof] = 0.0
        A[dof, dof] = 1.0
        rhs[dof] = 0.0

    sol = np.linalg.solve(A, rhs)

    # Solution quality, measured directly. `np.linalg.cond` used to sit here
    # and was dropped: it is insensitive to k (sweeping E over 10^6 did not
    # move it at all) and scales as h^-4 and d^4 instead, so it reported
    # "untrustworthy" for an ordinary 1 in bolt and for any REFINED mesh while
    # the answers agreed to six figures. It measured the beam matrix's
    # intrinsic conditioning, not whether the solve worked. It was also an SVD
    # on the largest matrix here, so removing it is a speedup.
    nrm = float(np.linalg.norm(rhs))
    residual = float(np.linalg.norm(A @ sol - rhs)) / nrm if nrm > 0 else 0.0
    w = sol[0:nd:2]
    offsets = {plates[j][0]: float(sol[nd + j]) for j in range(npl)}

    # ── subdivide each plate into strips carrying the solved distribution ──
    out: list[Layer] = []
    load_error = 0.0
    for idx, (ly, a, b) in enumerate(segs):
        if ly.kind != "plate" or ly.thickness <= 0:
            # Pass a plate's load through even when it has no thickness to
            # spread it over. Zeroing it here would make the refined stack
            # balance while the baseline's does not, so the same input would
            # be gated differently by the two models. Let the kernel's closure
            # check see the same loads in both.
            out.append(Layer(ly.kind, ly.thickness,
                             ly.load if ly.kind == "plate" else 0.0))
            continue
        edges = np.linspace(a, b, strips_per_plate + 1)
        wc = np.interp(0.5 * (edges[:-1] + edges[1:]), xn, w)
        P = ks[idx] * (offsets[idx] - wc) * (ly.thickness / strips_per_plate)
        total = P.sum()

        # How far the SOLVED distribution is from the constraint it was given,
        # measured BEFORE the normalisation below. This is the real quality
        # gate: the normalisation forces the right total onto a wrong shape,
        # so checking after it would always pass and mask a bad solve.
        if abs(ly.load) > 1e-12:
            load_error = max(load_error, abs(total - ly.load) / abs(ly.load))

        if abs(total) > 1e-12:
            P = P * (ly.load / total)          # honour the entered load split
        else:
            P = np.full(strips_per_plate, ly.load / strips_per_plate)
        out += [Layer("plate", ly.thickness / strips_per_plate, float(p))
                for p in P]
    return out, offsets, residual, load_error


def refined_analysis(
    layers: list[Layer],
    *,
    d_bolt: float,
    E_bolt_msi: float,
    E_plate_msi: float | Sequence[float | None],
    plate_materials: Sequence[str] | None = None,
    close_moment: bool = True,
    elements_per_inch: int = ELEMENTS_PER_INCH,
    strips_per_plate: int = STRIPS_PER_PLATE,
) -> RefinedResult:
    """Run the baseline and the refined bearing solve side by side.

    Args:
        layers:        The stack, head to nut — the same list the baseline uses.
        d_bolt:        Bolt shank diameter, in (sets EI).
        E_bolt_msi:    Bolt Young's modulus, Msi.
        E_plate_msi:   Plate Young's modulus, Msi. A scalar puts every plate on
                       one bed. A sequence is **per layer**, aligned with
                       `layers` — one entry per entry, `None` for gaps or to
                       fall back to the stack's first stated modulus. A steel
                       doubler and an aluminium skin have genuinely different
                       bearing stiffness, and the peaking follows the stiffer
                       plate, so averaging them puts it on the wrong one.
        plate_materials: Optional per-layer names, carried into the printout so
                       the basis for each `k` travels with the result.
        close_moment:  Passed through to `analyse()` for both runs.

    Returns:
        A `RefinedResult` carrying both analyses, the per-plate β·t
        diagnostics, the documented basis, and the Huth cross-check.
    """
    Es = _per_layer_moduli(layers, E_plate_msi)
    names = list(plate_materials or [])
    names += [""] * (len(layers) - len(names))

    # The headline basis is the governing plate's — the one that peaks hardest
    # — so a mixed stack never advertises a modulus no plate actually has.
    bases = {i: tate_rosenfeld_k(E) for i, E in Es.items()}
    EI = _bolt_EI(d_bolt, E_bolt_msi)

    baseline = analyse(layers, close_moment=close_moment)
    ks = {i: b.k for i, b in bases.items()}
    strips, offsets, residual, load_error = _solve(
        layers, ks, EI, elements_per_inch, strips_per_plate)
    refined = analyse(strips, close_moment=close_moment)

    plates: list[PlateBearing] = []
    n = 0
    for idx, ly in enumerate(layers):
        if ly.kind != "plate" or ly.thickness <= 0:
            continue
        n += 1
        k = ks.get(idx, 0.0)
        beta = (k / (4.0 * EI)) ** 0.25 if EI > 0 and k > 0 else 0.0
        plates.append(PlateBearing(
            index=n, t=ly.thickness, P=ly.load, beta=beta,
            offset=offsets.get(idx, 0.0), k=k, material=names[idx]))

    governing = max(plates, key=lambda q: q.beta_t, default=None)
    basis = (bases[_layer_index_of(layers, governing.index)]
             if governing is not None and bases else tate_rosenfeld_k(0.0))

    huth_C, model_C = _cross_check(
        layers, plates, d_bolt, E_bolt_msi, Es)

    return RefinedResult(
        baseline=baseline, refined=refined, strips=strips, basis=basis,
        plates=plates, residual=residual, load_error=load_error,
        huth_C=huth_C, model_C=model_C)


def _layer_index_of(layers: list[Layer], plate_number: int) -> int:
    """Layer index of the nth loaded plate (1-based), as `plates` numbers them."""
    n = 0
    for i, ly in enumerate(layers):
        if ly.kind == "plate" and ly.thickness > 0:
            n += 1
            if n == plate_number:
                return i
    return 0


def _per_layer_moduli(
    layers: list[Layer], E_plate_msi: float | Sequence[float | None],
) -> dict[int, float]:
    """Resolve the modulus argument to {layer index: E in Msi} for plates.

    A scalar applies to every plate. A sequence is positional over `layers`;
    `None` or a non-positive entry falls back to the first stated modulus in
    the stack, so a half-filled material list degrades to the old behaviour
    instead of producing a zero-stiffness plate.
    """
    if isinstance(E_plate_msi, (int, float)):
        seq: list[float | None] = [float(E_plate_msi)] * len(layers)
    else:
        seq = list(E_plate_msi)
        seq += [None] * (len(layers) - len(seq))

    stated = [E for E in seq if E is not None and E > 0]
    fallback = stated[0] if stated else 10.7

    out: dict[int, float] = {}
    for i, ly in enumerate(layers):
        if ly.kind != "plate" or ly.thickness <= 0:
            continue
        E = seq[i] if i < len(seq) else None
        out[i] = float(E) if E is not None and E > 0 else fallback
    return out


def _cross_check(layers, plates, d_bolt, E_bolt_msi, Es):
    """Huth lumped compliance vs the model's own relative plate displacement.

    Compares the two plates carrying the largest opposing loads: Huth predicts
    a relative displacement C·P between them; the model produces `d_i − d_j`
    directly. The ratio is a sanity check on the derived `k`, NOT an input to
    it — the two come from independent sources by design.
    """
    if len(plates) < 2:
        return None, None
    pos = max((p for p in plates if p.P > 0), key=lambda p: p.P, default=None)
    neg = min((p for p in plates if p.P < 0), key=lambda p: p.P, default=None)
    if pos is None or neg is None:
        return None, None

    P = min(abs(pos.P), abs(neg.P))
    if P <= 0:
        return None, None

    # Each plate brings its own modulus. k = E under Tate & Rosenfeld, so the
    # PlateBearing's k IS the modulus Huth wants for that plate.
    huth_C = huth_compliance(
        d_bolt, pos.t, neg.t, pos.k_msi or 10.7, neg.k_msi or 10.7,
        E_bolt_msi, n_shear_planes=2)
    model_C = abs(pos.offset - neg.offset) / P
    return huth_C, model_C
