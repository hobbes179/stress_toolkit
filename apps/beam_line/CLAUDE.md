# CLAUDE.md — Beam Diagrams module

Context for Claude Code working on `apps/beam_line/` and
`library/beam_line/`. Read this before making changes here.

Shear, moment, slope and deflection along a straight prismatic beam, with
arbitrary supports, releases and loads. Built 2026-09-04. This is roadmap
item 14 (`Beam Deflection`) from the root `CLAUDE.md`, widened into a full
line-beam solver.

---

## Files

| File | Role |
|---|---|
| `library/beam_line/model.py` | Dataclasses + validation. **Pure data** — no numpy, no solver, no Streamlit. The sign conventions are stated here, once. |
| `library/beam_line/solver.py` | Direct-stiffness assembly and solve → nodal DOF + reactions. Pure; numpy only. |
| `library/beam_line/diagrams.py` | Exact piecewise-polynomial V, M, θ, δ, peaks, and the validity gate. Pure. |
| `apps/beam_line/plotting.py` | The four-panel figure, as an SVG string. Pure; takes the model plus its solution. |
| `apps/beam_line/method.py` | The Method section, as HTML. Pure data. |
| `apps/beam_line/styles.py` | Page CSS on toolkit tokens. Pure. |
| `apps/beam_line/app.py` | Streamlit glue: session state, widgets, layout. |
| `ui/handoff.py` | The section snapshot shared with Beam Section Stress. |
| `pages/5_Beam_Diagrams.py` | Thin page wrapper. |
| `tests/beam_line/` | Closed-form gates + headless page execution. |

---

## Hard constraints

Do not break these without asking.

- **`library/beam_line/` stays pure.** Mechanics only. No Streamlit, no
  session state. `app.py` is the only file in the module that may import
  `streamlit`.
- **One sign convention, stated once, in `model.py`.** x left to right;
  `v`, `P`, `w` positive **up**; `θ` and applied `M` positive
  **counterclockwise**; the plotted bending moment is **sagging-positive**.
  The solver, the diagrams, the figure and the Method section all use it
  unchanged. A convention drift between any two of them poisons every
  downstream reading and is nearly invisible in a screenshot —
  `test_a_gravity_load_sags_and_a_cantilever_hogs` is the gate.
- **Pin and roller are the same restraint, and the module says so.** There is
  no axial DOF, so both restrain vertical translation and nothing else. Do
  not add two symbols that compute the same answer. If an axial DOF is ever
  added, `test_pin_and_roller_are_the_same_restraint` is the test that must
  change first.
- **Results are gated on the integrated diagrams, not on ΣF = 0.** `ΣF = 0`
  is necessary, not sufficient — the same lesson the bolt module paid for
  when a loaded zero-thickness layer passed the force sum with `V(L) = 1000`.
  The gate is `|V(L)|`, `|M(L)|` and the deflection residual, all relative,
  all at 10⁻⁶. `test_the_gate_is_not_vacuous` proves the gate can fire and
  `test_the_gate_tolerates_ordinary_floating_point_noise` proves it does not
  fire on a correct solve.
- **The closure ratio is normalised by the TRUE peak, over the interior.**
  Normalising by piece endpoints is not equivalent and shipped as a bug
  during the build: a simply supported beam has `M = 0` at both ends, so the
  endpoint scale collapses onto the closure residue itself and every such
  beam reports a ratio of exactly 1. Same for the deflection residual, whose
  scale is the peak of the **field** — on a propped cantilever or a stiff
  spring every *nodal* deflection is at or near zero while the span deflects
  normally, and normalising by those turns 1e-16 of rounding into an apparent
  1e-5 error.
- **Singularity is detected spectrally, and that is not the same tool as the
  bolt module's rejected condition number.** `np.linalg.cond` was removed
  from `refined.py` because it was being asked to *grade a solve*. Here the
  question is binary and structural — is there a rigid-body mode — and a
  genuine mechanism sits at the 1e-16 floor while a real beam on deliberately
  soft springs sits many orders above. `test_the_singularity_verdict_is_not_a_marginal_judgement_call`
  pins that gap. Report `null_ratio`; do not nudge `SINGULAR_RATIO`.
- **There is no mesh parameter, and adding one would be a regression.**
  Euler-Bernoulli elements are exact at the nodes for these load types and
  `diagrams.py` recovers the element interior in closed form, so refinement
  is a null operation. `test_extra_nodes_cannot_change_the_answer` pins it at
  `rel=1e-12`. Anything that makes the answer mesh-dependent has broken the
  recovery.
- **Peaks are rooted, never sampled.** `M_max` comes from rooting `V`, so
  both the value and the station are exact. A sampled peak is wrong by up to
  half a sample interval and silently depends on the sample count.
  `test_the_peak_moment_is_rooted_not_sampled` checks the reported station
  does *not* coincide with a sample point.
- **Evaluation at a station takes an explicit `side`.** V steps at a point
  load and M steps at an applied couple, so `M_at(x)` at a boundary is
  genuinely two-valued. Do not resolve it with a floating-point tie-break —
  that was tried, and an epsilon offset equal to `POSITION_TOL` picked the
  wrong piece.
- **The page is never fragmented.** Model, figure, peaks and reactions are
  visible at once; only the Method section may be collapsed. Same reason as
  the bolt module: the tool exists so you can move a support and watch the
  moment peak move with it. `test_the_page_is_never_fragmented` pins it.
- **An unstable beam still draws its elevation.** The elevation is the user's
  own input; hiding it leaves them nothing to correct. The *diagrams* go,
  because one drawn for a mechanism looks plausible and means nothing.
- **Nothing above the figure may change height on a load toggle.** The whole
  point of the per-item switch is flipping a load on and off and watching the
  diagrams change IN PLACE; anything above the figure that appears or
  disappears makes the plot stack jump by its height and destroys that. The
  excluded-items notice shipped above the figure and did exactly this, so it
  now sits BELOW the SVG inside the figure card. The gate is exact:
  `test_toggling_a_load_does_not_move_the_figure` asserts the rendered page is
  **byte-identical up to the `<svg>` tag** in both states. Anything new added
  to the page must go below the figure unless its height is fixed.
- **A switched-off item must be named in the OUTPUT, not just the sidebar.**
  Every support, load and hinge row carries an include/exclude switch so the
  effect of one can be seen without rebuilding it. An excluded item is
  therefore *not* omitted: it is listed by value and station in an amber
  notice above the figure, and drawn ghosted (30% opacity, dashed) on the
  elevation. This page gets screenshotted into stress reports, and a load
  that is simply absent from the picture is one nobody notices is missing.
  `test_a_switched_off_item_is_named_in_the_results` and
  `test_a_switched_off_item_is_ghosted_on_the_elevation_not_omitted` pin both
  halves.
- **`on` is part of the row shape check.** Defaulting it in for a stored row
  that predates the switch would leave that row in a state the widget cannot
  represent; failing the check and reseeding is correct.
- **The ghost layer shares the distributed-load scale with the active one.**
  Otherwise a ghosted 100 lb/in patch is drawn the same height as an active
  1 lb/in one and reads as comparable. `library/beam_line` never sees the
  ghost — "disabled" is a UI idea, and the `Beam` passed to the solver is
  always the real model.
- **The load envelope is n+1 solves, never 2^n.** `library/beam_line/
  envelope.py`. The model is linear in the loads, so the extreme over all
  subsets is reached by including exactly the loads that contribute that way
  at each station. It is EXACT, not a bound, and
  `tests/beam_line/test_envelope.py` checks it against brute force over all
  2^n subsets on four model types. Do not "optimise" it into a sampling
  heuristic, and do not reintroduce a combination loop.
- **The empty-set response must be subtracted from each single-load solve.**
  An imposed settlement is a boundary condition, present in every subset
  including the empty one; forgetting this counts it n times.
  `test_settlement_is_counted_once_not_once_per_load` is the gate.
- **The envelope varies loads only, never supports.** The response is linear
  in the loads and NOT in the structure, so a support toggle legitimately
  moves the scale while a load toggle must not.
- **The locked scale is floored by the drawn peak.** The envelope is sampled
  on a grid; the floor is what guarantees a curve can never run outside its
  own panel because the grid missed a peak by a hair.
- **The stack is edited with native widgets, in the sidebar.**
  `st.number_input`, never `st.data_editor` — the stepper buttons and the
  scroll-wheel nudge come from the native input and a NumberColumn has
  neither. **Two number inputs to a row, maximum** (a third widget that is
  not a number input, such as a selectbox or a delete button, is fine). The
  sidebar is widened to 30rem in `styles.py` for the same reason.
- **Row widget keys are built from a stable row id, never the list
  position.** Deleting row 1 would otherwise shift every key below it and
  Streamlit would replay row 2's stored value into row 1. `_reset()` must
  drop every `bl::` key for the same reason.
- **Session state is shape-checked, not presence-checked.** Streamlit Cloud
  redeploys under live sessions, so a browser holding the previous format
  must be reseeded rather than crash the page on its next rerun. This applies
  to the handoff payload too, which carries a `SCHEMA` integer.
- **Render HTML with `st.markdown(..., unsafe_allow_html=True)`, never
  `st.html()`.** `st.html` sanitises with an HTML-only profile that strips
  `<svg>` **silently** — the figure column comes out blank with no error and
  nothing in the logs.
- **No `<defs>`, no `url(#id)` in the SVG.** Arrowheads are explicit polygons
  and hatching explicit line segments. Patterns and markers need a `<defs>`
  block plus ids that must survive the page's sanitiser and stay unique
  against everything else on the page.
- **Colours come from `ui.theme.BEAM_PALETTE`.** No hex literals in
  `plotting.py`, `styles.py` or `app.py`; there is a test asserting it.
- **No browser storage.** Nothing here may use `localStorage`,
  `sessionStorage` or IndexedDB. State lives in Streamlit session state.
- **The Method section is part of the deliverable.** If the mechanics change,
  update `method.py` in the **same commit**.

## Before you commit

Run `tests/beam_line/`. It ends green. The closed-form suite in
`test_kernel.py` must still reproduce every textbook case to 1e-9 — those are
published formulae, not recorded outputs, so a failure there is a real
regression and never a stale golden.

---

## The section handoff

`ui/handoff.py` mirrors the section from Beam Section Stress into a plain
(non-widget) session key so this module can offer it as a starting point.

**Why a mirror and not the widget keys.** Streamlit garbage-collects a
widget's `session_state` entry once the widget stops being instantiated.
Navigating between pages in `pages/` means the previous page's widgets are not
rendered on that run, so their state is dropped — reading
`st.session_state["dim_0_I-Beam / W-Shape"]` from another page gets nothing,
reliably. A plain key is not collected.

What it deliberately is **not**: a live link. It is a snapshot of what that
page last built in this browser session, and the page says so in words. It is
also session-only — a browser that opens Beam Diagrams first sees nothing,
which is why manual E and I are the default and the toggle is offered only
when a snapshot exists. A toggle that is inert most of the time is worse than
no toggle.

The publish call in `apps/beam_section/app.py` is wrapped in a bare `except`
on purpose: a handoff convenience must never be able to break the page that
produces it.

---

## Known gaps and backlog

Ranked.

### 1. Stepped / tapered EI (foundation laid, UI not built)

`solver.element_EI()` is called per element and the result stored per element;
`diagrams.build()` integrates `M/EI` per interval with carried constants. Both
already handle a varying EI. What is missing is only the UI and the extra
mesh stations. To finish: return the segment value containing the element
midpoint, and add every step station to `Beam.feature_stations()` so no
element straddles a change.

### 2. No stress or margin output

The module reports V, M and δ. Converting the peak moment to a stress and a
margin is the beam-section module's job, and the Method section says so. The
obvious next step is the reverse handoff — publish `M_max` and `V_max` from
here and let Beam Section Stress pick them up as loads, which would close the
loop that item 1 of the handoff opened. Worth doing; not started.

### 3. Shear deformation (Euler-Bernoulli only)

Deflections are under-predicted on deep, short spans, roughly
`L/d < 10` for metals. A Timoshenko element needs `GA_s` and a shear form
factor — both derivable from the `Section` class, so the section handoff would
carry them. Not started, and the limit is stated in Method §10.

### 4. Load cases and envelopes

One load case at a time. The model is linear elastic and small-displacement
throughout, so superposition holds and cases could be combined and enveloped
cheaply. Pairs with the same item in the bolt module's backlog.

### 5. Moving loads / influence lines

Falls out of the same machinery — the solve is fast enough to sweep a load
position and envelope the result. Not requested; logged because the
architecture already supports it.

### 6. Rotational spring symbol is weak

`_supports()` draws a rotational spring as a bare arc. It reads as a decoration
rather than a spring. The support's kind label carries the truth, so this is
cosmetic, but it is the least legible symbol in the figure.

---

## Not modelled (by design, stated on the page)

Shear deformation, axial force, P–Δ, buckling of any kind, torsion,
out-of-plane loading, self-weight (enter it as a distributed load),
plasticity, large deflection.

---

## Verifying a UI change

Tests catch logic; they do not catch a label printed on top of another label.
Two collisions in this module's first build — the shear panel title under the
peak callout, and the reaction caption under its own value — were invisible to
a green suite and obvious in a screenshot.

The screenshot loop from the bolt module works unchanged:

```
python -m streamlit run pages/5_Beam_Diagrams.py --server.port 8572 \
       --server.headless true &
# then drive Chrome over CDP: navigate, sleep real seconds, capture.
```

Chrome's plain `--headless --screenshot` is not enough: it uses virtual time,
which does not wait for Streamlit's websocket, so it captures the grey loading
skeleton. Streamlit also scrolls inside its own container, so `window.scrollTo`
does nothing — scroll the tallest overflowing element.

Restart the server after editing an imported module; the watcher does not
always pick up changes to `styles.py`, `method.py` or `plotting.py`, and a
stale render will happily convince you a fix did not work.

## Style notes

- Analyst-facing wording throughout. Standard structures terminology.
- The horizontal axis of the figure **is** dimensionally true — unlike the
  bolt module's elevation — and every station on every panel lines up with it.
  Only the vertical extents are schematic.
- Peak labels flip to the other side of their marker when they would collide
  with the panel title or the station axis. Do not remove that clamp; the
  peak of a shear diagram routinely sits at the very top of its band.
