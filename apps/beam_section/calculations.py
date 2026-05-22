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
        tau_total = math.sqrt(tvy**2 + tvz**2 + tau_T**2)

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

    Includes:
      - σ₁ vs Fty (yield)
      - σ₁ vs Ftu (ultimate)
      - |σ₂| vs Fcy (compression yield)
      - τ_total vs Fsu (shear ultimate)
      - σ_vm vs Ftu (von Mises ultimate)
      - MMPDS combined interaction (Rc² + Rb² + Rs²)
    """
    Fty = material.Fty or 0.0
    Ftu = material.Ftu or 0.0
    Fcy = material.Fcy or 0.0
    Fsu = material.Fsu or 0.0
    Fbu = section.f_cozzone * Ftu

    s1_max  = df_stress["σ1"].max()
    s2_min  = df_stress["σ2"].min()
    svm_max = df_stress["σ_vm"].max()
    tau_max = df_stress["τ_total"].max()
    sb_max  = df_stress["σ_bend"].abs().max()

    A = section.area()
    sa_abs = abs(loads.P / A / 1000) if A > 0 else 0.0

    Rc = sa_abs / Ftu if Ftu > 0 else 0.0
    Rb = sb_max / Fbu if Fbu > 0 else 0.0
    Rs = tau_max / Fsu if Fsu > 0 else 0.0
    denom = math.sqrt(Rc**2 + Rb**2 + Rs**2)
    ms_int = 1 / denom - 1 if denom > 0 else 999.0

    rows: list[dict] = [
        {"Check": "σ₁ vs Fty (yield)",
         "Allow": Fty, "SF": sf_yield, "Applied": s1_max,
         "MS": _safe_ms(Fty, sf_yield, s1_max)},

        {"Check": "σ₁ vs Ftu (ultimate)",
         "Allow": Ftu, "SF": sf_ult, "Applied": s1_max,
         "MS": _safe_ms(Ftu, sf_ult, s1_max)},

        {"Check": "|σ₂| vs Fcy (compression yield)",
         "Allow": Fcy, "SF": sf_yield, "Applied": abs(s2_min),
         "MS": _safe_ms(Fcy, sf_yield, abs(s2_min))},

        {"Check": "τ_total vs Fsu (shear ultimate)",
         "Allow": Fsu, "SF": sf_ult, "Applied": tau_max,
         "MS": _safe_ms(Fsu, sf_ult, tau_max)},

        {"Check": "σ_vm vs Ftu (von Mises, ultimate)",
         "Allow": Ftu, "SF": sf_ult, "Applied": svm_max,
         "MS": _safe_ms(Ftu, sf_ult, svm_max)},

        {"Check": "MMPDS combined interaction §1.3",
         "Allow": "—", "SF": sf_ult, "Applied": "Rc²+Rb²+Rs²",
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
