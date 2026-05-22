# CLAUDE.md — Stress Toolkit
## Context for Claude Code / AI-assisted development

This file provides context for Claude Code (or any AI assistant) working on
this repository. Read it before making any changes.

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
├── pages/
│   └── 1_Beam_Section_Stress.py    ← Auto-discovered page wrapper
├── apps/
│   └── beam_section/
│       ├── app.py                   ← Streamlit render() for beam module
│       ├── calculations.py          ← Stress + MS engine (no Streamlit deps)
│       └── plotting.py              ← matplotlib figures (no Streamlit deps)
├── library/
│   ├── materials/
│   │   ├── materials.py             ← Material dataclass + MATERIALS dict
│   │   └── README.md                ← Schema + how-to-add docs
│   └── shapes/
│       ├── shapes.py                ← Section base class + 13 shape subclasses
│       └── README.md                ← How-to-add-a-shape docs
├── ui/
│   ├── theme.py                     ← Color tokens: THEME, PLOT_PALETTE
│   ├── styles.py                    ← CSS injection (call inject_css() at top of each page)
│   └── components.py                ← Reusable widgets (section_header, info_card, etc.)
├── requirements.txt
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

### 6. Dark mode only (for now)
Dark mode is the current default and only active theme. Light mode is defined
in `ui/theme.py` (`LIGHT` token set) but is NOT wired to the UI.

**Reason:** Streamlit's number input and text input widgets render text in
incorrect colors in light mode in some browsers — this requires browser-
specific CSS fixes that have not been verified yet.

Do not add a working light-mode toggle until this is tested. The
architecture is in place; it is a two-line change once verified.

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

### Normal stress
```
σ_axial  = P / A
σ_bend   = (My·z)/Iy + (Mz·y)/Iz
σ_total  = σ_axial + σ_bend
```

### Shear stress (VQ/It)
```
τ_Vy = Vy·Q_y / (Iy·t_w)
τ_Vz = Vz·Q_z / (Iz·t_w)
```
Q and t_w are defined per-shape and reflect the maximum shear at the
neutral axis. The same Q/t_w value is used at all key points (conservative).

### Torsional shear stress
Depends on section type:
- **Closed sections** (Rect Tube, Circular Tube): Bredt-Batho `τ = T/(2·Am·t)`
- **Circle**: Exact `τ = 16T/(π·d³)`
- **Ellipse**: Exact `τ = 2T/(π·a·b²)` at minor axis end
- **Open thin-walled sections**: St. Venant `τ = T·t_max/J` where `J = Σ(b·t³)/3`

⚠️ Warping stresses are **not** included for open sections. The UI warns the
user when torsion is applied to an open section.

### Total shear and principal stresses
```
τ_total = √(τ_Vy² + τ_Vz² + τ_T²)
σ1, σ2  = σ/2 ± √[(σ/2)² + τ_total²]
σ_vm    = √(σ1² − σ1·σ2 + σ2²)
```

### Margins of safety
```
MS = Allowable / (SF · Applied) − 1
```
Six checks:
1. σ1 vs Fty (yield)
2. σ1 vs Ftu (ultimate)
3. |σ2| vs Fcy (compression yield)
4. τ_total vs Fsu (shear ultimate)
5. σ_vm vs Ftu (von Mises)
6. MMPDS Interaction §1.3: `MS = 1/√(Rc²+Rb²+Rs²) − 1`
   where `Rc = σ_axial/Ftu`, `Rb = σ_bend/Fbu`, `Rs = τ/Fsu`

### Cozzone bending allowable
```
Fbu = f · Ftu
```
Shape factor `f` is a simplified constant per shape class (attribute
`f_cozzone`). These are conservative values from Cozzone (1943) /
NACA TN-1818. See `shapes.py` docstring for the full table and note on
when a rigorous Cozzone analysis would be warranted.

### Bending on geometric axes
L-beam and Z-beam have nonzero product of inertia `Iyz` — their principal
bending axes are rotated from the geometric Y/Z axes. The tool assumes
bending about the geometric axes, which is valid when the member is
constrained by adjacent structure (skin, frames, fasteners) to bend in
the geometric plane. This assumption is documented with `⚠️ ASSUMPTION`
comments in `shapes.py` and in the UI formulae block.

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

24 alloys in 4 categories: Aluminum, Steel, Titanium, Stainless.
Source: MMPDS-01 / MIL-HDBK-5J (structural steels from AISC/ASTM).

Each material stores: Fty, Ftu, Fcy, Fsu, Fbru, Fbry, E, Ec, G, ν,
alpha (CTE), k (thermal conductivity), T_max, rho, source, notes.

Properties not available from MMPDS are flagged with `⚠️ ESTIMATED` and
listed in `Material.estimated_fields`. Current estimated fields: Fbru/Fbry
for A36, A572, and 300M.

---

## Known issues and tech debt

| Issue | Severity | Location | Notes |
|-------|----------|----------|-------|
| Light mode input field colors broken | Low | `ui/styles.py` | CSS doesn't override Streamlit widget internal theme in all browsers. Dark mode works perfectly. Fix before adding light mode toggle. |
| Shear stress at non-centroidal KPs | Low | `calculations.py` | τ_Vy and τ_Vz use the max (neutral-axis) Q value at all key points. This is conservative. A rigorous implementation would compute Q at each point's z-coordinate. Acceptable for preliminary sizing. |
| Z-beam key-point coordinates | Low | `shapes.py ZBeam.key_points()` | Top flange right tip coordinate has a tautological expression. Review when Z-beam is tested with combined Mz loading. |
| Triangulation warnings | Info | `plotting.py` | matplotlib prints "Ignoring fixed axis limits" when `set_aspect("equal")` conflicts with explicit xlim/ylim. Cosmetic only — does not affect figures. |
| Warping torsion | Medium | `shapes.py`, `calculations.py` | St. Venant torsion only for open sections. Warping normal stresses (σ_w) are not computed. For short open-section members with restrained ends, this can significantly underestimate stress. Engineering judgment required. |
| L-beam / Z-beam Iyz | Medium | `shapes.py` | Product of inertia not computed. Unsymmetric bending formulas not implemented. Safe only when structural constraint assumption holds. |

---

## Planned future work

### Near-term (next session priorities)

1. **Test on Streamlit Cloud**
   Deploy and verify all 13 shapes render correctly in a browser. Check
   mobile layout (sidebar collapses, tables scroll horizontally).

2. **Light mode fix**
   Identify and apply browser-specific CSS overrides for Streamlit number
   input fields. Test in Chrome and Safari before exposing in the menu.

3. **Hamburger menu improvements**
   Current theme toggle is functional but basic. Improve dropdown styling
   so it doesn't affect the main page layout when open.

4. **Add `.gitignore`**
   Should ignore `__pycache__/`, `*.pyc`, `.streamlit/`, `venv/`, `.env`.

5. **Report export (PDF)**
   Add a button that generates a print-quality PDF snapshot of the results:
   title block, section diagram, section properties, stress table, MS table.
   Suggested approach: `matplotlib.backends.backend_pdf` or `reportlab`.
   The PDF should be fully standalone — not reliant on the browser's print function.

### Medium-term

6. **Shear stress accuracy improvement**
   Compute Q(z) at each key point's actual z-coordinate rather than using
   the neutral-axis maximum everywhere. This requires per-point shear flow
   computation, which is shape-dependent.

7. **Unsymmetric bending (L-beam, Z-beam)**
   Implement the full bending tensor approach using Iy, Iz, Iyz to compute
   stress at each point without the "geometric axis" assumption. Makes the
   tool valid without relying on structural constraint.

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

### Long-term (new modules)

Each new module follows the same pattern:
- `apps/<module_name>/app.py` (render function)
- `apps/<module_name>/calculations.py` (pure engineering math)
- `apps/<module_name>/plotting.py` (figures)
- `pages/N_Title.py` (thin wrapper)

Planned modules:

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

14. **Beam Deflection** (`apps/beam_deflection/`)
    Euler-Bernoulli beam deflection and slope for standard load cases
    (cantilever, simply supported, fixed-fixed). Could share section
    properties from the beam section module.

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