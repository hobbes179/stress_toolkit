# CLAUDE.md — tierod module

Tie-rod layout analysis and optimization: rigid bodies on two-force members with
spherical bearings both ends. Finds attachment geometry minimizing governing load ratio
across a 26-case load-factor sweep; detects and visualizes mechanisms.

Full spec: `FABLE_BUILD_PROMPT.md`. Session plan: `IMPLEMENTATION_PLAN.md`. Follow the
session boundaries in the plan — do not build ahead.

## Architecture

- `library/tierod/` — analysis kernel. **NEVER imports Streamlit.** Pure
  numpy/scipy/dataclasses, fully pytest-able.
- `apps/tierod/` — Streamlit UI only. All math lives in library.
- `tests/tierod/` — gate tests V1–V17 mapped in the plan. Tests are written BEFORE the
  code they gate.

## Non-negotiable conventions

- Units: IPS (lb, in, psi) everywhere. No unit systems, no conversions in the kernel.
- Rod sign: `P > 0 is TENSION`. `û` points end-a → end-b.
- Kernel equations (do not re-derive, do not flip signs):
  `δ = -Ĝᵀ U`, `K = Ĝ K_d Ĝᵀ`, `K U = F`, `P = -K_d Ĝᵀ U`, equilibrium `Ĝ P = -F`.
  Ĝ column: `+[û; a×û]` in body-p block, `-[û; b×û]` in body-q block, ground = no block.
- Per-body datums; rotations about each body's own datum. Free bodies only in U.
- Ground is a FLAG on Body, never a subclass. Zero ground bodies = valid free-free mode
  (expect nullity 6, not an error). Multiple grounds valid.
- Regions are body-local, store a full frame triad. Axis dropdowns POPULATE the triad;
  nothing downstream branches on the dropdown value.
- Rods carry axial load only (spherical bearings both ends). `end_fixity = 1.0` default.
  There is NO mount-axis or misalignment-cone constraint on regions — that was removed
  deliberately; do not reintroduce it. Non-penetration comes from Body.clearance
  half-space tests instead.
- Conditioning/rank: ALWAYS non-dimensionalize K with characteristic length before SVD.
  Raw-K condition numbers are meaningless (mixed units).
- Optimization (Phase 2+): constraints are two one-sided inequalities per rod-case,
  NEVER `max(tension, compression)` — the kink stalls gradient methods. Numerical
  gradients first; analytic only if profiling demands.

## Load case convention

**Every case has the same magnitude. The sweep varies DIRECTION only.** Magnitude lives
on the body as a scalar `Body.g_factor`; the case carries a unit direction `n̂` and a
`factor`. One direction is shared by all bodies.

`W_p = m_p G_p [I₃; [c_p]×]`; `T = G W`; per-case loads `T n̂`.

Default set `cube26`: the 6 face + 12 edge + 8 corner normals of a cube, **normalized**.
Sets live in the `DIRECTION_SETS` registry; `cases_from_directions()` takes any custom
sweep. Nothing downstream may branch on which set is in use — the kernel sees only a
`(3, n_cases)` matrix of unit columns.

**The exact envelope is closed form and IS the reportable value:**
`max|P_i| = ‖t_i‖₂` at `n̂*_i = t_i/‖t_i‖₂`. The enumerated set is a *sample* — it can
only under-predict, never exceed. Report `‖t_i‖₂`, label it with `nearest_case(n̂*_i)`
and the angle so the sampling shortfall is visible. Do NOT report the enumerated max as
the envelope.

> **Withdrawn 2026-08-21.** An earlier draft used a *box* convention: `g_factors` as a
> 3-vector with sign-vector cases applying every active axis at full factor at once.
> That made corners 1.0–1.73× larger than the ellipsoid, which the owner judged to be
> double-dipping. The L1 corner identity (old V17) went with it — under unit directions
> the max over cases is **not** `‖t_i‖₁` and corners do **not** always govern.

## UI gotchas (cost real debugging time — do not relearn them)

- `uirevision` must be a constant in the Plotly layout or the camera resets every rerun.
- `scene.aspectmode = 'data'` or geometry renders distorted.
- Static traces (bodies, regions, CG) cached; only rod traces rebuilt per rerun.
- Ground toggle grays mass/cg inputs, never clears them.

## Locked decisions

- Streamlit + Plotly; no Excel; kernel importable standalone
- Topology (which region pair a rod spans) is user input, not optimized
- Damage/case factors: user-input `factor` field on the case record, never hardcoded
- Rod section fixed per rod in v1 (catalog snap is Phase 5)
- `k_backup` per rod end exists in the model from Session 1, unused until Phase 5
- `σ_floor`, `α` exposed as settings with defaults (`α = 0`)
- Sweep is translational; `Body.inertia` reserved, unused

## Status

- [x] Session 1 — scaffold, model, clearance, cases (V16, geometry tests) — 2026-08-21,
      102 tests green (`library/tierod/{__init__,model,clearance,cases}.py`,
      `tests/tierod/{conftest,test_geometry}.py`). Revised same day for the
      unit-direction load case convention.
- [x] Session 2 — kernel (V1–V6) — 2026-08-22, 149 tests green
      (`library/tierod/kernel.py`, `tests/tierod/test_kernel.py`)
- [x] Session 3 — mechanisms (V7, V8, V11, V12) — 2026-08-22, 184 tests green
      (`library/tierod/mechanisms.py`, `tests/tierod/test_mechanisms.py`).
      **End of kernel-side Phase 0.**
- [x] Session 4 — Phase 0 UI, mechanism animation — 2026-08-22, 226 tests green
      (`apps/tierod/{render,ui_inputs,ui_scene,examples}.py`,
      `pages/3_Tie_Rod_Layout.py`, Home.py card,
      `tests/tierod/test_{ui_scene,ui_inputs,app_smoke}.py`). **Phase 0 ships.**
- [x] Session 5 — allowables + sweep (V9, V15, V16, V17) — 2026-08-22, 343 tests green
      (`library/tierod/{allowables,sweep}.py`, `apps/tierod/ui_results.py`,
      rod editor + safety-factor cells in `ui_inputs`/`ui_results`, worst-direction
      cone in `ui_scene`, Results tab in `render.py`,
      `tests/tierod/test_{allowables,sweep,ui_results}.py`). **End of push 1.**

## What this tool is for (reframed 2026-08-22 by the owner — READ THIS FIRST)

> "I don't want to use this tool to figure out if all of the tie rods are going to
> have positive margins. The main goal is for somebody to say *here's what we're
> trying to hold down, here are some places where we have room to mount some rods.
> Where can we tie them together to make it work and meet fail-safe requirements?*"

**Margins are a feasibility GATE, not the output.** The output is a layout. This
overturns build-prompt **§8.1**, which made minimax load ratio the objective:

```
choose   N, which region pair each rod spans, positions, section per group
minimize (max lambda, total length, rod count)      lexicographic
s.t.     sigma_min(K~) >= sigma_floor      not a mechanism, with room
         rho_j^2 > 0 for every j            any one rod can be lost
         MS >= ms_required          intact
         MS >= ms_required_damaged  in every failure state
         q within declared regions, no penetration
```

**Slenderness, not length.** `lambda_crit` is a knee: below it a rod is on the
Johnson branch and barely buckling limited, above it the allowable dies as
`1/lambda^2`. `lambda` also makes "fatter section" and "shorter rod" the same
currency, which is what couples the rod pool to the geometry search.

**The short-rod cliff is real and must stay a hard constraint.** Measured on the
demo geometry, same rods, same declared regions, only the end positions moved:

| variant | length | max lambda | sigma_min | rank |
|---|---|---|---|---|
| as shipped (z 22 / 8) | 9.3–22.5 | 240 | 0.0964 | 12/12 |
| shortened (z 10 / 5) | 6.9–11.1 | 118 | 0.2007 | 12/12 — **dominates the shipped layout** |
| all short (z 5 / 4.5) | 5.6–6.0 | 64 | 0.0418 | 12/12 — fragile |
| all short, one height | 5.6 | 60 | 0.0000 | 6/12 — **mechanism** |

Shortening improves slenderness AND conditioning together, up to a cliff where
the moment arms vanish. A length-hungry search drives straight off it, so
`sigma_floor` is a constraint and not a diagnostic.

**The shipped demo is statically determinate** — 12 rods against 12 DOF, so
every rod is critical and it can never be fail-safe at any load or any section.
`6*n_free + 1 = 13` is the minimum that could be. Say this before anyone sizes
anything.

### Push 2 — user-built geometry, rod pool, identification

- [x] Session 6 — construction API + JSON persistence — 2026-08-22, 361 tests green
      (`library/tierod/serialize.py`; `ParamSpec`/`PARAMS`, `REGION_TYPES`,
      `CLEARANCE_TYPES`, `new_region`/`new_clearance`/`new_rod`, `Rod.group`,
      add/remove with cascade in `model.py`; `tests/tierod/test_construction.py`)
- [x] Session 7 — feasibility + scoring (`library/tierod/failsafe.py`,
      `tests/tierod/test_failsafe.py`) — 2026-08-22, 442 tests green.
      **Re-sequenced ahead of the UI when the owner reframed the tool** (above):
      the scoring layer is what a layout search plugs into, so it comes first.
- [x] Session 8 — layout search (`library/tierod/optimize.py`,
      `tests/tierod/test_optimize.py`) — 2026-08-22, 482 tests green.
      seed -> refine -> score -> rank, with the N-vs-lambda trade curve.
- [x] Session 9 — construction UI (`apps/tierod/ui_build.py`,
      `tests/tierod/test_ui_build.py`) — 2026-08-23, 767 tests green.
- [x] Session 10 — layout-search UI (`apps/tierod/ui_search.py`,
      `tests/tierod/test_ui_search.py`) — 2026-08-23, 824 tests green.
      The engine had existed since Session 8 with zero callers in `apps/`.
- [x] Session 10b — owner feedback: rod-count floor, "Most rods", live
      visualization — 2026-08-23, 824 tests green.
- [x] Session 10c — interference check + gate (`library/tierod/clash.py`,
      `tests/tierod/test_clash.py`), CG snap, demos rewritten
      (`apps/tierod/examples.py`, `tests/tierod/{test_examples,legacy_demo}.py`)
      — 2026-08-24, 933 tests green.

## Pre-commit cleanup (2026-08-23)

Bookkeeping only — no behaviour changed, 824 tests still green.

- Deleted `apps/tierod/model_draft.py` (374 lines, dead since Session 1) and
  reworded the `model.py` header that referenced it.
- `plan_counts` / `plan_size` added to the `library.tierod` package exports;
  they were public in `optimize.py` but not re-exported, so the package
  surface disagreed with the module's own `__all__`.
- `render.py`'s docstring and the page subtitle still said "Phase 0 — what
  this page does NOT do yet: allowables, margins, optimization". All three of
  those shipped in Sessions 5, 7 and 10. Replaced with the six-tab map and an
  honest list of what is still missing (rod pool, warping, rotational
  inertia, report export).
- The `Home.py` module card said "Phase 0: loads and mechanisms; allowables
  and margins are next". Rewritten to describe the tool as it is.

## Session 10b — owner feedback (2026-08-23)

Three changes after the owner used the search tab. 16 mutations, 2 initial
misses, both closed. 824 tests green.

- **The rod-count floor ignored the fail-safe toggle — a real defect the owner
  found.** `n_range_floor` called `min_rods_for_single_failure` (6·n_free + 1)
  unconditionally, so with fail-safe OFF the tool started one count too high
  and never offered the count that would have worked. It now takes the
  criteria and picks between the two bounds `failsafe.py` already had.
  **Option B was chosen deliberately over snapping the input**: the widget has
  a session key, so a recomputed default is ignored on later reruns anyway,
  and forcing it would discard a number the user typed on purpose.
  `floor_hint()` is advisory text — it names the bound, says which of the two
  it is quoting and why, and warns when the entry is below it. It never
  returns a value to write back, and a test pins that it returns a string.
- **"Counts to try" became "Most rods"** at the owner's suggestion. Two bounds
  read better than a bound plus a width, and `range(lo, hi + 1)` is what a
  user means by "13 to 17". Kept the module's noun (*rods*, not *links*) —
  `Rod`, `rod_ids` and "Fewest rods" all say rods already.
- **Live visualization while the search runs**, the owner's third ask: minutes
  of blocking work with a blank page is indistinguishable from a hang, and you
  could not see what was being made. `search()` gained an optional
  `on_candidate(candidate, done, total)` hook; the UI drives a progress bar
  from it and redraws the scene **only when the best improves** — a handful of
  redraws per run, not one per candidate. An exception from the callback is
  SWALLOWED: a run is minutes and losing it to a failed progress bar would be
  the wrong trade. A test seeds a raising callback and demands the result
  survives.
- **The Build tab now draws the model above the editors**, which was the other
  half of "too difficult to see what you're making" — before this the builder
  had no view at all and you had to change tabs to find out what your numbers
  made. `scene_caption` states the counts, because a region that was never
  created and a view that has not refreshed look identical.
- **`plan_counts` / `plan_size` moved into `optimize.py`** and the cost
  estimate now reads them instead of re-deriving the skip rule. The estimate
  going quietly stale when the search changed was a live risk; a test still
  compares the quote against a real run's `n_evaluated`.
- **Two mutation misses, both from loose assertions rather than missing code.**
  "The budget re-derives the plan" survived because nothing checked
  `Budget.counts` (only `n_candidates`); "the builder scene is not drawn"
  survived a `>= 2` chart count. Both now assert exact values, and the chart
  count carries a comment naming all three charts so the next person updates
  it on purpose.

## Session 10c — interference, CG snap, new demos (2026-08-23/24)

Four owner asks, in one round. 32 mutations seeded, 26 caught first pass, 6
missed — 5 real gaps closed, 1 documented equivalent mutant. 933 tests green.

### `library/tierod/clash.py` — the interference engine

- **Scope is rod↔body and rod↔rod. Rod↔region is deliberately NOT checked** —
  the owner's call. A region is a declared mounting *surface*, so a rod
  touching one is the normal case, not a fault.
- **Signed** distance, not distance. Measured on a cylinder r=3, the unsigned
  field reads 0.0 for a point on the surface, a point at the centre, a rod
  skimming the wall and a rod driven straight through it — four states, one
  number, useless for collision. `signed_clearance()` is positive outside and
  negative inside, so depth is a real quantity.
- **Sampled along the rod, with a Lipschitz correction.** An SDF is 1-Lipschitz,
  so the sampled minimum minus half the sample spacing is a genuine lower
  bound, not an estimate. That is what makes 33 samples defensible.
- **The margin applies only to pairs that are NOT attached.** Applying it
  everywhere made every rod appear to penetrate its own mounting face by
  exactly the margin, and took the shipped demo from clean to 12 interferences.
  A rod is allowed to touch the body it is bolted to; it is not allowed to
  touch anything else.
- **Two rods sharing a pin are not a clash.** A bipod or hexapod pair meeting
  at one fitting is normal hardware, and the first version condemned three
  shipped fixtures for it. `_trim_shared_ends` pulls co-mounted rods back from
  the shared pin by the clearance they need, and the step is **clamped to
  0.49·length** so a rod shorter than its required gap is not turned inside
  out. Five of the six surviving mutations were in these ~20 lines.
- **Performance was the constraint, not correctness.** The first version cost
  6.09 ms against `layout_metrics`' 0.51 ms — a 12× tax on the inner loop of a
  search that already runs for minutes. Profiling put 0.38 ms/call in a
  golden-section `distance_to_segment`; vectorized, the whole check is
  **0.68 ms**.

### The gate

- `Criteria.min_gap` (default 0.25 in) turns the check on; `None` turns it off.
  **`feasible` consults the criteria** — the first version gated on
  `metrics.interferes` alone, so switching the check off had no effect.
- The opposite error is the dangerous one, so it **raises**: criteria that
  demand a check, handed metrics computed without one, get a `ValueError`.
  Silence there hands back layouts with rods through tanks.
- `worst_clash` is three-valued — `None` (not checked), `0.0` (clear), `>0`
  (shortfall in inches) — and the UI says which. "Not checked" must never
  render as "clear".
- `check_failsafe` passes its own `criteria.min_gap` down to `layout_metrics`;
  it previously built metrics at a different gap from the criteria judging them.
- The surrogate gained a **linear** clearance penalty scaled by `min_gap`, so
  the refiner walks out of a clash instead of being told only that it is bad.

**Why this is a hard gate and not a report.** Measured on the old demo, 32
layouts, everything else identical:

| | best lambda | sum L | clash shortfall | time |
|---|---|---|---|---|
| clearance off | 107 (16 rods) | 109 | **0.625 in — unbuildable** | 211 s |
| clearance on | 239 (14 rods) | 250 | 0.000 | 467 s |

The unchecked search does not merely allow the clash — it *prefers* it. Routing
through a body is a shortcut, and shortcuts win on both length and slenderness.
It costs about 2× the runtime to not do that.

### CG snap

`Body.shell_centroid()` / `snap_cg_to_shell()`, with a checkbox in the body
editor that grays the cg inputs. `snap_cg_to_shell` returns True only if the cg
actually moved, so a caller can tell "snapped" from "already there".
`ClearancePrimitive.centroid()` needed a real per-type `_centroid_local` for
this — the base returns zeros, and **Cylinder overrides it**, because a
cylinder spanning z_min..z_max has its centre of volume at the midpoint, not at
the origin of its frame.

### Demos rewritten

The owner scrapped the old set. Three new ones, **every geometry probed
numerically before it was written down** — parameters swept, rank and
interference measured, winning values frozen:

- `payload_deck()` (default) — 3 bodies over a ground deck, 21 rods against 18
  DOF, rank 18/18, sigma_min 0.133, clash-free, fail-safe. Redundant by three
  on purpose: a bare 18-rod set is determinate and can never be fail-safe.
- `mechanism_turntable()` — 6 radial coplanar spokes, **rank 3 of 6**. Same rod
  count as a working hexapod, half the restraint.
- `clash_gantry()` — full rank, sound load path, 3 interferences. Every
  strength number reports happily and it is still unbuildable.

Two sweep findings are recorded inline in `examples.py` because they are easy
to re-introduce: a hexapod whose base twist equals its top twist collapses to
**rank 9 of 18**, and overlapping ground rings put rods from different clusters
through each other.

**`tests/tierod/legacy_demo.py`** is a frozen copy of the OLD demo geometry.
Scrapping the demos broke 69 tests that were keyed to region names like
`band_a`. The lesson is that **fixtures and demos have different jobs**: a demo
is a moving illustration of the current tool, a fixture is a fixed thing to
measure against, and 69 tests had been quietly relying on one to be the other.

### `.claude/settings.json`

Prefix allow-rules so a test run does not need a click. Two things to know: the
file is read at **session start**, so creating it mid-session does nothing; and
a rule matches a command *prefix*, so heredocs and `a && b` chains match
nothing and are each a unique string to approve. Write a script to a file, run
it with one plain command.

## Session 10 as-built notes

- **The search must never run on a rerun.** It is minutes; a stray run would
  present as a hang, not an error. It runs on a button, the `SearchResult` is
  parked in session state, and `test_the_page_does_not_run_a_search_on_load`
  pins it via a caption that is only reachable when nothing was searched.
- **The cost is estimated and shown BEFORE the button.** `budget()` reproduces
  `search`'s own skip rule (counts below `len(space.topologies)` are skipped)
  rather than guessing, and a test asserts `budget(...).n_candidates ==
  search(...).n_evaluated` on a real run — so a change to the search's seeding
  breaks the estimate loudly instead of silently under-quoting.
  `SECONDS_PER_CANDIDATE = 5.2` is measured on the DEMO geometry (50 layouts in
  258 s) and over-estimates small models; it warns, it never decides.
- **`geometry_fingerprint` covers bodies and regions but NOT rods.** The search
  replaces rods, so including them would make a result mark itself stale the
  instant it was adopted. Editing a region must invalidate it; adopting must
  not. Three mutations pin all three directions.
- **Adoption is destructive and ordered for atomicity.** Everything that can
  fail — the blocker checks and building the replacement rods — happens before
  the first deletion, because a model left with no rods by a half-finished
  install has no undo. `adoptable()` refuses a candidate whose regions were
  deleted, retyped, or shrunk since the search ran, and names which.
- **The dimension check has to be reachable on its own.** A retype from
  CircleArc(1) to PlanarPatch(2) is normally caught by whichever check fires
  first, and a `q` that happens to land inside the new bounds slips past the
  bounds check entirely. The mutation "adoption does not check the parameter
  count" was MISSED until a hand-built candidate with `q = 0.5` (inside the
  patch's [0, 1]) forced the ndim check to stand alone. The other 26 mutations
  were caught first time.
- **Rods are deep-copied on adoption.** Dragging a slider afterwards must not
  rewrite the search result the user is still comparing against.
- **The trade figure draws infeasible counts as red x markers on the axis**,
  with the reason on hover, instead of leaving a gap. A floor the topology
  imposes should be visible, not inferred.
- **`lambda_crit` travels with `max lambda` everywhere it is shown.** A
  slenderness with no knee beside it is not interpretable.
- The tab is worded to say what it is: a **stochastic local method** that finds
  a good layout, not a proof of the optimum.

## Session 9 as-built notes

- **Streamlit does not police stale widget state, and the docstring that said
  it did was wrong.** Measured on 1.57 rather than assumed: a slider bounded
  [0, 1] whose stored key holds 9.0 returns **9.0**, and a selectbox whose key
  names a deleted option silently reverts to the first. Neither raises. So the
  failure is not a traceback at the widget — it is a wrong number written into
  the model, and `Assembly.validate()` refusing the whole assembly on the NEXT
  rerun, naming a rod the user never touched, with Reset (i.e. losing their
  work) as the only way out. Two defences: `stale_keys` purges the transient
  keys on any structural edit, and `ui_inputs.apply_rod_q` now CLIPS into
  `region.bounds()` on the way in. A test pins the measured Streamlit
  behaviour, so if a future version starts clamping, the guard gets
  reconsidered instead of quietly becoming dead code.
- **One code path for all three kinds of region edit** — parameter, axis, type
  — through `replace_region`, because each of them can invalidate the
  attachments already on that region and there must be exactly one place where
  the repair can be forgotten. `ndim` changed -> reseed to the new midpoint;
  still in the same dimension but out of the new domain -> clip. Either way the
  affected `rod.end` is NAMED in the returned report and shown, since silently
  relocating an attachment is worse than the crash it prevents.
- **`axis=None` keeps the existing triad rather than re-deriving one from "Z".**
  A region loaded from JSON can sit on an arbitrary frame that no dropdown
  value describes; `axis_name` reports `custom` for it. This is the same blind
  spot that produced three Session-6 mutation misses (every shipped example is
  on the XY frame), so it is tested with a QR-generated triad.
- **Parameters carry across a retype BY NAME.** CircleArc -> Annulus keeps the
  theta range; `radius` has no counterpart in `r_inner`/`r_outer` and falls
  back to the new type's default rather than being guessed at.
- **`region_changed` exists so the builder does not rebuild on every rerun.**
  Without it a region would be replaced — and its slider keys purged — on every
  unrelated keystroke on the page, which makes the design sliders unusable. It
  compares in DISPLAY units, because `theta_max` is 2*pi stored and 360 shown
  and a raw comparison reads "changed" forever.
- **Units convention:** anything called `params` in a `ui_build` signature is in
  display units (degrees). One conversion site, `display_to_stored`, so the
  widget layer never touches it.
- **A rodless model is a legitimate mid-build state**, not an error. `render()`
  short-circuits the four analysis tabs with a pointer to the Build tab; a
  traceback there would take the builder tab down with it.
- **`PlanarPatch` is the wrong shape to test clipping with** — its `q` is
  normalized to [0, 1] regardless of width, so shrinking one can never strand
  an attachment. The fixture uses a `CircleArc` (theta range) and an `Annulus`
  (radii), which have dimensional bounds. Probed numerically before the test
  expectations were written, which is how this was caught.
- 25 mutations seeded across `ui_build`, `render` and `apply_rod_q`; all 25
  caught. The clipping guard came out of a genuinely vacuous test found while
  checking that the AppTest half was load-bearing.
- **Not in scope, deliberately:** renaming an existing body/region/rod. IDs are
  dict keys and cross-referenced from rod ends; identification is Session 11's
  job (tags, click-to-select), and names are settable at creation.

## Session 8 as-built notes

- **A symmetric seed with NO TWIST is a mechanism, at every rod count.** Both
  ends land at the same angle, every rod lies in a plane through the body axis,
  and nothing reacts rotation about it — `sigma_min` exactly 0. Half a turn
  (twist 0.5) is degenerate for the same reason. This made every symmetric seed
  useless until it was found, and it is why the family sweeps twist strictly
  inside (0, 0.5). Spread fraction 0.5 is the matching trap on the other knob:
  it collapses the alternation and puts every attachment at one height.
- **The penalty must be ADDITIVE, in units of `lambda_crit`.** The first
  version multiplied it by the slenderness: the objective came out ~1e3x larger
  than the quantity being optimized (f = 6.3e5, gradients 4e4) and L-BFGS-B
  stopped after ONE iteration having improved nothing. Additive keeps a
  constant violation a constant offset, so the gradient comes cleanly from
  lambda. After the fix, a stretched seed refines 287 -> 72.
- **A mechanism must NOT return `inf` from the surrogate** — an inf mid-line-
  search kills the optimizer. `sigma_min = 0` already saturates the
  conditioning penalty, so the continuous form covers it and stays
  differentiable on the way in.
- **The search is a stochastic local method and the tests must not pretend
  otherwise.** Switching the SVD driver (`compute_uv=False` -> `full_matrices=
  True`) perturbed values at 1e-15 and changed the L-BFGS-B trajectory enough to
  move the achieved max lambda from 70 to 230 at a small seed budget. Quality
  assertions are therefore either CATEGORICAL (fail-safe vs not) or RELATIVE to
  the run's own seeds. Do not re-add an absolute threshold on max lambda.
- **Topology is a real design lever, measured both ways.** With only
  tank->plate pairs offered, the demo's floor is 14 rods against the global
  bound of 13; allow tank-to-tank rods and 13 becomes reachable. A search that
  trusted `6 n_free + 1` would report an unreachable count as available.
- **A same-body rod contributes a column of exactly zero** — the two blocks
  cancel and `(a-b) x u` vanishes because `a-b` is parallel to `u`. Not a weak
  constraint: no constraint. `topology_options` excludes them, and a test
  measures the zero column rather than arguing it.
- `layout_metrics` now takes ONE SVD for both the spectrum and `rho^2`
  (`_spectrum`); it previously decomposed the same matrix twice and rebuilt the
  non-dimensionalized copy with it. That is the search's inner loop.
- Gate tests mutation-checked; the test file carries a ~59 s budget, which is
  the price of exercising a real search.

- [x] Session 9 — construction UI (`apps/tierod/ui_build.py`,
      `tests/tierod/test_ui_build.py`) — 2026-08-23, 557 tests green.
      Build tab (Bodies / Regions / Rods / Save-load), JSON download+upload.
- [x] Session 10 — layout-search UI (`apps/tierod/ui_search.py`,
      `tests/tierod/test_ui_search.py`) — 2026-08-23, 803 tests green.
      "Find a layout" tab: cost estimate, trade curve, candidate gallery,
      Adopt. The Session 7/8 engines are reachable from the app at last.
- [ ] Session 11 — rod pool (section x material from the toolkit `MATERIALS`
      library), enable checkboxes + sizing study, rod tags, click-to-select
## Session 7 as-built notes

- **`rho_j^2 > 0` iff rod j can be lost without creating a mechanism** — verified
  against brute-force removal on every fixture, not assumed. One SVD replaces N
  rank re-solves for the structural half of fail-safe. It is invariant to row
  scaling, so it does not depend on `L_c`; a test pins that, because a fail-safe
  verdict that moved with a bookkeeping choice would be worthless.
- **A Session 5 bug surfaced here: `run_sweep`'s closed-form envelope ignored the
  case `factor` entirely.** The envelope is a property of the UNIT sphere, so
  nothing in `T` knows about the factor — every margin was reported at factor 1.0
  while the enumerated case table showed scaled loads. Found because the damaged
  load factor had no effect on anything. `envelope()` now takes a factor and
  `run_sweep` applies `max(case.factor)`.
- **`feasible()` uses two distinct vocabularies on purpose.** "mechanism" means
  rank-deficient and nothing else; the near-singular reason says "fragile". They
  used to share the word, which made a mutation deleting the rank check pass a
  substring assertion.
- **The damaged check is deliberately the more lenient one** (SF_ult 1.0 vs the
  intact 1.5) because fail-safe is normally "survive LIMIT load with one member
  gone". Whether the damaged margin lands above or below the intact one depends
  on whether redistribution or the factor relief wins — that is a property of the
  layout, not a rule, and the tests deliberately do not assert a direction.
- **`report.ok` needs the `all(states ok)` check independently.** A collapsed
  state contributes no margin, so `damaged_worst_margin` is taken over the
  survivors and reads healthy on its own. Only reachable for multi-rod damage
  sets: if the cheap screen passes, no singleton removal can be singular by
  construction. symmetric8 has 12 of 28 two-rod losses going singular, which is
  the fixture for it.
- `check_failsafe(subsets=...)` takes arbitrary rod tuples, so Phase 3 widening
  the damage set is a caller change rather than a rewrite.
- Gate tests mutation-checked: 21 seeded defects, three initial misses (all
  described above), all caught.

**Owner decisions, 2026-08-22.** Rod materials come from the existing 24-alloy
`library/materials/` library, converted **ksi→psi and Msi→psi at one guarded
boundary** (a silent 1000x on Ftu produces margins that look entirely plausible).
Section assignment is **per group, default one group holding every rod** — a
group is sized as a unit; per-rod free choice was rejected as unbuildable.

## Session 1 as-built notes

- **Standoff direction.** `h` offsets the pin along `Body.clearance.outward(p)`, NOT a
  region-level normal. That is deliberate: a region normal is the deleted mount-axis
  concept wearing a hat, and `CircleArc` has no unique one (that ambiguity is what
  `axis_mode` existed to paper over). A non-zero `h` on a body with no clearance
  primitive raises — the standoff has no defined direction without one.
- **Clearance primitives are body-local**, same convention as regions, oriented by a
  stored triad. `Assembly.endpoint_global` applies the standoff in body-local coords
  then transforms by `Body.R`.
- `distance_to_segment` returns a **non-negative clearance** (0 when the segment meets
  the solid), not a signed penetration depth. Phase-2 non-penetration is the half-space
  test (§8.2), not this; this is for rod-vs-body clearance limits.
- Generic `distance_to_segment` is a golden-section search over the segment parameter.
  Valid because distance-to-a-convex-set is convex along a line. `Sphere` overrides it
  with the exact closed form.
- **`SphericalPatch` added** — it is in the build prompt's §3.2 region table but was
  missing from the draft `model.py`.
- `Body.g_factor` is a scalar defaulting to 1.0.
- Small additions beyond the draft: `Assembly.validate()`, `n_design_vars()`,
  `rod_endpoints()`, `Region.clip()` / `in_bounds()`, `frame_from_axis()`,
  `check_orthonormal()`, `cases.parse_case_name()`.
- `tests/tierod/conftest.py` carries the push-1 demo assembly (2 cylinders + baseplate,
  12 rods) as a shared fixture. Session 1 only asserts it is a valid model; the kernel
  gates land later.
- The gate tests were mutation-checked (16 seeded defects, all caught) rather than
  merely run green.

## Session 2 as-built notes

- **`assemble()` returns an `Assembled` dataclass**, not the bare
  `(Ĝ, K_d, K)` tuple the plan names. Those three are `.G_hat`, `.K_d`, `.K`;
  the extras (`lengths`, `units`, `rod_ids`, `body_order`, `L_c`, `points_a/b`)
  are all things later stages would otherwise recompute from the geometry.
- **`solve()` verifies its own answer.** `np.linalg.solve` only raises on an
  EXACT zero pivot, which rank-deficient geometry rarely produces — it returns a
  large, silently wrong `U` instead. `_solve_checked` rejects any solution whose
  relative residual exceeds 1e-6. The `rotary_hexapod` fixture exists solely to
  exercise this path; without the guard it returns garbage and every test still
  passes.
- **`influence()` needs a RANK guard, not a residual guard.** `Kᵀ X = Ĝ` is
  always *consistent* (`range(Ĝ) == range(K)`), so a singular K yields a small
  residual and one of infinitely many influence matrices. Only a rank test
  catches it.
- **`L_c` and the non-dimensionalized rank test landed here, not in Session 3.**
  `influence()` cannot be made safe without them and the convention forbids
  raw-K spectra. Session 3 still owns everything diagnostic: null modes, the
  graph pre-check, geometric degeneracy messages, σ_floor. It should consume
  `asm.L_c` / `asm.nondim_screws()` rather than recompute.
- **V6 uses two exact statements.** `test_v6_parallel_rods_split_load_in_proportion_to_stiffness`
  duplicates a hexapod rod onto identical endpoints: same screw ⇒ same
  elongation ⇒ `P ∝ k` exactly, and the pair sums to the original single-rod
  load. The redundant 8-rod case then checks monotonicity, since a general
  redundant layout has no closed-form "known proportion".
- **The 6-6 rotary hexapod is rank 3.** Top and bottom rings with a uniform
  angular offset is a classic singular Stewart platform. It bit the first
  `two_body` fixture; `make_rotary_hexapod()` now keeps it deliberately as the
  singular-layout fixture. Do not build a "generic" hexapod that way.
- Gate tests mutation-checked: 17 seeded defects (every sign in the convention
  block, the datum-relative moment arm, the reversed cross product, `K U = -F`,
  both guards, the non-dimensionalization), all caught.

## Session 3 as-built notes

- **An SVD null-space basis is arbitrary within the null space.** When the
  nullity is 2 or more, a physically meaningful motion — "the whole assembly
  turns about the ground line" — is generally a COMBINATION of the returned
  basis vectors and appears in none of them. `mechanisms.rigid_rotation_mode()`
  builds a named motion explicitly so it can be asserted and animated;
  `mode.common_axis()` is only decisive when nullity == 1. This bit twice while
  writing V8 and will bite the UI too.
- **Modes are normalized by `max(|d| + L_c·|θ|)`, not by attachment-point
  motion.** In a concurrent layout every attachment sits on the rotation axis
  and does not move, which would leave the mode unscaled at 0.
  `max_point_displacement` still reports real attachment motion and is
  legitimately 0.0 there.
- **A screw motion has no stationary line**, so `axis_line()` / `common_axis()`
  return None for one. `make_screw_motion()` exists solely to test that: no
  other fixture produces a screw, because every rotationally symmetric
  two-circle layout collapses to rank 3 instead (verified over n = 6..12 and
  four helix angles).
- **The four geometric checks are not a complete classifier**, and should not
  be made into one. The 6-6 rotary hexapod is rank 3 yet is not parallel, not
  concurrent (best-fit concurrency point misses by 9.6 in against L_c = 10) and
  has its ground attachments on a circle. It correctly produces NO finding —
  the three animated modes are the diagnosis, which §5.3 says is the highest
  value output anyway. Staying quiet beats inventing a cause.
- The collinear-ground finding **self-checks its own theorem**: it only fires
  if rotating every free body about the fitted line actually stretches no rod.
- Graph check stays silent about "unsupported" when there are NO ground bodies:
  that is the free-free mode, and the rank check owns it.
- `_fit_line` on a (3, n) point cloud takes the principal direction from
  `U[:,0]`, not `Vt[0]` — `Vt`'s rows live in point-index space, not R³.
- Gate tests mutation-checked: 16 seeded defects, all caught.

## Session 4 as-built notes

- **`ui_scene.py` imports Plotly but NOT Streamlit**, so the whole figure layer
  is unit-testable. Only `ui_inputs.py` (widgets) and `render.py` touch
  Streamlit. A test enforces this in a subprocess.
- **`streamlit run` starting proves nothing** — the script body does not
  execute until a browser connects. `test_app_smoke.py` uses
  `streamlit.testing.v1.AppTest` to actually run `render()` headlessly and
  surface exceptions, including the ground-toggle round trip through the real
  widget layer. That is the automatable half of the manual gate.
- **Clearance primitives gained `surface_mesh()`** in `library/tierod/clearance.py`,
  not in the scene layer: a triangulated boundary is geometry, not rendering,
  and the tests assert every vertex satisfies `distance_to_point == 0`. Regions
  need no equivalent — they mesh from `region.point(q)`, the same function the
  optimizer differentiates.
- **Mode animation is a LINEARIZED rigid motion**, matching the kernel's small
  displacement assumption, so points travel along tangents and the radius about
  a rotation axis grows second order (~3.5e-4 relative at the default
  amplitude). The test asserts that error is quadratic in amplitude rather than
  hiding it behind a loose tolerance. Do not "fix" this by applying an exact
  rotation: screw and mixed modes have no exact rotation to apply, and the
  linear field is what the kernel actually solved.
- **The gate's collinear example needed tuning to nullity exactly 1.** A first
  attempt hung a flat pad from the rail and came out nullity 3 — coplanar
  body-side attachments PLUS a collinear ground is doubly degenerate, and the
  extra modes muddy the demonstration. It is now a pipe on a rail, whose
  band attachments are non-coplanar.
- `examples.py` is an extra file beyond the plan's list: pure model
  construction shared by the app, the tests and the gate checklist.
- `Assembly.design_vector()` / `set_design_vector()` / `design_bounds()` added
  to `model.py` — the sliders drive the model through them now, and Phase 2's
  optimizer will use the same pair.
- Sliders generate themselves from `ndim` + `bounds()`; a test greps
  `slider_specs` for every region class name to keep it that way.
- UI layer mutation-checked: 13 seeded defects (both `uirevision`s,
  `aspectmode`, rods detaching during animation, the region mesh being written
  twice, the ground-toggle data-loss bug, sliders ignoring bounds), all caught.

### Session 4 gate — status

| Check | How verified |
|---|---|
| Camera survives slider moves | structural: `uirevision` constant across rebuilds, both layout and scene (mutation-checked) |
| Collinear layout animates rotation about the line and names the cause | `test_the_collinear_plate_animates_rotation_about_the_plate_line`; axis recovered as [-1,0,0] through the origin, message names "collinear" |
| Ground toggle round-trips without data loss | `AppTest` drives the real checkbox on/off/on; mass and g_factor preserved |
| Page renders | `AppTest` on all three examples, no exceptions |
| **Visual confirmation in a browser** | **still owed — nobody has looked at it yet** |

## Session 6 as-built notes

- **`PARAMS` is a `ClassVar`, not a dataclass field.** Declared with a bare
  `PARAMS: tuple = (...)` it becomes a constructor argument and shows up in
  `dataclasses.fields()`, which broke the "declaration tracks the dataclass"
  test on the clearance primitives (the Region base absorbed it, so regions
  looked fine). Use `ClassVar[tuple]`.
- **`CLEARANCE_TYPES` lives in `clearance.py`, not `model.py`** — `clearance`
  imports `model`, so the reverse import would be a cycle. `model.new_clearance`
  imports it lazily inside the function.
- **A UI-built layout is very easy to make singular.** The obvious first thing
  anyone draws — one flat pad on the body, one ring of ground anchors — is rank
  3, because BOTH attachment sets are coplanar. Kept as a test
  (`test_a_ui_built_layout_can_be_a_mechanism_and_the_tool_says_so`) so the
  builder is known to fail loudly there. The band-with-alternating-z pattern is
  the one that works.
- **Round-trip fidelity is gated on the ANALYSIS, not on the fields.** Field
  comparison passes while a dropped frame triad silently rotates a region. Three
  mutation misses came from exactly this, all because every shipped example is
  built on the XY frame with clearance at the origin: dropping the region triad,
  dropping the clearance triad and zeroing the clearance origin all changed
  nothing measurable. Fixed by round-tripping an arbitrary QR-generated triad
  and by measuring clearance orientation through the STANDOFF, which is the path
  by which a shell's frame reaches a rod endpoint.
- `new_rod` seeds each end at `region.q0()`, not zeros: zero is outside the
  domain of an Annulus (`r_inner`) or a band (`z_min`), so a rod created at zero
  fails validation far from the click that made it.
- Deletions return a `Removed` record (bodies / regions / rods) so the UI can
  say "also removed 6 rods". A refused cascade (`cascade=False`) must leave the
  model byte-identical — asserted by comparing `dumps()` before and after.
- `Rod.group` added, defaulting to `"main"`. One spec per group is the
  assignment granularity chosen by the owner (2026-08-22); the pool that fills
  those groups is Session 8.
- Gate tests mutation-checked: 32 seeded defects across `model.py`,
  `clearance.py` and `serialize.py`; the five initial misses are described
  above. All caught after the test gaps were closed.

## Session 5 as-built notes

- **`Body.sweep_block()` had a latent bug: the inertial moment arm was `cg`, not
  `R @ cg`.** `cg` is stored body-local, but the load direction and `Ghat`'s moment
  rows are both in GLOBAL axes about the body datum, so the arm must be rotated first.
  Every example and fixture has `R = I`, which is exactly why it survived Sessions 1–4.
  Fixed here, gated by `test_a_rotated_body_frame_leaves_every_rod_load_unchanged`
  (one physical layout expressed in two frames must give identical rod loads).
- **The governing value is the closed form `‖t_i‖₂`, and the results table says so on
  the page.** The enumerated set is a labelled sample: the table shows the nearest case
  name plus the angle to `n̂*_i`, and the summary shows the worst shortfall across rods.
  On the shipped demo that shortfall is **7.7%** — big enough that reporting the
  enumerated maximum would have overstated every margin.
- **Every rod is checked two-sided.** `n̂*` and `−n̂*` are both unit directions, so the
  envelope is reachable in both senses and `two_sided_load_ratio` takes the weaker of
  the tension and compression allowables. The demo comes out compression-governed on
  all 12 rods, on the Euler branch — §7.2's "a full-sweep design is a buckling-driven
  design", confirmed by a test rather than assumed.
- **Load ratio is `|P| / min(effective allowable)`,** where each check's effective
  allowable is its raw value divided by its own safety factor. The governing check is
  then just the argmin, and adding a check later is adding a list entry. Four checks
  exist: tension ultimate (vendor rated, else `A_net·Ftu`), tension yield (`A·Fty`,
  optional — `Rod.Fty` added this session), compression ultimate (Euler/Johnson) and
  compression yield (`A·Fcy`).
- **`Fcy` is required, so the compression side ALWAYS has a check** — which means a rod
  with no tension data still produces a margin, off compression alone. That number is
  not wrong, it is incomplete, and in a table the two are indistinguishable. Those rods
  are named in `SweepResult.incomplete_rods` and warned about in the UI. (Found by
  mutation testing: the original "no allowable at all" guard was unreachable.)
- **The sweep must be gated on `asm.is_singular`, NOT on `report.ok`.** A model with
  zero ground bodies is the legitimate free-free diagnostic (V12) and reports ok, but
  it still has six null modes and no influence matrix. Un-grounding the last body in
  the sidebar goes straight there — caught by `AppTest`, not by any unit test.
- **`mask_assembled()` deletes columns of `Ghat` and rebuilds `K`; it never
  re-assembles from geometry, and it keeps `L_c` pinned to the geometry** so rank
  checks stay comparable across failure states. Phase 3's rod-removal states are
  therefore a parameter (`active_rods`), not a rewrite.
- `RodSpec` + `ROD_SPECS` live in `allowables.py` (an extra concept beyond the plan's
  file list, no extra file). A spec is section + material only — topology and
  `end_fixity` are untouched. Assignment is **reported, not stored**: `spec_assignments`
  derives the match from the Rod's own fields, so a stale label can never contradict the
  numbers driving the margins. This is NOT the Phase-5 catalog snap.
- Gate tests mutation-checked: **21 seeded defects on the library** (every sign and
  factor in §6.2, both branch directions, the tension source order, the safety-factor
  direction, the L1/L2 envelope, the mask, the sort) and **20 on the UI layer** (the
  table reporting the sample as the envelope, the dropped coverage angle, the cone, the
  `report.ok` gate). All caught; the two initial misses are described above and in the
  test files.

Deviations from plan (note here with date and reason):
- 2026-08-24 — **`library/tierod/clash.py` is a new module the plan does not
  list.** The plan's feasibility constraint says "no penetration" but assigns it
  to nothing. It is a geometry kernel, not a scoring rule, so it sits beside
  `clearance.py` rather than inside `failsafe.py`, and `failsafe.py` consumes it.
- 2026-08-24 — **rod↔region interference is NOT checked**, by the owner's
  decision (2026-08-23). Regions are declared mounting surfaces; a rod touching
  one is the intent.
- 2026-08-24 — the old demos were **replaced, not kept alongside**. The owner
  reversed an earlier "don't delete the old demos" the same day. Their geometry
  survives as `tests/tierod/legacy_demo.py` because 69 tests were keyed to it.
- 2026-08-24 — `Region.keepouts` remains a **dead field, read by nothing**.
  Interference is computed from body clearance shells and rod segments instead.
  Left in place rather than removed mid-round; decide it deliberately later.
- 2026-08-22 — `Rod.Fty` added (optional, defaults None) so the tension yield check is
  a real check rather than a plumbed-but-unused safety factor. The owner asked for SF
  input cells with defaults; two factors with only one live check would have been half
  a feature.
- 2026-08-22 — rod editor (`ui_inputs.rod_editor`) built in Session 5 though the plan
  does not list it. Session 5 makes `A`, `I`, `Fcy`, `Ftu`, `A_net` and
  `P_tension_allow` load-bearing and there was nowhere in the UI to enter any of them.
  Built as a **spec table + group assignment** rather than twelve sets of loose fields,
  per the owner's manufacturing concern (2026-08-21).
- 2026-08-22 — characteristic length `L_c` + the non-dimensionalized rank check
  implemented in Session 2 rather than Session 3, because `influence()` returns a
  silently non-unique matrix on a mechanism without them. Diagnosis stays in
  Session 3.
- 2026-08-21 — **load case convention changed by the owner** from the box/sign-vector
  form to unit directions with a per-body scalar `g_factor`. `Body.g_factors` (3-vector)
  → `Body.g_factor` (scalar); `LoadCase.sign_vector` → `LoadCase.direction`;
  `sign_matrix()` → `direction_matrix()`. Old gate V17 (L1 corner identity) withdrawn and
  replaced. Both `docs/tierod/IMPLEMENTATION_PLAN.md` and this file updated to match.
  Reason: the box convention made multi-axis cases up to 1.73× the ellipsoid, which the
  owner judged double-dipping.
- 2026-08-21 — `apps/tierod/model_draft.py` left in place rather than deleted after the
  port, because it was untracked in git and deleting it would have been unrecoverable.
  **Deleted 2026-08-23** in the pre-commit cleanup: nothing imported it, and 374 lines
  of dead code sitting next to `model.py` under a near-identical name is a trap. The
  reference in `library/tierod/model.py`'s header was reworded at the same time so it
  does not point at a file that no longer exists.
