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
mesh-dependent and not a converged design value — enable **corner fillets**
(below) or model a fillet radius for real corner stresses.

---

## v2.4.0 — Refined bearing, and a bolt-bending audit (2026-09-04)

**New, opt-in, less-conservative.** A sidebar toggle on the Bolt Bending page
replaces uniform bearing with a beam-on-elastic-foundation solve. The baseline
is untouched and stays the default answer — the toggle is off by default.

**One analysis drives the page.** The toggle chooses *which*; it does not add a
parallel set of results. Two peak moments on one screen is how the wrong one
ends up in a report. The baseline-vs-refined comparison lives in a grid inside
the refined supplement, below the margins it qualifies. (This shipped briefly
as a second tab and was changed to a toggle before release, at the owner's
request — the page now has no tabs at all.)

Because a toggle can silently move the peak moment by 15%, the bearing
assumption in force is stated in words above the Strength card in **both**
states, and the refined blocks — basis for `k`, per-plate β·t, and the limits —
are rendered directly beneath the numbers they qualify. Turning it off restores
the baseline exactly.

### What it refines — and what it deliberately does not

Uniform bearing is equivalent to assuming the bolt is **rigid across each
plate's thickness**: it cannot tilt in the hole, so it presses evenly. That is
conservative on a long grip, where a real bolt bends, bearing concentrates
toward the shear planes, and the effective moment arm shortens.

Each plate is given an unknown rigid offset `d_i` with a Winkler bed of modulus
`k` between it and the bolt, so `q(x) = k·(d_i − w(x))` and

```
EI·w'''' + k·w = k·d_i     with   ∫ k(d_i − w) dx = P_i  over plate i
```

One extra equation per plate for one extra unknown — **a single linear solve,
no iteration** — and the constraint means the entered load split is honoured
exactly. It refines *where within each plate's thickness the load acts*, and
nothing else.

Explicitly NOT modelled: the **load split** (still an input; statically
indeterminate), bolt–hole **clearance** and one-sided contact (the bed is
linear and two-sided, so a negative reaction is bearing on the far side of the
hole — right for a close fit, wrong for a sloppy one), and **plastic bearing**
redistribution at ultimate. All three are stated on the page.

### Why it can be trusted: the rigid-bolt limit

Pinned at both ends and straight ⇒ `w ≡ 0` ⇒ `q = k·d_i`, uniform over each
plate. **The refined model reduces to the baseline exactly as `k → 0`**, so it
is a correction to the model already in service rather than a rival to it.
That is the governing gate in `tests/bolt_bending/test_refined.py`, along with
the standing check that refined diagrams still close at the nut and that each
plate's strips sum to the entered load.

### Basis for k — Tate & Rosenfeld, cross-checked against Huth

`k = E_plate`, from the Tate & Rosenfeld (NACA TN 1051, 1946) bearing term:
the plate bearing compliance `δ = P/(E·t)` against the Winkler `P = k·δ·t`.

Only the **bearing** part belongs in `k`. Lumped fastener-flexibility formulas
(Huth, Swift) bundle bolt bending, bolt shear and bearing into one empirical
number, and this model already computes bolt bending explicitly from EI — so
calibrating `k` to a lumped compliance would **double-count** the very thing
being refined. Huth (ASTM STP 927, 1986) is therefore carried as an
*independent cross-check* on the resulting joint compliance, never as an input.
On the shipped default it reads 1.47× — inside the ±2× band these published
formulas occupy among themselves. ⚠️ VERIFY: the Huth exponent and coefficient
are the commonly quoted bolted-metallic constants and have not been checked
against the paper.

### Per-plate foundation modulus

Each plate now takes **its own material**, and therefore its own bed `k = E_i`,
from a selector on its row. `refined_analysis` accepts either a scalar (one bed
for the stack, the previous behaviour, bit-identical) or a per-layer sequence.

This is not cosmetic. A steel doubler and an aluminium skin differ by ~2.7× in
bearing stiffness; β scales as `k^¼`, so the stiffer plate draws its bearing in
harder and **the peaking follows it**. One averaged bed puts that peak on the
wrong plate. On a 2024-T3 / 4340 / 2024-T3 stack the steel plate reads β·t =
2.00 against 0.78 for the aluminium ones.

Guards: a short or gappy material list falls back to the first stated modulus
rather than leaving a plate on a zero-stiffness bed, which would make the solve
singular. `RefinedResult.mixed_stack` adds the material and `k` columns to the
per-plate table and stops the basis card advertising a single `k` that no plate
actually has — on a mixed stack the headline is the **governing** plate's, never
an average. The Huth cross-check uses each plate's own modulus.

⚠️ Metallic only. `k = E_plate` is a Tate & Rosenfeld metallic bearing
derivation and the Huth constants shipped here are the bolted-metallic set;
composite laminates need a different bearing model, a different Huth constant
set, and CMH-17 allowables. The plate material list is limited to metallics on
purpose.

### Results on the shipped verification case

| plate material | β·t (0.5 in plate) | peak M | vs baseline | MS bending |
|---|---|---|---|---|
| — (baseline, uniform) | — | 278.7 | — | +1.64 |
| 2024-T3 | 1.56 | 235.2 | −15.6% | +2.13 |
| Ti-6Al-4V | 1.73 | 218.8 | −21.5% | +2.37 |
| steel | 2.00 | 187.7 | −32.7% | +2.92 |

`β = (k/4EI)^¼`; `1/β` is the decay length of the bolt's deflection inside a
plate. **β·t is the screening number**: below ~1 bearing is already near-uniform
and the baseline is the right model; above ~2 it peaks hard. The page says
which case it is in plain language rather than leaving it to be inferred.

### Numerics — a trap worth recording

The system has **two rigid-body null modes** (translate or rotate the bolt while
shifting every `d_i` to match, and the constraints still hold). An early draft
left it singular and leaned on a least-squares minimum-norm solve: it looked
entirely plausible and **drifted with mesh refinement**, giving 239.4 lb·in at
coarse mesh against the correct 235.1.

The fix is physical as well as numerical: **pin lateral deflection at the head
and nut faces.** That removes exactly those two modes. Now mesh-independent
from 100 to 1600 el/in; `test_converged_and_stable_in_mesh` would have caught
the original.

Those pins are a deflection boundary condition **on the shape solve only** —
the same idealisation as the baseline's end pair, but their reactions are not
carried forward and are **not** equal to `R_0`/`R_L`. (An earlier draft of this
entry and of the module docstring claimed they were; they are not.) The refined
distribution goes back through `kernel.analyse()` as strips, and the kernel
recomputes `M_res` from that strip layout and closes it with its own end pair.
On the shipped default the refined layout still leaves `M_res` = −78.9 lb·in,
closed at 74.5 lbf.

Also fixed here: the figure builder gained an optional `groups` argument, so a
figure whose segments are subdivisions of the physical layers annotates by
plate rather than drawing 24 station ticks per plate. The peak-moment callout
and the governing-station note take the same treatment via a `names=` argument
— without it the refined peak reports "in plate 36" instead of "in plate 2".

### Fixed: a loaded layer with no thickness passed the closure gate

**Results-changing. This produced confident, meaningless margins.**

The §4.1 gate tested `ΣP ≈ 0` — the *input* sum. A layer carrying load with
zero (or negative, hence clamped) thickness contributes to `ΣP` and to `M_res`,
but `w = P/t` is guarded to zero, so it applies **no bearing** and its load
never reaches the diagrams. `ΣP` can therefore be zero while the diagrams do
not close:

```
[plate 0.25 +1000] [plate 0.000 −1000] [plate 0.25 0]
  ΣP = 0            → balanced = True → margins displayed
  V(L) = +1000 lbf, M(L) = +250 lb·in  → the diagrams never closed
```

Every screening check reported green. It is reachable in one keystroke: the
thickness input allows 0, so clearing a thickness leaves `0.000` beside a load.

The tell was that **the two bearing models disagreed**: the refined path zeroed
a starved plate's load, so the same stack was gated one way with the toggle off
and the other way with it on.

Fixed by gating on the **integrated output** as well as the input sum —
`|V(L)|` against the same lbf tolerance, and `|M(L)|` against `tol × L` (a
moment scale from load × grip, deliberately not from `max|M|`, which is
inflated when the diagram is wrong and would slacken its own tolerance).
`M(L)` is only checked when the end pair is applied, since it is meant to be
non-zero otherwise.

`analyse()` now also reports `starved` — the 1-based layers carrying load with
no thickness — so the screening check and the banner name the layer instead of
saying "the diagrams do not close", which would not tell anyone what to fix.
The banner was branched at the same time: it previously recited the ΣP message
unconditionally and read "Plate loads sum to 0.0 lbf, not zero" on this stack.
`_solve` now passes a starved plate's load through so both models see the same
loads and fail together.

### Replaced the refined solve's trustworthiness check

`np.linalg.cond` was measuring the wrong thing. Swept:

| varied | condition number |
|---|---|
| `E_plate` 0.001 → 1000 Msi (10⁶×) | 1.081e13 — **does not move at all** |
| mesh 100 → 1600 el/in | 2.3e12 → 5.5e15 |
| bolt dia 0.1 → 1.0 in | 5.5e10 → 5.5e14 |

It tracked the beam stiffness matrix's intrinsic conditioning (`EI/Le³` against
the unit-diagonal pinned rows), not solution quality — so it called an ordinary
**1 in bolt at the default mesh** untrustworthy, and flipped to untrustworthy
whenever the mesh was **refined**, while the answers agreed to six figures. It
also advised "reduce the mesh", a control the UI does not expose.

Replaced with two direct measures, both thresholded from measured behaviour:

- `residual` — relative residual of the linear solve. Observed 1.6e-10 to
  3.8e-6 (growing with mesh through float64 accumulation); a failed solve is
  O(1). `RESIDUAL_WARN = 1e-4`.
- `load_error` — how far the strip discretisation lands from each plate's
  entered load **before** the strips are normalised onto it. This is the
  meaningful one: the normalisation forces the right total onto whatever shape
  came out, so a check after it would always pass. Measured to scale as
  1/strips², i.e. midpoint-quadrature error, and to grow with β·t as the
  distribution gets peakier. Observed 3e-8 to 4e-3; 3e-4 on the default.
  `LOAD_ERROR_WARN = 1e-2`.

Dropping the `cond` call also removed an SVD on the largest matrix in the
solve: `tests/bolt_bending/` went from ~8s to ~3.4s.

### Shear basis now follows what Fsu actually is

**Results-changing for non-fastener bolt materials.**

`f_s = V/A` is the **average** shear. That is the correct basis against an
MMPDS-01 Table 8.1.4 fastener allowable, which is tabulated as ultimate load
over the shank area. It is **not** correct against a *material* shear strength:
on a solid round the parabolic distribution peaks at 4/3 of the average.

The bolt material dropdown offers structural stock (4340 HT180, etc.) alongside
fastener grades, so the wrong basis was reachable and worth 33%. On a
short-grip case where shear governs, MS_shear +2.70 → +1.78.

`Allowables.shear_peak_factor` (default 1.0 — the fastener case, which is what
this tool is for) scales the average, and is applied to the interaction scan as
well as the standalone check so the two cannot disagree about a station. The
app sets it from the selected material's `category`, warns in the sidebar,
renames the results cell from "Average shear" to "Peak shear", and states the
factor and its reason on the Strength card. Method §8 was rewritten — it
previously told the reader to apply the factor themselves.

### Corrected: what physically reacts the residual moment

**Text only — no number changes.** The model, the kernel and every result are
unchanged; this corrects a description that was wrong.

The tool closes `M_res` with an equal and opposite pair at `x = 0` and `x = L`,
and the kernel docstring, Method §3, the screening-check line and the imbalance
banner all described this as the **head and nut bearing** the load. They cannot.
A bolt head's underside bears **axially** on the plate face; there is no surface
for it to push against laterally.

What actually reacts the residual moment in a preloaded joint is the
**redistribution of clamp pressure across the head and nut undersides**: as the
bolt tries to tilt, the annular contact pressure shifts toward one edge. That
shift is a moment, and it requires **no change in bolt tension** while the
annulus stays in contact — for a 3/8 hex head, roughly `0.10·P_clamp` lb·in of
capacity before the light-side edge lifts. Past that the contact collapses to
one side and the bolt does pick up axial tension. That is prying, and it is not
modelled.

The `R_0`/`R_L` pair is therefore a **statically equivalent bookkeeping device**
for delivering a couple of magnitude `M_res`, not a claim about a contact. That
distinction has consequences: a force pair and an end moment are equivalent
globally but not locally — the pair injects shear at the ends (`V(0) = R_0 ≠ 0`)
where an end moment would not. On the §6 verification case:

| closure of the same `M_res` | `V(0)` | `M(0)` | peak &#124;M&#124; |
|---|---|---|---|
| none (raw) | 0 | 0 | 310.0 — does not close |
| **force pair at head and nut** (this model) | −56.6 | 0 | **278.7** |
| end moment at the head alone | 0 | −60.0 | 250.0 |
| end moments split head and nut | 0 | −30.0 | 280.0 |

About a **12% spread** on the governing number, with this model near the top of
it. Deliberately **not** exposed as a setting: the analyst's lever is the loads,
not the closure idealisation, and the conservative choice is already in force.
Recorded here so the assumption is visible rather than implied.

It changes nothing about bearing. The `P_i` are inputs, so `P_i/(d·t_i)` is
untouched by the closure choice; the refined pass preserves the entered split
to 1e-13 lbf.

### Corrected: the figure labelled a force pair in moment units

`R₀` and `Rₗ` are **forces** (lbf). Their **moment** — `R·L` — is what closes
the residual. The caption added with the dashed arrows said the pair "are one
statically equivalent couple of 60 lb·in", which conflates a pair of forces
with its moment and left the same object carrying two different units next to
a straight arrow.

Rewritten to state both quantities and the relation between them: equal and
opposite forces of N lbf, L apart, adding no net force, whose moment R·L is
what closes the diagram. `R·L` is given **symbolically**, because the displayed
reaction is now rounded to whole lbf and spelling the product out numerically
would not visibly come to the stated moment.

Reaction and couple annotations are rounded to whole units (`whole()`, falling
back to `sig()` below 1.0 so a small residual cannot print as a bare "0").
Decimals on a ~57 lbf idealisation imply precision it does not have — the
choice of closure form is itself worth ~12% on the peak moment.

The caption block also **overran the viewBox and was silently clipped** at the
right edge once it grew. It is now broken into hand-measured lines under ~125
characters (the drawable width is ~750 user units, about 135 characters at
font-size 11) and the height allows for three. There is no wrapping in SVG
text: an over-long line just disappears past the edge.

### Method section audited against the implementation

Every claim in the Method section was checked against the code it documents.
Five had gone stale — the section had been describing a tool that no longer
existed. All are corrected; the equations that were right are unchanged.

| § | claim | status |
|---|---|---|
| lead | "does no iteration and **calls no solver**" | **false with the refinement on** — it assembles and solves a linear system |
| 1–2 | bearing is uniform over each plate's thickness | true of the baseline only; silent about the refined option |
| 4 | closure gate is `\|ΣP\| > 0.005·max\|Pᵢ\|` | superseded — the gate also tests `V(L)` and `M(L)` |
| 9 | `R_s = V·FF/(A·Fsu)` | missing the shear basis factor κ |
| 11 | "**No bearing peaking**" | flatly denied a feature the tool ships |

Sections 3, 5, 6, 7, 8 and 10 were verified correct and left alone: the
integration recursion, the `u* = −V₀/w` peak location, `Z = πd³/32`,
`A = πd²/4`, the `Fb = k·Ftu` modulus of rupture, and the worked example's
station table all match the kernel as built.

`method_html()` now takes the active bearing model, because the lead paragraph
cannot be true in both states. With the refinement on it says which sections
are still calculator-reproducible (§3 onward) and which are not (§1–2), and
that the uniform baseline is still computed as the comparison. §4 now documents
the three-part closure gate and *why* the moment tolerance is scaled by the
grip. §11 describes bearing peaking as available-but-off rather than absent,
and keeps the distinction from the ESDU 91008 and Melcon & Hoblit treatments,
which the elastic model still does not implement.

A Method section that describes a superseded gate is worse than no Method
section: it tells the reader the tool checks something it does not. Four tests
now pin these against regression.

### The stack editor moved to the sidebar

Rebuilt from `st.data_editor` to native `st.number_input` widgets, one block per
layer, and moved into the sidebar. The editor is a set-up input — typed once,
then left alone while the diagrams are read — so the main column now gives the
figure the full page width.

The widget change is the point, not the move: a data-editor NumberColumn has
**no stepper buttons and no scroll-wheel nudge**; a native number input has
both. Two number inputs to a row is the limit — Streamlit drops the steppers
when a column gets narrow, and three-to-a-row was under that threshold while
still passing every test. The sidebar is widened to 30rem for the same reason.

**A gap now has no load field at all** — not disabled, not zeroed, not a
placeholder holding an empty column. A spacer carries no bearing, so a load box
beside it invites a number the model silently discards.

Row widget keys are built from a stable row id rather than the list position,
so deleting a row cannot replay the row below it into the gap. Stack state is
shape-checked rather than presence-checked, so a browser still holding the
previous DataFrame format is reseeded instead of crashing on the first rerun
after a deploy.

### Bearing model moved to the top of the sidebar

It is the first decision: it changes the peak moment by ~15% and it changes
what the stack editor below asks for, since the per-plate material selector
only appears when it is on. It now sits above the thing it reconfigures.

Rendering the toggle before the stack also removed a wart — the editor used to
read the flag out of session state ahead of the widget, because the widget sat
further down the sidebar. It now takes the toggle's return value directly.

### Joint elevation: whole layers, with the unloaded side doing the talking

Each layer was drawn only on the side it bears from, so the stack read as a set
of half-plates rather than a joint. Every layer is now drawn to its **full
width**, both sides of the bolt, with the two sides separated by weight instead
of by presence:

- **Bearing side** — solid, and it keeps the bearing block and its arrows.
- **Unloaded side** — pale (38% fill), and it now carries the **load-direction
  arrow** and the **labels**, which previously competed with the bearing
  graphics for the same space.

The direction arrow shows the external load on that layer. It acts in the same
sense as the layer's bearing arrows, so it always points outward from the bolt
on the pale side — which makes the sign convention readable straight off the
picture rather than from the caption.

The label now carries the **entered load** rather than the intensity `P/t`. The
intensity is already shown graphically by the block's width, whereas the total
is what was typed, so the figure doubles as a check on data entry — the reason
the stack editor moved to the sidebar in the first place.

Spacers are drawn full width too, so they read as the same kind of object as a
plate, but with **wider, lighter hatching**: at the old density a full-width
hatch was the heaviest thing in the stack, which reads as importance when a
spacer is the one layer that carries nothing. Its label sits inside the band on
a backing rect — just outside would land on the shear panel.

No geometry change: the one-sided plates already reached the full `PL` on
whichever side they occupied, so drawing both sides fits the existing envelope.

### The figure no longer draws the end pair as sideways bearing

Text-only in effect, but it closes the gap left by the wording correction
below: every prose description of `R_0`/`R_L` was fixed, and **the drawing was
left asserting the thing the prose now denies** — two solid arrows shoving
horizontally on the head and nut.

The arrows still point laterally, because that is genuinely what the model
applies (it is why `V(0) = R_0 ≠ 0` in the shear panel). What changed is that
they no longer read as contact forces:

- the shafts are **dashed**, marking them as a statically equivalent
  idealisation rather than a bearing reaction;
- they are labelled `R₀` and `Rₗ` rather than a bare force value;
- a second caption line under the figure states that the pair is **one couple**
  of `M_res` lb·in, not sideways bearing on the head, and points at Method §3.

The caption is suppressed on a stack that closes on its own, where annotating a
zero couple would be noise. Figure height went 552 → 572 px for the extra line.

### Verification

`tests/bolt_bending/` — 119 tests, green (53 → 119). Full suite green (1052).

Every results-changing item above is pinned by a test named for the defect
it prevents, so the reason each gate exists survives in the suite rather
than only here.

---

## v2.3.0 — Bolt Bending module (2026-09-03)

**New module, no change to existing results.** `apps/bolt_bending/` +
`library/bolt_bending/` + `pages/4_Bolt_Bending.py`. Shear and moment diagrams
along a bolt in a multi-layer joint, with bending, shear, and combined margins.

Ported from a standalone single-file browser tool. The original and its
specification are archived, unmodified, under `docs/bolt_bending/`
(`index.html`, `HANDOFF.md`) as the reference implementation the port was
checked against. The port's own conventions and backlog live in
`apps/bolt_bending/CLAUDE.md`.

### Method

The bolt is a beam on axis `x` from head face (0) to nut face (`L`). Each
plate bears **uniformly over its own thickness** — conservative, since real
bearing peaks toward the shear planes and shortens the arm. Gaps and spacers
carry no bearing and pass shear straight through, which is why a spacer adds
moment arm at no benefit.

```
w_i   = P_i / t_i                          bearing intensity, lbf/in
M_res = Σ P_i · x̄_i,  x̄_i = x0_i + t_i/2   residual moment about the head
R_L   = −M_res / L,   R_0 = −R_L           head/nut couple, adds no net force
V(u)  = V_0 + w·u,    M(u) = M_0 + V_0·u + ½·w·u²      u = x − x0
```

Interior peaks at `u* = −V_0/w` where `0 < u* < segment length`; a quadratic
has no other stationary points, so evaluating `M` there, at every boundary,
and at both ends finds the true peak.

```
f_b  = M_max/Z,  f_s = V_max/A,  F_b = k·F_tu     (k = 1.5 working, 1.7 plastic)
MS_b = F_b/(f_b·FF) − 1        MS_s = F_su/(f_s·FF) − 1
MS_c = 1/√( max over stations [ R_b² + R_s² ] ) − 1
```

**The combined check is scanned station by station, not evaluated by pairing
`M_max` with `V_max`.** Those maxima sit at different places; pairing them is
both wrong and needlessly harsh. Asserted in
`tests/bolt_bending/test_kernel.py::test_combined_scans_stations_rather_than_pairing_maxima`.

### Handoff defect §4.1 — FIXED: force closure now gates the margins

`R_0 = −R_L` adds no net force, so it restores equilibrium **only if `ΣP` is
already zero**. When `ΣP ≠ 0` the shear diagram does not return to zero at the
nut, `M(L) ≠ 0`, and every margin is meaningless — but the original tool still
rendered them as ordinary numbers an analyst could paste into a report.

`BoltAnalysis.balanced` now gates `Margins.valid`, and the page suppresses
every stress and margin behind a warning banner when it is False. The
tolerance is a **pure ratio**, `|ΣP| > 0.005·max|P_i|`, replacing the original
test that mixed an absolute 0.5 lbf floor with a scaled term and therefore
flipped its verdict when the whole problem was scaled
(`test_imbalance_tolerance_is_a_pure_ratio`).

### Handoff defect §4.2 — NOT fixed, deferred with a stated assumption

`Z` is constant along the bolt, so the critical station is selected by
`max|M|` rather than `max|M/Z|`. With a shank-to-thread transition or an
undercut **inside the bending region**, this can check the wrong station and
report a **non-conservative** margin — and on a long grip with a spacer the
peak moment often lands near the thread runout.

> **⚠️ ASSUMPTION — no threads in the bending region.** Deferred at the
> owner's request (2026-09-03). Stated in the kernel docstring, on the Margins
> tab, and in Method §7. The `d_section` input is the interim mitigation:
> entering the thread minor diameter is conservative everywhere, exact
> nowhere. Station-varying section is the top backlog item.

### Materials — new `Fastener` category (6 entries)

Alloy Steel Bolt 160/180 ksi, A286 CRES 160 ksi, H-11 260 ksi, Ti-6Al-4V
160 ksi, Inconel 718 180 ksi. `Ftu` is the definitional strength level of the
grade; `Fsu` is the corresponding tabulated fastener shear allowable.

`Fty` is **⚠️ ESTIMATED** on every entry — MMPDS fastener tables do not
tabulate yield for fasteners at all. `Fcy`, `Fbru` and `Fbry` are deliberately
left `None`: bearing is a check on the **plate**, not on the fastener.

⚠️ **VERIFY** — these are grade-level nominals for preliminary sizing. A
released stress report needs the actual part number and diameter from MMPDS-01
Table 8.1.4 or the procurement spec; allowables vary with diameter, thread
form, and whether threads lie in the shear plane.

`CATEGORY_ORDER` was added to `library/materials/materials.py` as the single
source of truth for grouped-UI display order. `names_grouped()` and the
Material Library page now iterate it instead of each repeating a hardcoded
4-category tuple — which is why the new category appears in both without
further edits, and why a future one cannot silently vanish.

### Presentation — the original layout, not the toolkit's default furniture

The first cut of this port used the toolkit's stock page furniture: three tabs
(Joint / Margins / Method), `ui.components` cards, and Streamlit's default
spacing. It was **worse than the single-file tool it replaced**, and was
rebuilt the same day. Recorded because the failure is a general one.

The margins ended up behind a tab, which destroyed the feedback loop that
justifies the tool — you change a load and watch the moment peak and the
margin move together. The toolkit's conventions exist to make *unrelated*
modules feel consistent; they are not a reason to discard a better design that
already exists. `beam_section` has tabs because it has seven screens of
content; this module has one.

The page now reproduces the original's composition — one page, two columns,
white cards on the warm ground, the six-cell results grid, and the two-column
Method section with tinted equation blocks — with colours remapped to `THEME`
and a new `BOLT_PALETTE`. `apps/bolt_bending/styles.py` holds that stylesheet;
`test_nothing_is_hidden_behind_a_tab` pins the single-page rule.

Two rendering traps found by screenshotting the running app, both invisible to
a green test suite:

- **`st.html()` silently strips `<svg>`.** It sanitises with an HTML-only
  profile, so the figure column rendered blank with no error and nothing in
  the logs. Raw HTML in this toolkit must go through
  `st.markdown(..., unsafe_allow_html=True)`, which renders SVG correctly.
  (`st.iframe` is not an alternative — it takes a URL, not markup.) Pinned by
  `test_the_figure_actually_reaches_the_page`.
- **Axis tick labels overprinted.** Ticks sit at the two data extremes plus
  zero, but a diagram that barely crosses zero puts two of them on the same
  pixel — the default stack dips to M = −0.4 against a 278.7 peak, so its
  "−0.400" and "0" labels collided. Ticks are now placed extremes-first and
  zero is dropped when it would collide; the zero line itself is already drawn.

### Verification

`tests/bolt_bending/` — 53 tests, green. The handoff §6 case is asserted
**station by station** against its published table, and reproduces every
number: `M_res` = −60 lb·in, `R_L` = +56.60 lbf, peak `M` = 278.7 lb·in at
x = 0.546 in (`in plate 2`), `V_max` = −1056.6 lbf, `Z` = 0.003069 in³,
`f_b` = 90.8 ksi, `MS_b` = `MS_c` = +1.64.

The standing arithmetic check — **`V(L)` = `M(L)` = 0** for every balanced
stack — is asserted across four stacks, not just the golden one. The second
case §6 suggested (symmetric double shear, `M_res` = 0 by symmetry, closed
form `M_max = P(2·t_outer + t_inner)/8`) is asserted too. `AppTest` executes
`render()` headlessly, including every fastener material and the unbalanced
case.

### Not modelled (unchanged from the original, stated on the page)

Clamp-up, preload, prying, axial load, bearing peaking, plate strength. The
load split between layers is an **input, not a result** — it is statically
indeterminate and should come from relative plate stiffness or a bounding
sensitivity study. Plate bearing, shear-out, net section and lug strength are
separate checks; a bolt-bending tool that ignores them can hand back a
comfortable margin on the wrong failure mode.

---

## v2.2.1 — element-wise crippling (fixes unconservative section-average) (2026-07-17)

**Results-changing.** The `σ_c vs Fcc` crippling row is now **element-wise**:
each thin plate element's own peak compressive normal stress (axial + bending)
is checked against **that element's own** crippling stress `Fcc_i`, and the
worst element by ratio governs the row. This replaces the v2.2.0 form, which
compared the section's peak compression against the **area-weighted** section
`Fcc` (`fcc_element`).

**Why (the defect).** The area-weighted average is only valid for *uniform*
(strut) compression, where post-buckling redistribution lets stocky elements
carry the load after slender ones buckle. Under **bending** it is
**unconservative**: a stocky interior element (e.g. a thick web) inflates the
average and masks a slender extreme-fiber flange that is actually past its own
crippling stress. Worked case that flipped sign — I-beam `[6, 6, 0.08, 0.5]`
(thin 0.08″ flange, thick 0.50″ web), 2024, `My = 60000 lb·in`:

| quantity | v2.2.0 (area-weighted) | v2.2.1 (element-wise) |
|---|---|---|
| allowable `Fcc` | 22.3 ksi (section avg) | **6.9 ksi** (flange element) |
| applied compression | 10.6 ksi | 10.6 ksi |
| **crippling MS** | **+0.40 (looks safe)** | **−0.57 (fails)** |

The reported flange was carrying the peak bending compression at ~1.5× its own
crippling stress, but the web-inflated average hid it. (Surfaced by an
independent margin-calculation review; confirmed numerically.)

**Mechanics.** Each catalog plate element now carries its two centroidal
midline endpoints (read from the section skeleton `geometry().nodes/segments`);
`worst_element_crippling()` evaluates the affine section normal-stress field
`σ(y,z) = σ_axial + (c_z·z + c_y·y)/1000` at those fibers, takes the most
compressive per element, and returns the worst element by `applied/Fcc_i`. The
field is exact for the bending + axial normal stress, so the check is
solver-agnostic (classical or FEM). The area-weighted `fcc_element` is
**retained** for the uniform-compression (strut) interpretation and the
Crippling-tab display; `crippling_limited` now keys off the **weakest** element
(`fcc_min < Fcy`), consistent with the row. The Crippling-tab verdict text and
per-element table were updated to match. No new user inputs; coefficients
unchanged (still ⚠️ VERIFY). `pytest` 201 passing.

---

## v2.2.0 — local crippling + Cozzone unlock (2026-07-17)

Adds local crippling (thin-element plate buckling) for thin-walled open sections
and wires it to the Cozzone plastic-bending credit (CLAUDE.md future-work 10c,
now implemented). New module `library/analysis/crippling.py`, new **Crippling**
tab, `tests/test_crippling.py` (+14). Crippling needs no member length or end
fixity — it is a section+material property.

**Two methods, side by side:**
- **Element method (Needham/Boeing, primary):** per plate element,
  `Fcc/Fcy = Ce·[(b/t)·√(Fcy/Ec)]^-0.75` capped at Fcy, `Ce = 0.30` (OEF) /
  `0.52` (NEF); section `Fcc = Σ(Fcc_i·A_i)/ΣA_i`. Each thin-walled open shape
  declares its plate elements from topology (no new user input).
- **Gerard g-method (cross-check, display-only):**
  `Fcc/Fcy = 0.56·[(g·t²/A)·√(Ec/Fcy)]^0.85` capped at 0.80·Fcy.

Coefficients are documented **defaults flagged ⚠️ VERIFY** (Bruhn C7 / Niu);
crippling carries ~±15% scatter vs test and cannot be FEM-cross-checked (the
solver is linear-elastic and does no buckling analysis). The gate uses the
**element method**, not Gerard — Gerard's 0.80·Fcy plateau can never reach Fcy,
so `min(element, Gerard)` would make the credit impossible to ever unlock.

**Results impact (two effects):**
1. **Crippling is a standalone stability check on TOTAL compression** —
   `σ_c vs Fcc`, its own margin row for thin-walled open sections. The applied
   stress is the peak total compressive **normal** stress `|min(σ_total)| =
   axial + bending`, NOT the bending part alone: crippling is driven by the
   whole compressive stress, so pure axial compression (a compression member)
   and combined axial+bending both count. Using bending-only would read `+∞` for
   a strut and miss it entirely. `Fcc` is the element-method section crippling
   stress (`min(Fcy, Fcc)`); for typical thin sections `Fcc ≈ 0.4–0.5·Fcy`, so
   a crippling-critical member is governed here. This is a *stability* check,
   kept OUT of the `(Ra+Rb)+Rs²` strength interaction (which would double-count
   and mishandle the axial term). The strength interaction's compression bending
   uses `Fcy`, not `Fcc`.

   **Bending tension is its own explicit row** `σ_bend,t vs Fbu` (Cozzone
   modulus of rupture, the one bending-specific allowable — the plastic-rupture
   credit lives on the tension fiber). There is deliberately no symmetric
   `σ_bend,c` strength row: the compression side's special concern is crippling
   (the `σ_c vs Fcc` row), and compression *strength* is covered by
   `|σ₂| vs Fcy` and the interaction. The interaction `Rb` still takes the worse
   of the tension-fiber (÷Fbu) and compression-fiber (÷Fcy) ratios.

   Net effect: pure/asymmetric compression is now caught by the crippling row;
   axial tension that *relieves* bending compression correctly de-rates it (the
   default channel's crippling applied drops to ~3.8 ksi and the section is
   governed by the strength interaction at MS ≈ +0.25, not the earlier −0.02
   from the interim bending-only-in-interaction form).
2. **The D5 tension-side Cozzone gate is REMOVED.** `effective_f_cozzone`'s
   blanket `f = 1.0` for thin-walled open sections was a *proxy* for "we don't
   check crippling." Now that crippling is checked directly and load-dependently
   on the compression fiber (effect 1), the gate is redundant and needlessly
   load-independent (it locked on the weakest element even when that element is
   in tension), so it is dropped: `effective_f_cozzone == f_cozzone` for every
   shape, and the tension bending fiber keeps its plastic factor. A crippling-
   sensitive section is governed by its `σ_bend,c vs Fcc` row instead — the
   governing margin is identical to what the gate would give (compression is
   lower), while the tension row now honestly shows `f·Ftu`. Residual: in an
   unusual asymmetric case (tension extreme fiber + a slender compression
   element at low stress near the neutral axis) the small tension `f` (≈1.05–
   1.30) is granted where the strict plastic-moment argument is weak; bounded by
   the compression row and `f`'s small size. The Crippling tab reframes from
   "credit locked/unlocked" to "crippling-limited" (Fcc < Fcy) or not.

---

## v2.1.0 — sign-aware bending allowable (2026-07-16)

Fixes a mismatched allowable on compression-governed bending. `Fbu = f·Ftu`
is the **Cozzone tension-fiber modulus of rupture** — the shape factor `f`
credits the extreme *tension* fiber redistributing plastically toward Ftu. It
has no meaning for a compression fiber, which is governed by compression yield
(or, in thin sections, local buckling/crippling).

Previously the combined-interaction `Rb` term used `|σ_bend|_max / Fbu`
regardless of the governing fiber's sign, and the Results "σ_bend" card always
paired against Fbu. When the compression fiber governed by magnitude (asymmetric
sections — T, L — or a large compressive P), this normalized a *compressive*
stress by a *tension* allowable → **unconservative** (for 6061, Fcy 35 < Ftu 42,
so `Rb` was ~20% low) and visually a category error.

Now the bending allowable is **sign-aware**:

- governing bending fiber in **tension** → `Fbu = f·Ftu` (plastic-bending credit);
- governing bending fiber in **compression** → `Fcy` (compression yield, no
  rupture credit) — consistent with the tool already zeroing the Cozzone credit
  where it is unsubstantiated.

Applied to both the interaction `Rb` term (`calc_margin_table`) and the Results
governing-stress card, and reflected in the interaction row's Allow label
(`Fbu=…` vs `Fcy=…`). The compression fiber was *already* independently checked
by `|σ₂| vs Fcy` and `σ_vm vs Fty`, so this tightens the combined check and the
display without opening any previously-covered gap. Locked by
`test_bending_allowable_is_sign_aware`.

---

## v2.1.0 — corner fillets (2026-07-16)

Adds an optional **re-entrant corner fillet** to the FEM geometry, so the
sharp-corner torsion singularity above becomes a finite, converged value.

- **Scope — Option A (FEM geometry only).** A `FilletedSection` wrapper
  (`library/shapes/filleted.py`) rounds the section's `outer`/`voids` loops at
  a single user radius and hands the rounded polygon to the FEM solver, while
  delegating **every closed-form property and the midline skeleton to the
  sharp base**. The classical midline / VQ-It results are therefore **byte-
  identical** with fillets on or off (locked by
  `test_classical_stress_is_invariant_to_fillets`); only the FEM stress field,
  mesh, and FEM properties see the rounded corners.
- **Re-entrant only.** Detection is orientation-based: with material on the
  left of every loop (CCW outer / CW voids), a right turn (signed cross < 0)
  that also deflects ≥ 30° is a re-entrant corner — valid at any corner angle,
  not just 90°, and it rejects the tiny reflex vertices of a faceted curve
  (a tube's inner circle reports zero). Convex/exterior corners are never
  rounded. Works for catalog shapes **and** sharp-cornered custom imports.
- **Exact geometry.** A 90° fillet of radius r adds exactly r²(1−π/4) of
  material per corner; the arc is tangent to both edges at setback
  t = r·tan(δ/2) with its centre on the notch side.
- **Fit / skip policy.** If the radius is too large to fit on a corner's
  adjacent edges (including a neighbouring fillet's setback), that corner is
  **left sharp and reported** — the output polygon is never self-intersecting.
  (Channel example: both corners share the 5.25 in web face, so r ≳ 2.62 in
  leaves them sharp.)
- **Mesh density.** Arc tessellation scales with the FEM mesh preset —
  **3 / 6 / 9 points per 90°** for Standard / Fine / Very fine. The dense
  fillet boundary makes Triangle refine locally and coarsen away from the
  corner, giving local refinement without globally shrinking the element size.
- **UI.** A sidebar "Apply corner fillets" toggle + radius input appears
  whenever the section has ≥1 interior corner; it reports how many corners
  were rounded vs left sharp, and the FEM corner-singularity warning flips to
  a converged-value note. The section diagram and FEM contour both draw the
  rounded corners; the Validation cross-check still uses the nominal sharp
  shape.

---

## v2.0.0 — release candidate (2026-07-16)

Completes the Phases 0–7 overhaul: dual solver (classical midline + FEM),
custom polygon/DXF import, unsymmetric-bending tensor, Bruhn shear flow, the
§3.6 margin set with the `(Ra+Rb)+Rs²=1` interaction curve, a tabbed UI with
an interactive FEM stress contour and correct shear field, cache + fragment
performance, an in-app validation page, and version stamping. 150 tests green.
Remaining before tagging: a manual Streamlit Cloud / mobile pass.

## Phase 7 — Validation page, docs, release

### 7.3 — Docs reconciled to v2

Documentation only. `CLAUDE.md` gained a v2 status banner (points to CHANGELOG
+ the now-historical handoff as authoritative) and its stale sections were
corrected: shape count 13→11, "dark mode only" → unified light theme, the
methodology block (normal-stress tensor, Bruhn shear, the removed RSS shear
combination, the §3.6 margin set + `(Ra+Rb)+Rs²=1` interaction, unsymmetric
bending replacing the geometric-axis assumption), and the Known-issues table
(resolved items called out; warping-stress, solid/tube per-point shear, and
FEM corner singularity remain). `README.md`: 13→11 shapes, dual-solver +
import description, `library/analysis/` added to the tree.

### 7.1 — In-app Validation page (§7.4)

The Validation tab now has two parts:

- **Current section** — FEM vs analytic closed form for A, Iy, Iz, J (as
  before), with tolerance-colored %Δ.
- **Full-catalog cross-check** — an on-demand, cached sweep over every catalog
  shape comparing the classical closed form against the FEM geometric solve
  for A, Iy, Iz, plus a **textbook anchor** table (rectangle b·h³/12, circle
  π d⁴/64) showing reference vs classical vs FEM. Colored by tolerance
  (green < 1%, amber < 3%, red ≥ 3%). Measured worst disagreement across the
  catalog: **0.04%**.

Single source of truth: `tests/golden_values.py` gained `VALIDATION_SWEEP`
(the shape list) and `anchor_goldens()`; the page and the new
`tests/test_phase7.py` consume the SAME shared helpers
(`calculations.validate_catalog_properties` / `validate_anchor_goldens`), so a
regression in either the closed forms or the FEM solve fails CI, not just the
page. New `fem_solver.fem_geometric_properties` runs a geometric-only solve
(no warping) so the 11-shape sweep completes in ~1.3 s instead of paying the
warping cost 11×.

## Phase 6 — UX / plotting overhaul

### 6D — Contour overlays + annotated geometry (§6.3)

Presentation only. Two additions:

- **Contour overlays** (new toggles in the Results contour): **principal axes**
  (two perpendicular cyan dash-dot lines through the centroid at the section's
  principal-inertia angle — coincide with Y/Z for symmetric shapes, rotated
  for L/Z) and **load-direction arrows** (red Vy/Vz vectors from the
  shear-application point + a ↺/↻ torsion spin glyph for the sign of T). New
  pure helper `principal_axis_angle_deg(section)` (Mohr's circle,
  2θ = atan2(2·Iyz, Iy−Iz); 0 when Iyz≈0). Both default off to avoid clutter.
- **Dimension leaders on the section diagram** (Geometry tab, toggle "Dimension
  leaders", default on): a new `Section.dimension_annotations()` returns
  `(p1, p2, label)` leader specs; the base implementation draws the overall
  bounding-box width and height for every shape, so the user can confirm the
  size before trusting results. Drawn as double-headed dimension lines by
  `draw_section`.

Note: the base dimension leaders show overall W×H only. Per-member callouts
(tf, tw, individual flange/web dims) are a future refinement — see CLAUDE.md
Planned future work item 10b.

### 6E — Results tables → st.dataframe + export (§6.3)

Presentation only. The two custom-HTML tables became sortable `st.dataframe`s
with pandas Styler styling and report export:

- **Stress results** (per KP): governing cell per column (max |value|) keeps
  the amber highlight via a Styler `.apply`; fixed 2-decimal formatting;
  `column_config` widths for KP/Description; the old redundant "↑ max |val|"
  summary row was dropped (the governing banner now carries that).
- **Margins**: the MS column is colored by `ui.theme.ms_status` (red < 0,
  amber < 0.25, green ≥ 0.25 — same thresholds as the banner) instead of a
  plain gradient, so it reads as pass/marginal/fail; "+HIGH" for MS > 10.
- **Export** (`ui.components.table_export_controls`): a CSV download button +
  a "Copy as Markdown" expander for each table, using a dependency-free
  `df_to_markdown` (no `tabulate`), exporting the display-formatted values so
  the copy matches the screen. For pasting into stress reports.

### 6C.2 — Clarify: the contour is always an FEM field

No results change; labeling only. The interactive contour (and the report
figure) are computed from the FEM field **regardless of the solver dropdown**,
because the classical/exact solvers produce values only at key points and
along the wall midline — there is no continuous 2-D classical field to color.
This was unlabeled, so a "Classical"/"Exact" run showed an FEM-meshed contour
that looked inconsistent with the "exact" solver label.

Added an `st.info` above the contour when the selected solver ≠ FEM: states
the contour is an FEM visualization only, that the table and margins use the
selected solver (no finite elements), and that the two agree away from sharp
corners. The results table, margins, and governing banner are unchanged and
remain fully closed-form / Bruhn-midline for the classical solvers.

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
