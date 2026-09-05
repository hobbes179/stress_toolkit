# CLAUDE.md — Stress Toolkit
## Context for Claude Code / AI-assisted development

This file provides context for Claude Code (or any AI assistant) working on
this repository. Read it before making any changes.

> **v2.0 status (2026-07).** The toolkit completed a methodology + UX overhaul
> (Phases 0–7). The **authoritative record of every results-changing decision
> is `CHANGELOG.md`** at the repo root; the original v2 design spec lives at
> `_TrainingData/v2_handoff/V2_DESIGN_HANDOFF.md` (now historical). Where this
> file conflicts with those two, they win. Key v2 changes vs the original
> description below: dual solver (classical midline **+** `sectionproperties`
> FEM), custom polygon/DXF import, unsymmetric-bending tensor (L/Z valid
> without the geometric-axis assumption), Bruhn midline shear flow, the §3.6
> margin check set with the `(Ra+Rb)+Rs²=1` interaction curve, a tabbed UI
> (Geometry | Loads | Results | Margins | Crippling | Formulas | Validation) with an
> interactive FEM stress contour, an in-app validation page, and a unified
> **light** theme. Version is stamped in the page footer (`version.py`).

---

## What this project is

A **structural stress analysis toolkit** for metallic airframe design, built as
a multi-page Streamlit web application. The primary user is a practicing
structural engineer, with the level of rigor expected in a formal stress report.

The tool performs **linear-elastic cross-section stress analysis** under
combined loading (axial, biaxial shear, biaxial bending, torsion), computing
margins of safety against MMPDS-01 material allowables.

It is designed to be:
- **Deployable on Streamlit Cloud** (accessible from any browser, including mobile)
- **Extensible** — structured so that new analysis modules (buckling, joints,
  fasteners, etc.) can be added as siblings under `apps/` without restructuring
- **Report-ready** — outputs are clean enough to screenshot directly into a
  stress report
- **Traceable** — every formula used is documented inline and shown in the UI

---

## Repository structure

```
stress_toolkit/
├── Home.py                          ← Streamlit Cloud entry point (landing page)
├── version.py                       ← __version__ + git SHA, stamped in page footers
├── pages/                           ← Thin wrappers, auto-discovered by Streamlit
│   ├── 1_Beam_Section_Stress.py
│   ├── 2_Material_Library.py
│   ├── 3_Tie_Rod_Layout.py
│   ├── 4_Bolt_Bending.py
│   └── 5_Beam_Diagrams.py
├── apps/                            ← UI only. The ONLY place Streamlit is imported.
│   ├── beam_section/
│   │   ├── app.py                   ← Streamlit render() for the beam module
│   │   ├── calculations.py          ← Stress + MS engine (no Streamlit deps)
│   │   ├── plotting.py              ← matplotlib figures (no Streamlit deps)
│   │   └── plotting_interactive.py  ← Plotly stress contour
│   ├── material_library/app.py
│   ├── tierod/                      ← render.py + ui_*.py; CLAUDE.md of its own
│   ├── bolt_bending/                ← app.py + plotting.py (SVG) + method.py
│   │   └── CLAUDE.md                ← module conventions + backlog
│   └── beam_line/                   ← app.py + plotting.py (SVG) + method.py
│       └── CLAUDE.md                ← module conventions + backlog
├── library/                         ← Pure engineering math. NEVER imports Streamlit.
│   ├── materials/
│   │   ├── materials.py             ← Material dataclass, MATERIALS, CATEGORY_ORDER
│   │   └── README.md                ← Schema + how-to-add docs
│   ├── shapes/
│   │   ├── shapes.py                ← Section base class + 11 shape subclasses
│   │   └── README.md                ← How-to-add-a-shape docs
│   ├── analysis/                    ← solvers, FEM, polygon props, crippling
│   ├── tierod/                      ← tie-rod kernel
│   ├── bolt_bending/kernel.py       ← bolt statics + margins
│   └── beam_line/                   ← line-beam model + stiffness solve + diagrams
├── ui/
│   ├── theme.py                     ← Color tokens: THEME, PLOT_PALETTE, BOLT_PALETTE
│   ├── styles.py                    ← CSS injection (call inject_css() at top of each page)
│   ├── components.py                ← Reusable widgets (section_header, info_card, etc.)
│   └── handoff.py                   ← Cross-page section snapshot (Beam Section → Beam Diagrams)
├── tests/                           ← pytest; tests/<module>/ per module
├── docs/                            ← Per-module source material and handoffs
│   ├── tierod/
│   └── bolt_bending/                ← archived standalone tool + its HANDOFF.md
├── requirements.txt
├── CHANGELOG.md                     ← Authoritative record of results-changing decisions
├── README.md
└── CLAUDE.md                        ← This file
```

---

## Architecture decisions (do not change without discussion)

### 1. Shape library — class-per-shape pattern
Each cross-section is a Python class inheriting from `Section`
(`library/shapes/shapes.py`). The class owns ALL of its geometry, formulas,
key-point definitions, and Cozzone shape factor in one place.

New shapes are added by subclassing `Section` and registering in
`SHAPE_REGISTRY`. Apps interact only with the abstract `Section` interface.

**Do not** store formulas as strings or use `eval`. All computations are plain
Python methods.

### 2. Materials library — dataclass + dict pattern
Materials are `Material` dataclasses stored in the `MATERIALS` dict
(`library/materials/materials.py`). The dict key is the display name.

Properties are optional fields (default `None`). When a property is not
available from MMPDS and a conservative estimate is used:
- The line is commented with `# ⚠️ ESTIMATED — <reason>`
- The field name is added to `Material.estimated_fields`
- The UI displays an `EST` badge next to that value

**Never** silently use estimated values without flagging them.

### 3. UI — shared theme system
All colors come from `ui/theme.py`. Never hardcode hex colors in app pages.
- `THEME` — UI color tokens (backgrounds, text, borders, status colors)
- `PLOT_PALETTE` — matplotlib color tokens (always white plot background)
- `BOLT_PALETTE` / `BEAM_PALETTE` — tokens for the two hand-built SVG figures

All reusable Streamlit components are in `ui/components.py`. Use these
instead of writing raw `st.markdown` HTML in app pages.

CSS is injected once at the top of each page via `inject_css()`.

### 4. Plotting — always white background
Both `draw_section()` and `draw_contour()` use `PLOT_PALETTE["background"] = white`
regardless of UI theme. This keeps figures print-friendly.

The contour plot uses **Delaunay triangulation** (`matplotlib.tri`) rather
than a masked rectangular grid. This produces smooth filled contours with the
boundary following the exact section outline, and inner voids (tubes) are
automatically excluded by masking triangles whose centroids fall in the void.

Uniform-stress edge case: when `vmax - vmin < 1e-8` relative to max value,
the function renders a flat-color fill with a text annotation showing the
uniform value, instead of a broken colorbar.

### 5. Streamlit page structure
- `Home.py` — landing page only; renders module cards
- `pages/N_Name.py` — thin wrapper; sets page config and calls `app.render()`
- `apps/<module>/app.py` — full UI lives here, imports from library + ui

### 6. Unified light theme (v2)
The app now ships a single unified **light** theme (warm off-white canvas,
signal-blue accent) defined by `THEME` in `ui/theme.py`. The earlier
dark-mode-only constraint (and its light-mode input-color bug) is resolved.
All colors still come from `ui/theme.py` — never hardcode hex in pages.
Margin-of-safety colors use the `MS_FAIL` / `MS_WARN` thresholds and
`ms_status()` there, not inline values.

---

## Coordinate system (important — used everywhere)

```
+Z (vertical up)
 |
 |
 ──────── +Y (horizontal right)
Origin = centroid of cross-section
X = beam axis (out of section plane, into the page)
```

- `My` — bending moment about Y; produces stress proportional to `z`
  (top/bottom fibres dominate)
- `Mz` — bending moment about Z; produces stress proportional to `y`
  (left/right fibres dominate)
- Positive `P` = tension

---

## Units

**IPS throughout:** inches, pounds, seconds.

| Quantity        | Unit    |
|-----------------|---------|
| Length          | in      |
| Force           | lb      |
| Moment          | lb·in   |
| Stress          | ksi     |
| Modulus (E, G)  | Msi     |
| Density         | lb/in³  |
| CTE (alpha)     | µin/in/°F (×10⁻⁶) |

Stress values returned by `calculations.py` are always in **ksi**.
Loads input from the sidebar are in **lb** / **lb·in** — the conversion to
ksi happens inside `calc_stress_at_points()` via `/1000`.

---

## Methodology

Authoritative methodology reference: handoff §3 + `CHANGELOG.md`. Summary:

### Normal stress
```
σ_axial  = P / A
σ_bend   = [(My·Iz − Mz·Iyz)·z + (Mz·Iy − My·Iyz)·y] / Δ,  Δ = Iy·Iz − Iyz²
σ_total  = σ_axial + σ_bend
```
Unsymmetric-bending tensor (reduces to (My·z)/Iy + (Mz·y)/Iz when Iyz = 0).

### Shear stress (v2 — see handoff §3.2–3.3, CHANGELOG Phases 2–3)
- **Open thin-walled**: per-point **Bruhn midline shear flow**
  `q(s) = −[(Vy·Iy − Vz·Iyz)·∫y·t ds + (Vz·Iz − Vy·Iyz)·∫z·t ds]/Δ`, τ = q/t,
  with the correct axis pairing (Vy↔Iz/∫y, Vz↔Iy/∫z) and Iyz included.
- **Solids / closed tubes**: VQ/It with the corrected pairing; Q at the
  neutral axis is used at all key points (conservative — see Known issues).
- **FEM / imported**: σ and the combined τ come straight from the
  `sectionproperties` elasticity solve (exact per-point, any polygon).

### Torsional shear stress
Depends on section type:
- **Closed sections** (Rect Tube, Circular Tube): Bredt-Batho `τ = T/(2·Am·t)`
- **Circle**: Exact `τ = 16T/(π·d³)`
- **Ellipse**: Exact `τ = 2T/(π·a·b²)` at minor axis end
- **Open thin-walled sections**: St. Venant `τ = T·t_max/J` where `J = Σ(b·t³)/3`

⚠️ Warping stresses are **not** included for open sections. The UI warns the
user when torsion is applied to an open section.

### Total shear and principal stresses (v2)
The v1 RSS combination `√(τ_Vy²+τ_Vz²+τ_T²)` was **unconservative** and has
been removed everywhere. Combined wall shear (handoff §3.3):
```
τ_wall  = |τ_Vy + τ_Vz| + |τ_T|     (open: flows share the wall tangent)
τ_wall  = √(τ_Vy² + τ_Vz²) + |τ_T|  (solids/tubes: biaxial, then torsion)
σ1, σ2  = σ/2 ± √[(σ/2)² + τ_wall²]
σ_vm    = √(σ1² − σ1·σ2 + σ2²)  ( = √(σ² + 3·τ²) )
```

### Margins of safety (v2 §3.6 check set — replaces the v1 six checks)
```
MS = Allowable / (SF · Applied) − 1        SF_yield default 1.0, SF_ult 1.5
```
1. σ_vm vs Fty (yield, distortion energy — primary yield criterion)
2. σ₁ vs Ftu (ultimate; governs only when σ₁ > 0)
3. |σ₂| vs Fcy (compression yield; governs only when σ₂ < 0)
4. τ_wall vs Fsu (shear ultimate)
5. Combined interaction, curve `(Ra+Rb) + Rs² = 1` (Bruhn C4-family):
   `MS = 2/[(Ra+Rb) + √((Ra+Rb)² + 4·Rs²)] − 1`, with SF_ult baked into
   Ra = |σ_axial|/Fa, Rb = |σ_bend|/Fb, Rs = τ_wall/Fsu. Replaces the v1
   RSS-style `1/√(Rc²+Rb²+Rs²) − 1`, which was unconservative (CHANGELOG).
   Both **Fa and Fb are sign-aware**: Fa = Ftu (tension) or Fcy (compression)
   by the sign of σ_axial; Fb = Fbu=f·Ftu when the governing bending fiber is
   tension, else Fcy (Fbu is a tension-fiber modulus of rupture — see
   CHANGELOG v2.1.0 "sign-aware bending allowable").

The removed v1 checks (σ₁ vs Fty, σ_vm vs Ftu) and rationale are in CHANGELOG.

### Cozzone bending allowable
```
Fbu = f · Ftu          (tension fiber only — v2.1.0 sign-aware; compression → Fcy, capped at Fcc)
```
Shape factor `f` is a simplified constant per shape class (attribute
`f_cozzone`). These are conservative values from Cozzone (1943) /
NACA TN-1818. See `shapes.py` docstring for the full table and note on
when a rigorous Cozzone analysis would be warranted.

**Crippling (v2.2.1, `library/analysis/crippling.py`).** Local crippling is a
**standalone stability check** — the `σ_c vs Fcc` margin row (thin-walled open
sections only), **element-wise**: each thin plate element's own peak compressive
normal stress (axial + bending, from the affine section field `σ(y,z)`) is
checked against **that element's own** crippling stress `Fcc_i`, and the worst
element by ratio governs (`worst_element_crippling`). Uses total (axial +
bending) compression, so pure axial compression (a strut) and combined
axial+bending both count — bending alone would miss a compression member.

The v2.2.1 fix (see CHANGELOG): the v2.2.0 row compared the section's peak
compression against the **area-weighted** section `Fcc` (`fcc_element`), which
is valid only for uniform/strut compression and is **unconservative under
bending** — a stocky web inflates the average and masks a slender extreme-fiber
flange. The area-weighted `fcc_element` is retained for the strut interpretation
and the Crippling-tab display; `crippling_limited` keys off the weakest element
(`fcc_min < Fcy`). Crippling is kept OUT of the `(Ra+Rb)+Rs²` strength
interaction (that would double-count / mishandle axial); the interaction's
compression bending uses `Fcy`. The tension fiber keeps the shape's plastic
factor (`Fbu = f·Ftu`, the `σ_bend,t` row). The old **D5 tension-side gate**
(forced `f = 1.0` for thin-walled open) is **removed** — it was a proxy for the
missing crippling check, so `effective_f_cozzone == f_cozzone` for every shape
now. Crippling is a section+material property (no length/fixity); coefficients
are ⚠️ VERIFY defaults. Custom/imported shapes have no plate-element
decomposition, so they get **no crippling row** (compression falls back to Fcy)
— a known gap. See CHANGELOG v2.2.0 / v2.2.1.

### Unsymmetric bending (v2 — the old geometric-axis assumption is GONE)
Normal stress uses the full unsymmetric-bending tensor (handoff §3.1):
```
σ_bend = [(My·Iz − Mz·Iyz)·z + (Mz·Iy − My·Iyz)·y] / Δ,   Δ = Iy·Iz − Iyz²
```
which reduces to (My·z)/Iy + (Mz·y)/Iz when Iyz = 0. L-beam and Z-beam
(nonzero Iyz) are therefore valid with **no** constraint assumption — the v1
`⚠️ ASSUMPTION` about bending on geometric axes has been removed. The neutral-
axis and principal-axis angles are shown as contour overlays.

---

## Current shapes (11 supported)

| Name | Category | Open/Closed | Dims used |
|------|----------|-------------|-----------|
| Rectangle | Solid | Open | D1=b, D2=h |
| Circle | Solid | Closed (exact) | D1=d |
| Ellipse | Solid | Closed (exact) | D1=a, D2=b |
| Rect Tube (HSS) | Hollow | Closed (Bredt) | D1=b, D2=h, D3=tf, D4=tw |
| Circular Tube | Hollow | Closed (exact) | D1=do, D2=t |
| I-Beam / W-Shape | Open thin-walled | Open | D1=bf, D2=d, D3=tf, D4=tw |
| T-Beam | Open thin-walled | Open | D1=bf, D2=tf, D3=hw, D4=tw |
| L-Beam / Angle | Open thin-walled | Open | D1=b, D2=h, D3=tb, D4=th |
| C-Beam / Channel | Open thin-walled | Open | D1=bf, D2=d, D3=tf, D4=tw |
| Z-Beam | Open thin-walled | Open | D1=bf, D2=d, D3=tf, D4=tw |
| Plus / Cross | Open thin-walled | Open | D1=b, D2=h, D3=th, D4=tv |

---

## Materials library

30 entries in 5 categories: Aluminum, Steel, Titanium, Stainless, **Fastener**.
Source: MMPDS-01 / MIL-HDBK-5J (structural steels from AISC/ASTM).

Each material stores: Fty, Ftu, Fcy, Fsu, Fbru, Fbry, E, Ec, G, ν,
alpha (CTE), k (thermal conductivity), T_max, rho, source, notes.

`CATEGORY_ORDER` in `materials.py` is the single source of truth for
display order in grouped UIs. Add a new category there or it will not
appear — `names_grouped()` and the Material Library page both iterate it.

Properties not available from MMPDS are flagged with `⚠️ ESTIMATED` and
listed in `Material.estimated_fields`. Current estimated fields: Fbru/Fbry
for A36, A572, and 300M; **Fty on every Fastener entry** (MMPDS fastener
tables do not tabulate yield for fasteners at all).

**Fasteners (v2.3.0)** are bolt *strength levels*, not bar or sheet stock:
Ftu is the definitional minimum for the grade and Fsu the corresponding
tabulated fastener shear allowable. Fcy/Fbru/Fbry are deliberately `None` —
bearing is a check on the **plate**, not on the fastener.
⚠️ VERIFY — grade-level nominals for preliminary sizing only; a released
stress report needs the actual part number and diameter from MMPDS-01
Table 8.1.4 or the procurement spec.

---

## Known issues and tech debt

Resolved in v2 (kept here so they aren't re-opened): the light-mode input-color
bug (light theme now ships); the degenerate/uniform shear contour (both the
interactive and report contours now render the FEM field — see CHANGELOG 6A /
6C.1); L/Z-beam product of inertia Iyz (now computed; unsymmetric-bending
tensor implemented, so the geometric-axis assumption is gone); per-point
open-section shear (Bruhn midline shear flow replaces v1's max-Q-everywhere).

| Issue | Severity | Location | Notes |
|-------|----------|----------|-------|
| Warping torsion (stress) | Medium | `shapes.py`, `calculations.py`, FEM | St-Venant torsion for open sections; warping **normal** stresses (σ_w) are not computed. The UI runs a warping *screen* (L/λ) but does not add σ_w. For short open members with restrained ends this can underestimate stress — engineering judgment required. |
| Solid/tube per-point shear | Low | `calculations.py` | Solids and closed tubes use VQ/It with the neutral-axis Q at all key points (conservative). Open sections use per-point Bruhn midline flow; the FEM solver is exact per-point for any shape. |
| FEM corner singularity | Info | `filleted.py`, `plotting_interactive.py`, docs | At a perfectly sharp re-entrant corner the FEM torsion stress is singular and grows with mesh refinement. **Resolved (opt-in) in v2.1.0:** the sidebar "Apply corner fillets" toggle wraps the section in `FilletedSection` (rounds only the FEM geometry, per Option A — closed-form/classical results unchanged), giving a finite, converged corner value. Left sharp by default; warned in-app. See CHANGELOG v2.1.0 + "FEM vs Classical at sharp corners". |
| Z-beam key-point coordinates | Low | `shapes.py ZBeam.key_points()` | Top flange right tip coordinate has a tautological expression. Review when Z-beam is tested with combined Mz loading. |
| Triangulation warnings | Info | `plotting.py` | matplotlib prints "Ignoring fixed axis limits" when `set_aspect("equal")` conflicts with explicit xlim/ylim. Cosmetic only. |
| Per-member dimension leaders | Low | `shapes.py`, `plotting.py` | `dimension_annotations()` draws overall bbox W×H only; per-member (tf/tw) callouts are wish-list item 10b. |

---

## Planned future work

### Near-term (next session priorities)

_Done in v2 (was near-term): light theme shipped, `.gitignore` added,
unsymmetric-bending tensor implemented (old item 7), open-section per-point
shear flow (old item 6, for open sections)._

1. **Test on Streamlit Cloud**
   Deploy and verify all 11 catalog shapes + custom import render correctly in
   a browser. Check mobile layout (sidebar collapses, tables scroll
   horizontally; the six tabs and the Plotly contour on small screens).

2. **Report export (PDF)**
   Add a button that generates a print-quality PDF snapshot of the results:
   title block, section diagram, section properties, stress table, MS table.
   Suggested approach: `matplotlib.backends.backend_pdf` or `reportlab`.
   The PDF should be fully standalone — not reliant on the browser's print function.

3. **`use_container_width` migration** — ✅ DONE in v2.5.1
   (logged 2026-09-04, fixed 2026-09-05) Streamlit's runtime warning still
   reads "will be removed after 2025-12-31" — a date now well past — and the
   removal is underway upstream (`use_column_width` is already gone from
   `st.image` as of 1.61). All 11 call sites in `Home.py`,
   `apps/beam_section/app.py` and `ui/components.py` now pass
   `width="stretch"` explicitly, matching the form `tierod`, `bolt_bending`
   and `beam_line` already used. `requirements.txt` is bounded
   `streamlit>=1.49,<2` — 1.49 is where `width=` landed on `st.dataframe`
   and `st.pyplot`, and the cap stops a major release changing the runtime
   under a deployed app.

   **Explicit, not deleted.** `st.dataframe` / `st.pyplot` / `st.plotly_chart`
   already default to `width="stretch"`, so those arguments *could* have been
   dropped — but `st.page_link` and `st.download_button` default to
   `"content"`. Dropping the argument there would have silently shrunk the
   landing-page CTA (which `ui/styles.py` styles as a full-width filled button
   completing the module card) and the CSV button, with no error to catch it.
   Every site is therefore explicit. `tests/test_layout_api.py` guards the
   whole class: no `use_container_width` anywhere, the `width=` API present on
   every element the app uses, the assumed defaults unmoved, the dependency
   bounded, and a headless render of both migrated pages.

### Medium-term

6. **Shear stress accuracy (solids/tubes)** — _partly done_
   Open sections now use per-point Bruhn midline shear flow, and the FEM
   solver is exact per-point for any shape. Remaining: solids/closed tubes
   still use VQ/It with the neutral-axis Q at all key points (conservative).
   Compute Q at each point's actual coordinate for those.

7. **Unsymmetric bending (L-beam, Z-beam)** — ✅ done in v2
   The full bending tensor (Iy, Iz, Iyz) is implemented; L/Z are valid with no
   geometric-axis assumption. Kept here for history.

8. **Section property override inputs**
   Allow the engineer to override any calculated section property (A, Iy, Iz,
   J, etc.) with a manually entered value — useful when pulling from AISC
   tables or FEA results rather than first principles.

9. **Custom material entry**
   Add a UI form on the material sidebar to define a custom material inline
   (not just in the Python file). Store temporarily in session state; offer
   export to `materials.py` format.

10. **Improved KP table display**
    Show the full stress state (σ1, σ2, σ_vm, τ_total) for each KP in a
    compact format next to the section diagram — reducing the need to scroll
    to the full results table to understand which point governs.

10a. **Classical-mode contour view** (wish list, requested 2026-07-16)
    Currently the Stress Contour is *always* an FEM field, even when a
    classical/exact solver is selected, because the classical solvers produce
    values only at key points and along the wall midline — not a continuous
    2-D field (a labeled `st.info` explains this in the Results tab). Wish:
    when classical analysis applies, offer a **classical view tab** that shows
    what the classical solver actually computes rather than borrowing the FEM
    field — e.g. the section diagram annotated with per-key-point stress
    values, and (for open sections) the shear-flow q(s) plotted along the wall
    midline. This makes the plot honestly reflect the classical method instead
    of showing an FEM mesh under an "exact" label, and avoids running the FEM
    solve at all in classical mode. Keep the FEM contour available as the
    cross-check view. See CHANGELOG "6C.2 — Clarify: the contour is always an
    FEM field."

10b. **Per-member dimension leaders** (wish list, 2026-07-16)
    `Section.dimension_annotations()` (added in Phase 6D) currently returns
    only the overall bounding-box width and height, drawn as dimension leader
    lines on the section diagram. Wish: override it per shape to also call out
    the individual member dimensions the engineer inputs — flange width bf,
    depth d, flange thickness tf, web thickness tw, etc. — each as its own
    labeled leader line, so the diagram becomes a full dimensioned drawing that
    confirms every input. Mechanical but touches all 11 catalog shapes; the
    hook and the base default are already in place.

10c. **Crippling check → unlocks Cozzone plastic-bending credit** — ✅ DONE in
    v2.2.0 (`library/analysis/crippling.py`, Crippling tab). Kept here for the
    rationale/history; the ⚠️ VERIFY on the element `Ce` and Gerard `β/m/g`
    coefficients is the remaining open item (reconcile to a chosen reference).

    > **As built differs from the plan below.** The D5 tension gate was
    > **removed outright** (not conditionally "unlocked when non-critical" as
    > the original plan text below reads): the tension fiber always keeps
    > `Fbu = f·Ftu`, and crippling is a **separate, element-wise** stability
    > row (`σ_c vs Fcc`, v2.2.1) on total compression — not a cap folded into
    > the bending allowable. The exploratory paragraphs below are retained only
    > as the original motivation; the authoritative description is the
    > "Crippling (v2.2.1)" methodology section above and CHANGELOG v2.2.0/v2.2.1.

    Local buckling (crippling) of the thin compression elements is the failure
    mode that currently forces `effective_f_cozzone → 1.0` for thin-walled open
    sections (decision D5, CHANGELOG v1.1.0). The v2.1.0 sign-aware bending
    allowable (Fbu only on the tension fiber) does **not** remove this gate:
    `f·Ftu` is a whole-section *plastic-moment* credit bookkept on the tension
    fiber, and it is only earned if the compression elements survive to let the
    section plasticize — crippling on the compression side caps the moment and
    the tension credit with it. See CHANGELOG v2.1.0 discussion.

    **Stays entirely within the cross-section framework — no length or fixity.**
    Crippling is short-wavelength *local* plate buckling, a section+material
    property, unlike column (Euler/Johnson) or lateral-torsional buckling. The
    standard methods (Gerard, Needham, Niu/Bruhn) give the crippling allowable
    Fcc from:
      • each element's **b/t** — already derivable from the section dims;
      • each element's **edge condition** (one-edge-free outstanding flange vs
        no-edge-free web-between-supports) — known from the shape topology, so
        each shape class can declare its elements;
      • material **Fcy** and **E** — already in the material library.
    Optional refinement inputs only: construction type (extruded/machined vs
    formed sheet with a bend radius) selecting the Gerard coefficient set, and
    (for a rigorous cutoff) the compression Ramberg-Osgood `n`. None of these is
    length or end-fixity. So the module needs essentially **no new user inputs**
    beyond what the beam-section module already has.

    Consequently the Cozzone "unlock" can happen **inside this module** with no
    cross-module model-data sharing: compute Fcc for the compression elements,
    grant `f > 1` only when they are non-critical, and cap the compression
    bending allowable at Fcc (tightening the `|σ₂| vs Fcy` / interaction-Fb
    side, which today uses Fcy and is itself optimistic for slender elements).
    Column-crippling interaction (Fcc as the Euler/Johnson cutoff) is the part
    that *would* need length + fixity — that belongs to the separate Column
    Buckling module (long-term item 11), not here.

10d. **Shear–crippling interaction** (wish list, 2026-07-17)
    The v2.2.0 crippling row (`σ_c vs Fcc`) checks the peak **total longitudinal
    compression** (`|min(σ_total)| = axial + bending`) against `Fcc`, and
    correctly ignores the principal-stress rotation (crippling is buckling in
    the beam-axis direction, so the longitudinal compression is the right
    measure — NOT `σ₂`, which would fold shear into a pure-compression
    allowable in the wrong frame). But it currently **omits shear's effect on
    the buckling capacity** entirely, so a wall carrying high compression *and*
    high shear (e.g. a web under `Vz` + `T`) is mildly unconservative. The
    physically correct fix is a plate **buckling interaction**, not `σ₂`:

        Rc + Rs² ≤ 1,   Rc = σ_comp/Fcc,   Rs = τ/F_scr

    where `F_scr` is a **separate shear-buckling** allowable per element (a
    `k_s` shear-buckling coefficient × the plate's elastic buckling stress —
    NOT `Fsu`, NOT `Fcc`). Needs only data the module already has (each
    element's `b/t` + edge condition) plus the `k_s` coefficient set. Deferred
    at the owner's request (2026-07-17): not needed now, logged for a possible
    later update.

### Long-term (new modules)

Each new module follows the same pattern:
- `apps/<module_name>/app.py` (render function)
- `apps/<module_name>/plotting.py` (figures)
- `pages/N_Title.py` (thin wrapper)
- `tests/<module_name>/` (pytest gates)

The engineering math goes in `library/<module_name>/` — the convention the
`tierod` and `bolt_bending` modules follow, and the one to use for new work.
`apps/beam_section/calculations.py` predates it and stays where it is.
Nothing under `library/` may import Streamlit. A module large enough to need
its own conventions gets an `apps/<module>/CLAUDE.md` (see `tierod`,
`bolt_bending`).

Planned modules:

_Shipped since this list was written: **Tie-Rod Layout** (`apps/tierod/`),
**Bolt Bending** (`apps/bolt_bending/`, v2.3.0) and **Beam Diagrams**
(`apps/beam_line/`, v2.5.0 — item 14 below). Each module's own backlog lives
in its `apps/<module>/CLAUDE.md`, not here._

11. **Column Buckling** (`apps/column_buckling/`)
    Euler and Johnson column buckling, effective length factors, margin of
    safety vs. critical load. Reuses `Section` class for `A`, `Iy`, `Iz`,
    radius of gyration.

12. **Fastener Pattern Analysis** (`apps/fastener_pattern/`)
    Shear flow distribution across a fastener group under eccentric load.
    Instantaneous center of rotation method. Critical fastener identification.

13. **Lug Analysis** (`apps/lug_analysis/`)
    Tension, shear bearing, and shear tearout for metallic lugs per MMPDS
    §9.6 / Niu Airframe Stress Analysis.

14. **Beam Deflection** — ✅ SHIPPED in v2.5.0 as **Beam Diagrams**
    (`apps/beam_line/`, `library/beam_line/`, page 5). Kept here for history.
    Built wider than planned: not standard load cases but a general
    direct-stiffness line-beam solver, so statically indeterminate beams
    (multiple interior supports, fixed-fixed, propped cantilever, elastic
    supports, imposed settlement) and internal hinges are in scope rather than
    deferred. Reports V, M, slope and deflection as exact piecewise
    polynomials — the peak moment is found by rooting the shear, not by
    sampling — plus reactions and a peak summary.

    It does share section properties from the beam-section module, via
    `ui/handoff.py`: a one-way snapshot into a plain session key, because
    Streamlit drops widget state on page navigation. Backlog and conventions
    live in `apps/beam_line/CLAUDE.md`. The obvious next step is the reverse
    handoff — publish M_max and V_max back as loads on the Beam Section Stress
    page, closing the loop.

15. **Beam with Web Openings / Vierendeel** (`apps/web_opening/`) — WISH LIST,
    not scheduled. Analysis of beams with web penetrations (MEP / conveyance
    pass-throughs) per AISC Design Guide 2 (Steel & Composite Beams with Web
    Openings) / the Darwin method. At an opening the section is two
    disconnected tees and prismatic beam theory breaks down: global shear
    splits between the tees and each carries local **Vierendeel bending** over
    the opening length; governing stresses are at the opening corners
    (global-moment axial ± Vierendeel bending). This is a distinct module, NOT
    a cross-section calculation — the beam-section engine correctly refuses a
    disconnected section. Would reuse the T-section properties for the tee
    chords. Explicitly deferred at the owner's request (2026-07-16).

---

## Development conventions

### File and function style
- Python 3.10+ compatible
- Type hints on all function signatures
- Docstrings on every module and public function
- Comments using `⚠️ ESTIMATED` and `⚠️ ASSUMPTION` markers for flagged items
  (these are searchable — use them consistently)

### Engineering standards
- All allowables from **MMPDS-01** unless otherwise documented
- Safety factors applied as `SF_yield = 1.0` (default), `SF_ult = 1.5` (default)
  — these are user-editable in the sidebar, not hardcoded
- Positive = tension convention throughout

### Adding a new shape — checklist
See `library/shapes/README.md` for the full procedure. Summary:
- [ ] Subclass `Section` in `shapes.py`
- [ ] Set all class attributes (`name`, `category`, `is_open_section`,
      `dim_labels`, `dim_defaults`, `f_cozzone`)
- [ ] Implement all required methods (area, centroid, Iy, Iz, J_torsion,
      tau_T, Qy, Qz, tw_y, tw_z, polygon_vertices, key_points)
- [ ] Register in `SHAPE_REGISTRY`
- [ ] Test by running the calculation pipeline with default dims
- [ ] Verify key points are geometrically on the section boundary
- [ ] Document any `⚠️ ASSUMPTION` entries in the method docstrings

### Adding a new material — checklist
See `library/materials/README.md` for the full procedure. Summary:
- [ ] Add `Material(...)` entry to `_materials` list in `materials.py`
- [ ] Source all values from MMPDS-01 or document the reference
- [ ] Flag any estimated values with `# ⚠️ ESTIMATED — <reason>` comment
      AND add to `estimated_fields` tuple
- [ ] Verify dict key matches `Material.name`

### Testing
No formal test suite yet. Before committing, verify at minimum:
```bash
python3 -c "
import sys; sys.path.insert(0,'.')
from library.shapes import SHAPE_NAMES, SHAPE_REGISTRY
from library.materials import MATERIALS
from apps.beam_section.calculations import Loads, calc_stress_at_points, calc_margin_table
from library.shapes import make_section

# Quick smoke test
sec = make_section('I-Beam / W-Shape', [4,6,0.375,0.25])
loads = Loads(P=0, Vy=0, Vz=500, My=1000, Mz=0, T=0)
df = calc_stress_at_points(sec, loads)
assert len(df) > 0
print('Smoke test passed')
"
```
Run from the repo root (`stress_toolkit/`).

---

## Streamlit Cloud deployment

- **Entry point:** `Home.py` (set in Streamlit Cloud app config)
- **Branch:** `main` (or as configured)
- **Requirements:** `requirements.txt` at repo root
- Streamlit Cloud auto-discovers `pages/*.py` for sidebar navigation
- No secrets or environment variables needed currently

After any push to the deployment branch, Streamlit Cloud redeploys
automatically within ~60 seconds.

### ⚠️ Adding a symbol to a SHARED module needs a reboot, not just a push

An automatic redeploy pulls the new source and hot-reloads the changed pages,
but modules already in `sys.modules` are **not** re-imported. So when a commit
adds a new name to a shared module — a token to `ui/theme.py`, a helper to
`ui/components.py` — a newly-imported page that reads the new name finds the
**stale** module object and dies at import:

```
File ".../apps/beam_line/plotting.py", line 39, in <module>
    from ui.theme import BEAM_PALETTE as C
ImportError
```

The source is correct and the push is complete; only the running process is
stale. Symptom is distinctive: **exactly the new page fails, every existing
page is fine**, and the traceback ends on an import of the shared module.

**Fix: Manage app → ⋮ → Reboot app.** Do this as a matter of course after any
commit that adds a name to `ui/`. (Observed 2026-09-04 on the v2.5.0 Beam
Diagrams deploy. Same class as the local watcher staleness recorded in
`apps/bolt_bending/CLAUDE.md`.)

---

## Session history summary

This project was developed in a Claude.ai chat session
(Claude Sonnet 4.6). Key decisions made during that session:

- Switched from Excel/Google Sheets to a Streamlit Python app after two
  Excel iterations proved too difficult to debug in a no-feedback environment
- Established the class-per-shape pattern after evaluating three alternatives
  (string formulas with eval, dataclass with function fields, inheritance)
- Adopted triangulation-based contour plotting after rectangular-grid masking
  produced stair-step artifacts at section boundaries
- Chose dark-mode-only until light-mode input field CSS issues are resolved
- Chose MMPDS-01 as primary source with `⚠️ ESTIMATED` convention for gaps
- Deferred warping torsion, unsymmetric bending (L/Z), and per-point shear
  flow to future work — noted in Known Issues above