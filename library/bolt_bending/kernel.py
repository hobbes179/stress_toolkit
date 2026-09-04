"""
library/bolt_bending/kernel.py

Shear and moment along a bolt in a multi-layer joint, and the resulting
strength margins. Pure engineering math — nothing here imports Streamlit.

Ported from the standalone single-file browser tool archived at
`docs/bolt_bending/index.html`; the original specification is
`docs/bolt_bending/HANDOFF.md`. The mechanics are unchanged from that tool
except for the equilibrium gate described under "Force closure" below, which
was defect §4.1 in the handoff.

═══════════════════════════════════════════════════════════════════════════
MODEL
═══════════════════════════════════════════════════════════════════════════
The bolt is a straight beam whose axis x runs from the head bearing face
(x = 0) to the nut face (x = L), where L is the total grip. The only
transverse loads are the bearing pressures the plates apply to the shank plus
the end pair that closes the residual moment (see below). Bending is taken in
a single plane, so the problem is one-dimensional.

Each plate bears **uniformly over its own thickness** — the conservative
baseline. Real bearing peaks toward the shear planes, which shortens the
effective moment arm. Gaps and spacers carry no bearing (w = 0): they support
nothing and simply pass shear across, which is why a spacer adds moment arm
at no benefit.

    w_i   = P_i / t_i                          bearing intensity, lbf/in
    ΣP_i  = 0                                  force closure (checked, §4.1)
    M_res = Σ P_i · x̄_i,  x̄_i = x0_i + t_i/2   residual moment about the head
    R_L   = −M_res / L,   R_0 = −R_L           end pair that closes M (below)

Segment recursion, u = x − x0, constant w:

    V(u) = V_0 + w·u
    M(u) = M_0 + V_0·u + ½·w·u²

Start V = R_0, M = 0 at the head, walk the segments in order, carry end
values into the next. Shear is piecewise linear, moment piecewise quadratic,
so the only interior stationary point of M is where V = 0, at u* = −V_0/w,
taken only when 0 < u* < segment length. R_L is added to V at the nut.

═══════════════════════════════════════════════════════════════════════════
CLOSING THE RESIDUAL MOMENT — ⚠️ ASSUMPTION
═══════════════════════════════════════════════════════════════════════════
`R_0` and `R_L` are equal, opposite and separated by L, so their resultant is
a **pure couple of magnitude M_res**. That resultant is the only thing this
model actually asserts; the split into two lateral point forces is a
bookkeeping device for delivering it, not a claim about a specific contact.

It is NOT the head and nut bearing sideways. Nothing at the underside of a
head can react a lateral force — there is no surface for it to push against.
What physically reacts the residual moment in a preloaded joint is the
**redistribution of clamp pressure across the head and nut undersides**: as
the bolt tries to tilt, the annular contact pressure shifts toward one edge.
That shift is a moment, and it needs no change in bolt tension while the
annulus stays in contact. For a 3/8 hex head the annulus carries roughly
0.10·P_clamp lb·in before the light-side edge lifts; past that the contact
patch collapses to one side, the reaction resultant walks off-axis, and the
bolt does pick up axial tension — classic prying, which is not modelled here.

The choice matters, because a force pair and an end moment are equivalent
globally but not locally: the pair injects shear at the ends (V(0) = R_0 ≠ 0)
where an end moment would not. On the §6 verification case the three
defensible closures of the same M_res give

    force pair at head and nut (this model)   peak |M| = 278.7 lb·in
    end moment at the head alone             peak |M| = 250.0 lb·in
    end moments split head/nut               peak |M| = 280.0 lb·in

— about a 12% spread, with this model near the top of it. Not exposed as an
option: the analyst's lever is the loads, not the closure idealisation.

═══════════════════════════════════════════════════════════════════════════
FORCE CLOSURE — handoff defect §4.1, fixed here
═══════════════════════════════════════════════════════════════════════════
R_0 = −R_L adds no net force. That construction only restores equilibrium if
ΣP is already zero. When ΣP ≠ 0 the shear diagram does not return to zero at
the nut, M(L) ≠ 0, and every margin below is meaningless.

`BoltAnalysis.balanced` is False when |ΣP| > IMBALANCE_TOL · max|P_i|, and
`Margins.valid` then follows it. Callers must not present margins from an
invalid result as ordinary numbers — the UI badges them.

Physically a non-zero ΣP means something outside the model is reacting the
difference: friction at the faying surfaces from clamp-up, some restraint
outside the grip, or — most often — an input error such as a missing layer or
a sign flip. It is NOT reacted at the head or nut: those bear axially on the
plate faces and have nothing to push against laterally.

═══════════════════════════════════════════════════════════════════════════
SECTION — constant along the bolt (handoff defect §4.2 NOT fixed)
═══════════════════════════════════════════════════════════════════════════
Z and A are evaluated at one user-chosen diameter and held constant, so the
critical station is selected by max|M| rather than by max|M/Z|. With a
shank-to-thread transition or an undercut inside the bending region that can
check the wrong station and report a non-conservative margin.

⚠️ ASSUMPTION — no thread runout, undercut, or diameter change falls within
the bending region. Enter the minor diameter as `d_section` if threads do
reach the peak moment; that is conservative everywhere but exact nowhere.
Station-varying section is logged as future work in `apps/bolt_bending/CLAUDE.md`.

═══════════════════════════════════════════════════════════════════════════
UNITS
═══════════════════════════════════════════════════════════════════════════
Inches, pounds. Layer thicknesses in in, layer loads in lbf, moments in
lb·in. Allowables are entered in **ksi** and stresses are returned in **ksi**,
matching the rest of the toolkit; the conversion happens inside `margins()`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Sequence

# Force-closure tolerance: |ΣP| above this fraction of the largest layer load
# counts as unbalanced (handoff §4.1). Deliberately a pure ratio — the old
# JS test mixed an absolute 0.5 lbf floor with a scaled term and was ad hoc.
IMBALANCE_TOL = 0.005

# Number of sampled stations per segment, used to draw the diagrams. Exact
# stationary points are added on top of this, so accuracy of the reported
# peak does not depend on N.
SAMPLES_PER_SEGMENT = 36

LayerKind = Literal["plate", "gap"]


# ══════════════════════════════════════════════════════════════════════════
# Inputs
# ══════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Layer:
    """One layer of the stack, ordered head to nut.

    Args:
        kind: "plate" (bears on the shank) or "gap" (spacer or air — no bearing).
        t:    Thickness along the bolt axis, in. Negative values clamp to 0.
        P:    Transverse load the layer applies to the bolt, lbf. Positive and
              negative denote opposing sides of the load path. Ignored (taken
              as 0) when kind is "gap".
    """

    kind: LayerKind
    t: float
    P: float = 0.0

    @property
    def thickness(self) -> float:
        """Thickness clamped at zero — a negative entry must not run x backwards."""
        return max(self.t, 0.0)

    @property
    def load(self) -> float:
        """Transverse load, forced to zero for a gap."""
        return self.P if self.kind == "plate" else 0.0


@dataclass(frozen=True)
class BoltSection:
    """Round solid bolt section.

    Args:
        d_shank:   Shank diameter, in. Used only for the grip/D screen.
        d_section: Diameter used for stress. Enter the thread minor diameter
                   if threads reach the bending region.
    """

    d_shank: float
    d_section: float

    @property
    def Z(self) -> float:
        """Elastic section modulus π d³/32, in³."""
        return math.pi * self.d_section**3 / 32.0

    @property
    def A(self) -> float:
        """Area π d²/4, in²."""
        return math.pi * self.d_section**2 / 4.0


@dataclass(frozen=True)
class Allowables:
    """Bolt material allowables and factors. Stresses in ksi.

    Args:
        Ftu:            Tensile ultimate, ksi.
        Fsu:            Shear ultimate, ksi.
        k_bending:      Bending shape factor. F_b = k · Ftu. A solid round has
                        a fully plastic shape factor of 1.7; 1.5 is the usual
                        defensible working value.
        fitting_factor: Fitting factor applied to the applied stress.
        shear_peak_factor:
                        Multiplier turning the average shear V/A into the value
                        compared against `Fsu`. **This depends on what Fsu is**,
                        and getting it wrong is worth 33%:

                        • **1.0 for a fastener allowable.** MMPDS-01 Table
                          8.1.4 tabulates fastener shear as ultimate load over
                          the shank area, so it is already an average and V/A
                          is the matching basis.
                        • **4/3 for a material shear strength.** On a solid
                          round the parabolic shear distribution peaks at 4/3
                          of the average, so a material Fsu must be compared
                          against that peak.

                        Defaults to 1.0 — the fastener case, which is what this
                        tool is for. The app sets it from the selected
                        material's category and says so on the Strength card.
    """

    Ftu: float
    Fsu: float
    k_bending: float = 1.5
    fitting_factor: float = 1.0
    shear_peak_factor: float = 1.0

    @property
    def Fb(self) -> float:
        """Bending modulus of rupture k·Ftu, ksi."""
        return self.k_bending * self.Ftu


# ══════════════════════════════════════════════════════════════════════════
# Outputs
# ══════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Segment:
    """One layer mapped onto the bolt axis."""

    x0: float
    x1: float
    w: float          # bearing intensity P/t, lbf/in (0 for a gap)
    kind: LayerKind
    P: float
    t: float

    @property
    def length(self) -> float:
        return self.x1 - self.x0


@dataclass(frozen=True)
class Station:
    """A sampled point on the diagrams."""

    x: float          # in, from the head face
    V: float          # lbf
    M: float          # lb·in


@dataclass(frozen=True)
class BoltAnalysis:
    """Result of `analyse()`. Statics only — no material, no margins."""

    segments: list[Segment]
    L: float                      # total grip, in
    stations: list[Station]
    sum_P: float                  # ΣP_i, lbf — zero in a valid model
    moment_residual: float        # M_res about the head, lb·in
    R0: float                     # head reaction, lbf
    RL: float                     # nut reaction, lbf
    M_max: Station                # station with the largest |M|
    V_max: float                  # largest |V| (signed value at that station)
    closes_moment: bool           # whether the R0/RL couple was applied
    balanced: bool                # closure satisfied (§4.1) — see `closure_*`
    imbalance_tol: float          # the lbf threshold `balanced` was tested against
    closure_V: float = 0.0        # |V(L)| after R_L, lbf — 0 in a valid model
    closure_M: float = 0.0        # |M(L)|, lb·in — 0 when close_moment is True
    moment_tol: float = 0.0       # the lb·in threshold `closure_M` was tested against
    starved: tuple[int, ...] = () # 1-based layers carrying load with no thickness

    @property
    def closes(self) -> bool:
        """True when the integrated diagrams actually return to zero.

        Distinct from `sum_P == 0`: a layer carrying load with **no thickness**
        contributes to ΣP and to the residual moment but applies no bearing
        (w = P/t is guarded to zero), so ΣP can be zero while V(L) and M(L)
        are not. `balanced` requires both.
        """
        return (self.closure_V <= self.imbalance_tol
                and self.closure_M <= self.moment_tol)

    @property
    def gap_thickness(self) -> float:
        """Total gap and spacer thickness, in — arm added with no support."""
        return sum(s.t for s in self.segments if s.kind == "gap")

    def layer_name_at(self, x: float) -> str:
        """Human name of the layer containing station x, e.g. 'in plate 2'."""
        i = 0
        for s in self.segments:
            if s.kind == "plate":
                i += 1
            if s.x0 - 1e-9 <= x <= s.x1 + 1e-9:
                return "in the gap" if s.kind == "gap" else f"in plate {i}"
        return ""


@dataclass(frozen=True)
class Margins:
    """Result of `margins()`. Stresses in ksi.

    `valid` is False when the underlying analysis failed force closure. Every
    number below is then meaningless and must not be displayed unqualified.
    """

    f_b: float                    # bending stress M_max/Z, ksi
    f_s: float                    # shear stress κ·V_max/A, ksi (κ = peak factor)
    F_b: float                    # bending allowable k·Ftu, ksi
    MS_bending: float
    MS_shear: float
    MS_combined: float
    critical: Station             # station governing the combined interaction
    R_b: float                    # bending ratio at `critical`
    R_s: float                    # shear ratio at `critical`
    valid: bool
    section: BoltSection = field(repr=False, default=BoltSection(0.0, 0.0))
    allowables: Allowables = field(repr=False, default=Allowables(0.0, 0.0))

    @property
    def MS_governing(self) -> float:
        """Lowest of the three margins."""
        return min(self.MS_bending, self.MS_shear, self.MS_combined)


# ══════════════════════════════════════════════════════════════════════════
# Statics
# ══════════════════════════════════════════════════════════════════════════
def analyse(layers: Sequence[Layer], close_moment: bool = True) -> BoltAnalysis:
    """Build the shear and moment diagrams along the bolt.

    Pure: same input, same output, no global state.

    Args:
        layers:       Stack ordered head to nut.
        close_moment: Apply the R_0/R_L end pair whose resultant is the
                      couple reacting the residual moment. Turn off to see the
                      raw imbalance. See "Closing the residual moment" above
                      for what that couple physically represents.

    Returns:
        A `BoltAnalysis`. Both diagrams close at the nut (V(L) = M(L) = 0)
        whenever `close_moment` is True and `balanced` is True — that is the
        standing arithmetic check.
    """
    segments: list[Segment] = []
    x = 0.0
    sum_P = 0.0
    moment_residual = 0.0

    for layer in layers:
        t = layer.thickness
        P = layer.load
        w = P / t if (layer.kind == "plate" and t > 0) else 0.0
        segments.append(Segment(x0=x, x1=x + t, w=w, kind=layer.kind, P=P, t=t))
        sum_P += P
        moment_residual += P * (x + t / 2.0)
        x += t

    L = x
    RL = (-moment_residual / L) if (close_moment and L > 0) else 0.0
    R0 = -RL

    # ── integrate segment by segment ──────────────────────────────────
    stations: list[Station] = []
    V, M = R0, 0.0
    N = SAMPLES_PER_SEGMENT

    for s in segments:
        length = s.length
        if length <= 0:
            continue
        V0, M0 = V, M
        for j in range(N + 1):
            u = length * j / N
            stations.append(
                Station(x=s.x0 + u, V=V0 + s.w * u, M=M0 + V0 * u + 0.5 * s.w * u * u)
            )
        # exact stationary point of M, where V crosses zero inside the segment
        if abs(s.w) > 1e-12:
            u = -V0 / s.w
            if 0.0 < u < length:
                stations.append(
                    Station(x=s.x0 + u, V=0.0, M=M0 + V0 * u + 0.5 * s.w * u * u)
                )
        V = V0 + s.w * length
        M = M0 + V0 * length + 0.5 * s.w * length * length

    stations.sort(key=lambda p: p.x)
    if stations:
        # the nut station AFTER R_L is applied — the shear jump at the nut.
        # Appended post-sort so it stays last; V here should return to zero.
        stations.append(Station(x=L, V=V + RL, M=M))

    # ── peaks ─────────────────────────────────────────────────────────
    M_max = Station(x=0.0, V=0.0, M=0.0)
    V_max = 0.0
    for p in stations:
        if abs(p.M) > abs(M_max.M):
            M_max = p
        if abs(p.V) > abs(V_max):
            V_max = p.V

    # ── closure (handoff §4.1, extended) ──────────────────────────────
    # ΣP = 0 is necessary but NOT sufficient. A layer carrying load with zero
    # (or negative, hence clamped) thickness applies no bearing, so its load
    # counts here and in M_res but never reaches the diagrams: ΣP can be zero
    # while V(L) and M(L) are not. Gating on the input sum alone let that case
    # through with confident, meaningless margins. Gate on the OUTPUT too.
    peak_P = max((abs(s.P) for s in segments), default=0.0)
    tol = IMBALANCE_TOL * peak_P
    # Moment scale from load × grip, not from max|M| — when the diagram is
    # wrong, max|M| is inflated and would slacken its own tolerance.
    moment_tol = tol * L

    closure_V = abs(V + RL)
    # M(L) is deliberately non-zero when the end pair is switched off; the
    # "unreacted residual" check covers that case instead.
    closure_M = abs(M) if close_moment else 0.0

    starved = tuple(
        i for i, s in enumerate(segments, start=1)
        if s.kind == "plate" and s.t <= 0.0 and abs(s.P) > 0.0
    )

    balanced = (abs(sum_P) <= tol
                and closure_V <= tol
                and closure_M <= moment_tol)

    return BoltAnalysis(
        segments=segments,
        L=L,
        stations=stations,
        sum_P=sum_P,
        moment_residual=moment_residual,
        R0=R0,
        RL=RL,
        M_max=M_max,
        V_max=V_max,
        closes_moment=close_moment,
        balanced=balanced,
        imbalance_tol=tol,
        closure_V=closure_V,
        closure_M=closure_M,
        moment_tol=moment_tol,
        starved=starved,
    )


# ══════════════════════════════════════════════════════════════════════════
# Strength
# ══════════════════════════════════════════════════════════════════════════
def margins(
    analysis: BoltAnalysis, section: BoltSection, allowables: Allowables
) -> Margins:
    """Bending, shear, and combined margins of safety.

        f_b  = M_max / Z            F_b = k · Ftu
        f_s  = κ · V_max / A        κ = Allowables.shear_peak_factor:
                                     1.0 against a fastener allowable (already
                                     an average), 4/3 against a material shear
                                     strength (the peak on a solid round)
        MS_b = F_b  / (f_b · FF) − 1
        MS_s = Fsu  / (f_s · FF) − 1
        MS_c = 1 / √( max over stations [ R_b² + R_s² ] ) − 1

    The combined check is evaluated **at every station** rather than pairing
    M_max with V_max. Those maxima sit at different places and pairing them is
    both wrong and needlessly harsh. Preserve this behaviour.

    Args:
        analysis:   Result of `analyse()`.
        section:    Bolt section — constant along the bolt (see module docstring).
        allowables: Material allowables in ksi, plus k and the fitting factor.

    Returns:
        A `Margins`. `valid` mirrors `analysis.balanced`: when force closure
        fails every number in the result is meaningless.
    """
    Z, A = section.Z, section.A
    FF = allowables.fitting_factor or 1.0
    Fb_psi = allowables.Fb * 1000.0
    Fsu_psi = allowables.Fsu * 1000.0

    # The shear peaking factor scales the AVERAGE V/A up to whatever basis
    # `Fsu` is stated on — see Allowables.shear_peak_factor. It must be applied
    # to the interaction scan as well as the standalone check, or the two would
    # disagree about the same station.
    kappa = allowables.shear_peak_factor or 1.0
    f_b_psi = abs(analysis.M_max.M) / Z if Z > 0 else math.inf
    f_s_psi = kappa * abs(analysis.V_max) / A if A > 0 else math.inf

    # combined interaction scanned station by station
    worst = 0.0
    critical = analysis.M_max
    R_b = R_s = 0.0
    for p in analysis.stations:
        rb = abs(p.M) * FF / (Z * Fb_psi) if Z > 0 and Fb_psi > 0 else math.inf
        rs = (kappa * abs(p.V) * FF / (A * Fsu_psi)
              if A > 0 and Fsu_psi > 0 else math.inf)
        r = rb * rb + rs * rs
        if r > worst:
            worst, critical, R_b, R_s = r, p, rb, rs

    MS_b = (Fb_psi / (f_b_psi * FF) - 1.0) if f_b_psi > 0 else math.inf
    MS_s = (Fsu_psi / (f_s_psi * FF) - 1.0) if f_s_psi > 0 else math.inf
    MS_c = (1.0 / math.sqrt(worst) - 1.0) if worst > 0 else math.inf

    return Margins(
        f_b=f_b_psi / 1000.0,
        f_s=f_s_psi / 1000.0,
        F_b=allowables.Fb,
        MS_bending=MS_b,
        MS_shear=MS_s,
        MS_combined=MS_c,
        critical=critical,
        R_b=R_b,
        R_s=R_s,
        valid=analysis.balanced,
        section=section,
        allowables=allowables,
    )


# ══════════════════════════════════════════════════════════════════════════
# Screening checks
# ══════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Check:
    """One screening line for the UI. `ok` False renders as a caution."""

    ok: bool
    text: str


def screening_checks(analysis: BoltAnalysis, section: BoltSection) -> list[Check]:
    """Equilibrium and engineering-judgement screens, in display order.

    These are advisory. The only one that invalidates the numbers is closure,
    which is also carried on `Margins.valid`.
    """
    a = analysis
    out: list[Check] = []

    # Closure, in the order that gives the most actionable diagnosis first.
    # A starved layer is reported by name because "the diagrams do not close"
    # would not tell anyone what to fix.
    if a.starved:
        which = ", ".join(str(i) for i in a.starved)
        plural = "s" if len(a.starved) > 1 else ""
        out.append(
            Check(
                False,
                f"**Layer{plural} {which}** carr{'y' if plural else 'ies'} "
                f"load but ha{'ve' if plural else 's'} no thickness. A layer "
                f"with zero thickness applies no bearing, so its load never "
                f"reaches the diagrams — every margin below is suppressed. "
                f"Give it a thickness, or move the load to a layer that has "
                f"one.",
            )
        )
    elif abs(a.sum_P) > a.imbalance_tol:
        out.append(
            Check(
                False,
                f"Plate loads sum to **{a.sum_P:,.1f} lbf**, not zero "
                f"(tolerance ±{a.imbalance_tol:,.1f} lbf). The diagrams do not "
                f"close and every margin below is suppressed. Check for a "
                f"missing layer or a sign flip.",
            )
        )
    elif not a.closes:
        # ΣP = 0 yet the integrated diagrams do not return to zero. Kept as a
        # distinct branch: it is the backstop for any future variant of the
        # starved-layer defect, not just the one we know about.
        out.append(
            Check(
                False,
                f"Loads sum to zero but the diagrams do not close: "
                f"**V(L) = {a.closure_V:,.1f} lbf**, "
                f"**M(L) = {a.closure_M:,.1f} lb·in**. Some load is not "
                f"reaching the bolt. Every margin below is suppressed.",
            )
        )
    else:
        out.append(Check(True, "Plate loads sum to zero, and the diagrams close."))

    if a.closes_moment:
        out.append(
            Check(
                True,
                f"Leftover moment **{a.moment_residual:,.1f} lb·in** closed "
                f"by a **{abs(a.RL):,.1f} lbf** end pair — a couple from "
                f"clamp pressure under the head and nut, not sideways "
                f"bearing. Method §3.",
            )
        )
    else:
        out.append(
            Check(
                abs(a.moment_residual) < 0.5,
                f"Leftover moment **{a.moment_residual:,.1f} lb·in** is unreacted, "
                f"so the diagram does not close at the nut.",
            )
        )

    ratio = a.L / section.d_shank if section.d_shank > 0 else 0.0
    if ratio > 1.5:
        out.append(Check(False, f"Grip/D = **{ratio:.2f}**. Bending is likely a driver."))
    else:
        tail = (
            "Bending is usually secondary below 1."
            if ratio < 1
            else "Borderline; keep the check."
        )
        out.append(Check(True, f"Grip/D = **{ratio:.2f}**. {tail}"))

    gap = a.gap_thickness
    if gap > 0:
        out.append(
            Check(False, f"**{gap:.3f} in** of gap adds arm with no bearing support.")
        )

    if section.d_section >= section.d_shank > 0:
        out.append(
            Check(
                False,
                "Section diameter is not smaller than the shank. Use the minor "
                "diameter if threads reach the peak moment.",
            )
        )

    return out


# ══════════════════════════════════════════════════════════════════════════
# Default stack — the handoff §6 verification case
# ══════════════════════════════════════════════════════════════════════════
def default_stack() -> list[Layer]:
    """The shipped default: the §6 verification case.

    Plates at t = 0.250 / 0.500 / 0.250 in carrying P = +1000 / −2000 / +1000
    lbf with a 0.060 in spacer between plates 1 and 2. L = 1.060 in, every
    plate at |w| = 4000 lbf/in, ΣP = 0, M_res = −60 lb·in, peak M = 278.7 lb·in
    at x = 0.546 in. Any refactor must still reproduce those numbers.
    """
    return [
        Layer("plate", 0.250, 1000.0),
        Layer("gap", 0.060, 0.0),
        Layer("plate", 0.500, -2000.0),
        Layer("plate", 0.250, 1000.0),
    ]


def symmetric_double_shear(t_outer: float = 0.250, t_inner: float = 0.500,
                           P: float = 2000.0) -> list[Layer]:
    """Symmetric double shear — the second verification case (handoff §6).

    M_res = 0 by symmetry, so R_0 = R_L = 0 and the peak moment has a clean
    closed form: M_max = P·(2·t_outer + t_inner)/8 at mid-grip.
    """
    return [
        Layer("plate", t_outer, P / 2.0),
        Layer("plate", t_inner, -P),
        Layer("plate", t_outer, P / 2.0),
    ]
