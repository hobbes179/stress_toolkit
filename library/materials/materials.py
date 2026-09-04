"""
library/materials/materials.py

Material allowables library for the Stress Toolkit.

Each material is a Material dataclass instance, registered in MATERIALS
(a dict keyed by display name). Apps look up materials by name from this
dict; properties not yet implemented in a given app can still be added
to a material without breaking anything.

═══════════════════════════════════════════════════════════════════════════
ESTIMATED VALUES CONVENTION
═══════════════════════════════════════════════════════════════════════════
When a property is not available from MMPDS for a given material we use a
conservative estimate and flag it. The convention is:

  1.  In the source code, mark the line with the comment marker:
          # ⚠️ ESTIMATED — <reason>
      Use the exact prefix "⚠️ ESTIMATED" so the marker is searchable.

  2.  Add the property's field name to `estimated_fields` on the Material
      so the UI can display an "EST" badge next to that value.

Example:
      Material(
          name="6061-T6",
          Fty=35, Ftu=42, ...,
          Fbru=1.5*42,     # ⚠️ ESTIMATED — MMPDS lacks bearing for sheet only
          estimated_fields=("Fbru",),
          ...
      )

═══════════════════════════════════════════════════════════════════════════
PROPERTY SCHEMA — all properties optional, default to None if unknown
═══════════════════════════════════════════════════════════════════════════
Strength allowables (ksi):
  Fty     Tensile yield
  Ftu     Tensile ultimate
  Fcy     Compressive yield
  Fsu     Shear ultimate
  Fbru    Bearing ultimate (e/D=1.5)
  Fbry    Bearing yield (e/D=1.5)

Stiffness (Msi):
  E       Young's modulus (tension)
  Ec      Compression modulus
  G       Shear modulus
  nu      Poisson's ratio (dimensionless)

Thermal:
  alpha   Coefficient of thermal expansion (in/in/°F × 10⁻⁶)
  k       Thermal conductivity (Btu·in / hr·ft²·°F)
  T_max   Maximum service temperature (°F)

Physical:
  rho     Density (lb/in³)

Metadata:
  category           One of CATEGORY_ORDER — "Aluminum" / "Steel" /
                     "Titanium" / "Stainless" / "Fastener". Add new
                     categories to CATEGORY_ORDER or they will not appear
                     in grouped UIs.
  source             MMPDS section or other reference
  notes              Free-form notes string
  estimated_fields   Tuple of field names that are estimates (not MMPDS)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Material:
    """A material with its allowables and physical properties."""

    name:     str
    category: str

    # ── Strength allowables (ksi) ─────────────────────────
    Fty:      Optional[float] = None
    Ftu:      Optional[float] = None
    Fcy:      Optional[float] = None
    Fsu:      Optional[float] = None
    Fbru:     Optional[float] = None
    Fbry:     Optional[float] = None

    # ── Stiffness ─────────────────────────────────────────
    E:        Optional[float] = None
    Ec:       Optional[float] = None
    G:        Optional[float] = None
    nu:       Optional[float] = None

    # ── Thermal ───────────────────────────────────────────
    alpha:    Optional[float] = None
    k:        Optional[float] = None
    T_max:    Optional[float] = None

    # ── Physical ──────────────────────────────────────────
    rho:      Optional[float] = None

    # ── Metadata ──────────────────────────────────────────
    source:           str = ""
    notes:            str = ""
    estimated_fields: tuple[str, ...] = field(default_factory=tuple)

    def is_estimated(self, prop_name: str) -> bool:
        """Return True if the named property is flagged as an estimate."""
        return prop_name in self.estimated_fields


# ═══════════════════════════════════════════════════════════════════════════
# MATERIAL LIBRARY
# ═══════════════════════════════════════════════════════════════════════════
# Sourced primarily from MMPDS-01. Values are room-temperature minimums for
# the dominant grain direction unless otherwise noted.
#
# To add a custom material, append it to MATERIALS below following the
# existing format. The name (dict key) must match Material.name.
# ═══════════════════════════════════════════════════════════════════════════

_materials: list[Material] = [

    # ── ALUMINUM ALLOYS ──────────────────────────────────────────────────
    Material(
        name="2024-T3 Sheet",  category="Aluminum",
        Fty=42, Ftu=62, Fcy=40, Fsu=37,
        Fbru=125, Fbry=85,
        E=10.7, Ec=10.9, G=4.0, nu=0.33,
        alpha=12.6, k=840, T_max=250,
        rho=0.101,
        source="MMPDS-01 §3.2.3.0",
        notes="L-direction; sheet 0.010–0.249 in",
    ),
    Material(
        name="2024-T351 Plate",  category="Aluminum",
        Fty=39, Ftu=58, Fcy=35, Fsu=35,
        Fbru=116, Fbry=78,
        E=10.7, Ec=10.9, G=4.0, nu=0.33,
        alpha=12.6, k=840, T_max=250,
        rho=0.101,
        source="MMPDS-01 §3.2.3.0",
    ),
    Material(
        name="2024-T4 Bar",  category="Aluminum",
        Fty=42, Ftu=62, Fcy=40, Fsu=37,
        Fbru=124, Fbry=84,
        E=10.7, Ec=10.9, G=4.0, nu=0.33,
        alpha=12.6, k=840, T_max=250,
        rho=0.101,
        source="MMPDS-01 §3.2.3.0",
    ),
    Material(
        name="6061-T6",  category="Aluminum",
        Fty=35, Ftu=42, Fcy=35, Fsu=25,
        Fbru=88, Fbry=58,
        E=10.0, Ec=10.1, G=3.8, nu=0.33,
        alpha=13.0, k=1075, T_max=250,
        rho=0.098,
        source="MMPDS-01 §3.7.3.0",
    ),
    Material(
        name="7075-T6 Sheet",  category="Aluminum",
        Fty=67, Ftu=77, Fcy=67, Fsu=46,
        Fbru=154, Fbry=108,
        E=10.4, Ec=10.7, G=3.9, nu=0.33,
        alpha=12.9, k=900, T_max=250,
        rho=0.101,
        source="MMPDS-01 §3.9.3.0",
    ),
    Material(
        name="7075-T651 Plate",  category="Aluminum",
        Fty=67, Ftu=77, Fcy=67, Fsu=46,
        Fbru=154, Fbry=108,
        E=10.4, Ec=10.7, G=3.9, nu=0.33,
        alpha=12.9, k=900, T_max=250,
        rho=0.101,
        source="MMPDS-01 §3.9.3.0",
    ),
    Material(
        name="7075-T73 Plate",  category="Aluminum",
        Fty=58, Ftu=68, Fcy=57, Fsu=41,
        Fbru=136, Fbry=92,
        E=10.4, Ec=10.7, G=3.9, nu=0.33,
        alpha=12.9, k=900, T_max=250,
        rho=0.101,
        source="MMPDS-01 §3.9.3.0",
    ),

    # ── STEEL ALLOYS ─────────────────────────────────────────────────────
    Material(
        name="4130 Normalized",  category="Steel",
        Fty=75, Ftu=95, Fcy=75, Fsu=57,
        Fbru=190, Fbry=120,
        E=29.0, Ec=29.0, G=11.0, nu=0.32,
        alpha=6.6, k=302, T_max=900,
        rho=0.284,
        source="MMPDS-01 §2.3.1.0",
    ),
    Material(
        name="4130 HT125",  category="Steel",
        Fty=112, Ftu=125, Fcy=112, Fsu=75,
        Fbru=219, Fbry=180,
        E=29.0, Ec=29.0, G=11.0, nu=0.32,
        alpha=6.6, k=302, T_max=900,
        rho=0.284,
        source="MMPDS-01 §2.3.1.0",
    ),
    Material(
        name="4130 HT150",  category="Steel",
        Fty=132, Ftu=150, Fcy=132, Fsu=90,
        Fbru=251, Fbry=212,
        E=29.0, Ec=29.0, G=11.0, nu=0.32,
        alpha=6.6, k=302, T_max=900,
        rho=0.284,
        source="MMPDS-01 §2.3.1.0",
    ),
    Material(
        name="4340 HT125",  category="Steel",
        Fty=112, Ftu=125, Fcy=112, Fsu=75,
        Fbru=219, Fbry=180,
        E=29.0, Ec=29.0, G=11.0, nu=0.32,
        alpha=6.6, k=296, T_max=900,
        rho=0.284,
        source="MMPDS-01 §2.3.4.0",
    ),
    Material(
        name="4340 HT180",  category="Steel",
        Fty=163, Ftu=180, Fcy=163, Fsu=108,
        Fbru=295, Fbry=261,
        E=29.0, Ec=29.0, G=11.0, nu=0.32,
        alpha=6.6, k=296, T_max=900,
        rho=0.284,
        source="MMPDS-01 §2.3.4.0",
    ),
    Material(
        name="300M",  category="Steel",
        Fty=215, Ftu=280, Fcy=215, Fsu=168,
        # ⚠️ ESTIMATED — Fbru/Fbry for 300M scarce in literature
        Fbru=1.6 * 280,  # ⚠️ ESTIMATED — Fbru ≈ 1.6·Ftu typical for high-strength steel
        Fbry=1.5 * 215,  # ⚠️ ESTIMATED — Fbry ≈ 1.5·Fty typical
        E=29.0, Ec=29.0, G=11.0, nu=0.32,
        alpha=6.4, k=290, T_max=600,
        rho=0.283,
        source="MMPDS-01 §2.3.8.0",
        estimated_fields=("Fbru", "Fbry"),
    ),
    Material(
        name="17-4 PH H900",  category="Steel",
        Fty=170, Ftu=190, Fcy=170, Fsu=114,
        Fbru=296, Fbry=255,
        E=28.5, Ec=28.5, G=11.0, nu=0.30,
        alpha=6.0, k=124, T_max=600,
        rho=0.282,
        source="MMPDS-01 §2.6.3.0",
    ),
    Material(
        name="17-4 PH H1025",  category="Steel",
        Fty=145, Ftu=155, Fcy=145, Fsu=93,
        Fbru=248, Fbry=218,
        E=28.5, Ec=28.5, G=11.0, nu=0.30,
        alpha=6.0, k=131, T_max=600,
        rho=0.282,
        source="MMPDS-01 §2.6.3.0",
    ),
    Material(
        name="A36 Structural",  category="Steel",
        Fty=36, Ftu=58, Fcy=36, Fsu=35,
        # ⚠️ ESTIMATED — A36 bearing not in MMPDS; AISC gives Fp = 1.5·Fy nominal
        Fbru=1.5 * 58,  # ⚠️ ESTIMATED — typical e/D=1.5 bearing estimate
        Fbry=1.5 * 36,  # ⚠️ ESTIMATED — yield bearing estimate
        E=29.0, Ec=29.0, G=11.2, nu=0.30,
        alpha=6.5, k=360, T_max=700,
        rho=0.284,
        source="AISC / ASTM A36",
        estimated_fields=("Fbru", "Fbry"),
    ),
    Material(
        name="A572 Gr.50",  category="Steel",
        Fty=50, Ftu=65, Fcy=50, Fsu=39,
        # ⚠️ ESTIMATED — A572 bearing values not tabulated in MMPDS
        Fbru=1.5 * 65,  # ⚠️ ESTIMATED — typical e/D=1.5 bearing estimate
        Fbry=1.5 * 50,  # ⚠️ ESTIMATED — yield bearing estimate
        E=29.0, Ec=29.0, G=11.2, nu=0.30,
        alpha=6.5, k=360, T_max=700,
        rho=0.284,
        source="AISC / ASTM A572",
        estimated_fields=("Fbru", "Fbry"),
    ),

    # ── TITANIUM ALLOYS ──────────────────────────────────────────────────
    Material(
        name="Ti-6Al-4V Annealed",  category="Titanium",
        Fty=120, Ftu=130, Fcy=120, Fsu=78,
        Fbru=199, Fbry=187,
        E=16.0, Ec=16.4, G=6.2, nu=0.31,
        alpha=4.9, k=46, T_max=800,
        rho=0.160,
        source="MMPDS-01 §5.4.3.0",
    ),
    Material(
        name="Ti-6Al-4V STA",  category="Titanium",
        Fty=150, Ftu=160, Fcy=155, Fsu=96,
        Fbru=246, Fbry=234,
        E=16.0, Ec=16.4, G=6.2, nu=0.31,
        alpha=4.9, k=46, T_max=750,
        rho=0.160,
        source="MMPDS-01 §5.4.3.0",
    ),
    Material(
        name="Ti-6Al-4V ELI",  category="Titanium",
        Fty=115, Ftu=125, Fcy=115, Fsu=75,
        Fbru=191, Fbry=180,
        E=16.0, Ec=16.4, G=6.2, nu=0.31,
        alpha=4.9, k=46, T_max=800,
        rho=0.160,
        source="MMPDS-01 §5.4.3.0",
        notes="ELI = Extra Low Interstitial",
    ),

    # ── STAINLESS STEELS ─────────────────────────────────────────────────
    Material(
        name="15-5 PH H900",  category="Stainless",
        Fty=170, Ftu=190, Fcy=170, Fsu=114,
        Fbru=296, Fbry=255,
        E=28.5, Ec=28.5, G=11.2, nu=0.30,
        alpha=6.0, k=124, T_max=600,
        rho=0.284,
        source="MMPDS-01 §2.6.6.0",
    ),
    Material(
        name="15-5 PH H1025",  category="Stainless",
        Fty=145, Ftu=160, Fcy=145, Fsu=96,
        Fbru=256, Fbry=218,
        E=28.5, Ec=28.5, G=11.2, nu=0.30,
        alpha=6.0, k=131, T_max=600,
        rho=0.284,
        source="MMPDS-01 §2.6.6.0",
    ),
    Material(
        name="17-7 PH TH1050",  category="Stainless",
        Fty=150, Ftu=175, Fcy=150, Fsu=105,
        Fbru=280, Fbry=240,
        E=29.0, Ec=29.0, G=11.1, nu=0.30,
        alpha=6.0, k=110, T_max=600,
        rho=0.276,
        source="MMPDS-01 §2.6.5.0",
    ),
    Material(
        name="17-7 PH RH950",  category="Stainless",
        Fty=185, Ftu=210, Fcy=185, Fsu=126,
        Fbru=336, Fbry=296,
        E=29.0, Ec=29.0, G=11.1, nu=0.30,
        alpha=6.0, k=110, T_max=600,
        rho=0.276,
        source="MMPDS-01 §2.6.5.0",
    ),

    # ── FASTENERS ────────────────────────────────────────────────────────
    # Bolt and screw STRENGTH LEVELS, not bar or sheet stock. Ftu is the
    # definitional minimum for the grade — a "160 ksi bolt" is procured to
    # 160 ksi Ftu — and Fsu is the corresponding tabulated fastener shear
    # allowable (MMPDS-01 §8.1.4 fastener strength tables).
    #
    # ⚠️ VERIFY — these are grade-level nominals for preliminary sizing. For a
    # released stress report look up the ACTUAL part number and diameter in
    # MMPDS-01 Table 8.1.4 or the procurement spec: allowables vary with
    # diameter, thread form, and (for shear) whether threads lie in the shear
    # plane. Fty is not tabulated for fasteners at all and is estimated here.
    #
    # Fcy, Fbru and Fbry are deliberately left None. Bearing is a check on the
    # PLATE, not on the fastener, and compressive yield does not govern a bolt
    # in tension, shear, or bending.
    Material(
        name="Alloy Steel Bolt 160 ksi",  category="Fastener",
        Fty=142,        # ⚠️ ESTIMATED — Fty is not tabulated for fasteners
        Ftu=160, Fsu=95,
        E=29.0, Ec=29.0, G=11.0, nu=0.32,
        alpha=6.3, k=225, T_max=450,
        rho=0.283,
        source="MMPDS-01 §8.1.4 fastener strength levels (AN/MS/NAS, 8740/4037)",
        notes="Standard 160 ksi alloy-steel airframe bolt. T_max reflects the "
              "cadmium-plating limit, not the base alloy.",
        estimated_fields=("Fty",),
    ),
    Material(
        name="Alloy Steel Bolt 180 ksi",  category="Fastener",
        Fty=163,        # ⚠️ ESTIMATED — Fty is not tabulated for fasteners
        Ftu=180, Fsu=108,
        E=29.0, Ec=29.0, G=11.0, nu=0.32,
        alpha=6.3, k=225, T_max=450,
        rho=0.283,
        source="MMPDS-01 §8.1.4 fastener strength levels (NAS144–158 class)",
        notes="180 ksi alloy-steel bolt. T_max reflects the plating limit.",
        estimated_fields=("Fty",),
    ),
    Material(
        name="A286 CRES Bolt 160 ksi",  category="Fastener",
        Fty=120,        # ⚠️ ESTIMATED — Fty is not tabulated for fasteners
        Ftu=160, Fsu=95,
        E=29.1, Ec=29.1, G=11.2, nu=0.31,
        alpha=9.2, k=100, T_max=1200,
        rho=0.286,
        source="MMPDS-01 §8.1.4 fastener strength levels (NAS1953, MS9556 class)",
        notes="Corrosion-resistant, retains strength hot. Low yield ratio "
              "relative to alloy steel — check Fty if yield governs.",
        estimated_fields=("Fty",),
    ),
    Material(
        name="H-11 Steel Bolt 260 ksi",  category="Fastener",
        Fty=220,        # ⚠️ ESTIMATED — Fty is not tabulated for fasteners
        Ftu=260, Fsu=156,
        E=30.0, Ec=30.0, G=11.6, nu=0.30,
        alpha=6.4, k=170, T_max=900,
        rho=0.281,
        source="MMPDS-01 §8.1.4 fastener strength levels (NAS1580 class)",
        notes="High-strength tool-steel bolt. Notch sensitive — do not take "
              "plastic bending credit above k = 1.5 without substantiation.",
        estimated_fields=("Fty",),
    ),
    Material(
        name="Ti-6Al-4V Bolt 160 ksi",  category="Fastener",
        Fty=145,        # ⚠️ ESTIMATED — Fty is not tabulated for fasteners
        Ftu=160, Fsu=95,
        E=16.0, Ec=16.4, G=6.2, nu=0.31,
        alpha=4.9, k=46, T_max=600,
        rho=0.160,
        source="MMPDS-01 §8.1.4 fastener strength levels (NAS6703 class)",
        notes="Titanium bolt — roughly 60% the density of steel at the same "
              "strength level, but E is 55% of steel, so it bends further.",
        estimated_fields=("Fty",),
    ),
    Material(
        name="Inconel 718 Bolt 180 ksi",  category="Fastener",
        Fty=150,        # ⚠️ ESTIMATED — Fty is not tabulated for fasteners
        Ftu=180, Fsu=108,
        E=29.0, Ec=29.0, G=11.2, nu=0.29,
        alpha=7.2, k=78, T_max=1200,
        rho=0.297,
        source="MMPDS-01 §8.1.4 fastener strength levels (NAS6203 class)",
        notes="Nickel-base superalloy bolt for hot structure.",
        estimated_fields=("Fty",),
    ),
]

# Display order for grouped UIs. Single source of truth — pages iterate this
# rather than repeating the tuple, so a new category cannot silently vanish
# from the Material Library page.
CATEGORY_ORDER: tuple[str, ...] = (
    "Aluminum", "Steel", "Titanium", "Stainless", "Fastener",
)

# Public dict — keyed by display name for app lookups.
MATERIALS: dict[str, Material] = {m.name: m for m in _materials}


def list_by_category() -> dict[str, list[Material]]:
    """Return materials grouped by category. Useful for grouped UIs later."""
    out: dict[str, list[Material]] = {}
    for m in MATERIALS.values():
        out.setdefault(m.category, []).append(m)
    return out


def names_grouped() -> list[str]:
    """
    Return material names in display order with category separators
    (e.g. "── Aluminum ──") suitable for a flat selectbox.
    """
    grouped = list_by_category()
    out: list[str] = []
    for cat in CATEGORY_ORDER:
        if cat in grouped:
            for m in grouped[cat]:
                out.append(m.name)
    return out
