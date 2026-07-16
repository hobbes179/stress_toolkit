"""
library/shapes/import_section.py

Custom-section import (design handoff §5, decision D3 — the v2 headline
feature). Two input paths, both feeding the same validated-geometry pipeline:

    1. Pasted vertices  — "y, z" per line; blank line separates loops; the
       first loop is the outer boundary (zero-friction; also the test harness).
    2. DXF upload       — parsed with ezdxf (see parse_dxf).

Imported geometry is UNTRUSTED input, so it is validated hard (§5.2) before
it can reach a solver: loops closed and non-self-intersecting, winding
auto-fixed (outer CCW, voids CW), voids strictly inside the outer boundary,
duplicate points removed, and a vertex-count cap with Douglas-Peucker
simplification. Failures raise `GeometryImportError` with a plain-English
message so the UI can show `st.error(...)` rather than a traceback.

Imported sections carry no midline skeleton and no named key points, so they
route to the FEM solver and get the full unsymmetric-bending treatment
automatically.

Heavy/optional backends (shapely, ezdxf) are imported lazily inside the
functions that need them.
"""

from __future__ import annotations
import re

import numpy as np

from library.shapes.shapes import Section, KeyPoint
from library.shapes.geometry import (
    SectionGeometry, ensure_ccw, ensure_cw, signed_area,
)
from library.analysis.polygon_props import polygon_section_props, PolygonProps


MAX_VERTICES = 2000
_SNAP_TOL = 1e-6
_ARC_SAGITTA = 0.001     # max chord sagitta (in) for arc/circle tessellation (§5.1)


class GeometryImportError(Exception):
    """Raised for any invalid imported geometry (caught and shown in the UI)."""


# ──────────────────────────────────────────────────────────────────────────
# Loop cleaning
# ──────────────────────────────────────────────────────────────────────────
def _clean_loop(loop) -> np.ndarray:
    """Drop a trailing duplicate closing vertex and consecutive duplicates."""
    p = np.asarray(loop, dtype=float)
    if len(p) >= 2 and np.allclose(p[0], p[-1], atol=_SNAP_TOL):
        p = p[:-1]
    if len(p) < 2:
        return p
    keep = [0]
    for i in range(1, len(p)):
        if not np.allclose(p[i], p[keep[-1]], atol=_SNAP_TOL):
            keep.append(i)
    return p[keep]


# ──────────────────────────────────────────────────────────────────────────
# Pasted-vertex parsing
# ──────────────────────────────────────────────────────────────────────────
def parse_vertex_text(text: str) -> list[np.ndarray]:
    """
    Parse pasted vertices into loops. One "y, z" (comma- or space-separated)
    per line; a blank line starts a new loop. First loop = outer boundary.
    """
    loops: list[np.ndarray] = []
    cur: list[tuple[float, float]] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        s = raw.strip()
        if not s:
            if cur:
                loops.append(np.array(cur, dtype=float))
                cur = []
            continue
        if s.startswith("#"):
            continue
        parts = re.split(r"[,\s]+", s)
        if len(parts) < 2:
            raise GeometryImportError(
                f"Line {lineno}: expected 'y, z', got {raw!r}.")
        try:
            y, z = float(parts[0]), float(parts[1])
        except ValueError:
            raise GeometryImportError(
                f"Line {lineno}: could not read two numbers from {raw!r}.")
        cur.append((y, z))
    if cur:
        loops.append(np.array(cur, dtype=float))
    if not loops:
        raise GeometryImportError("No vertices found.")
    return loops


# ──────────────────────────────────────────────────────────────────────────
# DXF parsing
# ──────────────────────────────────────────────────────────────────────────
def parse_dxf(data: bytes) -> tuple[list[np.ndarray], list[str]]:
    """
    Parse closed LWPOLYLINE / POLYLINE and CIRCLE entities from a DXF byte
    stream into loops (arcs/bulges tessellated). Returns (loops, skipped)
    where `skipped` lists per-entity reasons for anything not imported.
    """
    import io
    from ezdxf import recover
    from ezdxf.path import make_path

    try:
        doc, _auditor = recover.read(io.BytesIO(data))
    except Exception as e:               # noqa: BLE001 — surface any parse failure cleanly
        raise GeometryImportError(f"Could not read DXF file: {e}")

    msp = doc.modelspace()
    loops: list[np.ndarray] = []
    skipped: list[str] = []

    # Chord/sagitta tolerance for arc flattening (~1° chord on a typical part).
    flat = _ARC_SAGITTA

    for e in msp:
        t = e.dxftype()
        try:
            if t == "LWPOLYLINE" and not e.closed:
                skipped.append("open LWPOLYLINE (not a closed loop)")
                continue
            if t == "POLYLINE" and not e.is_closed:
                skipped.append("open POLYLINE (not a closed loop)")
                continue
            if t not in ("LWPOLYLINE", "POLYLINE", "CIRCLE"):
                skipped.append(f"{t} (unsupported entity type)")
                continue
            # make_path handles bulges/arcs/circles uniformly; flattening
            # tessellates to the chord tolerance.
            pts = np.array([(p.x, p.y) for p in make_path(e).flattening(flat)],
                           dtype=float)
            loops.append(pts)
        except Exception as ex:          # noqa: BLE001
            skipped.append(f"{t} (could not tessellate: {ex})")

    if not loops:
        detail = ("; ".join(skipped)) or "no geometry entities present"
        raise GeometryImportError(
            "No closed LWPOLYLINE/POLYLINE or CIRCLE loops found in the DXF. "
            f"Skipped: {detail}.")
    return loops, skipped


# ──────────────────────────────────────────────────────────────────────────
# Validation → (outer, voids) centred on the centroid
# ──────────────────────────────────────────────────────────────────────────
class ImportResult:
    """Validated, centroid-centred geometry plus reporting info."""
    def __init__(self, outer, voids, area, bbox, notes):
        self.outer = outer
        self.voids = voids
        self.area = area
        self.bbox = bbox          # (b, h)
        self.notes = notes        # list[str]


def validate_loops(loops: list[np.ndarray]) -> ImportResult:
    """
    Validate raw loops (§5.2) and return centroid-centred geometry. Raises
    GeometryImportError with a clear message on any invalid input.
    """
    from shapely import Polygon
    from shapely.validation import explain_validity

    cleaned = [_clean_loop(l) for l in loops]
    cleaned = [l for l in cleaned if len(l) >= 3]
    if not cleaned:
        raise GeometryImportError(
            "Need at least one closed loop with 3+ distinct vertices.")

    notes: list[str] = []

    # Vertex-count cap with Douglas-Peucker simplification (§5.2).
    total = sum(len(l) for l in cleaned)
    if total > MAX_VERTICES:
        span = float(np.ptp(np.concatenate(cleaned), axis=0).max())
        tol = span * 1e-4
        simplified = []
        for l in cleaned:
            sp = Polygon(l).simplify(tol, preserve_topology=True)
            simplified.append(np.asarray(sp.exterior.coords)[:-1])
        cleaned = [l for l in simplified if len(l) >= 3]
        new_total = sum(len(l) for l in cleaned)
        notes.append(f"Simplified {total} → {new_total} vertices "
                     f"(Douglas-Peucker, tol={tol:.4g} in).")

    # Largest-area loop is the outer boundary; the rest must be interior voids.
    areas = [abs(signed_area(l)) for l in cleaned]
    oi = int(np.argmax(areas))
    outer = cleaned[oi]
    others = [l for i, l in enumerate(cleaned) if i != oi]

    outer_poly = Polygon(outer)
    if not outer_poly.is_valid:
        raise GeometryImportError(
            f"Outer boundary is self-intersecting: {explain_validity(outer_poly)}.")

    voids = []
    for i, l in enumerate(others):
        vp = Polygon(l)
        if not vp.is_valid:
            raise GeometryImportError(
                f"Void loop #{i + 1} is self-intersecting: {explain_validity(vp)}.")
        if not outer_poly.contains(vp):
            raise GeometryImportError(
                f"Loop #{i + 1} is not strictly inside the outer boundary "
                "(a stray, overlapping, or crossing loop). Every non-outer "
                "loop must be a hole fully within the section.")
        voids.append(l)

    final = Polygon(outer, voids)
    if not final.is_valid:
        raise GeometryImportError(
            f"Section is invalid (overlapping voids?): {explain_validity(final)}.")

    # Winding: outer CCW, voids CW.
    outer = ensure_ccw(outer)
    voids = [ensure_cw(v) for v in voids]

    # Centre on the centroid so it behaves like the catalog shapes.
    props = polygon_section_props(outer, tuple(voids))
    shift = np.array([props.y_bar, props.z_bar])
    outer_c = outer - shift
    voids_c = tuple(v - shift for v in voids)

    b = float(np.ptp(outer_c[:, 0]))
    h = float(np.ptp(outer_c[:, 1]))
    return ImportResult(outer_c, voids_c, props.A, (b, h), notes)


# ──────────────────────────────────────────────────────────────────────────
# ImportedSection — a Section backed by an arbitrary validated polygon
# ──────────────────────────────────────────────────────────────────────────
class ImportedSection(Section):
    """
    A Section built from imported geometry. Properties come from Green's
    theorem (A, Iy, Iz, Iyz — the full unsymmetric-bending path applies);
    torsion / shear route to the FEM solver (no midline skeleton). Marked
    with `is_imported = True` so calculations.py forces the FEM solver.
    """
    name = "Custom (imported)"
    category = "Imported (FEM)"
    is_open_section = False
    is_imported = True
    f_cozzone = 1.0            # no plastic-bending credit for arbitrary shapes

    def __init__(self, outer, voids=(), meta: dict | None = None):
        self._outer = np.asarray(outer, dtype=float)
        self._voids = tuple(np.asarray(v, dtype=float) for v in voids)
        self._props: PolygonProps = polygon_section_props(self._outer, self._voids)
        self.dims = []
        self.meta = meta or {}
        self._J_cache: float | None = None

    # ── Geometry / properties ────────────────────────────────────────────
    def area(self): return self._props.A
    def centroid(self): return (0.0, 0.0)      # already centred
    def Iy(self): return self._props.Iy
    def Iz(self): return self._props.Iz
    def Iyz(self): return self._props.Iyz
    def section_props(self): return self._props

    def cy(self):
        return float(max(abs(self._outer[:, 0].min()), abs(self._outer[:, 0].max())))

    def cz(self):
        return float(max(abs(self._outer[:, 1].min()), abs(self._outer[:, 1].max())))

    def polygon_vertices(self):
        return [self._outer, *self._voids]

    def geometry(self) -> SectionGeometry:
        return SectionGeometry(
            outer=ensure_ccw(self._outer),
            voids=tuple(ensure_cw(v) for v in self._voids),
            nodes=None, is_thin_walled=False,
        )

    def J_torsion(self):
        if self._J_cache is None:
            from library.analysis.fem_solver import fem_properties, default_mesh_size
            ms = default_mesh_size(self._outer, self._voids)
            self._J_cache = fem_properties(self._outer, self._voids, ms)["J"]
        return self._J_cache

    def tau_T(self, T_load):
        # Torsion stress is produced by the FEM path, not this method.
        return 0.0

    # First-moment / wall quantities have no simple closed form for an
    # arbitrary polygon; shear for imported sections comes from the FEM path
    # (calc_stress_at_points), not VQ/It. These 0 stubs keep the legacy
    # contour evaluator (plotting._stress_at) from raising — its shear field
    # is superseded by the Phase-6 FEM contour.
    def Qy(self): return 0.0
    def Qz(self): return 0.0
    def tw_y(self): return 0.0
    def tw_z(self): return 0.0

    def validate_dims(self):
        return None

    def Cw(self):
        return None

    # ── Evaluation points: boundary vertices + centroid (§5.2) ───────────
    def key_points(self, My=0.0, Mz=0.0):
        kps = [KeyPoint(f"B{i}", "boundary vertex", float(y), float(z))
               for i, (y, z) in enumerate(self._outer)]
        for j, void in enumerate(self._voids):
            for i, (y, z) in enumerate(void):
                kps.append(KeyPoint(f"H{j}.{i}", "void vertex", float(y), float(z)))
        kps.append(KeyPoint("C", "centroid", 0.0, 0.0))
        return kps


def make_imported_section(loops: list[np.ndarray]) -> tuple[ImportedSection, ImportResult]:
    """Validate loops and build an ImportedSection. Raises GeometryImportError."""
    res = validate_loops(loops)
    sec = ImportedSection(res.outer, res.voids,
                          meta={"area": res.area, "bbox": res.bbox, "notes": res.notes})
    return sec, res
