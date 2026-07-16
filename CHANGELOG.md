# CHANGELOG

All results-changing methodology decisions are recorded here with engineering
rationale, per `_TrainingData/v2_handoff/V2_DESIGN_HANDOFF.md` §9 (Phase 0)
and the project convention it establishes: **every future results-changing
commit adds an entry to this file.**

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
