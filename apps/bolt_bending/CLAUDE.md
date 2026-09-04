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
- **One page. Nothing behind a tab.** The stack, the diagrams, the margins and
  the checks must all be visible at once — the point of the tool is changing a
  load and watching the moment peak and the margin move together. Splitting
  that across tabs is the regression that forced the 2026-09-03 rebuild;
  `test_nothing_is_hidden_behind_a_tab` pins it.
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
