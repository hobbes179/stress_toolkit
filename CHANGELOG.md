# CHANGELOG

All results-changing methodology decisions are recorded here with engineering
rationale, per `_TrainingData/v2_handoff/V2_DESIGN_HANDOFF.md` §9 (Phase 0)
and the project convention it establishes: **every future results-changing
commit adds an entry to this file.**

---

## Known behavior — FEM vs Classical at sharp re-entrant corners

Not a bug; recorded so it is not mistaken for one. The classical midline
solver is a **nominal-stress** method (τ = T·t/J, smooth VQ/It) and ignores
corners by construction. The FEM solver meshes the geometry exactly as drawn,
and the catalog shapes have perfectly sharp, unfilleted 90° re-entrant
corners at their web–flange junctions. Consequences when comparing solvers:

- Under bending/shear, FEM reads a *finite but elevated* stress at those
  junctions (~10–25% above classical at default dims).
- Under **torsion**, the stress at a sharp inside corner is theoretically
  **singular**, so the FEM peak there does not converge — it grows with mesh
  refinement (channel pure-T example: 1.66 → 1.91 → 2.26 → 2.64 ksi across
  Coarse→finer, vs the classical nominal 1.41 ksi). The FEM shear cluster
  sampling reports this local peak.

The §7.2 cross-solver agreement suite deliberately samples wall **midpoints**
(away from corners), where the two solvers agree to the documented
tolerances. Per the project owner's decision, the app keeps the raw FEM peaks
(they are the true corner concentration for the geometry as drawn) and shows
a header warning when FEM is selected: the peak at a sharp junction is
mesh-dependent and not a converged design value — model a fillet radius for
real corner stresses. (A fillet-on-import option remains available as future
work if convergent corner values are wanted.)

---

## Phase 6 — UX / plotting overhaul (in progress, unreleased)

### 6C.1 — Report figure: fix uniform-shear contour

Bug fix (plotting only; table/margin numbers unaffected). The "Report figure
(matplotlib, print-quality)" in the Results tab still called the legacy
`draw_contour`, whose `_stress_at` computes shear from **section-level
constants** (`Qy, Qz, tw_y, tw_z, tau_T`) that don't depend on (y, z). Result:
the shear field (and the τ contribution to σ_vm/σ₁/σ₂) rendered as a single
uniform value — the "old uniform shear" the report figure showed. Only the
interactive Plotly view had been switched to the real FEM field in 6A.

Fix: new `draw_report_contour(section, ys, zs, sig, tau, field_key)` renders
the print figure from the **same `compute_stress_field` FEM grid** the
interactive view uses (fetched via the 6B cache → instant), so the report
figure and the interactive contour are now identical fields in different
renderers. Void masking (tube bore) preserved via the centroid-in-section
triangle mask. The legacy `draw_contour` is retained only for the no-FEM
fallback. Regression test asserts the legacy τ path is uniform (no colorbar)
while the FEM report path varies (colorbar present).

### 6C — Tabbed layout + governing banner (§6.3)

Presentation only; no results change. The single long scrolling page was
reorganized into six tabs — **Geometry | Loads | Results | Margins |
Formulas | Validation** — with a persistent governing banner above them.

- **Governing banner** (`ui.components.governing_banner`): a 4-cell metric
  row — min MS (color-chipped), governing check, its location (the KP where
  that check's stress column peaks), and the solver used. Colors come from
  new **`ui.theme` thresholds** `MS_FAIL = 0.0`, `MS_WARN = 0.25` via
  `ms_status()` (never inline, per the handoff).
- **`governing_summary(df_stress, df_ms)`** (pure, in calculations.py):
  reduces the margin table to `(min_ms, check_name, location)`; the
  combined-interaction row is reported as section-wide. Unit-tested.
- **Tab mapping**: Geometry = section diagram + key points + properties (+ FEM
  mesh subtab); Loads = applied loads + material allowables; Results =
  governing summary cards + interactive contour (the 6B fragment, relocated
  intact) + per-KP stress table; Margins = MS table; Formulas = the reference
  (promoted out of an expander); Validation = a lightweight FEM-vs-closed-form
  section-property cross-check (A/Iy/Iz/J with %Δ chips) previewing the full
  Phase 7 validation page.

Both render paths (FEM and the no-FEM matplotlib fallback) verified end-to-end
via `streamlit.testing.v1.AppTest`.

### 6B — Performance: caching + result fragment

No results change; interaction latency only. Streamlit reruns the whole
script on every widget change, so before this the app recomputed the FEM
stress field (~0.8 s) on *every* overlay toggle or displayed-field switch,
even though neither changes σ/τ. Measured pipeline: mesh+warping solve
~4.5 s (already persisted across reruns by the module-level mesh cache),
contour grid ~0.8 s, J-convergence ~1.4 s.

- **`st.cache_data` layer** (app.py) keyed on geometry + loads + mesh:
  `_cached_results` (stress + margin tables), `_cached_stress_field` (the
  contour grid solve), `_cached_jconv` (mesh-tab J delta). Object args are
  passed underscore-prefixed so only the lightweight key is hashed.
- **Split `interactive_stress_contour`**: the expensive FEM grid solve moved
  to a pure, picklable `compute_stress_field()`; the function now accepts a
  precomputed `field=` so figure assembly (overlays, field selection) runs
  without re-solving. The per-point min-MS loop was vectorized
  (`_min_ms_field`) — numerically identical to the old scalar loop (0.0 err).
- **`@st.fragment`** around the contour controls + chart: toggling an overlay
  or switching the displayed field reruns only that fragment and hits the
  cached field. Measured: contour rebuild with a reused field **0.016 s vs
  0.93 s** for a full solve (~58×). The matplotlib report figure moved just
  outside the fragment so it isn't redrawn on every overlay tick.

Deliberately did **not** wrap loads in `st.form` (the handoff mentioned it):
the sidebar's live induced-torsion and warping-screen feedback depend on
reactive load values, and caching already makes a load edit cheap (mesh stays
warm; only the ~0.8 s grid re-solves). Easy to add later if wanted.

Tidy-up: removed unused `KeyPoint` import (calculations.py) and the now-dead
`_point_min_ms` scalar helper (replaced by the vectorized field).

### 6A.2 — Mesh quality + contour overlays

**Mesh sizing — guarantee ≥2 elements through wall thickness.**
`default_mesh_size` for thin-walled sections changed from a max element area
of `t²/2` to `t²/8` (edge ≈ t/2). Rationale: at `t²/2`, ~50% of elements
spanned the full wall thickness — a single element touching both faces of a
wall, which the owner explicitly does not want. At `t²/8` the worst element's
through-thickness span is ≈0.6·t and **zero** elements bridge a wall
(measured on a 2.0×0.1 strip: 254 elements, max span 0.62·t). Effect on
results: finer FEM mesh ⇒ marginally more accurate warping/stress and better
J convergence (all existing convergence tolerances still met). ~4× element
count at the default mesh; the warping solve remains the slow step but is
cached. The app mesh-refinement presets were relabeled **Standard (2 elem /
thickness) / Fine / Very fine** — the coarsest option no longer goes below
2-through-thickness (dropped the old "Coarse" = `t²/2`).

Note on mesh type: the FEM backend (`sectionproperties` → Triangle) produces
**6-node quadratic triangles (Tri6)** — midside nodes are already used in the
solve. Quadrilateral / structured "square" elements are not available without
replacing the mesher; element *area* (above) is the controllable quality knob,
alongside Triangle's built-in 30° min-angle constraint.

**Interactive contour overlays.** The Plotly contour gained a shear-application
-point marker (yellow diamond, distinct from the orange shear-center ✕ — the
offset between them is what induces torsion), plus per-overlay visibility
toggles (Centroid / Shear center / Neutral axis / Shear point) and an optional
**Mesh lines** overlay. `interactive_stress_contour` gained keyword args
`shear_app`, `overlays`, `show_mesh` (defaults preserve prior behavior).

### 6A — Interactive stress contour with a correct shear field (§6.2)

Fixes the long-standing degenerate shear contour and adds the Plotly hover
view. `apps/beam_section/plotting_interactive.py::interactive_stress_contour`
builds the field from the **FEM elasticity solution** over a ~160×160 grid
(mesh cached; ~0.6 s), so σ_x, τ, σ₁/σ₂, σ_vm and the local min-MS are all
**correct at every interior point** and readable on hover. The legacy
matplotlib contour computed shear from a single neutral-axis Q, so τ came out
uniform across the whole section (verified: I-beam τ = 0.3794 everywhere) and
rendered as a flat fill — that is now replaced.

- **Hover probe** stacks σ_x, τ, σ₁, σ₂, σ_vm and min-MS into `customdata`
  and shows all of them at the cursor (y, z). Cividis colormap.
- **Overlays**: centroid, shear-centre marker, and the bending neutral-axis
  line. (Principal-axes / load-arrow overlays and the annotated geometry
  preview come in a later 6D step.)
- **Report figure** retained: the matplotlib triangulated contour lives
  behind an expander for print/screenshot use.
- Falls back to the matplotlib contour if the FEM backend is absent.

**Von Mises re-check (owner request):** the formula is confirmed correct —
`σ_vm = √(σ₁² − σ₁σ₂ + σ₂²)` equals `√(σ² + 3τ²)` (the plane-stress
uniaxial-normal + shear form) to machine precision, and the FEM results-table
σ_vm matches `√(σ_total² + 3·τ_total²)` row-by-row. No change to the formula;
the inputs are consistent across paths. Locked with tests.

**Colormap:** the contour uses **Jet** (classic blue→green→red stress-plot
look, per owner preference) rather than the handoff's cividis suggestion.

**Bug fixed — curved/hollow sections returned an empty contour:** the
circle/ellipse/tube polygons close with a duplicate vertex (`linspace(0, 2π,
N)` → point[0] == point[-1]), which created a zero-length facet that made the
`sectionproperties` warping solve return **J = NaN** → all shear NaN → blank
contour (most visible on the hollow circular tube). `fem_solver._get_meshed`
now strips the trailing duplicate before meshing; FEM J for tube/circle/
ellipse now matches the closed forms to ≤2%. This slipped through Phase 4
because the cross-solver suite only exercised the open shapes. Regression
tests added.

`requirements.txt` adds `plotly>=5.18` (ships with streamlit).

Tests: `tests/test_phase6.py` (9) — von Mises identity, FEM-table σ_vm vs
σ/τ, the shear field is non-degenerate (varies > 0.05 ksi across the section),
and every field builds.

Still to do in Phase 6: caching + fragments + load form (6B); tabbed layout +
governing banner (6C); remaining overlays + annotated geometry preview (6D);
results-table `st.dataframe` upgrades with CSV / copy-markdown (6E).

---

## Phase 5 — custom-section import (DXF / pasted polygon) (unreleased)

The v2 headline feature (decision D3): analyse an arbitrary cross-section,
not just the catalog shapes. Two input paths feed one validated-geometry
pipeline; imported sections route automatically to the FEM solver and get
the full unsymmetric-bending treatment.

### 1. Import module — `library/shapes/import_section.py`

- **Pasted vertices** — "y, z" per line, blank line separates loops, first
  loop = outer boundary. Zero-friction, and the test harness for the whole
  pipeline.
- **DXF upload** — `parse_dxf` reads closed LWPOLYLINE / POLYLINE and CIRCLE
  entities via `ezdxf` (`ezdxf.path.make_path().flattening()` tessellates
  bulges/arcs/circles to a ~0.001 in chord sagitta). Non-closed / unsupported
  entities are skipped with a per-entity reason shown in the UI.
- **Validation (§5.2 — imported geometry is untrusted)**: loops closed and
  non-self-intersecting (`shapely.is_valid`), winding auto-fixed (outer CCW,
  voids CW), largest-area loop = outer with every other loop required to be
  strictly inside it (stray/overlapping/crossing loops rejected), duplicate
  points removed, and a 2000-vertex cap with Douglas-Peucker simplification.
  Every failure raises `GeometryImportError` with a plain-English message so
  the UI shows `st.error(...)` — never a traceback.
- **`ImportedSection`** — a `Section` backed by the validated polygon.
  A / Iy / Iz / Iyz come from Green's theorem (so the Phase-1 unsymmetric
  bending applies automatically); it carries `is_imported = True`, no midline
  skeleton, and its evaluation points are the boundary/void vertices plus the
  centroid (no named key points).

### 2. Routing

`calc_stress_at_points` forces the FEM solver for any `is_imported` section
(no skeleton, no closed-form shear/torsion). `shear_center()` returns the FEM
shear centre for imported sections, so the §3.4 induced-torsion path works
for them too. Imported normal stress at boundary points outside the FEM mesh
falls back to the analytic unsymmetric-bending tensor.

### 3. UI

Geometry tab gains a **"Geometry source: Catalog shape / Custom import"**
toggle. Custom import shows the paste-vertices text area or the DXF uploader,
then a **bounding-box + area confirmation** with an explicit "units assumed
INCHES — confirm before trusting results" caption (silent unit errors are the
classic DXF-import failure). Imported sections show an **"IMPORTED — FEM"**
badge in the results header, force the FEM solver (with the mesh-refinement
control available), and render through the existing section diagram and
contour (the contour's shear field for imported sections is superseded by the
Phase-6 FEM contour; normal-stress fields are correct via the tensor).

### 4. Dependency

`requirements.txt` adds `ezdxf>=1.3`. Like `sectionproperties`, confirm it
installs on Streamlit Cloud (it is pure-Python, so low risk).

### Tests

`tests/test_phase5.py` (13; DXF cases guarded by `ezdxf`): pasted-vertex
parse + build, rectangle / voided-box / I-beam-roundtrip properties vs
catalog, imported-routes-through-FEM with FEM shear-centre check, the §7.3
hostile-input gate (self-intersection, void outside boundary, void crossing
boundary, degenerate, unparseable — all raise cleanly), DXF round-trip
(I-beam ≤1%), DXF CIRCLE import, and DXF open-polyline rejection.

---

## Phase 4 — FEM solver (sectionproperties) + routing (unreleased)

Adds a finite-element section solver as a second, independent analysis path,
proves its axis mapping by test, and lets the user switch solvers to
cross-check. This does not change any Auto-path result — it adds a
capability (and is the only path that will handle imported polygons in
Phase 5).

### 1. FEM wrapper — `library/analysis/fem_solver.py`

Thin wrapper over `sectionproperties` (v3.7.3). Nothing outside this module
imports the backend, and the import is lazy (inside functions), so app
start-up and the non-FEM paths are unaffected. Provides A, Iy, Iz, Iyz, J,
Cw, shear centre, and per-point σ / τ; meshed sections are cached
(geometry-hash keyed, LRU-capped) so a loads-only change never re-meshes.

### 2. Axis mapping — proved by test, not inspection (§4)

`sectionproperties` uses an (x, y) section plane with z longitudinal; this
project uses (y, z) with x longitudinal. The adapter maps our (y, z) →
their (x, y) as identity coordinates, giving Iy=ixx, Iz=iyy, Iyz=ixy,
J=j, Cw=gamma, shear-centre identity. Load mapping
`n=P, mxx=My, myy=−Mz, mzz=T, vx=Vy, vy=Vz` — **the `myy=−Mz` sign flip was
found by probing, not assumed**: `sectionproperties`' myy convention
produces −σ at +y, opposite to this project's. Each component is unit-tested
one at a time, both signs, on a rectangle and I-beam against the exact
formula (`tests/test_phase4.py`), per the handoff's "prove the signs with
tests" mandate. No unexplained fudge factors remain.

### 3. Cross-solver agreement (§7.2 gate)

Classical/analytic vs FEM for every thin-walled catalog shape:
A / Iy / Iz / Iyz agree to ≤0.5% (machine-level for the analytic shapes),
J to ≤3.5% and shear centre to ≤3% (thin-wall midline theory vs FEM differ
legitimately by a couple of percent), transverse-shear τ to ≤7%, and
open-section torsion τ to ≤10%. An additional cross-check confirms the FEM
normal stress matches the Phase-1 unsymmetric-bending tensor at interior
points of an L-section (Iyz ≠ 0) — validating the adapter and the tensor
together.

**Torsion sampling note:** open-section torsion shear is antisymmetric
across the wall thickness — zero on the midline, peak at the surface. The
§3.8 evaluation points sit on the midline, so the FEM path samples a small
CLUSTER around each point (centre ± offsets) and takes the peak shear, so
surface torsion is captured. Documented in `_fem_precompute`.

### 4. Solver routing + UI override (§2.3)

`calc_stress_at_points(section, loads, solver=...)`:
Auto (open→classical, solid/tube→VQ/It), Classical, or FEM (any shape).
A sidebar "Solver" selectbox exposes the choice — offered as
Auto/Classical/FEM when the backend is installed, Auto/Classical otherwise —
so a classical-vs-FEM cross-check is one click. The chosen solver's name and
method citation (including the installed `sectionproperties` version) are
shown in the results header (acceptance criterion #7).

### 5. Dependencies

`requirements.txt` adds `sectionproperties>=3.7,<4` and `shapely>=2.0`
(sectionproperties also pulls in `cytriangle` and `scipy`). Verified to
install and run on Windows / Python 3.10 locally.

**⚠️ Deployment action for the project owner (handoff §4/§8):** these must
also install on Streamlit Cloud. Deploy a throwaway branch and confirm the
meshing backend builds there *before* relying on the FEM path in production —
this is a user/deploy step the assistant cannot perform.

### 6. Mesh refinement control + mesh visualization (Phase 4 follow-on)

Closes the two §4 UI items skipped in the first Phase-4 commit:

- **Mesh refinement selector** — a sidebar "FEM mesh refinement"
  Coarse / Default / Fine control (shown only when the FEM solver is
  selected), mapping to element-area scales ×4 / ×1 / ×0.25 of the
  `default_mesh_size` heuristic. Threaded through
  `calc_stress_at_points(..., mesh_scale=)` and
  `fem_mesh_size_for(section, mesh_scale)` so the stress path, the mesh view,
  and the J check all use the same mesh.
- **Coarse-vs-fine J sanity delta** — the FEM Mesh tab reports J at the
  chosen mesh vs J at 4× finer, with the % delta (`fem_j_convergence`), the
  convergence check the handoff asked for. On the default I-beam mesh this
  is ~0.7%.
- **FEM Mesh view** — a new "FEM Mesh" tab (FEM solver only) renders the
  `sectionproperties` triangulation via `plotting.draw_fem_mesh`, drawn in
  the project's white print theme with the crisp section outline overlaid
  and the element count in the title. The mesh was previously computed but
  never shown.

### Tests

`tests/test_phase4.py` (18, auto-skipped if sectionproperties is absent):
axis-mapping sign proofs, L-section FEM-vs-tensor bending, §7.2 property
agreement for all thin-walled shapes, transverse-shear and torsion-surface
agreement, citation/version, mesh-refinement element scaling, and the
J-convergence delta.

---

## Phase 3 — solids, closed cells, induced torsion, warping screen (unreleased)

Completes the shear/torsion methodology for the catalog: corrects the
remaining shear pairing, adds the §3.4 induced-torsion path, and adds the
§3.5 warping screen — which lets the open-section torsion input be unlocked.

### 1. Transverse-shear axis pairing corrected on the solid/tube path

The VQ/It path now uses the correct pairing (Vz↔Iy/Qy, Vy↔Iz/Qz), matching
the fix already made for open sections in Phase 2. For the doubly-symmetric
solids (Rectangle, Circle, Ellipse) this is a **no-op** — their max-shear
factor is the same on both axes (1.5·V/A, 4·V/3A), so v1 was accidentally
correct there. It **does** change asymmetric closed tubes: e.g. a tall 2×10
Rect Tube under vertical shear now correctly resolves on the strong axis
`Iy` (v1 used the weak axis `Iz`, ~3× too high here). The contour-plot
evaluator (`plotting._stress_at`) was corrected to match.

### 2. Closed catalog tubes: exact by VQ/It + Bredt (why no q₀ integrator)

The Phase-3 gate for closed cells — thin-ring property goldens
(A=2πrt, I=πr³t, J=2πr³t) and the Vz+T combination = 2τ (not the RSS 1.414τ)
— passes on the corrected path. The design-handoff §3.2 closed-cell shear
flow adds a redundant constant flow `q₀ = −∮(q_open/t)ds / ∮(1/t)ds`; for a
**doubly-symmetric single cell under transverse shear through the shear
centre, q₀ = 0 exactly** (the symmetric cut gives an antisymmetric q_open
with ∮q_open/t ds = 0), so VQ/It is not merely approximate but exact for the
two symmetric catalog tubes. A general q₀ integrator only matters for
asymmetric or imported closed sections, which route to the FEM solver in
Phase 4 — so it is intentionally not built here. (Recorded so the omission
is a documented decision, not a gap.)

### 3. Induced torsion from off-shear-center shear (§3.4)

New `calculations.induced_torsion()`:

    T_induced = Vz·(y_app − y_sc) − Vy·(z_app − z_sc)

and a sidebar "Shear applied at: Shear center / Centroid / Custom (y, z)"
control. Transverse shear applied anywhere other than the shear centre now
adds its induced torque to the total, shown broken out in the sidebar and
the Applied-Loads panel.

**Why this matters (v1 gap):** v1 applied shear at the centroid implicitly
and computed **no** induced torsion for channels. Example — the default
channel under Vz=1000 lb at the centroid has 2042 lb·in of induced torsion,
raising the governing shear from 0.77 ksi (v1) to **6.07 ksi** (~8×). This
was a silent, large unconservatism for any single-symmetry open section.
Doubly-symmetric sections (shear centre = centroid) are unaffected when
loaded at the centroid.

### 4. Warping screen + open-section torsion unlocked (§3.5)

- `Section.Cw()` warping constant: closed form for the I-beam
  `Cw = t_f·b_f³·(d−t_f)²/24`; `0.0` for the warping-free sections whose
  walls meet at a point (T, L, Plus); `None` (unavailable) for C and Z,
  whose closed forms are deferred so the screen advises judgment rather than
  showing a wrong number.
- `calculations.warping_characteristic_length()`:
  `λ = √(E·Cw/(G·J))`, with the L/λ screening bands (≳10 St-Venant OK;
  ≲2 restrained → warping dominates, red warning).
- **The open-section torsion input is now unlocked.** v1 hard-locked it to
  zero (St-Venant omits warping normal stresses). It is replaced by the
  quantitative screen: users may apply torsion and enter a member length L;
  the screen flags when St-Venant-only results are untrustworthy. Warping
  *stresses* themselves remain out of scope (screen only), per §3.5.

### Scope / still deferred

- Warping **stresses** (σ_w) — screen only, per handoff (roadmap).
- Rectangle solid torsion still uses the documented Timoshenko approximation
  rather than Roark α/β coefficients (the existing form is conservative and
  documented; refinement deferred).
- The contour-plot shear field remains a coarse whole-section VQ/It
  approximation pending the Phase-6 plotting overhaul; results-table numbers
  use the per-point solvers.

### Tests

`tests/test_phase3.py` (10): solid shear factors, tall-tube strong-axis
pairing, thin-ring goldens, tube Vz+T algebraic combination, channel
induced-torsion sign + zero-at-shear-centre, symmetric-section zero induced
torsion, I-beam Cw closed form, warping-free Cw=0, λ screen.

---

## Phase 2 — Classical midline solver, open sections (unreleased)

Builds the Bruhn-style midline shear-flow solver for open thin-walled
sections (design handoff §2.3, §3.2–3.3, §3.8) and routes those shapes
through it. This corrects a significant v1 transverse-shear defect and
replaces the Phase-0 interim shear combination with the exact algebraic one
for open sections. Committed in two parts: `2A` (skeleton geometry,
`a347cd7`) and `2B` (the solver + integration).

### 1. v1 transverse-shear axis mix-up (the finding §3.2 asked us to record)

**Finding:** the v1 shear code paired the loads with the wrong axes. In
`calc_stress_at_points` it computed `τ_Vy = Vy·Qy/(Iy·tw_y)` and
`τ_Vz = Vz·Qz/(Iz·tw_z)`, where each shape's `Qy`/`tw_y` are the *vertical*-
shear first moment / width and `Qz`/`tw_z` the *horizontal*-shear ones. The
physically correct pairing (Megson/Bruhn) is **Vy ↔ (Iz, ∫y dA)** and
**Vz ↔ (Iy, ∫z dA)**. v1 had them swapped: vertical shear `Vz` was resolved
with the weak-axis `Iz` and the horizontal-shear `Q`, and vice-versa.

**Why it went unnoticed:** on the rectangle and circle the two directions
give the same `1.5·V/A` (or tube equivalent), so the error is invisible
there. It only bites shapes with `Iy ≠ Iz` and distinct directional `Q` —
I, C, T, Z, L (and, on the still-legacy path, the ellipse and rect tube).

**Impact (example):** default I-beam under `Vz` (the app's default load)
computed web-NA shear ~**34% low** (0.499 vs 0.759 ksi at Vz=1000) — an
unconservative error at the governing shear point. Fixed for open sections
by the new solver (below); solids/tubes are corrected in Phase 3.

### 2. Open-section transverse shear via the classical midline solver

`library/analysis/solvers.py` — `ClassicalMidlineSolver` and supporting
functions integrate the general open-section shear flow along the wall
midline (design handoff §3.2):

    q(s) = −[(Vy·Iy − Vz·Iyz)·∫y·t ds + (Vz·Iz − Vy·Iyz)·∫z·t ds] / Δ

from a free edge, summing branch flows at junctions (tree topology). This
uses the correct axis pairing and includes the product of inertia `Iyz`
(so it composes with the Phase-1 unsymmetric-bending path). `τ_V = q/t` is
now evaluated **per point** along the wall, retiring v1's single
max-Q-everywhere value (design handoff §3.2, §3.8).

### 3. Algebraic shear combination for open sections (retires the interim)

For open sections the Phase-0 interim combination
`√(τ_Vy²+τ_Vz²)+|τ_T|` is replaced by the exact §3.3 rule
`τ_wall = |τ_Vy + τ_Vz| + |τ_T|` — the two transverse flows share the wall
tangent and add signed; torsion adds in magnitude. Solids and closed tubes
keep the interim combination until Phase 3.

### 4. Shear center now computed (open sections)

`calculations.shear_center()` returns the shear center (y_sc, z_sc) from the
moment of the shear-flow distribution about the centroid (design handoff
§3.2). Verified against goldens: I-beam / Plus / Z at the centroid, T on its
axis of symmetry, and a uniform-thickness channel matching
`e = 3b²/(h+6b)` to <3%. Displayed in the Section Properties panel. This is
the prerequisite for the §3.4 induced-torsion input (Phase 3).

### 5. Open-section St-Venant torsion (engine) + evaluation-point scheme

- The solver provides `J = Σ Lᵢ·tᵢ³/3` and per-segment `τ_T = T·t/J`. The
  engine now applies open-section torsion per wall thickness. **The UI
  torsion input remains locked to zero for open sections** until the Phase-3
  warping screen (§3.5) lands — St-Venant-only torsion can be unconservative
  for short restrained members, so it is not exposed without the screen.
- Evaluation set (design handoff §3.8): open thin-walled sections are now
  evaluated at the midline segment endpoints and midpoints **in addition to**
  the legacy named `key_points()` (deduplicated), so the true governing
  shear location — often mid-flange, which the named KPs miss — is captured.

### Scope note (still on the legacy path until Phase 3)

Solids (Rectangle, Circle, Ellipse) and closed tubes (Rect Tube, Circular
Tube) still use the VQ/It shear path with the interim combination — and thus
still carry the v1 axis pairing described in item 1. They are corrected by
the ExactSolidSolver and closed-cell (Bredt) solver in Phase 3. The
contour-plot shear field (`plotting._stress_at`) likewise remains on the
legacy path pending the Phase-6 plotting overhaul; the governing numbers in
the results table use the solver.

### New / changed

- `library/analysis/solvers.py` (new) — SectionSolver protocol,
  SolverResult, ClassicalMidlineSolver, shear-flow / shear-center / open-J
  functions.
- `library/shapes/shapes.py` — `Section._midline()` skeletons for I, T, L,
  C, Z, Plus (2A); `library/shapes/geometry.py` point-in-polygon helpers.
- `apps/beam_section/calculations.py` — `_build_eval_points`, solver routing
  in `calc_stress_at_points`, `shear_center()`.
- `apps/beam_section/app.py` — shape-aware shear formulas, shear-center
  display.
- Tests: `tests/test_phase2a.py` (skeleton geometry gate, 24),
  `tests/test_phase2b.py` (solver goldens — shear centers, channel
  `e=3b²/(h+6b)`, I-beam τ profile vs VQ/It, 9).

---

## Phase 1 — PolygonProperties engine & unsymmetric bending (unreleased)

Introduces the v2 geometry/analysis separation (design handoff §2) and
replaces the geometric-axis bending assumption with the full unsymmetric-
bending tensor (§3.1). No release tag yet — intermediate v2 phases are not
tagged as releases (only Phase 7 → v2.0.0). `CLAUDE.md` still describes the
pre-v2 architecture; its rewrite is scoped to Phase 7.

### 1. Normal-stress bending: geometric-axis formula → unsymmetric tensor

**Before:** `σ_bend = My·z/Iy + Mz·y/Iz` — implicitly assumes the product
of inertia `Iyz = 0`, valid only for sections with an axis of symmetry.
L-beam and Z-beam carried a `⚠️ ASSUMPTION` caveat that their results were
only trustworthy when adjacent structure constrained bending to the
geometric axes.

**After:**
`σ_bend = [(My·Iz − Mz·Iyz)·z + (Mz·Iy − My·Iyz)·y] / Δ`, `Δ = Iy·Iz − Iyz²`.

**Why:** The tensor form accounts for `Iyz` exactly, so L and Z sections are
now valid with no constraint assumption. It reduces to the v1 formula when
`Iyz = 0` (unit-tested to machine precision), so every symmetric shape is
numerically unchanged. The `⚠️ ASSUMPTION` docstrings (L-beam, Z-beam) and
the "bending evaluated on geometric axes" UI caption are removed; the UI
Formulas tab now shows the tensor form.

**Location:** `apps/beam_section/calculations.py::calc_stress_at_points`,
`apps/beam_section/plotting.py::_stress_at` (contour evaluator, kept in
sync), `library/shapes/shapes.py` (L/Z docstrings), `apps/beam_section/
app.py` (Formulas tab + caption).

### 2. Product of inertia `Iyz` now computed (was implicitly zero)

**Added:** `Section.Iyz()` (and `Section.geometry()` / `Section.
section_props()`) compute `Iyz`, principal axes, and radii of gyration from
the section polygon via Green's theorem
(`library/analysis/polygon_props.py`). Symmetric shapes return ~0 (to
numerical precision); L and Z return their true nonzero product of inertia,
which now feeds the bending tensor above. `Iyz` and, for unsymmetric
sections, the neutral-axis angle are surfaced in the Section Properties
panel.

**Why:** Required by §3.1. Also enables the neutral-axis overlay (§3.1,
rendered in Phase 6) via `calculations.neutral_axis_angle_deg`.

### 3. Two latent v1 section-property bugs fixed (caught by the Phase 1 gate)

The Phase 1 validation gate — "polygon-derived A/Iy/Iz must match each
shape's closed form ≤ 0.1%" — surfaced two closed-form errors that had been
silently producing wrong bending stress. The polygon values are correct;
the closed forms were fixed to match.

- **Z-Beam `Iz`** omitted the flange parallel-axis term. A Z-section's
  flanges are offset in Y (top +Y, bottom −Y), so each requires `A·y_c²`
  with `y_c = (bf − tw)/2`. The v1 form used only `2·tf·bf³/12`,
  underestimating `Iz` by ~3.5× at default dims (1.694 → 5.948 in⁴). This
  had **over-predicted** Mz-bending stress on Z-sections (conservative, but
  wrong).
- **Plus/Cross `Iy` and `Iz`** used the wrong integral limits for the arm
  bands: `(h/2 − th/2)³` instead of `(h/2)³ − (th/2)³`. At default dims
  1.828 → 2.703 in⁴. Also over-predicted bending stress.

**Impact:** bending stress and margins change for the Z-Beam and Plus/Cross
shapes only. All other shapes' A/Iy/Iz already matched their polygons to
≤ 0.1% (analytic shapes to machine precision; circle/ellipse/tubes within
discretization error).

**Location:** `library/shapes/shapes.py::ZBeam.Iz`,
`library/shapes/shapes.py::PlusCross.Iy` / `PlusCross.Iz`.

### New modules / tests

- `library/analysis/polygon_props.py` — Green's-theorem section properties
  (A, centroid, Iy, Iz, Iyz, principal moments/angle, radii of gyration).
- `library/shapes/geometry.py` — `SectionGeometry` + `MidlineSegment`
  containers (midline skeleton fields present but unpopulated until
  Phase 2) and winding helpers.
- `tests/golden_values.py` — shared analytic golden module (pytest now; the
  in-app Validation page in Phase 7).
- `tests/test_phase1.py` — analytic property goldens (rectangle, offset-
  rectangle Iyz, 45°-rotated principal-axis recovery), tensor-bending
  reduction, L-section rotated-neutral-axis check, and the polygon-vs-
  closed-form gate for all 11 shapes.

---

## v1.1.0 — Phase 0 safety patch (unreleased on `main` until tagged)

This release is a stopgap. It corrects two unconservative defects in the v1
margin methodology without waiting for the v2 geometry/solver engine
(`SectionGeometry`, classical/FEM solvers) to land. Everything here is
superseded piece-by-piece as later v2 phases are implemented.

### 1. Shear combination: RSS → conservative interim algebraic sum

**Before:** `τ_total = √(τ_Vy² + τ_Vz² + τ_T²)`
**After:** `τ_total = √(τ_Vy² + τ_Vz²) + |τ_T|`

**Why:** Transverse shear and torsional shear act along the same wall
tangent direction at a given point on a thin-walled section — they are
**collinear**, not orthogonal. Combining them by root-sum-square (as if they
were independent orthogonal components) understates the combined stress. For
a circular tube under `Vz + T` sized so `τ_V = τ_T` at the horizontal
diameter, RSS returns `1.414·τ` instead of the correct `2·τ` — a ~29% low
(unconservative) result at the governing point.

This is an **interim** fix. The true fix (v2 Phase 2/3) computes exact
per-wall-point shear flow and combines signed flows algebraically, point by
point. The interim formula above is deliberately conservative (upper-bound)
in the meantime — see `_TrainingData/v2_handoff/V2_DESIGN_HANDOFF.md` §3.3.

**Location:** `apps/beam_section/calculations.py::calc_stress_at_points` and
`apps/beam_section/plotting.py::_stress_at` (the contour-plot stress
evaluator had its own independent copy of the RSS combination, caught by
the §7.1 grep-guard test — both are now updated identically).

### 2. Margin-of-safety check set replaced (not kept alongside)

**Removed:**
- `σ₁ vs Fty (yield)` — max-normal-stress yield criterion. Unconservative
  vs. the distortion-energy (von Mises) criterion for shear-dominated
  stress states — reported passing margins up to ~73% non-conservative
  in that regime.
- `σ_vm vs Ftu (ultimate)` — von Mises is a **yield** criterion by
  construction (it's a distortion-energy measure); pairing it with an
  ultimate allowable was ad hoc and had no clean physical basis. Its
  intended role is already covered by the new checks 2 (σ₁ vs Ftu) and 4
  (τ_wall vs Fsu).

**Added / changed:**
- `σ_vm vs Fty (yield)` — now the primary yield criterion (replaces
  `σ₁ vs Fty`).
- `σ₁ vs Ftu (ultimate)` — unchanged allowable pairing, but now only
  "active" when σ₁ > 0 (tension); floored to ~0 applied stress (and
  therefore a trivial pass) when the max principal stress is compressive,
  since this check has no meaning in that state.
- `|σ₂| vs Fcy (compression yield)` — unchanged allowable pairing, now only
  "active" when σ₂ < 0 (compression), for the same reason.
- `τ_wall vs Fsu (shear ultimate)` — same as v1's `τ_total vs Fsu`, renamed
  to `τ_wall` for consistency with v2 terminology (the "combined shear at a
  wall point" quantity from item 1 above).

**Why:** See `_TrainingData/v2_handoff/V2_DESIGN_HANDOFF.md` §3.6 (D2 —
"Replace legacy outright").

**Location:** `apps/beam_section/calculations.py::calc_margin_table`

### 2b. Interaction ratios now factored by SF_ult

**Before/as literally specified in the handoff doc (§3.6):**
`Ra = |σ_axial|/Fa`, `Rb = |σ_bend|/Fbu`, `Rs = τ_wall/Fsu` — no safety
factor anywhere in the ratio definitions (this matches v1's equivalent
`Rc/Rb/Rs` computation too — not a new gap introduced by this release).

**After:** `Ra = SF_ult·|σ_axial|/Fa`, `Rb = SF_ult·|σ_bend|/Fbu`,
`Rs = SF_ult·τ_wall/Fsu`.

**Why:** Every other check in this tool follows `MS = Allowable /
(SF · Applied) − 1` — SF always scales the applied side. Without factoring
Ra/Rb/Rs by SF_ult, moving the `SF Ult` sidebar control had **zero effect**
on the interaction MS while changing every other row — a silent
inconsistency an engineer would have no reason to expect. Baking SF_ult in
makes `MS = 0` land exactly at `SF_ult · applied = allowable` on the
interaction curve, consistent with the rest of the tool, and the
`Ra=Rb=0.5, Rs=0 → MS=0` /`Ra=Rb=0, Rs=1 → MS=0` golden tests are
unaffected since they're stated directly in terms of the (already-factored)
ratios, not raw stress.

**Location:** `apps/beam_section/calculations.py::calc_margin_table`

### 2c. Interaction MS table row now shows real Allowable/Applied values

**Before:** the "Combined interaction" row displayed `Allow: —` and
`Applied: "Ra+Rb, Rs"` — literal placeholder text, not computed numbers.

**After:** `Allow` shows `Fa=…  Fbu=…  Fsu=…` (ksi) and `Applied` shows the
computed `Ra=…  Rb=…  Rs=…` for that load case, so the check is traceable
directly from the MS table without cross-referencing the sidebar.

**Location:** `apps/beam_section/calculations.py::calc_margin_table`

### 3. Combined interaction equation replaced

**Before:** `MS = 1/√(Rc² + Rb² + Rs²) − 1` where `Rc = σ_axial/Ftu`,
`Rb = σ_bend/Fbu`, `Rs = τ/Fsu` (RSS-style, MMPDS §1.3 as previously
implemented).

**After:** `MS = 2 / [(Ra+Rb) + √((Ra+Rb)² + 4·Rs²)] − 1`, the closed-form
solution of the interaction curve `(Ra + Rb) + Rs² = 1`, where
`Ra = |σ_axial|/Fa` (`Fa = Ftu` in tension, `Fcy` in compression),
`Rb = |σ_bend|/Fbu`, `Rs = τ_wall/Fsu`.

**Why:** The RSS-style interaction treats all three ratios as if they
combine like orthogonal vector components. For a true zero-margin
axial+bending state (`Ra = Rb = 0.5`, `Rs = 0`), the old formula reports
`MS = 1/√(0.5² + 0.5²) − 1 = +0.41` — a *passing* margin at a state that is
actually at the edge of the interaction envelope. The corrected curve
groups normal-stress ratios **linearly** (`Ra + Rb`) — consistent with the
Bruhn C4-family combined-loading interaction approach — and lets shear enter
**quadratically** (`Rs²`). At `Ra = Rb = 0.5, Rs = 0`: `MS = 2/(1 + 1) − 1 =
0.0` exactly, correctly identifying the zero-margin state.

**Location:** `apps/beam_section/calculations.py::calc_margin_table`

### 4. Cozzone shape factor gated to 1.0 for thin-walled open sections

**Before:** Thin-walled open catalog shapes carried Cozzone shape factors
of 1.07–1.30 (I-Beam 1.07, T-Beam 1.15, L-Beam 1.15, C-Beam 1.15, Z-Beam
1.10, **Plus/Cross 1.30**), used directly as `Fbu = f·Ftu`.

**After:** `Section.effective_f_cozzone` returns `1.0` for any shape where
`is_open_section and is_thin_walled` (i.e. `category == "Open thin-walled"`).
Solid and closed/hollow shapes (Rectangle, Circle, Ellipse, Rect Tube,
Circular Tube) are unaffected and keep their documented table values
(`f_cozzone`, 1.30–1.70).

**Why:** The Cozzone plastic-bending shape factor credits inelastic stress
redistribution across the section at ultimate load. For thin-walled open
sections this credit is not conservative unless local crippling
(compression-flange buckling) is checked — a module that does not yet
exist in this tool (see roadmap). Per project decision D5, `f > 1.0` is
permitted only for solid/compact-closed shapes with a documented source.
**Plus/Cross at f = 1.30 was the most non-conservative of the gated
values** — flagged here because it exceeds the "no thin-walled shape should
carry f > ~1.1" sanity bound noted in the v2 design doc.

**Location:** `library/shapes/shapes.py::Section.effective_f_cozzone`;
wired into `apps/beam_section/calculations.py::calc_margin_table` and the
`apps/beam_section/app.py` UI (Fbu display, Section Properties "f" card —
both show a "GATED" badge / caption when active).

### 5. Ellipse a ≥ b validation guard added

**Added:** `Ellipse.validate_dims()` returns an error (surfaced in the UI,
blocks the solve) when `D2 (b, vertical semi-axis) > D1 (a, horizontal
semi-axis)`.

**Why:** The exact torsion formula `τ_T = 2T/(π·a·b²)` requires `b` to be
the semi-**minor** axis. The existing `tau_T()` implementation already
internally reorders via `min()/max()` so the torsion *value* itself was not
actually wrong — but leaving that reordering implicit was fragile:
`Iy`/`Iz`/`polygon_vertices()`/`key_points()` all use `D1`/`D2` as literal
horizontal/vertical axes (not major/minor), so a future change to any one
of these methods could silently reintroduce a mismatch between "which axis
is drawn where" and "which axis the torsion formula treats as minor."
Making the `a ≥ b` convention an explicit, enforced input constraint removes
that class of risk entirely rather than relying on every method
independently reimplementing the same implicit correction.

**Location:** `library/shapes/shapes.py::Ellipse.validate_dims`;
`apps/beam_section/app.py` (calls `validate_dims()` after section creation).

### 6. Rect Tube (Bredt-Batho) min-thickness / geometry guard added

**Added:** `RectTube.validate_dims()` returns an error when `t_f`/`t_w` ≤ 0,
or when the wall thickness consumes the entire section (`b − 2·t_w ≤ 0` or
`h − 2·t_f ≤ 0`).

**Why:** In that degenerate regime the median-line enclosed area `Am` used
by the Bredt-Batho torsion formulas goes to zero or negative, and
`J_torsion()` / `tau_T()` were silently returning `0.0` — a torsion-critical
input error masquerading as "no torsional stress," rather than being
flagged as invalid geometry.

**Location:** `library/shapes/shapes.py::RectTube.validate_dims`.

### 7. UI formula block and governing-stress card pairing updated to match

- "Total Shear" formula entry rewritten to the interim algebraic form
  (item 1) with a note on why RSS was replaced.
- "MMPDS Interaction" entry replaced with "Combined Interaction (v1.1.0)"
  showing the new closed-form MS expression and curve.
- "Cozzone Fbu" entry updated to reference `f_eff` and the thin-walled gate.
- The "Governing Stress Summary" card strip (`ui/components.py::
  stress_card_strip`, `apps/beam_section/app.py`) paired each governing
  stress with an allowable **by list position**, which had not been
  updated when the check set changed — σ₁ was still visually paired with
  Fty and σ_vm with Ftu, the reverse of the new check semantics. Reordered
  to σ₁↔Ftu, σ₂↔Fcy, σ_vm↔Fty, τ_total↔Fsu, σ_bend↔Fbu (display-only
  pairing; σ_bend has no standalone MS check post-v1.1.0, having folded
  into the `Rb` interaction term). The combined-MS card label/caption
  updated from "MMPDS Interaction" / `Rc² + Rb² + Rs² §1.3` to "Combined
  Interaction" / `(Ra+Rb) + Rs² = 1`.

### Not changed in this release

`CLAUDE.md` still documents the pre-v1.1.0 methodology (six-check set, RSS
combination, ungated Cozzone factors) — its rewrite is scoped to v2 Phase 7
per the design handoff, once the full engine and check set are final.
`_TrainingData/v2_handoff/V2_DESIGN_HANDOFF.md` supersedes `CLAUDE.md`
wherever they conflict in the interim (stated explicitly at the top of that
document).
