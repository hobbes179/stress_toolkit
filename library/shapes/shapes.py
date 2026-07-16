"""
library/shapes/shapes.py

Cross-section shape library for the Stress Toolkit.

Each supported shape is a Python class inheriting from `Section`. Every
class defines:

    * Identification:        name, category, is_open_section
    * Inputs:                 dim_labels, dim_defaults
    * Geometry:               area, centroid (yb, zb), polygon_vertices
    * Bending:                Iy, Iz
    * Torsion:                J_torsion, t_max_for_torsion, tau_T
    * Shear (VQ/It):          Qy, Qz, tw_y, tw_z
    * Bending plasticity:     f_cozzone
    * Stress evaluation:      key_points

All formulas are documented with their source.

═══════════════════════════════════════════════════════════════════════════
COORDINATE SYSTEM
═══════════════════════════════════════════════════════════════════════════
    X = beam axis (out of section plane)
    Y = horizontal right
    Z = vertical up
    Origin at the section centroid (after centering).
    Loads:
        My causes bending stress proportional to z (top/bottom fibres)
        Mz causes bending stress proportional to y (left/right fibres)

═══════════════════════════════════════════════════════════════════════════
COZZONE SHAPE FACTOR  f
═══════════════════════════════════════════════════════════════════════════
Used to compute Fbu = f · Ftu (bending-ultimate allowable).
Stored as a class constant for each shape. These are SIMPLIFIED handbook
values from the Cozzone simplified method (Cozzone 1943, NACA TN-1818).

A rigorous Cozzone analysis derives f from both shape AND material stress-
strain behaviour. The values used here are conservative for ductile metals.

⚠️ GATED (v2 D5, CHANGELOG.md v1.1.0): for thin-walled open sections
(category == "Open thin-walled"), `effective_f_cozzone` overrides the
table value below to 1.0 — plastic-bending credit is not substantiated
without a crippling check. Use `effective_f_cozzone`, not `f_cozzone`,
wherever Fbu is computed. Solids and closed sections are unaffected.

  Rectangle:              f = 1.50
  Circle:                 f = 1.70
  Ellipse:                f = 1.60
  Rect Tube (HSS):        f = 1.30
  Circular Tube:          f = 1.40
  I-Beam / W-Shape:       f = 1.07     GATED → 1.0
  T-Beam:                 f = 1.15     GATED → 1.0
  L-Beam / Angle:         f = 1.15     GATED → 1.0
  C-Beam / Channel:       f = 1.15     GATED → 1.0
  Z-Beam:                 f = 1.10     GATED → 1.0
  Plus / Cross:           f = 1.30     GATED → 1.0

═══════════════════════════════════════════════════════════════════════════
ADDING A NEW SHAPE — see library/shapes/README.md
═══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import math

import numpy as np

from library.shapes.geometry import (
    SectionGeometry, MidlineSegment, ensure_ccw, ensure_cw,
)
from library.analysis.polygon_props import PolygonProps, polygon_section_props


# ──────────────────────────────────────────────────────────────────────────
# KeyPoint — a labelled location where stresses are evaluated.
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class KeyPoint:
    """A stress evaluation location on the section."""
    id:          str    # short identifier shown in plots/tables ("A", "B", ...)
    description: str    # plain-English location ("Top fiber", etc.)
    y:           float  # horizontal position from centroid (in)
    z:           float  # vertical position from centroid (in)


# ──────────────────────────────────────────────────────────────────────────
# Section — base class. All shape classes inherit and override the methods
# they need. Methods provided here that work for all sections (centroid,
# Sy, Sz, cy, cz) use the subclass's other methods.
# ──────────────────────────────────────────────────────────────────────────
class Section:
    """
    Base class for all cross-section shapes.

    Subclasses MUST define:
        name             — display name (str)
        category         — "Solid" / "Hollow" / "Open thin-walled"
        is_open_section  — True if open thin-walled (St. Venant torsion only)
        dim_labels       — list of (symbol, label) tuples, length 4. Use
                           None for unused slots.
        dim_defaults     — list of default values, length 4. Use None for
                           unused slots.
        f_cozzone        — Cozzone shape factor (float)

    Subclasses MUST implement:
        area()
        centroid()  -> (y_bar, z_bar) measured from a shape-local origin
        Iy()        -> second moment about centroidal Y axis
        Iz()        -> second moment about centroidal Z axis
        J_torsion() -> torsion constant
        Qy(), Qz()  -> first moments at neutral axis (for shear stress)
        tw_y(), tw_z() -> web/wall thickness at neutral axis for each shear
        polygon_vertices() -> list[np.ndarray]; one array per loop (outer,
                              inner). Coordinates centered on centroid.
        key_points(My, Mz) -> list[KeyPoint]
        tau_T(T_load)      -> max torsional shear stress (ksi)

    Subclasses MAY override:
        cy(), cz()  -> extreme-fiber distance from centroid (defaults to
                       max distance from centroid to bounding box).
    """

    # ── Subclass overrides ───────────────────────────────────────────────
    name: str = ""
    category: str = ""
    is_open_section: bool = False
    dim_labels: list = []
    dim_defaults: list = []
    f_cozzone: float = 1.0

    # ─────────────────────────────────────────────────────────────────────
    def __init__(self, dims: list):
        """
        dims is a list of 4 floats; unused slots may be 0 or None and
        won't be referenced by the subclass's methods.
        """
        self.dims = [d if d is not None else 0.0 for d in dims]
        self.d1 = self.dims[0]
        self.d2 = self.dims[1]
        self.d3 = self.dims[2]
        self.d4 = self.dims[3]

    # ── Abstract-ish methods (subclasses MUST implement) ─────────────────
    def area(self) -> float:               raise NotImplementedError
    def centroid(self) -> tuple[float, float]: raise NotImplementedError
    def Iy(self) -> float:                 raise NotImplementedError
    def Iz(self) -> float:                 raise NotImplementedError
    def J_torsion(self) -> float:          raise NotImplementedError
    def Qy(self) -> float:                 raise NotImplementedError
    def Qz(self) -> float:                 raise NotImplementedError
    def tw_y(self) -> float:               raise NotImplementedError
    def tw_z(self) -> float:               raise NotImplementedError
    def polygon_vertices(self) -> list:    raise NotImplementedError
    def key_points(self, My: float, Mz: float) -> list[KeyPoint]:
        raise NotImplementedError
    def tau_T(self, T_load: float) -> float: raise NotImplementedError

    # ── Common derived properties ────────────────────────────────────────
    def cy(self) -> float:
        """Max |y| from centroid. Default = half overall width."""
        # Default uses bounding box of the polygon
        pts = self.polygon_vertices()
        if not pts: return 0.0
        ys = np.concatenate([p[:, 0] for p in pts])
        return float(max(abs(ys.min()), abs(ys.max())))

    def cz(self) -> float:
        """Max |z| from centroid. Default = half overall height."""
        pts = self.polygon_vertices()
        if not pts: return 0.0
        zs = np.concatenate([p[:, 1] for p in pts])
        return float(max(abs(zs.min()), abs(zs.max())))

    def Sy(self) -> float:
        """Section modulus about Y."""
        cz = self.cz()
        return self.Iy() / cz if cz > 0 else 0.0

    def Sz(self) -> float:
        """Section modulus about Z."""
        cy = self.cy()
        return self.Iz() / cy if cy > 0 else 0.0

    def validate_dims(self) -> Optional[str]:
        """
        Return a validation error message if the current dims are
        physically invalid, else None. Subclasses override to add
        shape-specific checks. Never raises — callers must surface the
        message and skip the solve rather than let an exception reach it.
        """
        return None

    @property
    def is_thin_walled(self) -> bool:
        """True for the 'Open thin-walled' shape category."""
        return self.category == "Open thin-walled"

    @property
    def effective_f_cozzone(self) -> float:
        """
        Cozzone plastic-bending shape factor used for Fbu = f·Ftu, gated
        per v2 decision D5 (see CHANGELOG.md, v1.1.0): thin-walled open
        sections are forced to f = 1.0 — plastic-bending credit is not
        substantiated without a crippling check for these shapes. Solid
        and compact closed shapes keep their documented table values
        (`f_cozzone`).
        """
        if self.is_open_section and self.is_thin_walled:
            return 1.0
        return self.f_cozzone

    # ── Geometry / polygon-derived properties (Phase 1) ──────────────────
    def geometry(self) -> SectionGeometry:
        """
        Build the shape's SectionGeometry (design handoff §2.1).

        Default implementation derives the outer boundary and voids from
        `polygon_vertices()` (loop 0 = outer, remaining loops = voids),
        normalizing winding to the CCW-outer / CW-void convention. Solids
        and Phase-1 thin-walled shapes leave the midline skeleton empty;
        thin-walled catalog shapes override this in Phase 2 to populate
        nodes/segments/cells.
        """
        loops = self.polygon_vertices()
        if not loops:
            return SectionGeometry(outer=np.zeros((0, 2)),
                                   is_thin_walled=self.is_thin_walled)
        outer = ensure_ccw(loops[0])
        voids = tuple(ensure_cw(loop) for loop in loops[1:])
        return SectionGeometry(outer=outer, voids=voids,
                               is_thin_walled=self.is_thin_walled)

    def section_props(self) -> PolygonProps:
        """
        Centroidal section properties computed from the polygon via Green's
        theorem. Used for the product of inertia (`Iyz`), principal axes,
        and as the cross-check against each shape's closed-form A/Iy/Iz
        (validation gate — see tests/test_phase1.py).
        """
        g = self.geometry()
        return polygon_section_props(g.outer, g.voids)

    def Iyz(self) -> float:
        """
        Product of inertia about the centroidal axes, ∫y·z dA, from the
        section polygon. Zero (to numerical precision) for any section with
        an axis of symmetry; nonzero for L and Z. Feeds the unsymmetric-
        bending tensor in calculations.py (design handoff §3.1).
        """
        return self.section_props().Iyz


# ══════════════════════════════════════════════════════════════════════════
# RECTANGLE — solid rectangular bar
# ══════════════════════════════════════════════════════════════════════════
class Rectangle(Section):
    """Solid rectangular cross-section.  D1=b (width), D2=h (height)."""

    name = "Rectangle"
    category = "Solid"
    is_open_section = True   # for torsion treated as solid rectangle (St. Venant)
    dim_labels = [
        ("b", "Width"),
        ("h", "Height"),
        None,
        None,
    ]
    dim_defaults = [4.0, 2.0, None, None]
    f_cozzone = 1.50

    def area(self):
        return self.d1 * self.d2

    def centroid(self):
        # Centroid at (b/2, h/2) measured from bottom-left.
        return (self.d1 / 2, self.d2 / 2)

    def Iy(self):
        # Bending about Y → stress ∝ z; Iy = b·h³/12
        return self.d1 * self.d2**3 / 12

    def Iz(self):
        # Bending about Z → stress ∝ y; Iz = h·b³/12
        return self.d2 * self.d1**3 / 12

    def J_torsion(self):
        # Solid rectangle St. Venant — Timoshenko approximation:
        # J = a·b³/3 · (1 − 0.63·b/a)  for a ≥ b
        b, h = self.d1, self.d2
        tmin, tmax = min(b, h), max(b, h)
        if tmax == 0:
            return 0.0
        return tmax * tmin**3 / 3 * (1 - 0.63 * tmin / tmax)

    def t_max_for_torsion(self):
        # τ = T·t/J uses the SHORT dimension (thin-plate form of St. Venant).
        return min(self.d1, self.d2)

    def tau_T(self, T_load):
        # τ = T·t_min/J  (Timoshenko thin-plate approximation for solid rectangle).
        # Accurate to ~10% for a/b ≥ 3; conservatively overestimates by ~70% for
        # a square (a/b = 1). Acceptable for preliminary sizing — error is safe-side.
        J = self.J_torsion()
        if J <= 0:
            return 0.0
        return abs(T_load) * self.t_max_for_torsion() / J / 1000

    def Qy(self):
        # First moment of area above neutral axis for Vy (vertical shear)
        # Q = b·(h/2)²/2  at z = 0 (neutral axis)
        return self.d1 * (self.d2 / 2)**2 / 2

    def Qz(self):
        # First moment for Vz shear
        return self.d2 * (self.d1 / 2)**2 / 2

    def tw_y(self):
        return self.d1   # entire width at neutral axis

    def tw_z(self):
        return self.d2

    def polygon_vertices(self):
        b, h = self.d1, self.d2
        return [np.array([(-b/2, -h/2), (b/2, -h/2),
                          (b/2,  h/2), (-b/2, h/2)])]

    def key_points(self, My, Mz):
        cy, cz = self.cy(), self.cz()
        return [
            KeyPoint("A", "Top fiber — mid",       0,    cz),
            KeyPoint("B", "Bottom fiber — mid",     0,   -cz),
            KeyPoint("C", "Right fiber — mid",      cy,   0),
            KeyPoint("D", "Left fiber — mid",      -cy,   0),
            KeyPoint("E", "Top-right corner",       cy,   cz),
            KeyPoint("F", "Top-left corner",       -cy,   cz),
            KeyPoint("G", "Bot-right corner",       cy,  -cz),
            KeyPoint("H", "Bot-left corner",       -cy,  -cz),
            KeyPoint("I", "Centroid — max shear",   0,    0),
        ]


# ══════════════════════════════════════════════════════════════════════════
# CIRCLE — solid round bar
# ══════════════════════════════════════════════════════════════════════════
class Circle(Section):
    """Solid circular cross-section.  D1=d (diameter)."""

    name = "Circle"
    category = "Solid"
    is_open_section = False   # closed-form torsion solution available
    dim_labels = [("d", "Diameter"), None, None, None]
    dim_defaults = [3.0, None, None, None]
    f_cozzone = 1.70

    def area(self):
        return math.pi * (self.d1 / 2)**2

    def centroid(self):
        return (self.d1 / 2, self.d1 / 2)

    def Iy(self):
        # π·d⁴/64
        return math.pi * self.d1**4 / 64

    def Iz(self):
        return self.Iy()

    def J_torsion(self):
        # Polar moment for circle: J = π·d⁴/32
        return math.pi * self.d1**4 / 32

    def tau_T(self, T_load):
        # EXACT closed-form: τ = 16·T / (π·d³). Divide by 1000 → ksi
        if self.d1 <= 0:
            return 0.0
        return abs(T_load) * 16 / (math.pi * self.d1**3) / 1000

    def Qy(self):
        # First moment of semicircle area above neutral axis = d³/12
        return self.d1**3 / 12

    def Qz(self):
        return self.Qy()

    def tw_y(self):
        # Width at neutral axis = full diameter
        return self.d1

    def tw_z(self):
        return self.d1

    def cy(self):
        return self.d1 / 2

    def cz(self):
        return self.d1 / 2

    def polygon_vertices(self):
        t = np.linspace(0, 2 * np.pi, 181)
        r = self.d1 / 2
        return [np.column_stack([r * np.cos(t), r * np.sin(t)])]

    def key_points(self, My, Mz):
        cy, cz = self.cy(), self.cz()
        kps = [
            KeyPoint("A", "Top fiber (+Z)",        0,    cz),
            KeyPoint("B", "Bottom fiber (−Z)",      0,   -cz),
            KeyPoint("C", "Right fiber (+Y)",       cy,   0),
            KeyPoint("D", "Left fiber (−Y)",       -cy,   0),
            KeyPoint("E", "Centroid — max shear",   0,    0),
        ]
        # Peak bending point for combined My,Mz lies on the boundary at
        # angle arctan(Mz/My) from the +Z axis. Only add it if it doesn't
        # coincide (within 5% of radius) with an existing cardinal point.
        M_res = math.sqrt(My**2 + Mz**2)
        if M_res > 0:
            alpha = math.atan2(Mz, My)
            y_pk = cy * math.sin(alpha)
            z_pk = cz * math.cos(alpha)
            tol = cy * 0.05
            existing = [(k.y, k.z) for k in kps]
            duplicate = any(
                abs(y - y_pk) < tol and abs(z - z_pk) < tol
                for y, z in existing
            )
            if not duplicate:
                kps.append(KeyPoint("F", "★ Peak bending point", y_pk, z_pk))
        return kps


# ══════════════════════════════════════════════════════════════════════════
# ELLIPSE — solid elliptical bar
# ══════════════════════════════════════════════════════════════════════════
class Ellipse(Section):
    """Solid elliptical section.  D1=a (semi-horiz), D2=b (semi-vert)."""

    name = "Ellipse"
    category = "Solid"
    is_open_section = False
    dim_labels = [("a", "Semi-axis horiz"), ("b", "Semi-axis vert"),
                  None, None]
    dim_defaults = [2.0, 1.0, None, None]
    f_cozzone = 1.60

    def area(self):
        return math.pi * self.d1 * self.d2

    def centroid(self):
        return (self.d1, self.d2)

    def Iy(self):
        # I about horizontal centroidal axis: π·a·b³/4
        return math.pi * self.d1 * self.d2**3 / 4

    def Iz(self):
        return math.pi * self.d2 * self.d1**3 / 4

    def J_torsion(self):
        # Closed-form for ellipse: J = π·a³·b³ / (a²+b²)
        if self.d1 + self.d2 == 0:
            return 0.0
        return math.pi * self.d1**3 * self.d2**3 / (self.d1**2 + self.d2**2)

    def tau_T(self, T_load):
        # EXACT closed-form max shear at end of minor axis (b):
        # τ_max = 2T / (π·a·b²)  if a > b
        # General form uses the smaller semi-axis squared in denominator.
        if self.d1 <= 0 or self.d2 <= 0:
            return 0.0
        b_minor = min(self.d1, self.d2)
        a_major = max(self.d1, self.d2)
        return 2 * abs(T_load) / (math.pi * a_major * b_minor**2) / 1000

    def validate_dims(self) -> Optional[str]:
        # ⚠️ v2 D-gate (CHANGELOG.md v1.1.0): the exact torsion formula
        # τ_T = 2T/(π·a·b²) requires b = semi-MINOR axis. Enforce a ≥ b
        # explicitly (D1 = a horizontal ≥ D2 = b vertical) rather than
        # silently reordering — a silent swap risks the geometry (Iy/Iz,
        # key points) and the torsion formula disagreeing about which
        # axis is "major" if only one of them is corrected.
        if self.d2 > self.d1:
            return (
                "Ellipse requires a ≥ b: D1 (horizontal semi-axis) must be "
                "≥ D2 (vertical semi-axis). Swap D1/D2 to model a "
                "tall ellipse, or reduce D2."
            )
        return None

    def Qy(self):
        # First moment of upper semi-ellipse: 2·a·b²/3
        return 2 * self.d1 * self.d2**2 / 3

    def Qz(self):
        return 2 * self.d2 * self.d1**2 / 3

    def tw_y(self):
        # Width at NA = 2·a
        return 2 * self.d1

    def tw_z(self):
        return 2 * self.d2

    def cy(self):
        return self.d1

    def cz(self):
        return self.d2

    def polygon_vertices(self):
        t = np.linspace(0, 2 * np.pi, 181)
        return [np.column_stack([self.d1 * np.cos(t),
                                 self.d2 * np.sin(t)])]

    def key_points(self, My, Mz):
        cy, cz = self.cy(), self.cz()
        kps = [
            KeyPoint("A", "Top fiber (+Z max)",    0,    cz),
            KeyPoint("B", "Bottom fiber (−Z max)", 0,   -cz),
            KeyPoint("C", "Right fiber (+Y max)",  cy,   0),
            KeyPoint("D", "Left fiber (−Y max)",  -cy,   0),
            KeyPoint("E", "Centroid — max shear",  0,    0),
        ]
        # Peak bending point on the ellipse boundary at angle of resultant
        # moment direction. Only adds if not duplicate of a cardinal point.
        M_res = math.sqrt(My**2 + Mz**2)
        if M_res > 0:
            alpha = math.atan2(Mz, My)
            y_pk = cy * math.sin(alpha)
            z_pk = cz * math.cos(alpha)
            tol = min(cy, cz) * 0.05
            existing = [(k.y, k.z) for k in kps]
            duplicate = any(
                abs(y - y_pk) < tol and abs(z - z_pk) < tol
                for y, z in existing
            )
            if not duplicate:
                kps.append(KeyPoint("F", "★ Peak bending point", y_pk, z_pk))
        return kps


# ══════════════════════════════════════════════════════════════════════════
# RECT TUBE (HSS) — closed rectangular tube
# ══════════════════════════════════════════════════════════════════════════
class RectTube(Section):
    """
    Hollow rectangular tube. D1=b (overall width), D2=h (overall height),
    D3=t_f (top+bottom thickness), D4=t_w (left+right thickness).
    """

    name = "Rect Tube (HSS)"
    category = "Hollow"
    is_open_section = False
    dim_labels = [
        ("b",   "Overall width"),
        ("h",   "Overall height"),
        ("t_f", "Flange thickness"),
        ("t_w", "Web thickness"),
    ]
    dim_defaults = [4.0, 6.0, 0.375, 0.25]
    f_cozzone = 1.30

    def area(self):
        b, h, tf, tw = self.d1, self.d2, self.d3, self.d4
        return b * h - (b - 2 * tw) * (h - 2 * tf)

    def centroid(self):
        return (self.d1 / 2, self.d2 / 2)

    def Iy(self):
        b, h, tf, tw = self.d1, self.d2, self.d3, self.d4
        # Iy = outer rectangle − inner rectangle
        return (b * h**3 - (b - 2 * tw) * (h - 2 * tf)**3) / 12

    def Iz(self):
        b, h, tf, tw = self.d1, self.d2, self.d3, self.d4
        return (h * b**3 - (h - 2 * tf) * (b - 2 * tw)**3) / 12

    def J_torsion(self):
        # Bredt-Batho closed section:  J = 4·Am² / ∮(ds/t)
        # For rectangular tube with uniform t per side:
        #   ∮(ds/t) = 2·(b - tw)/tw + 2·(h - tf)/tf
        # using median-line dimensions.
        b, h, tf, tw = self.d1, self.d2, self.d3, self.d4
        if tf <= 0 or tw <= 0:
            return 0.0
        Am = (b - tw) * (h - tf)
        s = 2 * (b - tw) / tw + 2 * (h - tf) / tf
        return 4 * Am**2 / s if s > 0 else 0.0

    def tau_T(self, T_load):
        # Bredt-Batho closed:  τ = T / (2·Am·t)
        # Use the THINNEST wall to get the maximum stress.
        b, h, tf, tw = self.d1, self.d2, self.d3, self.d4
        Am = (b - tw) * (h - tf)
        tmin = min(tf, tw)
        if Am <= 0 or tmin <= 0:
            return 0.0
        return abs(T_load) / (2 * Am * tmin) / 1000

    def validate_dims(self) -> Optional[str]:
        # ⚠️ Bredt min-thickness guard (CHANGELOG.md v1.1.0): if the walls
        # consume the whole section, the inner void area used by area()
        # and the Bredt-Batho median-line Am go to zero/negative — J and
        # τ_T were silently returning 0.0 rather than flagging invalid
        # geometry.
        b, h, tf, tw = self.d1, self.d2, self.d3, self.d4
        if tf <= 0 or tw <= 0:
            return "Rect Tube wall thicknesses (t_f, t_w) must be > 0."
        if (b - 2 * tw) <= 0 or (h - 2 * tf) <= 0:
            return (
                "Rect Tube wall thickness exceeds the section — the "
                "enclosed (Bredt-Batho) area would be zero or negative. "
                "Reduce t_f/t_w or increase b/h."
            )
        return None

    def Qy(self):
        b, h, tf, tw = self.d1, self.d2, self.d3, self.d4
        # Q at neutral axis = first moment of area above NA
        # = outer half rectangle − inner half rectangle
        return b * h**2 / 4 - (b - 2 * tw) * (h / 2 - tf)**2 / 2

    def Qz(self):
        b, h, tf, tw = self.d1, self.d2, self.d3, self.d4
        return h * b**2 / 4 - (h - 2 * tf) * (b / 2 - tw)**2 / 2

    def tw_y(self):
        # Both vertical walls carry vertical shear → 2·tw
        return 2 * self.d4

    def tw_z(self):
        return 2 * self.d3

    def polygon_vertices(self):
        b, h, tf, tw = self.d1, self.d2, self.d3, self.d4
        outer = np.array([(-b/2, -h/2), (b/2, -h/2),
                          (b/2,  h/2), (-b/2, h/2)])
        inner = np.array([
            (-b/2 + tw, -h/2 + tf),
            ( b/2 - tw, -h/2 + tf),
            ( b/2 - tw,  h/2 - tf),
            (-b/2 + tw,  h/2 - tf),
        ])
        return [outer, inner]

    def key_points(self, My, Mz):
        cy, cz = self.cy(), self.cz()
        return [
            KeyPoint("A", "Top flange outer-mid",   0,    cz),
            KeyPoint("B", "Bot flange outer-mid",   0,   -cz),
            KeyPoint("C", "Right web mid",          cy,   0),
            KeyPoint("D", "Left web mid",          -cy,   0),
            KeyPoint("E", "Top-right outer corner", cy,   cz),
            KeyPoint("F", "Top-left outer corner", -cy,   cz),
            KeyPoint("G", "Bot-right outer corner", cy,  -cz),
            KeyPoint("H", "Bot-left outer corner", -cy,  -cz),
        ]


# ══════════════════════════════════════════════════════════════════════════
# CIRCULAR TUBE — closed round tube
# ══════════════════════════════════════════════════════════════════════════
class CircularTube(Section):
    """Hollow circular tube. D1=d_o (outer diameter), D2=t (wall thick)."""

    name = "Circular Tube"
    category = "Hollow"
    is_open_section = False
    dim_labels = [
        ("d_o", "Outer diameter"),
        ("t",   "Wall thickness"),
        None, None,
    ]
    dim_defaults = [4.0, 0.25, None, None]
    f_cozzone = 1.40

    def area(self):
        ro = self.d1 / 2
        ri = ro - self.d2
        return math.pi * (ro**2 - ri**2)

    def centroid(self):
        return (self.d1 / 2, self.d1 / 2)

    def Iy(self):
        return math.pi * (self.d1**4 - (self.d1 - 2 * self.d2)**4) / 64

    def Iz(self):
        return self.Iy()

    def J_torsion(self):
        # Polar moment: J = π·(d_o⁴ − d_i⁴)/32
        return math.pi * (self.d1**4 - (self.d1 - 2 * self.d2)**4) / 32

    def tau_T(self, T_load):
        # Closed tube — exact: τ = T·r_o / J (at outer surface)
        J = self.J_torsion()
        if J <= 0:
            return 0.0
        return abs(T_load) * (self.d1 / 2) / J / 1000

    def Qy(self):
        # Q for thin-walled tube at NA = (r_o³ − r_i³) · 2/3
        ro = self.d1 / 2
        ri = ro - self.d2
        return (ro**3 - ri**3) * 2 / 3

    def Qz(self):
        return self.Qy()

    def tw_y(self):
        # Two wall thicknesses (left and right of NA)
        return 2 * self.d2

    def tw_z(self):
        return 2 * self.d2

    def cy(self):
        return self.d1 / 2

    def cz(self):
        return self.d1 / 2

    def polygon_vertices(self):
        t = np.linspace(0, 2 * np.pi, 181)
        ro = self.d1 / 2
        ri = ro - self.d2
        outer = np.column_stack([ro * np.cos(t), ro * np.sin(t)])
        # Inner contour reversed so matplotlib treats as hole
        inner = np.column_stack([ri * np.cos(t[::-1]),
                                 ri * np.sin(t[::-1])])
        return [outer, inner]

    def key_points(self, My, Mz):
        cy, cz = self.cy(), self.cz()
        kps = [
            KeyPoint("A", "Top fiber (+Z)",        0,    cz),
            KeyPoint("B", "Bottom fiber (−Z)",      0,   -cz),
            KeyPoint("C", "Right fiber (+Y)",       cy,   0),
            KeyPoint("D", "Left fiber (−Y)",       -cy,   0),
            KeyPoint("E", "Centroid — max shear",   0,    0),
        ]
        # Peak bending point on outer surface
        M_res = math.sqrt(My**2 + Mz**2)
        if M_res > 0:
            alpha = math.atan2(Mz, My)
            y_pk = cy * math.sin(alpha)
            z_pk = cz * math.cos(alpha)
            tol = cy * 0.05
            existing = [(k.y, k.z) for k in kps]
            if not any(abs(y - y_pk) < tol and abs(z - z_pk) < tol
                       for y, z in existing):
                kps.append(KeyPoint("F", "★ Peak bending point", y_pk, z_pk))
        return kps


# ══════════════════════════════════════════════════════════════════════════
# I-BEAM / W-SHAPE
# ══════════════════════════════════════════════════════════════════════════
class IBeam(Section):
    """
    Symmetric I-beam / W-shape. D1=b_f (flange width), D2=d (overall depth),
    D3=t_f (flange thickness), D4=t_w (web thickness).
    """

    name = "I-Beam / W-Shape"
    category = "Open thin-walled"
    is_open_section = True
    dim_labels = [
        ("b_f", "Flange width"),
        ("d",   "Overall depth"),
        ("t_f", "Flange thickness"),
        ("t_w", "Web thickness"),
    ]
    dim_defaults = [4.0, 6.0, 0.375, 0.25]
    f_cozzone = 1.07     # flange-dominated; small plasticity gain

    def area(self):
        bf, d, tf, tw = self.d1, self.d2, self.d3, self.d4
        return 2 * bf * tf + (d - 2 * tf) * tw

    def centroid(self):
        return (self.d1 / 2, self.d2 / 2)

    def Iy(self):
        bf, d, tf, tw = self.d1, self.d2, self.d3, self.d4
        # Two flanges (parallel-axis) + web
        flanges = 2 * (bf * tf**3 / 12 + bf * tf * (d/2 - tf/2)**2)
        web = tw * (d - 2 * tf)**3 / 12
        return flanges + web

    def Iz(self):
        bf, d, tf, tw = self.d1, self.d2, self.d3, self.d4
        return 2 * tf * bf**3 / 12 + (d - 2 * tf) * tw**3 / 12

    def J_torsion(self):
        # Open thin-walled: J = Σ(b·t³)/3
        bf, d, tf, tw = self.d1, self.d2, self.d3, self.d4
        return (2 * bf * tf**3 + (d - 2 * tf) * tw**3) / 3

    def t_max_for_torsion(self):
        return max(self.d3, self.d4)

    def tau_T(self, T_load):
        J = self.J_torsion()
        if J <= 0:
            return 0.0
        return abs(T_load) * self.t_max_for_torsion() / J / 1000

    def Qy(self):
        bf, d, tf, tw = self.d1, self.d2, self.d3, self.d4
        # Q at neutral axis = top flange + web above NA
        Q_flange = bf * tf * (d/2 - tf/2)
        Q_web = tw * (d/2 - tf)**2 / 2
        return Q_flange + Q_web

    def Qz(self):
        bf, d, tf, tw = self.d1, self.d2, self.d3, self.d4
        # Q for horizontal shear ≈ both flange halves to one side
        return 2 * tf * bf**2 / 8

    def tw_y(self):
        return self.d4   # web

    def tw_z(self):
        # Two flange widths combined
        return 2 * self.d3

    def polygon_vertices(self):
        bf, d, tf, tw = self.d1, self.d2, self.d3, self.d4
        return [np.array([
            (-bf/2, -d/2),   (bf/2,  -d/2),
            ( bf/2, -d/2+tf),( tw/2, -d/2+tf),
            ( tw/2,  d/2-tf),( bf/2,  d/2-tf),
            ( bf/2,  d/2),   (-bf/2,  d/2),
            (-bf/2,  d/2-tf),(-tw/2,  d/2-tf),
            (-tw/2, -d/2+tf),(-bf/2, -d/2+tf),
        ])]

    def key_points(self, My, Mz):
        bf, d, tf, tw = self.d1, self.d2, self.d3, self.d4
        return [
            KeyPoint("A", "Top flange — tip right",  bf/2,   d/2),
            KeyPoint("B", "Top flange — tip left",  -bf/2,   d/2),
            KeyPoint("C", "Bot flange — tip right",  bf/2,  -d/2),
            KeyPoint("D", "Bot flange — tip left",  -bf/2,  -d/2),
            KeyPoint("E", "Top web-flange junction", tw/2,   d/2 - tf),
            KeyPoint("F", "Bot web-flange junction", tw/2,  -d/2 + tf),
            KeyPoint("G", "Web mid — max shear",     0,      0),
            KeyPoint("H", "Web-flange re-entrant",  -tw/2,   d/2 - tf),
        ]


# ══════════════════════════════════════════════════════════════════════════
# T-BEAM
# ══════════════════════════════════════════════════════════════════════════
class TBeam(Section):
    """
    T-beam. D1=b_f (flange width), D2=t_f (flange thickness),
    D3=h_w (web height), D4=t_w (web thickness).
    Flange on top, web below.
    """

    name = "T-Beam"
    category = "Open thin-walled"
    is_open_section = True
    dim_labels = [
        ("b_f", "Flange width"),
        ("t_f", "Flange thickness"),
        ("h_w", "Web height"),
        ("t_w", "Web thickness"),
    ]
    dim_defaults = [4.0, 0.375, 4.0, 0.25]
    f_cozzone = 1.15

    def area(self):
        bf, tf, hw, tw = self.d1, self.d2, self.d3, self.d4
        return bf * tf + tw * hw

    def centroid(self):
        bf, tf, hw, tw = self.d1, self.d2, self.d3, self.d4
        Af, Aw = bf * tf, tw * hw
        # Measured from bottom of web (z=0); flange centroid at hw + tf/2
        zb = (Af * (hw + tf/2) + Aw * hw/2) / (Af + Aw)
        yb = bf / 2
        return (yb, zb)

    def Iy(self):
        bf, tf, hw, tw = self.d1, self.d2, self.d3, self.d4
        Af, Aw = bf * tf, tw * hw
        _, zb = self.centroid()
        I_flange = bf * tf**3 / 12 + Af * (hw + tf/2 - zb)**2
        I_web = tw * hw**3 / 12 + Aw * (hw/2 - zb)**2
        return I_flange + I_web

    def Iz(self):
        bf, tf, hw, tw = self.d1, self.d2, self.d3, self.d4
        # About centerline (Z axis through centroid)
        return tf * bf**3 / 12 + hw * tw**3 / 12

    def J_torsion(self):
        bf, tf, hw, tw = self.d1, self.d2, self.d3, self.d4
        return (bf * tf**3 + hw * tw**3) / 3

    def t_max_for_torsion(self):
        return max(self.d2, self.d4)

    def tau_T(self, T_load):
        J = self.J_torsion()
        if J <= 0:
            return 0.0
        return abs(T_load) * self.t_max_for_torsion() / J / 1000

    def Qy(self):
        # Approximate Q at neutral axis ≈ t_w · zb² / 2
        _, zb = self.centroid()
        return self.d4 * zb**2 / 2

    def Qz(self):
        bf = self.d1
        return self.d2 * bf**2 / 8

    def tw_y(self):
        return self.d4

    def tw_z(self):
        return self.d2

    def polygon_vertices(self):
        bf, tf, hw, tw = self.d1, self.d2, self.d3, self.d4
        _, zb = self.centroid()
        # Centered on centroid
        return [np.array([
            (-tw/2, 0 - zb),   (tw/2, 0 - zb),
            ( tw/2, hw - zb),  (bf/2, hw - zb),
            ( bf/2, hw + tf - zb), (-bf/2, hw + tf - zb),
            (-bf/2, hw - zb), (-tw/2, hw - zb),
        ])]

    def key_points(self, My, Mz):
        bf, tf, hw, tw = self.d1, self.d2, self.d3, self.d4
        _, zb = self.centroid()
        return [
            KeyPoint("A", "Flange — top right tip",   bf/2,  hw + tf - zb),
            KeyPoint("B", "Flange — top left tip",   -bf/2,  hw + tf - zb),
            KeyPoint("C", "Flange-web junction R",    tw/2,  hw - zb),
            KeyPoint("D", "Flange-web junction L",   -tw/2,  hw - zb),
            KeyPoint("E", "Web bottom — right",       tw/2,  0 - zb),
            KeyPoint("F", "Web bottom — left",       -tw/2,  0 - zb),
            KeyPoint("G", "Centroid",                 0,     0),
        ]


# ══════════════════════════════════════════════════════════════════════════
# L-BEAM / ANGLE
# ══════════════════════════════════════════════════════════════════════════
class LBeam(Section):
    """
    L-beam / angle. D1=b (horizontal leg width), D2=h (vertical leg height),
    D3=t_b (horiz leg thickness), D4=t_h (vert leg thickness).

    Bending uses the full unsymmetric-bending tensor (design handoff §3.1),
    so the nonzero product of inertia Iyz is accounted for exactly — no
    geometric-axis constraint assumption is required (Phase 1, CHANGELOG).
    Iyz is computed from the section polygon via Green's theorem
    (Section.Iyz / library.analysis.polygon_props).
    """

    name = "L-Beam / Angle"
    category = "Open thin-walled"
    is_open_section = True
    dim_labels = [
        ("b",   "Horiz leg width"),
        ("h",   "Vert leg height"),
        ("t_b", "Horiz leg thick"),
        ("t_h", "Vert leg thick"),
    ]
    dim_defaults = [3.0, 3.0, 0.25, 0.25]
    f_cozzone = 1.15

    def area(self):
        b, h, tb, th = self.d1, self.d2, self.d3, self.d4
        return b * tb + (h - tb) * th

    def centroid(self):
        b, h, tb, th = self.d1, self.d2, self.d3, self.d4
        Ah, Av = b * tb, (h - tb) * th
        # Origin at bottom-left of L
        zb = (Ah * tb/2 + Av * (tb + (h - tb)/2)) / (Ah + Av)
        yb = (Ah * b/2 + Av * th/2) / (Ah + Av)
        return (yb, zb)

    def Iy(self):
        b, h, tb, th = self.d1, self.d2, self.d3, self.d4
        Ah, Av = b * tb, (h - tb) * th
        _, zb = self.centroid()
        I_h = b * tb**3 / 12 + Ah * (tb/2 - zb)**2
        I_v = th * (h - tb)**3 / 12 + Av * (tb + (h - tb)/2 - zb)**2
        return I_h + I_v

    def Iz(self):
        b, h, tb, th = self.d1, self.d2, self.d3, self.d4
        Ah, Av = b * tb, (h - tb) * th
        yb, _ = self.centroid()
        I_h = tb * b**3 / 12 + Ah * (b/2 - yb)**2
        I_v = (h - tb) * th**3 / 12 + Av * (th/2 - yb)**2
        return I_h + I_v

    def J_torsion(self):
        b, h, tb, th = self.d1, self.d2, self.d3, self.d4
        return (b * tb**3 + (h - tb) * th**3) / 3

    def t_max_for_torsion(self):
        return max(self.d3, self.d4)

    def tau_T(self, T_load):
        J = self.J_torsion()
        if J <= 0:
            return 0.0
        return abs(T_load) * self.t_max_for_torsion() / J / 1000

    def Qy(self):
        # Approximate; uses upper-leg moment about NA
        _, zb = self.centroid()
        return self.d4 * zb**2 / 2

    def Qz(self):
        yb, _ = self.centroid()
        return self.d3 * yb**2 / 2

    def tw_y(self):
        return self.d4

    def tw_z(self):
        return self.d3

    def polygon_vertices(self):
        b, h, tb, th = self.d1, self.d2, self.d3, self.d4
        yb, zb = self.centroid()
        return [np.array([
            (0 - yb,  0 - zb),
            (b - yb,  0 - zb),
            (b - yb,  tb - zb),
            (th - yb, tb - zb),
            (th - yb, h - zb),
            (0 - yb,  h - zb),
        ])]

    def key_points(self, My, Mz):
        b, h, tb, th = self.d1, self.d2, self.d3, self.d4
        yb, zb = self.centroid()
        return [
            KeyPoint("A", "Vert leg top — left",     0 - yb,    h - zb),
            KeyPoint("B", "Vert leg top — right",    th - yb,   h - zb),
            KeyPoint("C", "Horiz leg right — bot",   b - yb,    0 - zb),
            KeyPoint("D", "Horiz leg right — top",   b - yb,    tb - zb),
            KeyPoint("E", "Inner corner",            th - yb,   tb - zb),
            KeyPoint("F", "Outer corner — bot-left", 0 - yb,    0 - zb),
            KeyPoint("G", "Centroid",                0,         0),
        ]


# ══════════════════════════════════════════════════════════════════════════
# C-BEAM / CHANNEL
# ══════════════════════════════════════════════════════════════════════════
class CBeam(Section):
    """
    Channel section. D1=b_f (flange width), D2=d (overall depth),
    D3=t_f (flange thickness), D4=t_w (web thickness).
    Channel opens to the +Y direction (web on the left).
    """

    name = "C-Beam / Channel"
    category = "Open thin-walled"
    is_open_section = True
    dim_labels = [
        ("b_f", "Flange width"),
        ("d",   "Overall depth"),
        ("t_f", "Flange thickness"),
        ("t_w", "Web thickness"),
    ]
    dim_defaults = [3.0, 6.0, 0.375, 0.25]
    f_cozzone = 1.15

    def area(self):
        bf, d, tf, tw = self.d1, self.d2, self.d3, self.d4
        return 2 * bf * tf + (d - 2 * tf) * tw

    def centroid(self):
        bf, d, tf, tw = self.d1, self.d2, self.d3, self.d4
        Af, Aw = 2 * bf * tf, (d - 2 * tf) * tw
        # Web at left edge (y=0); centroid shifted right
        zb = d / 2
        yb = (Af * bf/2 + Aw * tw/2) / (Af + Aw)
        return (yb, zb)

    def Iy(self):
        bf, d, tf, tw = self.d1, self.d2, self.d3, self.d4
        # Symmetric about Y axis through centroid (since flanges symmetric vertically)
        flanges = 2 * (bf * tf**3 / 12 + bf * tf * (d/2 - tf/2)**2)
        web = tw * (d - 2 * tf)**3 / 12
        return flanges + web

    def Iz(self):
        bf, d, tf, tw = self.d1, self.d2, self.d3, self.d4
        yb, _ = self.centroid()
        Af, Aw = 2 * bf * tf, (d - 2 * tf) * tw
        I_flanges = 2 * (tf * bf**3 / 12 + bf * tf * (bf/2 - yb)**2)
        I_web = (d - 2 * tf) * tw**3 / 12 + Aw * (tw/2 - yb)**2
        return I_flanges + I_web

    def J_torsion(self):
        bf, d, tf, tw = self.d1, self.d2, self.d3, self.d4
        return (2 * bf * tf**3 + (d - 2 * tf) * tw**3) / 3

    def t_max_for_torsion(self):
        return max(self.d3, self.d4)

    def tau_T(self, T_load):
        J = self.J_torsion()
        if J <= 0:
            return 0.0
        return abs(T_load) * self.t_max_for_torsion() / J / 1000

    def Qy(self):
        bf, d, tf, tw = self.d1, self.d2, self.d3, self.d4
        # Q at NA = flange + half-web above
        Q_flange = bf * tf * (d/2 - tf/2)
        Q_web = tw * (d/2 - tf)**2 / 2
        return Q_flange + Q_web

    def Qz(self):
        # Approximate
        bf, d, tf, tw = self.d1, self.d2, self.d3, self.d4
        yb, _ = self.centroid()
        return bf * tf * (bf/2 - yb)

    def tw_y(self):
        return self.d4

    def tw_z(self):
        return 2 * self.d3

    def polygon_vertices(self):
        bf, d, tf, tw = self.d1, self.d2, self.d3, self.d4
        yb, _ = self.centroid()
        return [np.array([
            (0 - yb,   -d/2),
            (bf - yb,  -d/2),
            (bf - yb,  -d/2 + tf),
            (tw - yb,  -d/2 + tf),
            (tw - yb,   d/2 - tf),
            (bf - yb,   d/2 - tf),
            (bf - yb,   d/2),
            (0 - yb,    d/2),
        ])]

    def key_points(self, My, Mz):
        bf, d, tf, tw = self.d1, self.d2, self.d3, self.d4
        yb, _ = self.centroid()
        return [
            KeyPoint("A", "Top flange tip",      bf - yb,   d/2),
            KeyPoint("B", "Bot flange tip",      bf - yb,  -d/2),
            KeyPoint("C", "Top flange-web jct",  tw - yb,   d/2 - tf),
            KeyPoint("D", "Bot flange-web jct",  tw - yb,  -d/2 + tf),
            KeyPoint("E", "Web top",             0 - yb,    d/2 - tf),
            KeyPoint("F", "Web mid — max shear", 0 - yb,    0),
            KeyPoint("G", "Web bot",             0 - yb,   -d/2 + tf),
        ]


# ══════════════════════════════════════════════════════════════════════════
# Z-BEAM
# ══════════════════════════════════════════════════════════════════════════
class ZBeam(Section):
    """
    Z-section. D1=b_f (flange width), D2=d (overall depth),
    D3=t_f (flange thickness), D4=t_w (web thickness).
    Top flange extends in +Y, bottom flange in -Y.

    Bending uses the full unsymmetric-bending tensor (design handoff §3.1),
    so the nonzero product of inertia Iyz is accounted for exactly — no
    geometric-axis constraint assumption is required (Phase 1, CHANGELOG).
    Iyz is computed from the section polygon via Green's theorem.
    """

    name = "Z-Beam"
    category = "Open thin-walled"
    is_open_section = True
    dim_labels = [
        ("b_f", "Flange width"),
        ("d",   "Overall depth"),
        ("t_f", "Flange thickness"),
        ("t_w", "Web thickness"),
    ]
    dim_defaults = [3.0, 6.0, 0.375, 0.25]
    f_cozzone = 1.10

    def area(self):
        bf, d, tf, tw = self.d1, self.d2, self.d3, self.d4
        return 2 * bf * tf + (d - 2 * tf) * tw

    def centroid(self):
        # Symmetric about both centroidal axes (point-symmetric)
        return (self.d1 / 2 + self.d4 / 2 - self.d1 / 2, self.d2 / 2)

    def Iy(self):
        bf, d, tf, tw = self.d1, self.d2, self.d3, self.d4
        flanges = 2 * (bf * tf**3 / 12 + bf * tf * (d/2 - tf/2)**2)
        web = tw * (d - 2 * tf)**3 / 12
        return flanges + web

    def Iz(self):
        bf, d, tf, tw = self.d1, self.d2, self.d3, self.d4
        # Z-section flange centroids are offset in Y (top flange +Y, bottom
        # −Y), so each flange carries a parallel-axis term A·y_c². The v1
        # closed form omitted this (used only tf·bf³/12), underestimating Iz
        # ~3.5× at default dims — caught by the Phase 1 polygon validation
        # gate; see CHANGELOG.md. y_c = (bf − tw)/2 = flange midline offset.
        y_c = bf / 2 - tw / 2
        flanges = 2 * (tf * bf**3 / 12 + bf * tf * y_c**2)
        web = (d - 2 * tf) * tw**3 / 12
        return flanges + web

    def J_torsion(self):
        bf, d, tf, tw = self.d1, self.d2, self.d3, self.d4
        return (2 * bf * tf**3 + (d - 2 * tf) * tw**3) / 3

    def t_max_for_torsion(self):
        return max(self.d3, self.d4)

    def tau_T(self, T_load):
        J = self.J_torsion()
        if J <= 0:
            return 0.0
        return abs(T_load) * self.t_max_for_torsion() / J / 1000

    def Qy(self):
        bf, d, tf, tw = self.d1, self.d2, self.d3, self.d4
        Q_flange = bf * tf * (d/2 - tf/2)
        Q_web = tw * (d/2 - tf)**2 / 2
        return Q_flange + Q_web

    def Qz(self):
        bf = self.d1; tf = self.d3
        return 2 * tf * bf**2 / 8

    def tw_y(self):
        return self.d4

    def tw_z(self):
        return 2 * self.d3

    def polygon_vertices(self):
        bf, d, tf, tw = self.d1, self.d2, self.d3, self.d4
        # Z-section: bot flange goes left, top flange goes right
        return [np.array([
            (-tw/2,       -d/2),
            (-tw/2 + bf,  -d/2),
            (-tw/2 + bf,  -d/2 + tf),
            ( tw/2,       -d/2 + tf),
            ( tw/2,        d/2),
            ( tw/2 - bf,   d/2),
            ( tw/2 - bf,   d/2 - tf),
            (-tw/2,        d/2 - tf),
        ])]

    def key_points(self, My, Mz):
        bf, d, tf, tw = self.d1, self.d2, self.d3, self.d4
        return [
            KeyPoint("A", "Top flange right tip",   tw/2 - bf + bf,  d/2),
            KeyPoint("B", "Top flange-web jct",     tw/2,            d/2 - tf),
            KeyPoint("C", "Bot flange left tip",   -tw/2 + bf - bf, -d/2),
            KeyPoint("D", "Bot flange-web jct",    -tw/2,           -d/2 + tf),
            KeyPoint("E", "Web mid — max shear",    0,               0),
        ]


# ══════════════════════════════════════════════════════════════════════════
# PLUS / CROSS
# ══════════════════════════════════════════════════════════════════════════
class PlusCross(Section):
    """
    Cross (plus) section. D1=b (total width), D2=h (total height),
    D3=t_h (horizontal bar thickness), D4=t_v (vertical bar thickness).
    """

    name = "Plus / Cross"
    category = "Open thin-walled"
    is_open_section = True
    dim_labels = [
        ("b",   "Total width"),
        ("h",   "Total height"),
        ("t_h", "Horiz bar thick"),
        ("t_v", "Vert bar thick"),
    ]
    dim_defaults = [4.0, 4.0, 0.5, 0.5]
    f_cozzone = 1.30

    def area(self):
        b, h, th, tv = self.d1, self.d2, self.d3, self.d4
        # Avoid double-counting overlap (tv × th rectangle at center)
        return b * th + h * tv - th * tv

    def centroid(self):
        return (self.d1 / 2, self.d2 / 2)

    def Iy(self):
        b, h, th, tv = self.d1, self.d2, self.d3, self.d4
        # Horizontal bar about Y: b·th³/12. Vertical arms above & below the
        # horizontal bar span z ∈ [th/2, h/2]; each contributes
        # ∫z²·tv dz = tv·[(h/2)³ − (th/2)³]/3. The v1 form used
        # (h/2 − th/2)³ (wrong integral limits), over-predicting bending
        # stress — caught by the Phase 1 polygon validation gate; see
        # CHANGELOG.md.
        I_horiz = b * th**3 / 12
        I_vert = 2 * tv * ((h/2)**3 - (th/2)**3) / 3
        return I_horiz + I_vert

    def Iz(self):
        b, h, th, tv = self.d1, self.d2, self.d3, self.d4
        # Same correction as Iy, on the horizontal arms about Z.
        I_vert = h * tv**3 / 12
        I_horiz = 2 * th * ((b/2)**3 - (tv/2)**3) / 3
        return I_vert + I_horiz

    def J_torsion(self):
        b, h, th, tv = self.d1, self.d2, self.d3, self.d4
        return (b * th**3 + h * tv**3 - th * tv**3) / 3

    def t_max_for_torsion(self):
        return max(self.d3, self.d4)

    def tau_T(self, T_load):
        J = self.J_torsion()
        if J <= 0:
            return 0.0
        return abs(T_load) * self.t_max_for_torsion() / J / 1000

    def Qy(self):
        b, h, th, tv = self.d1, self.d2, self.d3, self.d4
        return b * th**2 / 8 + tv * (h/2 - th/2)**2 / 2

    def Qz(self):
        b, h, th, tv = self.d1, self.d2, self.d3, self.d4
        return h * tv**2 / 8 + th * (b/2 - tv/2)**2 / 2

    def tw_y(self):
        return self.d4   # vertical bar carries vertical shear

    def tw_z(self):
        return self.d3

    def polygon_vertices(self):
        b, h, th, tv = self.d1, self.d2, self.d3, self.d4
        return [np.array([
            (-b/2,  -th/2), (-tv/2, -th/2), (-tv/2, -h/2),
            ( tv/2, -h/2),  ( tv/2, -th/2), ( b/2,  -th/2),
            ( b/2,   th/2), ( tv/2,  th/2), ( tv/2,  h/2),
            (-tv/2,  h/2),  (-tv/2,  th/2), (-b/2,   th/2),
        ])]

    def key_points(self, My, Mz):
        b, h, th, tv = self.d1, self.d2, self.d3, self.d4
        return [
            KeyPoint("A", "Top arm tip",             0,    h/2),
            KeyPoint("B", "Bot arm tip",             0,   -h/2),
            KeyPoint("C", "Right arm tip",           b/2,  0),
            KeyPoint("D", "Left arm tip",           -b/2,  0),
            KeyPoint("E", "Top-right re-entrant",    tv/2, th/2),
            KeyPoint("F", "Top-left re-entrant",    -tv/2, th/2),
            KeyPoint("G", "Centroid — max shear",    0,    0),
        ]


# ══════════════════════════════════════════════════════════════════════════
# FLAT BAR  (thin rectangle)
# ══════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════
# SHAPE REGISTRY
# Append new shapes here to make them available everywhere.
# ══════════════════════════════════════════════════════════════════════════
SHAPE_REGISTRY: dict[str, type[Section]] = {
    Rectangle.name:    Rectangle,
    Circle.name:       Circle,
    Ellipse.name:      Ellipse,
    RectTube.name:     RectTube,
    CircularTube.name: CircularTube,
    IBeam.name:        IBeam,
    TBeam.name:        TBeam,
    LBeam.name:        LBeam,
    CBeam.name:        CBeam,
    ZBeam.name:        ZBeam,
    PlusCross.name:    PlusCross,
}

# Display order (used in dropdowns)
SHAPE_NAMES: list[str] = list(SHAPE_REGISTRY.keys())


def make_section(shape_name: str, dims: list) -> Section:
    """Factory: instantiate a Section subclass by name."""
    cls = SHAPE_REGISTRY.get(shape_name)
    if cls is None:
        raise ValueError(f"Unknown shape: {shape_name}")
    return cls(dims)
