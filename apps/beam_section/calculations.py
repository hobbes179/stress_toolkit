"""
apps/beam_section/calculations.py

Stress and margin-of-safety calculations for the Beam Section module.

The Section object (from library.shapes) provides all the geometric
properties. This module computes per-point stresses and the overall MS
table from those properties and the applied loads.

All stresses in this module are in ksi unless otherwise noted.
Loads are in lb (forces) and lb·in (moments).
"""

from __future__ import annotations
from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

from library.shapes import Section, KeyPoint
from library.materials import Material


# ──────────────────────────────────────────────────────────────────────────
# Loads container
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Loads:
    """Applied section loads in IPS units."""
    P:  float = 0.0   # axial force (lb)
    Vy: float = 0.0   # shear in Y (lb)
    Vz: float = 0.0   # shear in Z (lb)
    My: float = 0.0   # bending about Y (lb·in)
    Mz: float = 0.0   # bending about Z (lb·in)
    T:  float = 0.0   # torsion about X (lb·in)


# ──────────────────────────────────────────────────────────────────────────
# Per-key-point stress calculation
# ──────────────────────────────────────────────────────────────────────────
def calc_stress_at_points(section: Section, loads: Loads) -> pd.DataFrame:
    """
    Compute the full stress state at each KeyPoint defined by the section.

    Returns a DataFrame with columns:
        KP, Description, y, z,
        σ_axial, σ_bend, σ_total,
        τ_Vy, τ_Vz, τ_T, τ_total,
        σ1, σ2, σ_vm
    """
    A   = section.area()
    Iy  = section.Iy()
    Iz  = section.Iz()
    Qy  = section.Qy()
    Qz  = section.Qz()
    tw_y = section.tw_y()
    tw_z = section.tw_z()
    tau_T = section.tau_T(loads.T)   # section-level max torsion stress (ksi)

    kps = section.key_points(loads.My, loads.Mz)
    rows = []

    for kp in kps:
        # Normal stresses (convert lb/in² → ksi via /1000)
        sa  = loads.P / A / 1000 if A > 0 else 0.0
        sb  = ((loads.My * kp.z / Iy if Iy > 0 else 0.0) +
               (loads.Mz * kp.y / Iz if Iz > 0 else 0.0)) / 1000
        sn  = sa + sb

        # Shear stresses
        tvy = (loads.Vy * Qy / (Iy * tw_y) / 1000
               if (Iy > 0 and tw_y > 0) else 0.0)
        tvz = (loads.Vz * Qz / (Iz * tw_z) / 1000
               if (Iz > 0 and tw_z > 0) else 0.0)
        # v2 Phase 0 interim combination (CHANGELOG.md v1.1.0): transverse
        # and torsional shear are collinear along a wall segment, not
        # orthogonal — RSS is unconservative. Algebraic combination (exact
        # per-wall signs) lands in Phase 2/3; this is the conservative
        # bound used until then.
        tau_total = math.sqrt(tvy**2 + tvz**2) + abs(tau_T)

        # Principal stresses (2D state)
        half = sn / 2
        radius = math.sqrt(half**2 + tau_total**2)
        s1 = half + radius
        s2 = half - radius
        svm = math.sqrt(s1**2 - s1 * s2 + s2**2)

        rows.append({
            "KP":          kp.id,
            "Description": kp.description,
            "y":           kp.y,
            "z":           kp.z,
            "σ_axial":     sa,
            "σ_bend":      sb,
            "σ_total":     sn,
            "τ_Vy":        tvy,
            "τ_Vz":        tvz,
            "τ_T":         tau_T,
            "τ_total":     tau_total,
            "σ1":          s1,
            "σ2":          s2,
            "σ_vm":        svm,
        })

    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────────────
# Margin of safety calculation
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class MSRow:
    """One row of the margin of safety table."""
    check:     str
    allowable: float | str
    sf:        float
    applied:   float | str
    ms:        float


def _safe_ms(allowable: float, sf: float, applied: float) -> float:
    """Compute MS = Allow / (SF · Applied) - 1, guarding division."""
    a = max(applied, 1e-12)
    return allowable / (sf * a) - 1


def interaction_ms(Ra: float, Rb: float, Rs: float) -> float:
    """
    Margin of safety from the v2 §3.6 combined-interaction curve
    (Bruhn C4-family):  (Ra + Rb) + Rs² = 1

    Normal-stress ratios (axial, bending) group linearly; shear enters
    quadratically. Closed-form solution for MS:

        MS = 2 / [ (Ra+Rb) + √( (Ra+Rb)² + 4·Rs² ) ] − 1

    Replaces the v1 RSS-style 1/√(Rc²+Rb²+Rs²) − 1 form (CHANGELOG.md
    v1.1.0), which reported MS = +0.41 at Ra=Rb=0.5, Rs=0 — a true
    zero-margin axial+bending state. This form gives MS = 0.0 there.
    """
    ra_rb = Ra + Rb
    denom = ra_rb + math.sqrt(ra_rb**2 + 4 * Rs**2)
    return 2 / denom - 1 if denom > 0 else 999.0


def calc_margin_table(
    df_stress: pd.DataFrame,
    material:  Material,
    section:   Section,
    sf_yield:  float,
    sf_ult:    float,
    loads:     Loads,
) -> pd.DataFrame:
    """
    Build the margin-of-safety table from the stress results.

    v2 §3.6 check set (CHANGELOG.md v1.1.0 — replaces the v1 six-check set
    outright, not alongside it):
      1. σ_vm vs Fty (yield, distortion energy — primary yield criterion)
      2. σ₁ vs Ftu (ultimate, max principal — only governs when σ₁ > 0)
      3. |σ₂| vs Fcy (compression yield — only governs when σ₂ < 0)
      4. τ_wall vs Fsu (shear ultimate)
      5. Combined interaction: (Ra+Rb) + Rs² = 1 curve (Bruhn C4-family),
         replacing the RSS-style 1/√(Rc²+Rb²+Rs²) − 1 form, which was
         unconservative (reported MS = +0.41 at a true zero-margin
         axial+bending state — see CHANGELOG.md). Ra/Rb/Rs are computed
         from SF_ult-factored applied stresses (see CHANGELOG.md
         "Interaction SF" note) so this check responds to the SF_ult
         control like every other row.

    Removed checks (see CHANGELOG.md for rationale): "σ₁ vs Fty" (max-
    normal-stress yield criterion — unconservative vs distortion energy
    for shear-dominated states) and "σ_vm vs Ftu" (von Mises is a yield
    criterion; pairing with an ultimate allowable was ad hoc and is
    superseded by checks 2 and 4).

    τ_wall is the per-point combined shear column ("τ_total"). In Phase 0
    this is the interim conservative combination
    √(τ_Vy²+τ_Vz²) + |τ_T|; Phase 2/3 replace it with the exact algebraic
    per-wall combination without changing this table's structure.
    """
    Fty = material.Fty or 0.0
    Ftu = material.Ftu or 0.0
    Fcy = material.Fcy or 0.0
    Fsu = material.Fsu or 0.0
    Fbu = section.effective_f_cozzone * Ftu

    s1_max  = df_stress["σ1"].max()
    s2_min  = df_stress["σ2"].min()
    svm_max = df_stress["σ_vm"].max()
    tau_max = df_stress["τ_total"].max()
    sb_max  = df_stress["σ_bend"].abs().max()

    A = section.area()
    sa = loads.P / A / 1000 if A > 0 else 0.0
    sa_abs = abs(sa)

    # Applied values for checks 2/3 are only "active" on their governing
    # sign; otherwise floored to ~0 by _safe_ms so the check trivially
    # passes rather than reporting a nonsensical MS.
    s1_applied = max(s1_max, 0.0)
    s2_applied = abs(min(s2_min, 0.0))

    # SF_ult scales the applied stress into each ratio (consistent with
    # every other check's MS = Allow/(SF·Applied) − 1 definition — see
    # CHANGELOG.md v1.1.0 "Interaction SF" note). The §3.6 handoff doc's
    # literal Ra/Rb/Rs formulas omit SF; baking it in here means the
    # interaction MS responds to the SF_ult sidebar control like every
    # other row, and MS=0 lands exactly at SF_ult·applied = allowable.
    Fa = Ftu if sa >= 0 else Fcy
    Ra = sf_ult * sa_abs / Fa if Fa > 0 else 0.0
    Rb = sf_ult * sb_max / Fbu if Fbu > 0 else 0.0
    Rs = sf_ult * tau_max / Fsu if Fsu > 0 else 0.0
    ms_int = interaction_ms(Ra, Rb, Rs)

    rows: list[dict] = [
        {"Check": "σ_vm vs Fty (yield)",
         "Allow": Fty, "SF": sf_yield, "Applied": svm_max,
         "MS": _safe_ms(Fty, sf_yield, svm_max)},

        {"Check": "σ₁ vs Ftu (ultimate)",
         "Allow": Ftu, "SF": sf_ult, "Applied": s1_applied,
         "MS": _safe_ms(Ftu, sf_ult, s1_applied)},

        {"Check": "|σ₂| vs Fcy (compression yield)",
         "Allow": Fcy, "SF": sf_yield, "Applied": s2_applied,
         "MS": _safe_ms(Fcy, sf_yield, s2_applied)},

        {"Check": "τ_wall vs Fsu (shear ultimate)",
         "Allow": Fsu, "SF": sf_ult, "Applied": tau_max,
         "MS": _safe_ms(Fsu, sf_ult, tau_max)},

        {"Check": "Combined interaction (Ra+Rb)+Rs²=1",
         "Allow": f"Fa={Fa:.1f}  Fbu={Fbu:.1f}  Fsu={Fsu:.1f}",
         "SF": sf_ult,
         "Applied": f"Ra={Ra:.3f}  Rb={Rb:.3f}  Rs={Rs:.3f}",
         "MS": ms_int},
    ]
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────────────
# Governing-stress lookup
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class GoverningStress:
    """Records the worst-case location & value for one stress type."""
    label:       str    # display label
    column:      str    # DataFrame column queried
    kp_id:       str    # KP identifier
    description: str    # KP description
    value:       float  # the governing stress value (ksi)
    unit:        str    # "ksi"


def find_governing(df_stress: pd.DataFrame) -> list[GoverningStress]:
    """Return one GoverningStress for each of the key stress types."""
    items = [
        ("Max σ₁ (principal)",   "σ1",      "max"),
        ("Min σ₂ (principal)",   "σ2",      "min"),
        ("Max σ_vm (von Mises)", "σ_vm",    "max"),
        ("Max τ_total (shear)",  "τ_total", "max"),
        ("Max σ_bend (bending)", "σ_bend",  "absmax"),
    ]
    out: list[GoverningStress] = []
    for label, col, mode in items:
        if mode == "max":
            idx = df_stress[col].idxmax()
        elif mode == "min":
            idx = df_stress[col].idxmin()
        else:  # absmax
            idx = df_stress[col].abs().idxmax()
        row = df_stress.loc[idx]
        out.append(GoverningStress(
            label       = label,
            column      = col,
            kp_id       = row["KP"],
            description = row["Description"],
            value       = row[col],
            unit        = "ksi",
        ))
    return out
