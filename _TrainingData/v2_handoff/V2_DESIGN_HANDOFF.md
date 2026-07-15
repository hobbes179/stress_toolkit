# Stress Toolkit v2.0 — Design Handoff & Implementation Guide

**Audience:** Claude Code (or any AI-assisted development session)
**Prerequisite reading:** `CLAUDE.md` at repo root. This document *supersedes* `CLAUDE.md` wherever the two conflict (notably: shear combination, margin check set, interaction equation, and the shape-owns-formulas architecture). Everything else in `CLAUDE.md` — coordinate system, units, theme rules, ⚠️ marker conventions, file layout patterns — remains in force.
**Working style:** Implement phase by phase (§9). Every phase ends with a test gate that must pass before the next phase begins. Do not skip Phase 0.

---

## 1. Decision record (locked — do not relitigate)

These decisions were made by the project owner (structural engineer of record) and are not open for reinterpretation during implementation:

| # | Decision | Choice |
|---|----------|--------|
| D1 | Shear/torsion generalization engine | **Both** — classical midline (Bruhn) solver as the default for parametric catalog shapes; `sectionproperties` FEM solver for imported/arbitrary polygons. One shared solver protocol. |
| D2 | Corrected margin methodology rollout | **Replace legacy outright.** The old check set and the RSS shear combination are removed, not kept alongside. Every removed/changed equation gets a `CHANGELOG.md` entry with engineering rationale. |
| D3 | Must-have feature for v2 | **Polygon / DXF section import.** Load-case CSV envelope, PDF report + calc trace, and goal-seek/sweeps move to the roadmap (§11). |
| D4 | Plotting | Hybrid: Plotly for the interactive working view (hover probe), matplotlib retained for print-quality/report figures. |
| D5 | Cozzone | `f_cozzone` is forced to 1.0 for thin-walled open sections until a crippling module exists. Values > 1.0 permitted only for solid/compact-closed shapes with a documented source. |
| D6 | Validation | pytest golden-value suite + an in-app **Validation** page are in scope. |
| D7 | Theme / units | Dark mode only (unchanged). IPS units only (unchanged). |

---

## 2. Architecture: geometry–analysis separation

The core v1 limitation was that each shape class owned its own closed-form stress formulas. In v2, **shapes become geometry generators; analysis lives in engines.**

```
                     ┌────────────────────────────┐
 Catalog shape ────► │  SectionGeometry           │ ◄──── DXF / pasted polygon
 (parametric)        │  • boundary polygon(s)     │       (import path)
                     │  • voids                   │
                     │  • midline skeleton (opt.) │
                     └────────┬───────────────────┘
                              │
                ┌─────────────┴──────────────┐
                ▼                            ▼
   PolygonProperties (Green's thm)   SectionSolver (protocol)
   A, ȳ, z̄, Iy, Iz, Iyz,            ├─ ClassicalMidlineSolver (default,
   principal axes, rgy/rgz           │    requires skeleton — Bruhn methods)
                                     ├─ ExactSolidSolver (solids: rect/circle/
                                     │    ellipse keep documented closed forms)
                                     └─ FEMSolver (sectionproperties wrapper —
                                          any polygon, no skeleton needed)
                              │
                              ▼
                  Stress evaluation + margin engine
                  (calculations.py — solver-agnostic)
```

### 2.1 `SectionGeometry` (new, in `library/shapes/`)

```python
@dataclass(frozen=True)
class MidlineSegment:
    n1: int            # node index
    n2: int
    t: float           # wall thickness, in

@dataclass(frozen=True)
class SectionGeometry:
    outer: np.ndarray                    # (N,2) closed polygon, CCW, (y, z)
    voids: tuple[np.ndarray, ...] = ()   # inner loops, CW
    nodes: np.ndarray | None = None      # (M,2) midline nodes, if skeleton exists
    segments: tuple[MidlineSegment, ...] = ()
    cells: tuple[tuple[int, ...], ...] = ()   # segment-index loops for closed cells
    is_thin_walled: bool = False
```

- Every catalog `Section` subclass implements `geometry() -> SectionGeometry`. Thin-walled catalog shapes (I, T, L, C, Z, Plus, Rect Tube, Circular Tube) MUST populate the skeleton; solids (Rectangle, Circle, Ellipse) leave it empty.
- Circular geometry is discretized for the polygon (≥64 boundary points) but the exact analytic radius is retained on the shape class for the exact-solid formulas.
- Keep `SHAPE_REGISTRY`, `dim_labels`, `dim_defaults`, `key_points()` and the class-per-shape pattern. The classes shrink (geometry only); they do not disappear.
- **Reconcile the shape count**: README claims 13 shapes, `CLAUDE.md` lists 11. Count `SHAPE_REGISTRY` and make all docs agree.

### 2.2 `PolygonProperties` (new module `library/analysis/polygon_props.py`)

Pure functions over `SectionGeometry` polygons using Green's theorem (shoelace-style integrals): `A`, centroid, `Iy = ∫z²dA`, `Iz = ∫y²dA`, `Iyz = ∫yz dA` (all about the centroid), principal angle and principal moments, radii of gyration. Voids subtract. No Streamlit imports, full type hints, docstring with the closed-form vertex-sum expressions for traceability.

### 2.3 `SectionSolver` protocol (new module `library/analysis/solvers.py`)

```python
class SolverResult(TypedDict):
    J: float                      # torsion constant, in^4
    shear_center: tuple[float, float]   # (y_sc, z_sc) from centroid
    Cw: float | None              # warping constant, in^6 (None if unavailable)
    # per evaluation point arrays, aligned with the point list:
    tau_v: np.ndarray             # transverse shear stress, signed along wall tangent (ksi at unit... see §3.3)
    tau_t: np.ndarray             # torsional shear stress, signed along wall tangent

class SectionSolver(Protocol):
    name: str                     # shown in UI + report for traceability
    method_citation: str          # e.g. "Bruhn C6/A15; Bredt-Batho" or "sectionproperties vX.Y FEM"
    def solve(self, geom: SectionGeometry, props: PolygonProps,
              loads: Loads, points: np.ndarray) -> SolverResult: ...
```

**Routing rule (implement in `calculations.py`):**
1. Solid catalog shape → `ExactSolidSolver` (documented closed forms).
2. Thin-walled catalog shape (has skeleton) → `ClassicalMidlineSolver`.
3. Imported polygon (no skeleton) → `FEMSolver`.
4. UI exposes an override selectbox ("Solver: Auto / Classical / FEM") so classical-vs-FEM cross-checks are one click. FEM on a catalog shape uses its polygon.

The chosen solver's `name` and `method_citation` must appear in the results header — a stress report needs to say which method produced the numbers.

---

## 3. Normative methodology (replaces the corresponding sections of CLAUDE.md)

Every equation below must appear, exactly as implemented, in the UI formula block. Grep for the old versions and remove them everywhere (code, UI text, docstrings, README).

### 3.1 Normal stress — unsymmetric bending tensor (replaces geometric-axis assumption)

With `Δ = Iy·Iz − Iyz²` and moments defined so the symmetric case reduces to the v1 convention (`My` → σ ∝ z, `Mz` → σ ∝ y):

```
σ_x(y, z) = P/A + [ (My·Iz − Mz·Iyz)·z + (Mz·Iy − My·Iyz)·y ] / Δ
```

- Verify: with `Iyz = 0` this reduces to `P/A + My·z/Iy + Mz·y/Iz` (v1 formula). Unit test this reduction explicitly.
- This removes the ⚠️ ASSUMPTION about L/Z-beam constraint. Delete that assumption from the UI; keep a note that results are now valid for unconstrained unsymmetric sections.
- Neutral axis: compute and return its angle for plotting (locus σ_x = 0 with P = 0).

### 3.2 Transverse shear — per-point shear flow (replaces max-Q-everywhere)

General open-section shear flow, integrating from a free edge along the skeleton, including `Iyz`:

```
q(s) = − [ (Vy·Iy − Vz·Iyz)·∫₀ˢ y·t ds  +  (Vz·Iz − Vy·Iyz)·∫₀ˢ z·t ds ] / Δ
```

- Verify against the symmetric case: reduces to `q = −Vy·Qz/Iz − Vz·Qy/Iy` with `Qz = ∫y dA`, `Qy = ∫z dA`. **⚠️ Note while porting:** v1 documentation pairs `τ_Vy = Vy·Qy/(Iy·t)` — check whether that pairing is a naming quirk or a real axis mix-up in `calculations.py`, and record the finding in `CHANGELOG.md` either way. The physically correct pairing is Vy ↔ (Iz, ∫y dA) and Vz ↔ (Iy, ∫z dA).
- Closed single cell: cut the cell to make it open, compute `q_open(s)`, then add the constant redundant flow
  `q₀ = −∮(q_open/t) ds / ∮(1/t) ds` (zero-twist condition, shear applied at the shear center). `τ_V = (q_open + q₀)/t`.
- Multi-cell sections are **out of scope** for v2 (no catalog shape needs them; imported multi-cell polygons route to FEM anyway). Note this limit in the docstring.
- Shear center: from moment equivalence of q(s) about the centroid, one axis at a time. Needed for §3.4 and reported in section properties.

### 3.3 Torsion and the shear combination (replaces RSS — the v1 unconservative defect)

Torsional stress by section class (unchanged formulas, corrected *combination*):

- Open: `J = Σ(L·t³)/3`, surface stress `τ_T = T·t/J` per segment (sign = ± across thickness).
- Closed single cell: `J = 4·Am² / ∮(ds/t)`, flow `q_T = T/(2·Am)`, `τ_T = T/(2·Am·t_local)` — use the *local* segment thickness, and for the governing value the *minimum* wall thickness.
- Solids: circle `τ = 16T/(πd³)`; ellipse `τ = 2T/(π·a·b²)` **with b = semi-MINOR axis — enforce `a ≥ b` by sorting inputs, or raise a validation error** (v1 silently goes unconservative if the user swaps them); rectangle uses Roark α/β coefficients (verify v1 does not misapply the thin-wall Σbt³/3 to the solid rectangle).

**Combination rule (normative):** transverse and torsional shear are collinear along a wall segment. They combine **algebraically, not by RSS**:

```
τ_wall(s) = q_V(s)/t  +  q_T/t            (closed cells — signed flows, same tangent convention)
τ_wall(s) = |q_V(s)/t| + |T·t/J|          (open sections — St. Venant surface stress, conservative sign)
τ_solid   = |τ_V| + |τ_T|                 (solids — conservative collinear assumption)
```

`√(τ_Vy² + τ_Vz² + τ_T²)` must not survive anywhere in the codebase. Add a test that greps/asserts the governing combined shear for a circular tube under Vz + T equals `τ_V + τ_T` at the horizontal-diameter point (v1 returned the RSS value, ~29% low when the components are equal).

### 3.4 Load application point and induced torsion (new)

Add a UI input: **"Shear loads applied at: Shear center (default) / Centroid / Custom (y, z)."** When not at the shear center:

```
T_total = T_applied + Vz·(y_app − y_sc) − Vy·(z_app − z_sc)
```

(right-hand rule about +X; validate the sign with the channel test in §7). Display the induced component separately in the results so the report shows where the torque came from. This matters most for channels — v1 silently assumed zero induced torsion.

### 3.5 Warping screen (new, quantitative — replaces the qualitative warning)

For open sections under torsion, compute `Cw` (FEM solver provides it; classical solver may return closed-form values for I/C/Z if implemented, else `None`) and report the characteristic length:

```
λ = √(E·Cw / (G·J))
```

UI adds an optional "member length L" input in the torsion warning box. Guidance text: `L/λ ≳ 10` → St. Venant-only is reasonable; `L/λ ≲ 2` with restrained ends → warping dominates, results unconservative, red warning. Warping *stresses* themselves remain out of scope (roadmap).

### 3.6 Margin-of-safety check set (REPLACES the v1 six checks — D2)

`MS = Allowable / (SF · f_applied) − 1`, with user-editable `SF_yield` (default 1.0) and `SF_ult` (default 1.5). Plane-stress state at each evaluation point: `σ = σ_x`, `τ = τ_wall`; `σ₁,σ₂ = σ/2 ± √((σ/2)² + τ²)`; `σ_vm = √(σ₁² − σ₁σ₂ + σ₂²)`.

| # | Check | Applied | Allowable | SF | Notes |
|---|-------|---------|-----------|----|-------|
| 1 | Yield (von Mises) | σ_vm | Fty | SF_yield | Primary yield criterion (replaces v1 "σ₁ vs Fty") |
| 2 | Ultimate (max principal) | σ₁ (if > 0) | Ftu | SF_ult | |
| 3 | Compression yield | \|σ₂\| (σ₂ < 0) | Fcy | SF_yield | Local material check; column/crippling stability NOT covered — keep the existing caveat |
| 4 | Ultimate shear | \|τ_wall\| | Fsu | SF_ult | |
| 5 | Combined interaction | see below | — | SF_ult | Replaces v1 check 6 |

**Interaction (replaces `1/√(Rc²+Rb²+Rs²) − 1`, which was unconservative — it reported MS = +0.41 at a true zero-margin axial+bending state):** normal-stress ratios group linearly; shear enters quadratically. Interaction curve `(Ra + Rb) + Rs² = 1`:

```
Ra = |σ_axial| / Fa      Fa = Ftu if σ_axial ≥ 0 else Fcy
Rb = |σ_bend|  / Fbu     Fbu = f_cozzone · Ftu   (f gated per D5)
Rs = |τ_wall| / Fsu
MS = 2 / [ (Ra + Rb) + √( (Ra + Rb)² + 4·Rs² ) ] − 1
```

Unit test: `Ra = Rb = 0.5, Rs = 0` must yield `MS = 0.0` exactly. Document the curve form and its Bruhn C4-family lineage in the docstring; the UI formula block must show the curve equation, not just the MS closed form.

**Removed checks (record in CHANGELOG with rationale):** "σ₁ vs Fty" (max-normal-stress yield criterion — unconservative up to 73% for shear-dominated states vs distortion energy) and "σ_vm vs Ftu" (von Mises is a yield criterion; pairing it with an ultimate allowable was ad hoc — its role is covered by checks 2 and 4).

### 3.7 Cozzone gating (D5)

In the `Section` base class: `effective_f_cozzone` returns 1.0 when `is_open_section and is_thin_walled`, with a UI badge "f = 1.0 (plastic bending gated pending crippling check)". For solids/compact closed shapes, keep the documented table values. Verify no thin-walled shape currently carries f > ~1.1; if any does, that was unconservative — CHANGELOG it.

### 3.8 Evaluation points (replaces fixed key points as the *analysis* set)

Stress is evaluated at: all midline segment endpoints and midpoints (thin-walled), or a dense boundary + interior sampling (solids/FEM), **plus** the legacy named `key_points()` for report continuity. The governing point is found over the full set — v1's max-Q-everywhere masked the true critical location; v2 must report the actual governing coordinates, labeled with the nearest named KP when within tolerance.

---

## 4. FEM solver — `sectionproperties` wrapper (D1)

Module `library/analysis/fem_solver.py`. Wrap, don't leak: nothing outside this module imports `sectionproperties`.

- **Axis mapping is the #1 defect risk.** `sectionproperties` uses an x–y section plane with z longitudinal; this project uses y–z with x longitudinal. Build an explicit adapter (our y → their x, our z → their y; P → N, Vy/Vz and My/Mz/T mapped with signs TBD) and *prove the signs with tests, not by inspection*: run the FEM solver on a symmetric I-beam and rectangle and assert agreement with the exact formulas for each load component applied one at a time, positive and negative. Do not proceed past this gate with any sign fudge factors left unexplained.
- Geometry: build `shapely` polygons (outer minus voids) → `sectionproperties` Geometry → mesh with `mesh_sizes` defaulting to ~(min wall thickness)²/2 for thin-walled imports, with a UI "mesh refinement" select (Coarse/Default/Fine). Run a coarse-vs-fine sanity delta on J and report it.
- Extract: A, Iy, Iz, Iyz (cross-check against our Green's-theorem values — assert ≤ 0.5% or fail loudly), J, Cw, shear center, and per-point stress fields for the evaluation points (interpolate from the FEM stress results at requested coordinates).
- Performance: the warping solve is the slow step. `@st.cache_data` on a hash of (vertices bytes, mesh size, loads) for stress; cache the meshed section object with `@st.cache_resource` keyed by geometry hash. Never re-mesh on a loads-only change.
- Deployment risk: `sectionproperties` and its meshing backend must install on Streamlit Cloud. Verify by deploying a branch **early in Phase 4**, not at the end.
- `method_citation` string must include the installed `sectionproperties` version (read at runtime) — reports need it.

---

## 5. Polygon / DXF import (D3 — the v2 headline feature)

New geometry source in the Geometry tab: **"Custom section"** alongside the catalog shapes.

### 5.1 Input paths
1. **DXF upload** (`st.file_uploader`, `.dxf`): parse with `ezdxf`. Accept closed `LWPOLYLINE`/`POLYLINE` entities (tessellate bulges/arcs to ≤ 1° chord error) and `CIRCLE` entities as loops. Largest-area loop = outer boundary; loops fully inside it = voids; anything else → clear per-entity error message listing what was skipped and why.
2. **Pasted vertices** (`st.text_area`): one `y, z` pair per line; blank line separates loops; first loop = outer. This is the zero-friction path and doubles as the test harness for the DXF path.

### 5.2 Validation (do all of it — imported geometry is untrusted input)
- Loops closed (snap tolerance 1e-6 in), non-self-intersecting (`shapely` `is_valid`), correct winding (auto-fix: outer CCW, voids CW), voids strictly inside outer, no duplicate consecutive points, vertex count cap (~2,000; offer Douglas-Peucker simplification above it).
- **Units:** assume drawing units are inches. Show the bounding box (b × h) and A prominently and require the user to visually confirm before analysis — silent unit errors are the classic failure of DXF import.
- Imported sections route to `FEMSolver` (no skeleton), get the full unsymmetric bending treatment from §3.1 automatically, and display an "IMPORTED — FEM" badge in results.
- Evaluation points: boundary vertices + FEM-suggested extrema. `key_points()` doesn't exist here; the governing-point report uses raw coordinates.

---

## 6. UX overhaul (D4 + defaults)

### 6.1 Responsiveness — do these before touching visuals
1. `@st.fragment` around the results panel so load edits don't re-run geometry/material code.
2. Load inputs inside `st.form` ("Apply loads" submit) — six edits, one recompute.
3. `@st.cache_data` on: polygon build (shape, dims), classical solve (geometry hash), property calcs. Cache functions return plain arrays/dataclasses — no figures, no Streamlit objects.
4. Figures built from cached arrays; never recompute stresses inside a plotting function.

### 6.2 Plotting — hybrid (D4)
- **Interactive working view (Plotly):** interpolate the existing Delaunay triangulation onto a ~300×300 grid (`matplotlib.tri.LinearTriInterpolator`), NaN-mask outside the section (shapely `contains` vectorized, or `matplotlib.path`), render `go.Heatmap`; overlay the exact boundary/void outlines as crisp `go.Scatter` strokes (this hides grid-edge raggedness); equal aspect via `yaxis scaleanchor="x"`. **Hover probe is the point of the exercise:** stack σ_x, τ, σ₁, σ_vm, and min-MS into `customdata` with a hovertemplate showing all of them at the cursor's (y, z). KP markers as labeled scatter. Colormap: cividis (perceptually uniform, grayscale-safe).
- **Report view (matplotlib):** keep the current triangulated contour exactly as-is (white background rule unchanged) behind a "Report figure" expander/download — it feeds screenshots and the future PDF export.
- Overlays on both: neutral axis line (§3.1), shear center marker, centroid marker, principal axes (dashed) when Iyz ≠ 0, and **positive load/moment convention arrows** (small glyph legend — the cheapest defense against sign-error inputs).

### 6.3 Layout
- Tabs: **Geometry | Loads | Results | Margins | Formulas | Validation**.
- Persistent governing banner above the tabs (`st.metric` row): min MS, governing check name, governing location, solver used. Color chips: MS < 0 red, 0 ≤ MS < 0.25 amber, else green — thresholds as constants in `ui/theme.py`, not inline.
- Geometry tab: live section preview with **dimension leader lines** (each shape provides an annotation spec: list of (p1, p2, label) drawn as dimension lines) so the user visually confirms b/h/tf/tw before trusting anything.
- Input validation per shape with inline `st.error` (tw < b/2, tf < h/2, wall < radius, a ≥ b for ellipse, …) — invalid inputs must never reach the solver as exceptions.
- Results table: `st.dataframe` with `column_config` (fixed decimals, right-aligned), background gradient on the MS column, governing row highlighted, CSV download button, and a "Copy as Markdown" button (for pasting into reports).
- Formula tab: regenerated from §3 — every equation shown must match the code (traceability rule).

---

## 7. Testing strategy & golden values (D6)

Create `tests/` with pytest; add `tests/golden_values.py` as a plain-data module **shared by both pytest and the in-app Validation page** (single source of truth).

### 7.1 Analytic golden cases (exact, hand-derivable — put the derivation in comments)
- Rectangle b×h: A, Iy, Iz (bh³/12), Iyz = 0.
- Thin ring (r, t): A = 2πrt, I = πr³t, J = 2πr³t; Bredt τ = T/(2πr²t).
- Circle: J = πd⁴/32, τ_max = 16T/(πd³).
- Uniform-thickness channel (midline dims b, h): shear center offset from web midline `e = 3b²/(h + 6b)` — validates the shear-flow integrator AND §3.4 induced torsion.
- Offset rectangle: Iyz of a rectangle displaced (dy, dz) from the origin = A·dy·dz — validates the Green's-theorem Iyz.
- Rotated rectangle (45°): principal axes recovery.
- Interaction: Ra = Rb = 0.5, Rs = 0 → MS = 0.0; Ra = Rb = 0, Rs = 1 → MS = 0.0.
- Shear combination: circular tube, Vz + T sized so τ_V = τ_T at the horizontal diameter → combined = 2τ (NOT 1.414τ).
- Tensor-bending reduction: Iyz = 0 case reproduces v1 `My·z/Iy + Mz·y/Iz` to machine precision.

### 7.2 Cross-solver agreement (the D1 payoff)
For every thin-walled catalog shape at default dims: classical vs FEM on A, Iy, Iz, Iyz (≤ 0.5%), J and shear center (≤ 3%), and τ at 5 sampled wall points under pure Vz, pure T, and combined (≤ 7% — thin-wall theory vs FEM legitimately differ near junctions; investigate anything beyond that, don't loosen the tolerance to pass).

### 7.3 Regression + smoke
- Port the CLAUDE.md smoke test into pytest; run the full pipeline for every registered shape × a combined load vector; assert finite results and at least one governing margin.
- DXF round-trip: generate a DXF of the I-beam polygon in the test, import it, assert FEM properties match the catalog I-beam ≤ 1%.
- Grep-guard test: assert the string pattern of the RSS combination does not appear in `apps/` or `library/` source.

### 7.4 In-app Validation page
Table per shape: property | classical | FEM | reference | %Δ, colored by tolerance, computed on demand (button) and cached. Sourced from `tests/golden_values.py`. This page is checker-facing evidence — treat its polish as part of the feature.

---

## 8. Dependencies & deployment

`requirements.txt` (pin exact versions at implementation time; verify each installs on Streamlit Cloud):

```
streamlit          # existing
numpy, pandas      # existing
matplotlib         # existing — report figures only
plotly             # new — interactive view
shapely            # new — polygon validation/masking
sectionproperties  # new — FEM solver (check its meshing backend installs on Cloud)
ezdxf              # new — DXF parsing
pytest             # new — dev dependency (may live in requirements-dev.txt)
```

Deploy a throwaway branch to Streamlit Cloud as soon as `sectionproperties` is added (Phase 4 gate) — dependency failures on Cloud are cheaper to discover early. App start must remain < ~10 s; lazy-import `sectionproperties` and `ezdxf` inside their modules, not at page import.

---

## 9. Phased implementation plan (each phase = one or more commits + green test gate)

**Phase 0 — Safety patch (ship to `main` immediately, before the v2 branch).**
The v1 RSS shear combination is *unconservative* at governing points — this cannot wait for the engine.
- Replace RSS with the conservative interim `τ_total = √(τ_Vy² + τ_Vz²) + |τ_T|`.
- Replace the margin check set and interaction equation per §3.6.
- Cozzone gate (§3.7), ellipse `a ≥ b` guard, Bredt min-thickness check.
- Create `CHANGELOG.md`; entries for every methodology change with engineering rationale (this file is a permanent project convention from now on — every future results-changing commit adds an entry).
- Update the UI formula block to match. Tag `v1.1.0`.
- *Gate:* interaction and shear-combination unit tests from §7.1 pass; smoke test passes.

**Phase 1 — PolygonProperties engine.** `SectionGeometry` + Green's-theorem properties; every catalog shape implements `geometry()`; wire normal stress through §3.1 (tensor bending). Delete the geometric-axis ⚠️ ASSUMPTION. *Gate:* analytic property goldens + tensor-reduction test pass; all shapes' polygon A/Iy/Iz match their v1 closed forms ≤ 0.1%.

**Phase 2 — Classical midline solver, open sections.** Skeletons for all thin-walled catalog shapes; shear-flow integrator (§3.2); open-section torsion; shear center; per-point τ with algebraic combination (§3.3); evaluation-point scheme (§3.8). Remove the interim Phase-0 combination in favor of the real one. *Gate:* channel shear-center golden passes; I-beam τ profile matches VQ/It hand values at web NA and flange points.

**Phase 3 — Closed cells, solids, induced torsion, warping screen.** Single-cell Bredt flow with the q₀ redundant (§3.2–3.3); `ExactSolidSolver`; load-application-point input + induced torsion (§3.4); λ warping screen (§3.5). *Gate:* thin-ring goldens; tube Vz+T combination golden; channel induced-torsion sign test.

**Phase 4 — FEM solver + routing.** `sectionproperties` wrapper with test-proven axis mapping (§4); Auto/Classical/FEM routing + UI override; caching. Deploy-to-Cloud check. *Gate:* §7.2 cross-solver agreement suite passes for all thin-walled shapes.

**Phase 5 — Polygon/DXF import.** Both input paths + full validation (§5). *Gate:* DXF round-trip test; hostile-input tests (open loop, self-intersection, void outside boundary) produce clean UI errors, never tracebacks.

**Phase 6 — UX overhaul.** Fragments/forms/caching, tabs, governing banner, Plotly hover view + matplotlib report view, annotated geometry preview, input validation, results-table upgrades (§6). *Gate:* manual pass on desktop + mobile; changing one load reruns only the results fragment (verify via `st.write` counters during dev, then remove).

**Phase 7 — Validation page, docs, release.** In-app Validation page (§7.4); rewrite `CLAUDE.md` to describe the v2 architecture (this handoff then becomes historical — move it to `_TrainingData/`); reconcile README shape count; `__version__ = "2.0.0"` + short git SHA in the page footer (traceability: reports must identify the tool version); tag `v2.0.0`.

---

## 10. Acceptance criteria (definition of done)

1. Full pytest suite green, including the grep-guard: no RSS shear combination anywhere in `apps/` or `library/`.
2. Classical vs FEM agreement per §7.2 tolerances for every thin-walled catalog shape.
3. A channel under Vz applied at the centroid reports nonzero induced torsion with the correct sign; the same load applied at the shear center reports zero.
4. An L-section under pure My shows a rotated neutral axis (Iyz ≠ 0 path exercised) and matches FEM ≤ 5% at corner points.
5. A DXF of a custom machined profile imports, analyzes via FEM, and renders the hover-probe contour.
6. Every equation in the UI Formulas tab is character-identical to the implementation docstrings (§3 is the source).
7. Solver name + citation + tool version + git SHA visible in the results header/footer.
8. `CHANGELOG.md` documents every results-changing decision with rationale; `CLAUDE.md` and `README.md` rewritten and mutually consistent (including the shape count).
9. Deployed on Streamlit Cloud; cold start < ~10 s; loads-only edits re-render in < ~1 s for catalog shapes.

---

## 11. Explicitly OUT of scope for v2 (roadmap — do not implement, do not partially implement)

Load-case CSV import + envelope reporting · PDF report export + substituted-values calc trace · goal-seek sizing + parametric sweeps · custom material entry UI + temperature knockdowns + A/B basis selection · warping *stress* computation (screen only in v2) · multi-cell closed sections in the classical solver · crippling module (prerequisite for un-gating Cozzone) · light mode · SI units · new analysis modules (column buckling remains first in line post-v2).

If any of these turns out to be trivially enabled by v2 work, note it in `CLAUDE.md`'s future-work section — still do not build it.

---

## 12. Guardrails (unchanged project law — from CLAUDE.md, restated because they bind this work)

- No `eval`, no string formulas. Plain Python methods, type hints, docstrings everywhere.
- `⚠️ ESTIMATED` / `⚠️ ASSUMPTION` marker conventions preserved and searchable; EST badges preserved in UI.
- IPS units; stresses in ksi; loads in lb / lb·in; the /1000 conversion stays inside `calculations.py`.
- Coordinate system unchanged (+Y right, +Z up, X = beam axis, origin at centroid; positive P = tension).
- All colors from `ui/theme.py`; matplotlib report figures keep the white background; dark mode only.
- `apps/<module>/` layout and thin `pages/N_*.py` wrappers unchanged; `calculations.py` and solver modules stay Streamlit-free.
- Never change a numerical result without a `CHANGELOG.md` entry.
