# Handoff: Beam Section Stress Tool — Readability Redesign

## Overview

This is a high-fidelity redesign of a structural / aerospace engineering tool that
computes linear-elastic stresses on a beam cross-section under combined axial, shear,
and bending loads. The original tool was a dark-on-dark dashboard that was difficult
to scan; this redesign re-centers it around the engineer's primary task: **read the
numbers, see where they govern, decide if it passes**.

Aesthetic direction: *aerospace tool precision*. Dark technical sidebar paired with a
light "engineering-report" canvas. Editorial serif headings, tabular monospace numerics,
restrained signal-blue accent, plus a three-tone status scale (Safe / Watch / Critical)
driven by % of material allowable.

## About the Design Files

The files in this bundle are **design references created in HTML/React+Babel** —
prototypes showing intended look and behavior, not production code to copy directly.
The task is to **recreate these designs in the target codebase's existing environment**
(likely React or whatever framework the engineering tool is built on) using its
established component primitives, state libraries, and routing — or, if no environment
exists yet, to choose a stack appropriate for an engineering-data-heavy app and
implement the designs there.

The Babel-compiled inline JSX is fine for design preview but should not ship. In
particular: real numbers should come from the actual stress engine, not the hard-coded
arrays in `app.jsx`.

## Fidelity

**High-fidelity (hifi).** All colors, type, spacing, borders, and interaction patterns
are intentional and should be matched closely. The data shown is illustrative (a 4×2 in
rectangular section under sample loads) but the layout, units, and column structure
are final.

## Screens / Views

Single page, two-column app shell.

### Left — Sidebar (dark, 268px wide, persistent)

The sidebar is deliberately kept dark to anchor the tool identity and visually
separate inputs from outputs. Top-level nav at top; then collapsible-look "section
cards" grouping the input parameters.

- **Nav items** (Home, Beam Section Stress, Joint Analysis, Fastener Group): 13px
  IBM Plex Sans, `--sb-text-dim` (`#7d8aa1`). Active item: full opacity, 2px inset
  left border in `--accent`, `--sb-section-bg` background, 6px radius.
- **Section cards**: 8px radius rounded box, top-down gradient from `--sb-section-bg`
  (`#182236`) fading to transparent at 80%, 8/10/12 padding.
- **Section headers**: small SVG icon + 11px uppercase label, `--accent` color
  (`#1d4ed8`), 0.08em tracking, 600 weight; underlined with a 1px `--sb-border` rule
  with 10px gap to first input.
- **Field labels**: 11px `--sb-text-dim`, 4px margin to input.
- **Inputs**: 36px height (`--row`), `--sb-input` background, 1px `--sb-input-border`,
  6px radius, IBM Plex Mono 13px. Focus border = `--accent`.
- **Steppers**: 3-column grid (1fr 28px 28px) — value input plus −/+ buttons.
  Buttons separated by 1px left border in `--sb-input-border`. Hover lightens
  background by `rgba(255,255,255,0.03)`.
- **Disclosure rows** (e.g. "Material allowables"): caret + label in a recessed input
  card; reveals an extended table inline when expanded.

Sections in order:
1. **Load Case** — Load Case ID, Analyst, Project / Component
2. **Material** — Material selector, SF Yield + SF Ult side-by-side, "Material
   allowables" disclosure
3. **Cross-Section** — Section Shape selector, b (Width), h (Height)
4. **Applied Loads** — P (Axial), Vy + Vz, My + Mz

### Right — Main canvas (light, scrolling)

Three horizontal bands separated by `--rule` borders and `<h2>` section headers
with a small monospace section number (01, 02 …).

#### Top bar
- Left: breadcrumb (`Aerostructures / Stress Tools / Beam Section Stress`), 12px,
  `--ink-3` (`#5b6472`), final crumb bolded to `--ink`.
- Right: "● Saved 2 min ago" safe-status badge + **Run Analysis** primary button
  (black background `--ink`, white text, 8px/16px padding, 6px radius, hover →
  `--accent`).

#### Page header
2-col grid: title block left, "drawing stamp" right.

- **Title** — IBM Plex Serif, 500, 32px, `-0.01em` tracking. Format: `Beam Section
  Stress — *rectangular cross-section*`, with the subtitle in italic `--ink-3`.
- **Meta line** — IBM Plex Mono 11px uppercase, 0.05em tracking, flex-wrap with
  6/14 gap. Items: LC-ID, "Linear-elastic", "IPS units", "MMPDS-01 allowables",
  axis legend.
- **Stamp** (right side, 180px min-width) — like a drawing-title block. White
  paper background, 1px `--rule` border, 6px radius, 10/14 padding. Three rows:
  Analyst / Rev / Status, each `space-between` with 11px uppercase key in
  `--ink-3` and 12px mono value in `--ink`. Status uses `--safe` for "Released".

#### 01 — Governing Stress Summary

A horizontal strip of **5 stress cards** in a 5-column grid inside one white card
(no inter-card gaps; cards separated by 1px `--rule` dividers; outer 8px radius,
1px border).

Each card stacks:
1. **Name + status badge** row — name in IBM Plex Mono 10px uppercase / 0.08em
   tracking; status badge is a 9px uppercase pill, soft-bg / saturated-fg in
   safe / caution / critical.
2. **Big value** — IBM Plex Mono 30px, 500, `-0.02em` tracking, baseline-aligned
   with a 12px `ksi` unit. Negative values prefix a `−` colored `--critical`.
3. **Utilization block**:
   - 10px-uppercase "DESCRIPTION" left, `B%` of `Fty/Ftu/Fcy/Fsu` right.
   - 4px tall bar (`--rule-soft` background), inner fill colored by status,
     width = `min(100, |σ| / allowable × 100)`.
   - "Margin of Safety" left, `MS = +X.X` right (or `+∞` if utilization is
     vanishing).

Status thresholds (utilization = `|σ| / allowable`):
- `≤ 0.50` → **Safe** (`--safe`, #1f7a4a)
- `0.50 – 0.90` → **Watch** (`--caution`, #b67400)
- `> 0.90` → **Critical** (`--critical`, #b3231c)

The 5 cards are: Max σ₁ (Principal, vs Fty), Min σ₃ (Principal, vs Fcy), Max σᵥₘ
(Von Mises, vs Fty), Max τ (Total shear, vs Fsu), Max σ_bend (Bending, vs Fty).

#### MS callout (below the strip, optional)

White card, 1px border, 3-column grid (auto 1fr auto). Left: "MIN. MARGIN OF
SAFETY" label + huge 40px mono `+X.X` in `--safe`. Center: prose summary
("Governing: <stress name> at KP <id> — value ksi vs allowable ksi <key>")
plus a faint second line stating "All applied factors of safety satisfied."
Right: large Pass/Released badge.

The minimum MS is computed across all 5 stresses; whichever has the smallest
margin governs.

#### 02 — Section Geometry & Key Points

2-column grid: diagram tab card (`1fr`) on the left, material allowables panel
(280px fixed) on the right.

##### Diagram tab card
- **Tab bar** at top: `Section Diagram` (active), `Stress Contour`, `Full Report`.
  Each tab: 10/16 padding, 13px text, 2px bottom border on active in `--accent`,
  `--ink` color on active vs `--ink-3` rest. Each tab has a small leading SVG
  icon (14px stroke).
- **Card body**: white, 1px `--rule` border (no top, joins under tab bar),
  bottom-radius 8px, 18px padding.
- **Card header inside body**: title (`Rectangle · b=4.00 × h=2.00 in`) left in
  16px IBM Plex Serif 500, properties right in a flex row of mono 11px:
  `A = 8.0000 in²`, `Iy = 2.6667 in⁴`, `Iz = 10.6667 in⁴`, `Sy = 2.6667 in³`.
  Separator: 1px dashed `--rule`.
- **Diagram SVG** (720×380 viewBox, scales to width):
  - Plot area background = `--bg-2`, overlaid with a 10px dot grid (`<pattern>`
    with 0.6r circles at 40% opacity).
  - Grid lines at integer ticks (–3 to 3): solid for axis 0 line, 2/3 dashed
    otherwise, all `--rule` 0.5 stroke. Tick labels in IBM Plex Mono 10px
    `--ink-3`.
  - Axis labels: `y (in)` bottom-center, `z (in)` left-center (rotated -90).
  - **Section shape** = rectangle from (-b/2, -h/2) to (b/2, h/2). Fill =
    accent at 8% opacity, stroke = accent 1.5px.
  - **Centroid crosshair** = 16px black `--ink-2` cross at origin.
  - **KP markers** = 9 circles for A–I. Each is a 7r (9r if governing) white
    circle, 1.5px (2px if governing) `--accent` stroke (red `--critical` if
    governing). Letter inside in 9px IBM Plex Mono 600.
- **KP table** below the SVG: full-width, IBM Plex Mono 12px.
  Columns: KP (round chip), Description, y (in), z (in), σ (ksi), σᵥₘ (ksi),
  τ (ksi), Status. Negative σ values render with `−` prefix in `--critical`.
  Governing row gets bold `--ink` text in Description col and a `▸` arrow
  rendered via `::before`. Header row: 10px uppercase `--ink-3` on `--bg-2`
  background, 1px `--rule` bottom border. Body rows: 1px `--rule-soft` bottom;
  hover bg = `--bg-2`. Numeric columns are right-aligned.

##### Stress Contour tab (alt diagram)
Same SVG envelope but contents are a 40×20 cell grid of `σ_bend = My·z/Iy + Mz·y/Iz`
evaluated at the cell center, colored on a 2-stop cool→neutral→warm gradient:
- compressive (`σ_min`): rgb(29, 78, 216) — blue
- neutral (mid): rgb(245, 243, 238) — paper
- tensile (`σ_max`): rgb(179, 35, 28) — red

Below the contour: a 30-stop legend bar with min/max ksi labels.

##### Material allowables panel (280px, sticky)
- White card, 1px border, 8px radius, `align-self: start` so it doesn't stretch.
- Header strip: `--bg-2` background, 1px bottom border, 12/16 padding.
  - Eyebrow: 10px IBM Plex Mono uppercase `--ink-3` "Material allowables"
  - Name: 15px IBM Plex Serif 500 in `--ink` (e.g. "2024-T3 Sheet")
- 6px tall accent-gradient rule below header (linear-gradient(90deg, accent,
  transparent), 40% opacity).
- **Rows** — 6 entries (Fty, Ftu, Fcy, Fsu, E, ν). 3-column grid
  (60px / 1fr / auto), baseline-aligned, 12/16 padding, 1px `--rule-soft`
  bottom (none on last).
  - Col 1 (key): IBM Plex Mono 11px uppercase 600, `--ink-3`
  - Col 2 (desc): 11px regular, `--ink-3`
  - Col 3 (value): IBM Plex Mono 16px 500 in `--ink`, with a 10px `--ink-3`
    `small` unit suffix (` ksi`, ` Msi`, etc.)
- Footer strip: 1px top border, 10px mono `SRC MMPDS-01 · A-Basis · <temper>`

#### Footer rule + metadata line
`HR` in `--rule`. Then a flex `space-between` line of IBM Plex Mono 11px
`--ink-3`: app version on left, disclaimer on right
("Linear-elastic only · Not for buckling, fatigue, or non-linear analysis").

## Interactions & Behavior

- **Sidebar inputs are live but unbound** in the prototype. In production they
  should drive a recompute of the stress arrays and re-render the cards/diagram.
- **Tab switching** in the diagram pane uses React state; no transition. The tab
  underline shifts via the `is-active` class change.
- **Run Analysis button**: hover changes background from `--ink` to `--accent`.
  In production: triggers the stress solver.
- **KP table row hover**: row background → `--bg-2`. Cells inherit.
- **Status badges** are derived from utilization on every render, not stored.
- **MS callout** is recomputed via `useMemo` from the same stress list — single
  source of truth.
- **Stepper buttons** increment / decrement the bound value; `Math.max(0, …)`
  clamp; `toFixed(decimals)` for display.
- **Tweaks panel** (bottom-right floating, gated by host toolbar toggle) lets
  the user swap theme (Hybrid / Dark / Light), density (Comfortable / Compact),
  accent color (4 swatches), and toggle the MS callout. These set CSS variables
  + `data-theme` / `data-density` attributes on `<html>`.

No animations beyond CSS hover and the 240ms utilization-bar width transition.

## State Management

For the prototype everything is local React state. In production you'd want:
- **Inputs store** (Load Case, Material, Section, Applied Loads) — drives solver
- **Results store** — computed stresses per KP, governing KP, min MS
- **UI store** — active tab, sidebar collapse, theme/density preferences
- **Material library** — fetched from MMPDS-01 dataset, keyed by spec + temper

Recompute pipeline: any input change → solver call → results store update →
cards / diagram / table re-render. Solver should run client-side for snappy
feedback; cache the last N runs for the "Full Report" tab.

## Design Tokens

### Colors

```
/* Sidebar (dark, kept across themes by default) */
--sb-bg            #0f1622
--sb-bg-2          #131c2c
--sb-border        #1f2a3d
--sb-text          #d6dde9
--sb-text-dim      #7d8aa1
--sb-text-faint    #4f5b73
--sb-input         #0a111c
--sb-input-border  #25324a
--sb-section-bg    #182236

/* Canvas (light "report" surface) */
--bg               #f5f3ee   /* warm off-white page */
--bg-2             #efece4   /* subtle band / table head bg */
--paper            #ffffff   /* card surface */
--ink              #15181d   /* primary text */
--ink-2            #2c323b   /* secondary text */
--ink-3            #5b6472   /* tertiary, labels */
--ink-faint        #97a0ae
--rule             #d8d3c7   /* card borders, dividers */
--rule-soft        #e7e2d4   /* table row dividers, bar tracks */
--grid             #ecead9   /* SVG grid */

/* Accent + status */
--accent           #1d4ed8   /* signal blue */
--accent-soft      #e1e9fb
--accent-deep      #0b2a7a
--safe             #1f7a4a   /* fg */
--safe-soft        #d9ecdf   /* bg */
--caution          #b67400
--caution-soft     #f6e8c8
--critical         #b3231c
--critical-soft    #f4d5d3
```

Dark theme overrides `--bg/--bg-2/--paper/--ink*/--rule*/--grid/--accent-soft`.
Light theme also overrides the sidebar to match.

### Typography

- Headings: **IBM Plex Serif** 400/500 — title 32/1.1, section h2 20/1.2,
  material name + diagram title 15-16/1.2
- UI body: **IBM Plex Sans** 300/400/500/600/700 — base 14/1.45, labels 11,
  meta 12
- Numerics + technical labels: **IBM Plex Mono** 400/500/600 with
  `font-variant-numeric: tabular-nums`. Card big values 30/1, MS callout 40/1,
  material value 16, KP table 12, axis ticks 10, eyebrow labels 10-11 uppercase
  0.05–0.1em tracking

Body font-feature-settings: `"ss01", "cv05", "cv11"` for Plex's straight-leg
glyphs.

### Spacing

- Card padding: 14–18px
- Section header margin: 28 top / 14 bottom
- Sidebar section padding: 8/10/12
- Row height (inputs / steppers): `--row` = 36px (30px in compact)
- Gutter (work-grid): 24px
- Canvas padding: 24/40

### Radius

- Cards / panels: 8px
- Inputs / buttons / small chips: 6px
- KP markers / status pills: 50% / 3px

### Shadows

None used. Hierarchy is built from rules + value contrast, not shadow.

### Status badge style

```
9px uppercase mono, 600, 0.1em tracking
padding 2/6, radius 3
safe   : bg #d9ecdf, fg #1f7a4a
caution: bg #f6e8c8, fg #b67400
critical: bg #f4d5d3, fg #b3231c
```

## Assets

No raster assets. All iconography is inline SVG defined in `sidebar.jsx`
(SbIcon) and `app.jsx` (tab icons). Replace with the codebase's existing icon
set (Lucide, Heroicons, custom) — match the 14px stroke-1.5/2 outline style.

Fonts loaded from Google Fonts:
- IBM Plex Sans 300/400/500/600/700
- IBM Plex Mono 400/500/600
- IBM Plex Serif 400/500/600

In production, self-host these or pull from a CDN per the codebase's font
strategy.

## Files

- `Beam Section Stress.html` — entry HTML, defines all CSS custom properties
  and theme/density attribute switching
- `sidebar.jsx` — left input pane (`Sidebar`, `Stepper`, `SbSection`, `SbIcon`)
- `diagram.jsx` — `SectionDiagram` SVG component (axes, grid, KP markers).
  **Note:** `kp.y` is the horizontal section coord, `kp.z` is the vertical —
  the SVG transform is `translate(X(kp.y) Y(kp.z))`. Don't swap these.
- `app.jsx` — `App` shell, `StressCard`, `MaterialPanel`, `ViewTabs`,
  `StressContour`, `KPTable`, hard-coded `STRESSES` / `MATERIAL` / `KP_STRESSES`
  arrays (replace with solver output), Tweaks wiring
- `tweaks-panel.jsx` — design-system panel component (don't ship; use your
  codebase's settings / preferences UI for theme/density if those are exposed
  to end users)

## Important caveats

1. **Numbers are illustrative.** All values in `STRESSES`, `KP_STRESSES`, and
   the `StressContour` heatmap are computed off a hard-coded sample load case
   (b=4, h=2, My=1000, Mz=500). Wire to your real solver.
2. **MMPDS-01 allowables** for 2024-T3 are placeholders matched to the
   original screenshot. Pull from your material database.
3. **Sign convention**: positive σ = tension, negative = compression. Negative
   values render with a `−` prefix in `--critical`. Don't show them as
   `-0.0000` — coerce zero to positive.
4. **Units**: all stresses ksi, moduli Msi, dimensions in. The "IPS units" note
   in the header pins this. If you support SI, add a unit toggle near the
   header and convert at render time (don't restructure the solver).
5. **Buckling, fatigue, non-linear** are explicitly out of scope — see footer
   disclaimer.
