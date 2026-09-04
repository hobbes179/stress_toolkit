# CLAUDE.md — Bolt Bending module

Context for Claude Code working on `apps/bolt_bending/` and
`library/bolt_bending/`. Read this before making changes here.

Shear and moment diagrams along a bolt in a multi-layer joint, with strength
margins. Ported 2026-09-03 from a standalone single-file browser tool; the
original and its specification are archived under `docs/bolt_bending/`.

---

## Files

| File | Role |
|---|---|
| `library/bolt_bending/kernel.py` | All the mechanics. **Pure** — no Streamlit, no DOM, no globals. The natural seam for tests. |
| `library/bolt_bending/refined.py` | Refined bearing distribution — beam on an elastic foundation. Pure. |
| `apps/bolt_bending/refined_view.py` | HTML blocks for the refined bearing pass. Pure. |
| `apps/bolt_bending/plotting.py` | The three-panel figure, as an SVG string. Pure; takes a `BoltAnalysis`. |
| `apps/bolt_bending/method.py` | The Method section, as HTML. Pure data. |
| `apps/bolt_bending/styles.py` | Page CSS — the original tool's stylesheet on toolkit tokens. Pure. |
| `apps/bolt_bending/app.py` | Streamlit glue: session state, widgets, layout. |
| `pages/4_Bolt_Bending.py` | Thin page wrapper. |
| `tests/bolt_bending/` | Kernel gates + headless page execution. |

---

## Hard constraints

These carry over from the original tool's constraints, translated to the
toolkit. Do not break them without asking.

- **`kernel.py` stays pure.** Mechanics only. No Streamlit import, no session
  state, no DOM. Same input, same output.
- **`plotting.py`, `method.py` and `styles.py` stay Streamlit-free** as well.
  `app.py` is the only file that may import `streamlit`.
- **The page is never fragmented.** The stack, the diagrams, the margins and
  the checks must all be visible at once — the point of the tool is changing a
  load and watching the moment peak and the margin move together. Splitting
  that across tabs is the regression that forced the 2026-09-03 rebuild.
  **There are now no tabs at all**; `test_the_page_is_never_fragmented` pins it.
- **The refinement is a toggle, not a second screen.** It was briefly a second
  tab (v2.4.0); it became a sidebar toggle at the owner's request on
  2026-09-04. One analysis drives the whole page — figure, checks and margins
  — because two peak moments on one screen is how the wrong one ends up in a
  report. The baseline-vs-refined comparison is a *grid inside* the refined
  supplement, not a parallel set of page results.
- **The baseline stays the default answer.** The toggle is off by default. The
  refined pass is less-conservative, so it must never appear without its basis
  and assumptions — `refined_view.supplement()` carries both, and it is
  rendered directly below the margins it qualifies.
- **The assumption in force is stated in words, in both states.** A toggle that
  silently moves the peak moment by 15% is a trap.
  `refined_view.model_strip_html()` sits above the Strength card either way;
  `test_the_bearing_model_is_stated_in_words_in_both_states` pins it.
- **Closure is gated on the INTEGRATED diagrams, not just ΣP.** `ΣP = 0` is
  necessary, not sufficient: a layer carrying load with zero thickness applies
  no bearing (`w = P/t` is guarded to 0), so its load counts in ΣP and `M_res`
  but never reaches the diagrams. That shipped as a bug — margins displayed
  with `V(L) = 1000 lbf`. `balanced` now also requires `|V(L)|` and `|M(L)|`
  within tolerance, and `analyse()` reports `starved` so the message can name
  the layer. Both bearing models must agree on `balanced` for the same stack;
  there is a test for that.
- **Solve quality is measured on the solve, never with a condition number.**
  `np.linalg.cond` was tried and removed: insensitive to `k`, scales as h⁻⁴ and
  d⁴, so it failed an ordinary 1 in bolt and got worse as the mesh improved.
  Use `residual` and `load_error`; the latter is taken **before** the strips
  are normalised onto the entered load, because the normalisation would
  otherwise mask a bad solve. Thresholds are set from measured ranges recorded
  in the module constants — re-derive them, do not nudge them.
- **`f_s = κ·V/A`, and κ depends on what `Fsu` is.** 1.0 against an MMPDS
  fastener allowable (already stated on the shank area); 4/3 against a material
  shear strength (the peak on a solid round). The app derives it from the
  material's `category`. Worth 33% on the shear margin, so it is stated on the
  Strength card and the results cell is relabelled — never applied silently.
- **The stack is edited with native widgets, in the sidebar.** Moved there
  2026-09-04. `st.number_input`, never `st.data_editor`: the stepper buttons
  and the scroll-wheel nudge come from the native input and a NumberColumn has
  neither. **Two number inputs to a row, maximum** — Streamlit drops the
  steppers when a column gets narrow, and three-to-a-row in this sidebar was
  under that threshold while still looking fine in a test. The sidebar is
  widened to 30rem in `styles.py` for the same reason. Measured in a browser,
  not guessed; re-check the steppers if the layout is ever re-compacted.
  `test_the_stack_is_edited_with_native_number_inputs` pins the widget type.
- **A gap has no load field at all** — not a disabled one, not a zeroed one,
  not a placeholder holding an empty column. A spacer carries no bearing, so a
  load box beside it invites a number the model will silently discard.
  `test_a_gap_gets_no_load_field_at_all` pins it.
- **Row widget keys are built from a stable row id, never the list position.**
  Deleting row 1 would otherwise shift every key below it and Streamlit would
  replay row 2's stored value into row 1. `_reset()` must drop every `bb::`
  key for the same reason.
- **Session state is shape-checked, not presence-checked.** Streamlit Cloud
  redeploys under live sessions, so a browser holding the previous format must
  be reseeded rather than crash the page on its next rerun.
  `test_stale_session_state_from_an_older_deploy_does_not_crash`.
- **Station names come from the physical layers, not the strips.** The refined
  analysis is 24 strips per plate, so `layer_name_at` on it reports "plate 36".
  Pass the baseline as `names=` to `peak_html` / `strength_html`, and
  `refined_view.groups()` to the figure.
- **Render HTML with `st.markdown(..., unsafe_allow_html=True)`, never
  `st.html()`.** `st.html` sanitises with an HTML-only profile that strips
  `<svg>` **silently** — the figure column just comes out blank, with no error
  and no warning in the logs. `test_the_figure_actually_reaches_the_page` pins
  it. (`st.iframe` is not an alternative: it takes a URL, not markup.)
- **No browser storage.** Nothing in this module may use `localStorage`,
  `sessionStorage`, or IndexedDB. State lives in Streamlit session state.
- **Colours come from `ui.theme.BOLT_PALETTE`.** No hex literals in
  `plotting.py` or `app.py` — there is a test asserting this
  (`test_svg_uses_only_theme_palette_colours`).
- **Conservative by default.** Any less-conservative option is opt-in and must
  carry a documented basis string that travels with the result.
- **The Method section is part of the deliverable, not decoration.** If the
  mechanics change, update `method.py` in the **same commit**.

## Before you commit

- Run `tests/bolt_bending/`. It ends green.
- The handoff §6 verification case must still reproduce station by station,
  and `V(L)` and `M(L)` must both be zero for every balanced stack.

---

## What the port changed vs the original tool

1. **Handoff §4.1 fixed — force closure gates the margins.** `analyse()`
   reports `balanced`; `margins()` carries it as `valid`; the page suppresses
   every stress and margin and shows a warning banner when it is False. The
   tolerance is a pure ratio (`IMBALANCE_TOL = 0.005` of `max|Pᵢ|`), replacing
   the JS test that mixed an absolute 0.5 lbf floor with a scaled term and
   flipped its verdict under scaling.
2. **Allowables come from the material library.** A `Fastener` category was
   added to `library/materials/materials.py` (six bolt strength levels).
   Selecting one reseeds Ftu/Fsu; both stay editable, and an override is
   labelled as such.
3. **Layout is the original's, not the toolkit's default page furniture.**
   One page, two columns, white cards on the warm ground, the six-cell results
   grid, and the two-column Method section with tinted equation blocks — all
   reproduced from `docs/bolt_bending/index.html` via `styles.py`, with the
   colours remapped to `THEME` / `BOLT_PALETTE`.

   > The first cut of this port used the toolkit's stock furniture — three
   > tabs, `ui.components` cards, Streamlit's default spacing — and it was
   > markedly worse than the single-file tool it replaced: the margins sat
   > behind a tab, so the feedback loop that justifies the tool was gone. The
   > toolkit's conventions exist to make *unrelated* modules feel consistent;
   > they are not a licence to discard a better design that already exists.
   > `beam_section` has tabs because it has seven screens of content. This has
   > one.

   Bolt properties live in the sidebar, which lands at roughly the width of
   the original's left column. Everything else is Python-generated HTML.
4. **`st.data_editor` replaces the hand-rolled row table.** The editor key
   carries a revision counter (`_REV_KEY`) so Reset drops the stored edit
   delta — without it, Reset appears to do nothing. It is wrapped in
   `st.container(border=True)`, restyled in `styles.py` to match `.bb-card`,
   because a live widget cannot live inside a raw-HTML card.

Everything else is a faithful port. In particular the **combined check still
scans every station** rather than pairing `M_max` with `V_max`; those maxima
sit at different places and pairing them is both wrong and over-conservative.
There is a test asserting the scanned result beats the paired one.

---

## Known gaps and backlog

Ranked. The handoff's §5 numbering is kept so the two documents line up.

### §4.2 / §5.1 — Variable section (correctness, deferred)

`Z` and `A` are constant along the bolt, so the critical station is selected
by `max|M|` rather than `max|M/Z|`. With a shank-to-thread transition or an
undercut inside the bending region this can check the wrong station and report
a **non-conservative** margin. On a long grip with a spacer the peak moment
often lands near the thread runout, which is exactly where it bites.

> **⚠️ ASSUMPTION — no threads in the bending region.** Deferred by the owner
> on 2026-09-03: assume no thread runout, undercut, or diameter change falls
> inside the bending region. The assumption is stated in the kernel docstring,
> on the Margins tab, and in Method §7. The `d_section` input is the interim
> mitigation: entering the thread minor diameter is conservative everywhere
> and exact nowhere.

To do it properly: let diameter vary with station (at minimum a shank/thread
transition at a user-entered `x`), then select the critical station by
`max(M/Z)` **and** by the interaction scan, not by `max(M)`.

### §5.2 Phase 2 — beam on elastic foundation — ✅ PARTIALLY DONE (v2.4.0)

The refined bearing pass (`library/bolt_bending/refined.py`, sidebar toggle)
implements the
bearing-distribution half of this: each plate gets an unknown rigid offset with
a Winkler bed between it and the bolt, and the offsets are solved so every
plate transfers exactly the entered load. One linear solve, no iteration.

Each plate carries **its own foundation modulus**, taken from a per-layer
material selector (2026-09-04): a steel doubler and an aluminium skin have
genuinely different bearing stiffness, the peaking follows the stiffer plate,
and one averaged bed would put it on the wrong one. `refined_analysis` takes
either a scalar (one bed) or a per-layer sequence; a short or gappy sequence
falls back to the first stated modulus rather than leaving a plate on a
zero-stiffness bed, which would make the solve singular. `RefinedResult.
mixed_stack` drives the extra material/k columns in the per-plate table and
stops the basis card advertising a single `k` no plate actually has.

What it deliberately does **not** do, and what remains of §5.2:

- **Composite plates are out of scope.** `k = E_plate` is a Tate & Rosenfeld
  *metallic* bearing derivation, and the Huth cross-check ships the metallic
  constants (b = 3.0). A composite laminate needs its own bearing model:
  direction-dependent modulus, a different Huth constant set (b ≈ 4.2 for
  graphite/epoxy), CMH-17 rather than MMPDS allowables, and progressive
  bearing damage instead of yield. Nothing stops a laminate modulus being
  entered by hand once custom materials exist, but the basis string would then
  be wrong, so the material list is deliberately limited to metallics.
- **The load split is still an input.** Determining it needs the plates' own
  in-plane stiffness, which is a different model. This refines only where
  within each plate's thickness the entered load acts.
- **No clearance or one-sided contact.** The bed is linear and two-sided, so a
  negative reaction means bearing on the far side of the hole — right for a
  close fit, wrong for a sloppy one. Adding it makes the solve iterative.
- **No plastic bearing redistribution** at ultimate.

Key implementation notes, so they are not relearned the hard way:

- **Pinning `w` at the head and nut is load-bearing, not cosmetic.** Without it
  the system has two rigid-body null modes and is singular. An early draft used
  a least-squares minimum-norm solve; it looked plausible and drifted with mesh
  (239.4 coarse vs 235.1 fine). The pinned reactions *are* `R_0` and `R_L`.
  `test_converged_and_stable_in_mesh` is the gate.
- **The rigid-bolt limit is the trust anchor.** As `k → 0`, `w ≡ 0`, so
  `q = k·d_i` — uniform bearing, exactly. The refined model provably degenerates
  to the baseline, which is what makes it a correction rather than a rival.
- **`k = E_plate` is derived, not guessed** — the Tate & Rosenfeld bearing term
  (`δ = P/(E·t)` against the Winkler `P = k·δ·t`). Only the *bearing* part
  belongs in `k`: bolt bending is already computed from EI, so folding in a
  lumped joint compliance (Huth, Swift) would double-count it. Huth is carried
  as an independent cross-check instead — ⚠️ its constants are unverified.

### §5.2 — Load-split assistant

The layer loads are statically indeterminate only when two or more layers sit
on the same side of the load path (the two tines of a clevis sharing one total
load). Group each plate to side A or B, enter total `P` once, and split by a
documented rule — equal / proportional to thickness / proportional to `AE/L` /
manual. `ΣP = 0` then holds by construction rather than being checked
afterwards. Keep manual per-layer entry as an escape hatch; do not remove it.

*Phase 2 (larger, optional):* replace uniform bearing with elastic bearing
springs and solve the bolt as a beam on an elastic foundation. That yields the
load split and the bearing distribution simultaneously, and peaking falls out
rather than being assumed away — the honest version of what Melcon & Hoblit
approximated. **Do not start this without discussing scope.**

### §5.3 — Show-work mode

Print each governing equation with numbers substituted at the critical
station. High value for review: the output becomes checkable without
re-deriving. The `Margins` result already carries `critical`, `R_b`, and `R_s`,
so the data is there.

### §5.4 — State export and case links

Serialise inputs to JSON and encode the same state in the URL query params so
a link reproduces a case exactly. Cheapest possible traceability. Note the
no-browser-storage rule — query params and file download only.

### §5.5 — Print / PDF export

Shares the toolkit-wide report-export item (root `CLAUDE.md` near-term 2).
Case ID, analyst, date, revision, inputs, joint elevation, diagrams, results,
method. The figure is already an SVG string, so it drops straight into a PDF
without a rasterisation step.

### §5.6 — Load case table

Multiple cases (limit/ultimate, thermal, several conditions) with a summary
margin table and the governing case flagged. Pairs with separate yield and
ultimate allowables, since the bending shape factor differs between them.

### §5.7 — Plate bearing and shear-out

Cheap to add and they frequently govern before the bolt breaks in bending. A
bolt-bending tool that ignores them can hand back a comfortable margin on the
wrong failure mode. The Method section says so explicitly; the check itself is
not implemented.

### §5.8 — Self-test on load

Run the §6 verification case at startup and display pass/fail, as the
beam-section module's Validation tab does. Currently covered by
`tests/bolt_bending/` instead, which is stronger but not visible in-app.

---

## Not modelled (by design, stated on the page)

Clamp-up, preload, prying, axial load, bearing peaking, plate strength. The
load split between layers is an **input, not a result**.

---

## Verifying a UI change

Tests catch logic; they do not catch a blank column. Two of the worst defects
in this module's history — the figure not rendering at all, and every bold
value in the checks list printing as a tofu box — were invisible to a green
suite and obvious in a screenshot.

There is no browser automation installed, but Chrome is present and speaks the
DevTools protocol, so a screenshot loop is a few lines:

```
python -m streamlit run pages/4_Bolt_Bending.py --server.port 8558 \
       --server.headless true &
# then drive Chrome over CDP: navigate, sleep for the websocket, capture.
```

Chrome's plain `--headless --screenshot` flag is **not** enough: it uses
virtual time, which does not wait for Streamlit's websocket, so it captures
the grey loading skeleton. Wait real seconds over CDP instead. Streamlit also
scrolls inside its own container, so `window.scrollTo` does nothing — scroll
the tallest overflowing element.

Restart the server after editing an imported module; the watcher does not
always pick up changes to `styles.py` or `method.py`, and a stale render will
happily convince you a fix did not work.

## Style notes

- Analyst-facing wording throughout. No introductory framing, no hedging
  padding. Standard aerospace structures terminology.
- The joint elevation is schematic in the **horizontal** direction only — bolt
  width and plate reach are fixed pixel values. The vertical (station) axis is
  dimensionally true and shared by all three panels. Do not let anyone "fix"
  the horizontal scale without realising the diameter-to-grip ratio makes it
  useless.
- Fastener allowables in the library are grade-level nominals carrying a
  ⚠️ VERIFY note. They are for preliminary sizing; a released stress report
  needs the actual part number and diameter from MMPDS-01 Table 8.1.4 or the
  procurement spec.
