"""
Tie-rod allowables and load ratios (build prompt §6).

Pure numpy. **Never imports Streamlit.**

Three allowable families, all per rod:

**Tension (§6.1).** The spherical bearing is normally the weakest link in the
assembly, so a *vendor rated* load is the primary input and `A_net * Ftu` is
only the fallback. Which source is active is carried on the result and must be
displayed — a margin computed off a fallback the engineer did not intend is the
kind of error that survives a review.

**Compression (§6.2).** Euler/Johnson column buckling:

    rho      = sqrt(I / A)
    L'       = L / sqrt(c)                  c = end_fixity, 1.0 = pinned-pinned
    lam      = L' / rho
    lam_crit = pi sqrt(2 E / Fcy)

    lam <= lam_crit  (Johnson):  F_c = Fcy [ 1 - Fcy lam^2 / (4 pi^2 E) ]
    lam >  lam_crit  (Euler):    F_c = pi^2 E / lam^2

    P_comp_allow = F_c A

Both branches give `Fcy/2` at `lam_crit`, and so do their slopes. That is not a
cosmetic detail: `P_comp_allow` is a function of `L`, and `L` is a design
variable, so this curve sits directly in the optimizer's objective. A step in it
is a place for a gradient method to get stuck.

**Yield.** `A * Fty` in tension (gross section) and `A * Fcy` in compression.
`Fty` is optional; `Fcy` is required, so the compression side always has both
checks available.

Load ratio (§6.3)
-----------------
Each check contributes an *effective* allowable — its raw allowable divided by
its own safety factor — and the governing check is simply the smallest of them:

    LR = |P| / min(effective allowables on the loaded side)
    MS = 1/LR - 1

Writing it that way means adding a check later is adding an entry to a list,
and the reported "source" is just the argmin. The safety factors are user
inputs with defaults (1.0 yield / 1.5 ultimate) — never hardcoded at a call
site.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Iterable

from library.tierod.model import Rod

__all__ = [
    "SafetyFactors",
    "Allowable",
    "ColumnState",
    "RodAllowables",
    "LoadRatio",
    "RodSpec",
    "ROD_SPECS",
    "lambda_crit",
    "johnson_stress",
    "euler_stress",
    "column_state",
    "tension_allowable",
    "tension_yield_allowable",
    "compression_allowable",
    "compression_yield_allowable",
    "rod_allowables",
    "load_ratio",
    "two_sided_load_ratio",
    "margin_of_safety",
]

NOT_SPECIFIED = "not specified"


# ----------------------------------------------------------------------
# Safety factors — user inputs, defaults only
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class SafetyFactors:
    """Applied to the LOAD, equivalently dividing the allowable.

    Defaults match the rest of the toolkit (`SF_yield = 1.0`,
    `SF_ult = 1.5`). They live here as defaults and nowhere else as constants:
    the UI owns the numbers.
    """

    ultimate: float = 1.5
    yield_: float = 1.0

    def __post_init__(self) -> None:
        for name in ("ultimate", "yield_"):
            value = float(getattr(self, name))
            if not (value > 0.0) or not math.isfinite(value):
                raise ValueError(f"safety factor {name} must be positive, got {value}")
            object.__setattr__(self, name, value)


# ----------------------------------------------------------------------
# Results
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Allowable:
    """One allowable and where it came from.

    `value is None` means the rod does not carry the data for this check. That
    is reported, never defaulted: a missing `Ftu` must not become an infinite
    tension allowable.
    """

    value: float | None
    source: str
    detail: str = ""

    @property
    def available(self) -> bool:
        return self.value is not None


@dataclass(frozen=True)
class ColumnState:
    """The column geometry behind a compression allowable — the intermediates
    a stress report has to show."""

    L: float
    rho: float
    L_eff: float
    lam: float
    lam_crit: float
    F_c: float
    branch: str          # 'Johnson' or 'Euler'


@dataclass(frozen=True)
class RodAllowables:
    """Every check available for one rod at one length."""

    rod_id: str
    L: float
    column: ColumnState
    tension_ult: Allowable
    tension_yield: Allowable
    compression_ult: Allowable
    compression_yield: Allowable

    def checks(self, sense: str, factors: SafetyFactors) -> list[tuple[str, float, float]]:
        """`[(label, effective allowable, raw allowable)]` for one sense.

        Only checks the rod actually has data for. The governing check is the
        smallest effective allowable, so callers never branch on check type.
        """
        if sense == "T":
            pairs = (
                ("ultimate", self.tension_ult, factors.ultimate),
                ("yield", self.tension_yield, factors.yield_),
            )
        elif sense == "C":
            pairs = (
                ("ultimate", self.compression_ult, factors.ultimate),
                ("yield", self.compression_yield, factors.yield_),
            )
        else:
            raise ValueError(f"sense must be 'T' or 'C', got {sense!r}")
        return [
            (f"{kind} — {a.source}", a.value / sf, a.value)
            for kind, a, sf in pairs
            if a.available
        ]


@dataclass(frozen=True)
class LoadRatio:
    """`LR = |P| / effective allowable`, plus the audit trail.

    `value is None` when the rod carries no usable allowable on the loaded
    side. The row is then reported as incomplete rather than as a margin.
    """

    value: float | None
    sense: str                      # 'T' or 'C'
    allowable: float | None         # raw, before the safety factor
    effective_allowable: float | None
    source: str
    margin: float | None


# ----------------------------------------------------------------------
# Column allowable (§6.2)
# ----------------------------------------------------------------------


def lambda_crit(E: float, Fcy: float) -> float:
    """`pi sqrt(2 E / Fcy)` — where the Johnson parabola meets the Euler
    hyperbola, tangentially, at `Fcy/2`."""
    if E <= 0.0 or Fcy <= 0.0:
        raise ValueError(f"E and Fcy must be positive, got E={E}, Fcy={Fcy}")
    return math.pi * math.sqrt(2.0 * E / Fcy)


def johnson_stress(E: float, Fcy: float, lam: float) -> float:
    """Short-column parabola. `Fcy` at zero slenderness, `Fcy/2` at
    `lam_crit`."""
    return Fcy * (1.0 - Fcy * lam * lam / (4.0 * math.pi**2 * E))


def euler_stress(E: float, lam: float) -> float:
    """Long-column hyperbola `pi^2 E / lam^2`. Independent of any strength
    property — a longer rod of stronger material buckles at the same load."""
    if lam <= 0.0:
        raise ValueError(f"slenderness must be positive for Euler, got {lam}")
    return math.pi**2 * E / (lam * lam)


def column_state(rod: Rod, L: float) -> ColumnState:
    """Slenderness and critical stress for one rod at length `L`."""
    if not (L > 0.0) or not math.isfinite(L):
        raise ValueError(f"rod {rod.id!r}: length must be positive, got {L}")
    if not (rod.A > 0.0):
        raise ValueError(f"rod {rod.id!r}: A must be positive, got {rod.A}")
    if rod.I is None or not (rod.I > 0.0):
        raise ValueError(f"rod {rod.id!r}: I must be positive, got {rod.I}")
    if not (rod.end_fixity > 0.0):
        raise ValueError(
            f"rod {rod.id!r}: end_fixity must be positive, got {rod.end_fixity}"
        )
    if rod.Fcy is None or not (rod.Fcy > 0.0):
        raise ValueError(f"rod {rod.id!r}: Fcy must be positive, got {rod.Fcy}")

    rho = math.sqrt(rod.I / rod.A)
    # L' = L / sqrt(c). Dividing by c instead is a silent factor of 2 at c = 4.
    L_eff = L / math.sqrt(rod.end_fixity)
    lam = L_eff / rho
    lam_c = lambda_crit(rod.E, rod.Fcy)

    if lam <= lam_c:
        F_c, branch = johnson_stress(rod.E, rod.Fcy, lam), "Johnson"
    else:
        F_c, branch = euler_stress(rod.E, lam), "Euler"

    return ColumnState(
        L=float(L), rho=rho, L_eff=L_eff, lam=lam, lam_crit=lam_c,
        F_c=F_c, branch=branch,
    )


def compression_allowable(rod: Rod, L: float) -> Allowable:
    """`P_comp_allow = F_c A`, the Euler/Johnson column allowable.

    A function of `L`, which is a design variable: lengthening a rod to improve
    its direction degrades its own compression allowable. That coupling is why
    the objective is on load ratio and not on load.
    """
    st = column_state(rod, L)
    return Allowable(
        value=st.F_c * rod.A,
        source=f"{st.branch} column (lam {st.lam:.1f} vs {st.lam_crit:.1f})",
        detail=st.branch,
    )


def compression_yield_allowable(rod: Rod) -> Allowable:
    """`A * Fcy`, material yield with no buckling — the Johnson branch's
    `lam -> 0` limit. Always available, since `Fcy` is a required field."""
    if rod.Fcy is None or not (rod.Fcy > 0.0):
        return Allowable(None, f"compression yield {NOT_SPECIFIED} (no Fcy)")
    return Allowable(rod.A * rod.Fcy, "A * Fcy", "compression yield")


# ----------------------------------------------------------------------
# Tension allowable (§6.1)
# ----------------------------------------------------------------------


def tension_allowable(rod: Rod) -> Allowable:
    """Vendor rated load if given, else `A_net * Ftu`, else nothing.

    Order matters and is not a preference: the bearing is usually weaker than
    the shank, so a rod that calculates strong on `A_net * Ftu` can still be
    limited by its rod end. When both are present the rating wins.
    """
    if rod.P_tension_allow is not None:
        value = float(rod.P_tension_allow)
        if not (value > 0.0):
            raise ValueError(
                f"rod {rod.id!r}: P_tension_allow must be positive, got {value}"
            )
        return Allowable(value, "vendor rated", "rod end")
    if rod.A_net is not None and rod.Ftu is not None:
        if rod.A_net <= 0.0 or rod.Ftu <= 0.0:
            raise ValueError(f"rod {rod.id!r}: A_net and Ftu must be positive")
        return Allowable(rod.A_net * rod.Ftu, "A_net * Ftu", "net section")
    return Allowable(
        None,
        f"tension {NOT_SPECIFIED} (needs a vendor rating, or A_net and Ftu)",
    )


def tension_yield_allowable(rod: Rod) -> Allowable:
    """`A * Fty` on the GROSS section.

    Gross area, not net: yielding of the full shank is the limit state, while
    the net section through the threads is an ultimate check. `Fty` is optional
    — without it there is simply no tension yield check, which is reported.
    """
    Fty = getattr(rod, "Fty", None)
    if Fty is None:
        return Allowable(None, f"tension yield {NOT_SPECIFIED} (no Fty)")
    if Fty <= 0.0:
        raise ValueError(f"rod {rod.id!r}: Fty must be positive, got {Fty}")
    return Allowable(rod.A * Fty, "A * Fty", "tension yield")


def rod_allowables(rod: Rod, L: float) -> RodAllowables:
    """Every check for one rod at one length, in one object."""
    return RodAllowables(
        rod_id=rod.id,
        L=float(L),
        column=column_state(rod, L),
        tension_ult=tension_allowable(rod),
        tension_yield=tension_yield_allowable(rod),
        compression_ult=compression_allowable(rod, L),
        compression_yield=compression_yield_allowable(rod),
    )


# ----------------------------------------------------------------------
# Load ratio and margin (§6.3)
# ----------------------------------------------------------------------


def margin_of_safety(lr: float | None) -> float | None:
    """`MS = 1/LR - 1`. Zero load is an infinite margin, not a divide by
    zero; an unavailable ratio stays unavailable."""
    if lr is None:
        return None
    if lr == 0.0:
        return float("inf")
    return 1.0 / lr - 1.0


def _ratio(magnitude: float, ra: RodAllowables, sense: str,
           factors: SafetyFactors) -> LoadRatio:
    checks = ra.checks(sense, factors)
    if not checks:
        word = "tension" if sense == "T" else "compression"
        return LoadRatio(None, sense, None, None,
                         f"{word} allowable {NOT_SPECIFIED}", None)
    label, eff, raw = min(checks, key=lambda c: c[1])
    value = abs(float(magnitude)) / eff
    return LoadRatio(value, sense, raw, eff, label, margin_of_safety(value))


def load_ratio(P: float, ra: RodAllowables, factors: SafetyFactors) -> LoadRatio:
    """One signed load against the allowables for its own sense."""
    return _ratio(P, ra, "T" if P >= 0.0 else "C", factors)


def two_sided_load_ratio(magnitude: float, ra: RodAllowables,
                         factors: SafetyFactors) -> LoadRatio:
    """A magnitude reachable in BOTH senses, against the weaker side.

    This is the right check for a symmetric orientation sweep: `n_hat*` and
    `-n_hat*` are both unit directions, so a rod that reaches `+||t||` reaches
    `-||t||` too and only `min(tension, compression)` matters (§7.2). For a tie
    rod that is almost always compression — a full-sweep design is a
    buckling-driven design.
    """
    options = [
        (sense, ra.checks(sense, factors)) for sense in ("T", "C")
    ]
    flat = [(sense, *c) for sense, checks in options for c in checks]
    if not flat:
        return LoadRatio(None, "C", None, None,
                         f"no allowable {NOT_SPECIFIED}", None)
    sense, label, eff, raw = min(flat, key=lambda c: c[2])
    value = abs(float(magnitude)) / eff
    return LoadRatio(value, sense, raw, eff, label, margin_of_safety(value))


# ----------------------------------------------------------------------
# Rod specs — a named section + material, assigned to rods
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class RodSpec:
    """A named bundle of the section and material properties a rod needs.

    Rods are grouped onto a handful of specs rather than each being given its
    own numbers: twelve individually-sized rods is not a thing anyone
    manufactures or assembles, and the grouping is also what makes a fail-safe
    layout reachable — a spec that carries the damaged case carries it for
    every rod assigned to it.

    A spec is section + material ONLY. Topology (which regions a rod spans) is
    a user input, and `end_fixity` is a joint property, so neither is touched.
    This is not the Phase-5 catalog snap; it is the data entry the strength
    checks need.
    """

    name: str
    E: float
    A: float
    I: float
    Fcy: float
    Ftu: float | None = None
    Fty: float | None = None
    A_net: float | None = None
    P_tension_allow: float | None = None
    note: str = ""

    FIELDS = ("E", "A", "I", "Fcy", "Ftu", "Fty", "A_net", "P_tension_allow")

    def apply_to(self, rod: Rod) -> None:
        for field in self.FIELDS:
            setattr(rod, field, getattr(self, field))

    def matches(self, rod: Rod) -> bool:
        return all(getattr(rod, f) == getattr(self, f) for f in self.FIELDS)

    def resized(self, **over) -> "RodSpec":
        return replace(self, **over)


def _specs(items: Iterable[RodSpec]) -> dict[str, RodSpec]:
    return {s.name: s for s in items}


# A starter list for the editor, not a catalog. Values are ordinary alloy-steel
# and CRES rod sections; edit or extend them in the app. `A_net` is the
# threaded root area, `P_tension_allow` is left None so the fallback
# `A_net * Ftu` is what is used until a real vendor rating is entered.
ROD_SPECS = _specs(
    [
        RodSpec(
            name='3/8" alloy steel', E=29.0e6, A=0.1104, I=9.71e-4,
            Fcy=180.0e3, Ftu=180.0e3, Fty=163.0e3, A_net=0.0775,
            note="0.375 dia, 3/8-24 threads",
        ),
        RodSpec(
            name='1/2" alloy steel', E=29.0e6, A=0.1963, I=3.07e-3,
            Fcy=180.0e3, Ftu=180.0e3, Fty=163.0e3, A_net=0.1419,
            note="0.500 dia, 1/2-20 threads",
        ),
        RodSpec(
            name='5/8" alloy steel', E=29.0e6, A=0.3068, I=7.49e-3,
            Fcy=180.0e3, Ftu=180.0e3, Fty=163.0e3, A_net=0.2260,
            note="0.625 dia, 5/8-18 threads",
        ),
        RodSpec(
            name='1/2" CRES A286', E=29.1e6, A=0.1963, I=3.07e-3,
            Fcy=95.0e3, Ftu=140.0e3, Fty=95.0e3, A_net=0.1419,
            note="corrosion resistant, lower Fcy",
        ),
        RodSpec(
            name='3/4" 6061-T6 tube', E=9.9e6, A=0.1963, I=1.15e-2,
            Fcy=35.0e3, Ftu=42.0e3, Fty=35.0e3, A_net=0.1963,
            note="0.75 OD x 0.095 wall — light, buckling-critical",
        ),
    ]
)
