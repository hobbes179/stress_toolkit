"""
library/analysis/crippling.py

Local crippling (short-wavelength plate buckling) of thin-walled OPEN sections,
and the Cozzone plastic-bending "unlock" it gates (CLAUDE.md future-work 10c).

Crippling is a section+material property — it needs NO member length or end
fixity (that is column buckling, a different module). Each thin-walled open
catalog shape decomposes into flat plate ELEMENTS; each element's crippling
stress Fcc depends only on its width/thickness ratio b/t, its edge support, and
the material (Fcy, Ec). The section crippling stress is the area-weighted mean
of its elements.

Two methods are computed side by side (owner decision 2026-07-17):

  • ELEMENT method (Needham/Boeing, primary — spot-checkable):
        Fcc_i / Fcy = Ce · [ (b/t)·√(Fcy/Ec) ]^(-0.75),  capped at Fcc ≤ Fcy
        Ce = 0.30 (one edge free) / 0.52 (no edge free)          ⚠️ VERIFY
        Fcc_section = Σ(Fcc_i·A_i) / Σ A_i     (area-weighted)

  • GERARD g-method (whole-section cross-check):
        Fcc / Fcy = β · [ (g·t²/A)·√(Ec/Fcy) ]^m,  capped at Fcc/Fcy ≤ 0.80
        β = 0.56, m = 0.85, g = flanges + cuts (per section type)  ⚠️ VERIFY

Both fits come from 1940s–50s crippling test data (Needham, Gerard, Heimerl);
neither is a rigorous bound. They typically agree to ~10–15%, and crippling
itself carries ~±15% scatter vs test — so the coefficients here are documented
DEFAULTS flagged ⚠️ VERIFY for reconciliation against the user's reference
(Bruhn C7 / Niu). Crippling cannot be cross-checked against the linear-elastic
FEM solver (it does no buckling analysis), so its reference is published curves.

How crippling enters the margins (v2.2.1 — element-wise, no tension-side gate):
the `σ_c vs Fcc` row checks each plate element's own peak compressive normal
stress (axial + bending, from the affine section field) against that element's
OWN crippling stress Fcc_i, and reports the worst element by ratio
(`worst_element_crippling`). This replaced the v2.2.0 area-weighted
`fcc_element`-vs-peak check, which was unconservative under bending (a stocky
web inflated the section-average Fcc and masked a slender compression flange).
The area-weighted `fcc_element` is retained for the uniform-compression (strut)
interpretation and the Crippling-tab display (`compression_bending_allowable`).
A crippling-sensitive section shows up as the `σ_c vs Fcc` row governing and
going negative. The tension bending fiber keeps the shape's plastic factor
(Fbu = f·Ftu) — the old blanket "f → 1.0 for thin-walled open sections" gate
(decision D5) was a proxy for "we don't check crippling," and is removed now
that we check it directly. All of this uses the ELEMENT method, not Gerard,
whose empirical 0.80·Fcy plateau is a displayed cross-check only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional
import math

EdgeCondition = Literal["OEF", "NEF"]   # one-edge-free / no-edge-free

# ── Method coefficients (⚠️ VERIFY against Bruhn C7 / Niu) ─────────────────
_CE = {"OEF": 0.30, "NEF": 0.52}        # element-method Needham coefficient
_ELEM_EXP = 0.75                         # element-method slenderness exponent
_GERARD_BETA = 0.56
_GERARD_M = 0.85
_GERARD_CUTOFF = 0.80                    # Gerard Fcc/Fcy plateau


@dataclass(frozen=True)
class PlateElement:
    """One flat plate element of a section (centroid-independent geometry)."""
    name: str
    b: float                 # flat width (in)
    t: float                 # thickness (in)
    edge: EdgeCondition      # "OEF" (one edge free) or "NEF" (no edge free)
    fibers: tuple = ()       # centroidal midline endpoints ((y,z), (y,z)) where
                             # this element's peak compression is evaluated for
                             # the element-wise crippling check (empty for
                             # manually built element lists)

    @property
    def area(self) -> float:
        return self.b * self.t

    @property
    def b_over_t(self) -> float:
        return self.b / self.t if self.t > 0 else float("inf")


@dataclass
class ElementResult:
    """Element-method crippling result for one plate element."""
    element: PlateElement
    fcc: float               # element crippling stress (ksi)

    @property
    def ratio(self) -> float:
        return self.fcc


@dataclass
class CripplingResult:
    """Section crippling outcome (both methods) + the Cozzone gate decision."""
    Fcy: float
    Ec: float
    elements: list                        # list[ElementResult]
    fcc_element: float                     # area-weighted section Fcc (ksi)
    fcc_min: float                         # weakest element Fcc (ksi)
    fcc_gerard: Optional[float]            # Gerard cross-check Fcc (ksi), or None
    fcc_governing: float                   # section Fcc used for gate + allowable
    gerard_g: Optional[int] = None
    notes: list = field(default_factory=list)

    @property
    def crippling_limited(self) -> bool:
        """True when local crippling can cap the compression fiber below yield,
        i.e. ANY plate element crripples below Fcy (`fcc_min < Fcy`). Uses the
        weakest ELEMENT, consistent with the element-wise `σ_c vs Fcc` margin row
        (`worst_element_crippling`) — a slender flange makes the section
        crippling-limited even if the area-weighted section Fcc stays at Fcy.
        Gerard's 0.80·Fcy plateau is a display-only cross-check."""
        return self.fcc_min < self.Fcy - 1e-9


# ──────────────────────────────────────────────────────────────────────────
# Core method math
# ──────────────────────────────────────────────────────────────────────────
def element_fcc(b: float, t: float, edge: EdgeCondition,
                Fcy: float, Ec: float) -> float:
    """
    Element-method (Needham/Boeing) crippling stress of one flat plate (ksi).
    Fcc/Fcy = Ce·[(b/t)·√(Fcy/Ec)]^(-0.75), capped at Fcy. Units: Fcy, Ec, and
    the result are all in ksi (Ec passed in ksi, not Msi).
    """
    if t <= 0 or b <= 0 or Fcy <= 0 or Ec <= 0:
        return 0.0
    lam = (b / t) * math.sqrt(Fcy / Ec)
    ratio = _CE[edge] * lam ** (-_ELEM_EXP)
    return min(ratio, 1.0) * Fcy          # cannot exceed yield


def section_fcc_element(elements: list, Fcy: float, Ec: float):
    """
    Area-weighted section crippling (element method). Returns
    (fcc_weighted, fcc_min, [ElementResult, ...]).
    """
    results = [ElementResult(e, element_fcc(e.b, e.t, e.edge, Fcy, Ec))
               for e in elements]
    tot_a = sum(e.area for e in elements)
    if tot_a <= 0:
        return 0.0, 0.0, results
    fcc_w = sum(r.fcc * r.element.area for r in results) / tot_a
    fcc_min = min(r.fcc for r in results)
    return fcc_w, fcc_min, results


def gerard_fcc(g: int, area: float, t_rep: float, Fcy: float, Ec: float) -> float:
    """
    Gerard g-method section crippling stress (ksi). t_rep is a representative
    (mean) thickness — for a section of non-uniform thickness this is an
    approximation (Gerard's method assumes uniform t), flagged by the caller.
    """
    if g <= 0 or area <= 0 or t_rep <= 0 or Fcy <= 0 or Ec <= 0:
        return 0.0
    x = (g * t_rep ** 2 / area) * math.sqrt(Ec / Fcy)
    ratio = _GERARD_BETA * x ** _GERARD_M
    return min(ratio, _GERARD_CUTOFF) * Fcy


# ──────────────────────────────────────────────────────────────────────────
# Per-shape plate-element decomposition (topology only — no user input)
# ──────────────────────────────────────────────────────────────────────────
def _elements_for(section) -> Optional[list]:
    """
    Flat plate elements of a thin-walled OPEN catalog shape, from its dims.
    Returns None for shapes crippling does not apply to (solids, closed tubes,
    imports). Flat widths subtract the supporting member's thickness; each
    outstanding element is "OEF" (free at its tip), each captured element "NEF".

    Each element also carries its two midline endpoints (centroidal (y,z)),
    read from the section's midline skeleton, so the element-wise crippling
    check (`worst_element_crippling`) can evaluate the compression on that
    element's extreme fiber. The skeleton segments correspond 1:1 to the
    elements below (per-shape index maps given inline).
    """
    name = getattr(section, "name", "")
    # Imported / custom polygons have no catalog dims (d1..d4) and no known
    # plate-element decomposition, so crippling does not apply — bail before
    # touching dims (an ImportedSection has no .d1).
    if name not in _GERARD_G:
        return None
    d1, d2, d3, d4 = section.d1, section.d2, section.d3, section.d4

    # Midline endpoints (centroidal) for the element-wise stress evaluation.
    geom = section.geometry()
    nodes, segs = geom.nodes, geom.segments

    def _fib(i: int) -> tuple:
        """Endpoints ((y,z),(y,z)) of skeleton segment i, centroid-relative."""
        s = segs[i]
        return (tuple(float(v) for v in nodes[s.n1]),
                tuple(float(v) for v in nodes[s.n2]))

    if name == "I-Beam / W-Shape":          # d1=bf d2=d d3=tf d4=tw
        bf, d, tf, tw = d1, d2, d3, d4       # segs: 0=web 1=top-L 2=top-R 3=bot-L 4=bot-R
        half = (bf - tw) / 2.0
        return [
            PlateElement("flange half (top-L)", half, tf, "OEF", _fib(1)),
            PlateElement("flange half (top-R)", half, tf, "OEF", _fib(2)),
            PlateElement("flange half (bot-L)", half, tf, "OEF", _fib(3)),
            PlateElement("flange half (bot-R)", half, tf, "OEF", _fib(4)),
            PlateElement("web", d - 2 * tf, tw, "NEF", _fib(0)),
        ]
    if name == "C-Beam / Channel":          # d1=bf d2=d d3=tf d4=tw
        bf, d, tf, tw = d1, d2, d3, d4       # segs: 0=web 1=top flange 2=bot flange
        return [
            PlateElement("top flange", bf - tw, tf, "OEF", _fib(1)),
            PlateElement("bot flange", bf - tw, tf, "OEF", _fib(2)),
            PlateElement("web", d - 2 * tf, tw, "NEF", _fib(0)),
        ]
    if name == "Z-Beam":                    # d1=bf d2=d d3=tf d4=tw
        bf, d, tf, tw = d1, d2, d3, d4       # segs: 0=web 1=bot flange 2=top flange
        return [
            PlateElement("top flange", bf - tw, tf, "OEF", _fib(2)),
            PlateElement("bot flange", bf - tw, tf, "OEF", _fib(1)),
            PlateElement("web", d - 2 * tf, tw, "NEF", _fib(0)),
        ]
    if name == "T-Beam":                    # d1=bf d2=tf d3=hw d4=tw
        bf, tf, hw, tw = d1, d2, d3, d4      # segs: 0=web(stem) 1=flange L 2=flange R
        half = (bf - tw) / 2.0
        return [
            PlateElement("flange half (L)", half, tf, "OEF", _fib(1)),
            PlateElement("flange half (R)", half, tf, "OEF", _fib(2)),
            PlateElement("stem", hw, tw, "OEF", _fib(0)),   # free at bottom tip
        ]
    if name == "L-Beam / Angle":            # d1=b d2=h d3=tb d4=th
        b, h, tb, th = d1, d2, d3, d4        # segs: 0=horiz leg 1=vert leg
        return [
            PlateElement("leg 1", b - th, tb, "OEF", _fib(0)),
            PlateElement("leg 2", h - tb, th, "OEF", _fib(1)),
        ]
    if name == "Plus / Cross":              # d1=b d2=h d3=th d4=tv
        b, h, th, tv = d1, d2, d3, d4        # segs: 0=+y 1=-y 2=+z 3=-z
        harm = (b - tv) / 2.0
        varm = (h - th) / 2.0
        return [
            PlateElement("arm +y", harm, th, "OEF", _fib(0)),
            PlateElement("arm -y", harm, th, "OEF", _fib(1)),
            PlateElement("arm +z", varm, tv, "OEF", _fib(2)),
            PlateElement("arm -z", varm, tv, "OEF", _fib(3)),
        ]
    return None


# Gerard g = number of flanges + number of cuts (⚠️ VERIFY — Gerard/Bruhn C7).
_GERARD_G = {
    "L-Beam / Angle": 2,
    "T-Beam": 3,
    "C-Beam / Channel": 4,
    "Z-Beam": 4,
    "Plus / Cross": 4,
    "I-Beam / W-Shape": 7,
}


# ──────────────────────────────────────────────────────────────────────────
# Section-level summary + Cozzone gate
# ──────────────────────────────────────────────────────────────────────────
def _ec_ksi(material) -> float:
    """Compression modulus in ksi (prefer Ec, fall back to E). Library stores
    moduli in Msi, so ×1000."""
    e_msi = getattr(material, "Ec", None) or getattr(material, "E", None) or 0.0
    return float(e_msi) * 1000.0


def crippling_summary(section, material) -> Optional[CripplingResult]:
    """
    Full crippling summary (both methods) for a thin-walled open catalog shape,
    or None if crippling does not apply (other categories / imports) or the
    material lacks Fcy / modulus.
    """
    elements = _elements_for(section)
    if not elements:
        return None
    Fcy = getattr(material, "Fcy", None) or 0.0
    Ec = _ec_ksi(material)
    if Fcy <= 0 or Ec <= 0:
        return None

    fcc_w, fcc_min, results = section_fcc_element(elements, Fcy, Ec)

    notes: list = []
    g = _GERARD_G.get(getattr(section, "name", ""))
    fcc_g = None
    if g:
        total_len = sum(e.b for e in elements)
        area = sum(e.area for e in elements)
        t_rep = area / total_len if total_len > 0 else 0.0
        fcc_g = gerard_fcc(g, area, t_rep, Fcy, Ec)
        # Non-uniform thickness → Gerard's uniform-t assumption is approximate.
        if len({round(e.t, 6) for e in elements}) > 1:
            notes.append("Gerard uses a mean thickness (section is non-uniform) "
                         "— treat the g-method as an approximate cross-check.")

    # The gate + the compression-allowable cap use the ELEMENT method: it is
    # both the spot-checkable primary and the more conservative answer to "does
    # the section reach Fcy before crippling?". Gerard is a displayed cross-
    # check only — its empirical 0.80·Fcy plateau can never reach Fcy, so
    # min(element, Gerard) would make the credit impossible to ever unlock.
    fcc_governing = fcc_w

    return CripplingResult(
        Fcy=Fcy, Ec=Ec, elements=results,
        fcc_element=fcc_w, fcc_min=fcc_min, fcc_gerard=fcc_g,
        fcc_governing=fcc_governing, gerard_g=g, notes=notes,
    )


def compression_bending_allowable(Fcy: float,
                                  res: Optional[CripplingResult]) -> float:
    """
    Compression-fiber bending allowable: Fcy, capped at the governing crippling
    stress when a crippling summary is available (a slender compression element
    fails by crippling below yield). Uses the area-weighted section Fcc
    (`fcc_governing`) — the uniform-compression (strut) interpretation. The
    per-element bending check is `worst_element_crippling`.
    """
    if res is None:
        return Fcy
    return min(Fcy, res.fcc_governing)


def worst_element_crippling(res: Optional[CripplingResult], sigma_at):
    """
    Element-wise crippling check under a normal-stress field (v2.2.1).

    For each plate element, evaluate the longitudinal normal stress
    `sigma_at(y, z)` (ksi, compression negative) at the element's extreme
    fibers, take the most compressive, and compare it to that element's OWN
    crippling stress Fcc_i. Returns the worst element by ratio
    (applied / Fcc_i):

        (applied_ksi, fcc_i, element_name, (y, z))     or None

    None when no element carries compression (nothing to cripple) or no element
    has fiber coordinates (e.g. a manually built element list).

    This replaces the earlier area-weighted `fcc_element`-vs-peak check, which
    was unconservative under bending: a stocky interior element (e.g. a thick
    web) inflated the section-average Fcc and masked a slender extreme-fiber
    flange carrying the peak bending compression (CHANGELOG v2.2.1). The
    area-weighted `fcc_element` is kept for the uniform-compression (strut)
    interpretation and the Crippling-tab display.
    """
    if res is None:
        return None
    worst = None                       # (ratio, applied, fcc, name, (y,z))
    for er in res.elements:
        el = er.element
        if not el.fibers or er.fcc <= 0:
            continue
        smin = None
        spt = None
        for (y, z) in el.fibers:
            s = sigma_at(y, z)
            if smin is None or s < smin:
                smin, spt = s, (y, z)
        if smin is None or smin >= 0:      # element entirely in tension
            continue
        ratio = -smin / er.fcc
        if worst is None or ratio > worst[0]:
            worst = (ratio, -smin, er.fcc, el.name, spt)
    if worst is None:
        return None
    _, applied, fcc, name, spt = worst
    return applied, fcc, name, spt
