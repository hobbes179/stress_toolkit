# Implementation Plan — `tierod` module in stress_toolkit

**Executor:** Claude Code
**Push 1 scope:** Phases 0–1 (Sessions 1–5). Later phases sketched only.
**Companion file:** `apps/tierod/CLAUDE.md` — conventions and locked decisions. Read it
at the start of every session. Update its status checklist at the end of every session.

---

## Global rules for every session

1. Read `apps/tierod/CLAUDE.md` first.
2. Write the session's gate tests BEFORE implementation. Gates are the V-numbers from
   the build prompt plus V16–V17 below.
3. Nothing in `library/tierod/` imports Streamlit. Ever.
4. Stop at the session boundary. Do not begin the next session's files even if it seems
   convenient.
5. Run the full `tests/tierod/` suite before ending a session; a session ends green.
6. Update the CLAUDE.md status checklist and note any deviation from this plan.

---

## Repo placement

```
stress_toolkit/
  apps/tierod/
    CLAUDE.md
    render.py
    ui_inputs.py
    ui_scene.py
    ui_results.py
  library/tierod/
    __init__.py
    model.py
    clearance.py
    cases.py
    kernel.py
    mechanisms.py
    allowables.py
    sweep.py
  tests/tierod/
    conftest.py          # golden fixtures shared across test files
    test_geometry.py
    test_kernel.py
    test_mechanisms.py
    test_allowables.py
    test_sweep.py
```

Hook the module into the existing multipage nav the same way the other apps register.
Phase-2+ files (`optimize.py`, `failsafe.py`, `ui_report.py`) are NOT created in push 1.

---

## Load case convention (locked — this is §7.1/§7.2 of the build prompt)

> **Revised 2026-08-21 by the owner.** An earlier draft of this section used a
> *box* convention: per-body `g_factors = (gx, gy, gz)` with cases as sign vectors
> `s ∈ {-1,0,+1}³` applying every active axis at full factor simultaneously. That
> made multi-axis cases larger than single-axis ones (a corner at `g = (3,3,6)` is
> 7.35 g vs 6.00 g on `+Z`, and 1.0–1.73× the ellipsoid depending on the rod). The
> owner's requirement is **every case the same magnitude, direction only varying**.
> The box convention and gate V17 as originally written are withdrawn.

Each body carries `mass` and a **scalar** load factor `G_p` (`Body.g_factor`).
Magnitude lives on the body; the case supplies only a direction.

A **case** is a **unit direction** `n̂` plus a per-case `factor`. One direction is
shared by every body. The default set is `cube26`: the 6 face, 12 edge and 8 corner
normals of a cube, **normalized** — 26 well-spread, engineer-nameable directions,
all of magnitude 1.

```
W_p = m_p G_p [ I₃ ; [c_p]× ]            (6×3, free bodies only)
W   = vstack(W_p)                         (n_dof × 3)
F_c = W n̂_c                               applied load for case c
P_c = G F_c = T n̂_c ,   T = G W           (N×n_cases in one matmul)
```

**Exact envelope (closed form).** `F` is linear in `n̂` and `‖n̂‖ = 1`, so the true
worst case over ALL orientations is

```
max |P_i| = ‖row_i(T)‖₂       at    n̂*_i = row_i(T) / ‖row_i(T)‖₂
```

This is the **reportable governing value**. The enumerated set is a readable
*sample* of the sphere: it can only under-predict the closed form, never exceed it,
with equality exactly when a sampled direction lands on `n̂*_i`. Report the closed
form and label it with the nearest enumerated case name plus the angle to it
(`cases.nearest_case`), so the shortfall of the sampling is visible rather than
hidden. Do **not** treat the enumerated maximum as the envelope.

**Extensibility.** `cases.DIRECTION_SETS` is a registry (`axes6`, `cube26`) and
`cases_from_directions()` accepts any custom sweep. A finer set is a new entry, not
a refactor: nothing downstream may branch on which set is in use — the kernel and
sweep see only a `(3, n_cases)` matrix of unit columns.

New validation cases:

| # | Case | Expected |
|---|---|---|
| V16 | Case generator | every case unit magnitude; 26 unique directions (6 face / 12 edge / 8 corner); antipodally symmetric; stable ordering & naming (`+X`, `+X+Y`, `+X-Y+Z`, …); registry honoured |
| V17 | Envelope vs sample | per-rod max over the enumerated set ≤ `‖t_i‖₂` for every rod; the closed-form direction `n̂*_i = t_i/‖t_i‖₂` reproduces `‖t_i‖₂` exactly. (Replaces the withdrawn L1 corner identity.) |

---

## Session 1 — scaffold, data model, clearance

**Files:** package scaffold, `model.py`, `clearance.py`, `cases.py`,
`tests/tierod/test_geometry.py`, `conftest.py`, `CLAUDE.md` (from companion draft).

**Work:**
- Port the draft `model.py` with the §3.4 revisions: delete `mount_axis`,
  `misalign_limit_deg`, `axis_mode`; add per-end standoff `h`; add per-end optional
  series stiffness `k_backup` defaulting to rigid (the Phase-5 hook — field only, unused).
- Add scalar `g_factor` to `Body`; `sweep_block()` becomes `m G [I;[c]×]`, error on
  ground bodies. (Was `g_factors` 3-vector + `diag(g)` before the 2026-08-21 revision.)
- `clearance.py`: `Sphere`, `Cylinder`, `Box`, axis-aligned orientation via stored triad
  (dropdown populates, nothing branches on it). Each exposes `outward(p)` and
  `distance_to_segment(a, b)`.
- `cases.py`: unit-direction case generator per the convention above; case record
  carries `id, name, direction, factor` (direction normalized on construction; factor
  default 1.0, the fail-safe damage factor uses this same field later). Direction sets
  live in a registry so a finer sweep is additive.

**Tests first:**
- Every region primitive: `jacobian(q)` vs central finite difference of `point(q)` at
  random interior q, tol 1e-6.
- Frame orthonormality after every dropdown-populated construction.
- Clearance: known distances (segment through / tangent / clear of each primitive);
  `outward` unit-length and outward-pointing on sampled boundary points.
- V16.

**Gate:** geometry tests green. No kernel code exists yet.

---## Session 2 — kernel

**Files:** `kernel.py`, `test_kernel.py`.

**Work:** exactly §4 of the build prompt. `assemble(assembly) -> Ĝ, K_d, K`;
`solve(K, F) -> U`; `rod_loads -> P = -K_d Ĝᵀ U`; `influence -> G = -K_d Ĝᵀ K⁻¹`.
Per-body datums; ground bodies contribute no block. Factor `K⁻¹` once, reuse across
cases. `k_i` uses `k_backup` in series when finite (defaults leave it pure rod).

**Tests first:** V1–V6. V4 (random `A·E` scaling leaves determinate loads unchanged) is
the highest-value test — implement it with at least 20 random draws.

**Gate:** V1–V6 green.

---

## Session 3 — mechanisms

**Files:** `mechanisms.py`, `test_mechanisms.py`.

**Work:**
- Graph pre-check: free body in a component with no ground body → report body by name.
- SVD rank check on non-dimensionalized `K̃`; nullity vs `6·n_free` expectation;
  zero-ground expectation is nullity exactly 6, reported as expected-free-free, not
  error. **`L_c` (max attachment radius) and the boolean rank test already exist as
  `Assembled.L_c` / `.nondim_screws()` / `.rank` — built in Session 2 because
  `influence()` is unsafe without them. Consume those, do not recompute.** What is new
  here is the diagnosis: which motion, which body, which geometric degeneracy.
- Null vectors returned as per-body rigid displacement modes (the animation payload).
- Geometric checks: all rod lines meet a common line / concurrent / parallel;
  collinear-ground-attachments special-cased with its own message.

**Tests first:** V7, V8 (assert the recovered null mode IS rotation about the plate
line, not just that nullity == 1), V11, V12.

**Gate:** V7, V8, V11, V12 green. **End of kernel-side Phase 0.**

---

## Session 4 — Phase 0 UI: viewer + mechanism animation

**Files:** `render.py`, `ui_inputs.py`, `ui_scene.py`; nav registration.

**Work:**
- Input editors for bodies (mass, cg, g-factors, ground toggle that grays rather than
  clears), regions (type + axis dropdown + size params), rods (topology as region-pair
  selection).
- Scene per §10: bodies translucent from clearance primitives, regions from `point(q)`
  (grid for d=2, sweep for d=1), rods as lines, CG markers. `uirevision` constant,
  `aspectmode='data'`, static traces cached via `st.cache_data`, only rod traces rebuilt.
- Sliders auto-generated from `region.bounds()` per design-vector layout — no per-type
  UI code.
- Mechanism panel: run checks on every rerun; when null modes exist, animate bodies
  along the mode (Plotly frames or a phase slider — either is acceptable) with rods
  drawn; show graph/geometric diagnostics as plain-language messages.

**Gate:** manual checklist — camera survives slider moves; a deliberately collinear
plate layout animates rotation about the plate line and names the cause; ground toggle
round-trips without data loss. **Phase 0 ships to main.**

---

## Session 5 — allowables + sweep (Phase 1)

**Files:** `allowables.py`, `sweep.py`, `ui_results.py`, `test_allowables.py`,
`test_sweep.py`.

**Work:**
- Euler/Johnson per §6.2 (`end_fixity` default 1.0), tension source selection
  (vendor rated primary, `A_net·Ftu` fallback, active source displayed), LR/MS per §6.3.
- `sweep.py`: `T = G W`; per-case loads `T @ N` for the unit-direction matrix; per-rod
  **closed-form envelope** `‖t_i‖₂` and worst direction `n̂*_i = t_i/‖t_i‖₂` (the
  reportable governing value and the cone glyph); enumerated per-case loads for the
  case table; `nearest_case(n̂*_i)` for the label + coverage angle.
- Results table: per-rod governing value (closed form), sense (T/C), nearest enumerated
  case name and its angle to `n̂*_i`, P, allowable + source, LR, MS, sorted by LR. Rods
  in the scene recolored by LR; cone on the selected rod along `n̂*_i`.

**Tests first:** V9 (branch continuity at `λ_crit`), V15 (closed-form vs dense sampled
directions — now the primary envelope gate), V17 (enumerated ≤ closed form).

**Gate:** V9, V15, V16, V17 green. **End of push 1.**

> **Done 2026-08-22.** As built also includes a **rod editor** (spec table + group
> assignment) and **SF yield / SF ultimate input cells**, neither listed above:
> Session 5 makes the strength fields load-bearing and there was nowhere to enter
> them. `sweep.run_sweep(..., active_rods=...)` carries a rod mask from the start so
> Phase 3's failure states are a parameter. `Rod.Fty` added. One real bug fixed:
> `Body.sweep_block()` used a body-local moment arm where a global one was required.
> See `apps/tierod/CLAUDE.md` "Session 5 as-built notes".

---

## Definition of done, push 1

- Full `tests/tierod/` suite green in CI alongside the existing toolkit tests
- Module registered in nav and deployed via the normal Streamlit Cloud flow
- CLAUDE.md status checklist current
- A saved demo assembly (2 cylinders + baseplate, 12 rods) loads, solves, and reports
  margins end-to-end

---

## REFRAMED 2026-08-22 — the objective changed

The owner redefined the deliverable: **the tool answers "where do we tie this
down", not "are the margins positive".** Margins became a feasibility gate;
slenderness and complexity became the objective. This **overturns §8.1** of the
build prompt. The authoritative statement is the top of `apps/tierod/CLAUDE.md`
("What this tool is for"); the phase plan below is superseded by the session
list there.

Consequences for the sketch below:

- **Phase 3 (`failsafe.py`) was pulled forward and built as Session 7**, because
  its scoring (`ρ²`, `λ`, `σ_min`, per-removal margins) is what a layout search
  ranks candidates with. Gates V13/V14 are covered by
  `tests/tierod/test_failsafe.py`.
- **Phase 2 (`optimize.py`) is re-aimed, and was built as Session 8.** The
  epigraph minimax on load ratio is no longer the objective — it is a constraint
  (`MS ≥ ms_required`). The objective is lexicographic `(max λ, Σ L, N)` and the
  search chooses rod COUNT as well as positions, seeded from symmetric families
  plus random draws and refined with bounded L-BFGS-B on a smooth surrogate.
  Topology stays a user input in the sense that matters: the search picks only
  from the region pairs the space offers, and `LayoutSpace.restrict()` narrows
  them. Gate: `tests/tierod/test_optimize.py`.

  Three things the plan did not anticipate, all recorded in
  `apps/tierod/CLAUDE.md` "Session 8 as-built notes":
  a symmetric seed with **no twist between its two ends is a mechanism** at any
  rod count; the constraint penalty must be **additive in units of λ_crit**
  (multiplying it by the slenderness stalled L-BFGS-B after one iteration); and
  the search is a **stochastic local method** whose achieved quality at a small
  seed budget is not stable enough to assert against — quality gates are
  categorical or relative to the run's own seeds.

- **The construction UI (Session 9, `apps/tierod/ui_build.py`) was never a
  phase in this plan.** It closes the gap the owner named directly ("how does a
  user define their geometry?"): before it, the only way in was to write a
  Python function in `examples.py`. It drives the Session 6 model layer —
  `REGION_TYPES` / `CLEARANCE_TYPES`, `new_region` / `new_rod`, the
  add/remove cascade, and `serialize` for JSON download and upload — and adds
  no engineering of its own. The one substantive discovery, recorded in
  `apps/tierod/CLAUDE.md` "Session 9 as-built notes": **Streamlit silently
  hands back stale widget state outside a widget's declared range**, so an
  edit that narrows a region can poison the model on the following rerun.
  `apply_rod_q` now clips into `region.bounds()` as the backstop.

- **Session 10 wired the engine to the app** (`apps/tierod/ui_search.py`).
  Sessions 7 and 8 built `failsafe.py` and `optimize.py` with full test
  coverage but no caller anywhere under `apps/` — the reframed deliverable was
  reachable only from a script. The "Find a layout" tab now runs the search
  behind a costed button, plots the N-vs-lambda trade curve, and adopts a
  chosen candidate into the live model. See `apps/tierod/CLAUDE.md`
  "Session 10 as-built notes".

## Later pushes (sketch only — do not start)

- **Phase 2 (`optimize.py`):** epigraph minimax over rods × 26 cases × 2 senses as
  separate one-sided constraints; SLSQP/trust-constr with numerical gradients first;
  multistart from `bounds()`; constraints per §8.2 including `σ_min(K̃) ≥ σ_floor` and
  the non-penetration half-space tests (sign flip at the 'b' end). Gate V10.
  _Superseded objective — see the reframing above._
- **Phase 3 (`failsafe.py`):** ✅ built as Session 7. Case-set expansion over
  rod-removal subsets (default singletons, arbitrary tuples supported);
  `rho[j]²` reported always; `N ≥ 6·n_free+1` pre-check surfaced. Gates V13, V14.
- **Phase 4:** capability polytope view, efficiency bounds η, utilization spread,
  Report page (clean single-pass kernel re-run of converged geometry — the auditable
  artifact).
- **Phase 5:** catalog section snap; activate `k_backup` bounding runs.
