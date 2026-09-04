# Bolt Bending Tool — Handoff

Single-file browser tool that builds shear and moment diagrams along a bolt in a
multi-layer joint and reports margins. Written to be droppable on a static host
and openable on a phone.

Status: working, deployed-quality, but has one known correctness gap and one
known bug (see §4). Three enhancement tracks are specified in §5.

---

## 1. File and constraints

`index.html` — one file, no build step, no bundler, no package manager.

These constraints are deliberate. Do not break them without asking:

- **No external runtime dependencies.** The only network reference is the IBM
  Plex Sans webfont, which degrades cleanly to a system stack. Everything else
  must work with the network off.
- **No browser storage.** No `localStorage`, no `sessionStorage`, no IndexedDB.
  All state lives in JS variables.
- **No framework.** Plain DOM and hand-built SVG. Adding React or a chart
  library would defeat the point of the file.
- **Single file.** CSS and JS stay inline. The deliverable is one artifact an
  analyst can email, host, or archive next to a stress report.
- **`index.html` is the filename.** Static hosts serve it at the site root.

## 2. Architecture

Four functions, roughly 400 lines of JS total.

| Function | Role |
|---|---|
| `drawRows()` | Renders the layer input table, wires per-row handlers |
| `analyse()` | All the physics. Pure. Returns a result object, touches no DOM |
| `plot(a)` | Builds the SVG from an `analyse()` result. Rendering only |
| `update()` | Calls `analyse()`, then `plot()`, then writes results and checks |

`analyse()` is the only place mechanics live, and it is deliberately pure —
same input, same output, no DOM reads. Keep it that way. It is the natural
seam for unit tests and for any headless verification harness.

**State:**

```js
layers = [{type: 'plate'|'gap', t: number, P: number}, ...]   // head to nut order
```

Bolt properties and options are read from DOM inputs by `update()`, not stored
in a state object. If the state model grows (load cases, groups), promote these
into a single state object first.

**`analyse()` returns:**

```
{segs, L, pts, sumP, momP, R0, RL, Mmax, Vmax, closeM}
```

- `segs` — one per layer: `{x0, x1, w, type, P, t}`, `w = P/t` (0 for gaps)
- `pts` — sampled stations `{x, V, M}`, 36 per segment plus exact stationary
  points where `V = 0`, sorted by `x`
- `Mmax` — the `pts` entry with the largest `|M|`

## 3. Mechanics (what the code implements)

Bolt as a beam, axis `x` from head face (0) to nut face (`L`). Bearing from
each plate is uniform over that plate's own thickness. Gaps carry no bearing.

```
w_i     = P_i / t_i                        bearing intensity, lbf/in
ΣP_i    = 0                                force closure (checked, not enforced)
M_res   = Σ P_i · x̄_i,  x̄_i = x0_i + t_i/2  residual moment about the head
R_L     = −M_res / L,   R_0 = −R_L         head/nut couple that closes M
```

Segment recursion, `u = x − x0`, constant `w`:

```
V(u) = V_0 + w·u
M(u) = M_0 + V_0·u + ½·w·u²
```

Start `V = R_0`, `M = 0`. Interior peak where `u* = −V_0 / w`, taken only if
`0 < u* < segment length`. Add `R_L` to `V` at the nut.

```
Z  = π d³/32,   A = π d²/4
f_b = M_max / Z,          F_b = k · F_tu   (k = 1.5 default; 1.7 fully plastic)
MS_b = F_b / (f_b · FF) − 1
MS_s = F_su / (f_s · FF) − 1
MS_c = 1 / √( max over stations [ R_b² + R_s² ] ) − 1
```

The combined check scans every station rather than pairing `M_max` with
`V_max`. Those maxima are at different places and pairing them is both wrong
and over-conservative. Preserve this behaviour.

**Not modelled:** clamp-up, preload, prying, axial load, bearing peaking, plate
strength. The load split between layers is an *input*, not a result.

## 4. Known defects — fix these first

### 4.1 Force imbalance silently produces meaningless margins

`R_0 = −R_L` adds no net force. That construction only restores equilibrium if
`ΣP` is already zero. When `ΣP ≠ 0`, the shear diagram does not return to zero
at the nut, `M(L) ≠ 0`, and the reported margins are garbage — but they are
still displayed as ordinary numbers an analyst could paste into a report.

Required behaviour:

- Keep the soft warning (a hard error is wrong; the user is transiently
  unbalanced while typing).
- Tolerance: `|ΣP| > 0.005 · max|P_i|` counts as unbalanced.
- When unbalanced, suppress or visibly badge every margin and stress value.
  Do not render a number that looks trustworthy.
- The existing `balanced` test in `update()` is ad hoc and mixes an absolute
  0.5 lbf floor with a scaled term. Replace it.

Physically, a non-zero `ΣP` means something outside the model is reacting the
difference: friction from clamp-up, transverse head/nut bearing, or — most
often — an input error such as a missing layer or a sign flip.

### 4.2 Single section diameter puts the check at the wrong station

`Z` is currently constant along the bolt. With a shank-to-thread transition or
an undercut, the critical station is `max(M/Z)`, not `max(M)`. On a long grip
with a spacer the peak moment often lands near the thread runout, so the
current model can check the wrong place and report a non-conservative margin.

Required behaviour: allow diameter to vary with station (at minimum a
shank/thread transition at a user-entered `x`), then select the critical
station by `max(M/Z)` and by the interaction scan, not by `max(M)`.

## 5. Enhancement tracks

Ranked. 5.1 and 5.2 are correctness; the rest are capability.

### 5.1 Variable section
See §4.2. Do this with §4.1 — together they are the correctness pass.

### 5.2 Load-split assistant
The layer loads are statically indeterminate only when two or more layers sit
on the same side of the load path (e.g. the two tines of a clevis sharing one
total load). Add a grouping layer above the current input:

- Assign each plate to group A or B (opposing sides of the load path).
- Enter total applied `P` once.
- Split rule per group: equal / proportional to thickness / proportional to
  axial stiffness `AE/L` / manual override.
- `ΣP = 0` then holds by construction rather than being checked afterwards.
- Each rule must carry a short documented basis string that travels with the
  case into any export or printout.

Keep manual per-layer entry working as an escape hatch. Do not remove it.

**Phase 2 (larger, optional):** replace uniform bearing with elastic bearing
springs and solve the bolt as a beam on an elastic foundation. That yields the
load split and the bearing distribution simultaneously, and peaking falls out
rather than being assumed away. This is the honest version of what Melcon &
Hoblit approximated. Do not start this without discussing scope.

### 5.3 Show-work mode
Print each governing equation with numbers substituted at the critical station.
High value for review: the output becomes checkable without re-deriving.

### 5.4 State export and case links
Serialise inputs to JSON, and encode the same state in the URL hash so a link
reproduces a case exactly. Cheapest possible traceability; makes the tool
citable from a report. Note the no-browser-storage rule — URL hash and file
download only.

### 5.5 Print stylesheet
`@media print`: inputs, joint elevation, diagrams, results and method on a
clean page with case ID, analyst, date, revision. Turns the tool into a
substantiation attachment.

### 5.6 Load case table
Multiple cases (limit/ultimate, thermal, several conditions) with a summary
margin table and the governing case flagged. Pairs with separate yield and
ultimate allowables, since the bending shape factor differs between them.

### 5.7 Plate bearing and shear-out
Cheap to add and they frequently govern before the bolt breaks in bending. A
bolt-bending tool that ignores them can hand back a comfortable margin on the
wrong failure mode.

### 5.8 Self-test on load
Run the §6 verification case at startup and display pass/fail. Useful
verification evidence for a toolkit.

## 6. Verification case

The shipped default. Any refactor must still reproduce these numbers.

Plates 1–3 at t = 0.250, 0.500, 0.250 in carrying P = +1000, −2000, +1000 lbf,
with a 0.060 in spacer between plates 1 and 2. `L` = 1.060 in, so every plate
runs at `|w|` = 4000 lbf/in.

`ΣP` = 0. `M_res` = 1000(0.125) − 2000(0.560) + 1000(0.935) = −60 in·lbf.
`R_L` = +56.60 lbf, `R_0` = −56.60 lbf.

| x, in | station | V, lbf | M, in·lbf |
|---|---|---|---|
| 0 | head | −56.6 | 0 |
| 0.250 | end plate 1 | 943.4 | 110.8 |
| 0.310 | end spacer | 943.4 | 167.5 |
| 0.546 | V = 0, plate 2 | 0 | **278.7** |
| 0.810 | end plate 2 | −1056.6 | 139.2 |
| 1.060 | nut, after R_L | 0 | 0 |

With d = 0.315 in: `Z` = 0.003069 in³, `A` = 0.07793 in². `f_b` = 90.8 ksi
against `F_b` = 240 ksi → `MS_b` = +1.64. Shear is zero at the peak-moment
station, so `MS_c` = +1.64 as well.

**The standing arithmetic check:** both diagrams must close at the nut. If
`V(L) ≠ 0` or `M(L) ≠ 0`, the load split or the residual moment has been
mishandled. Assert this in any test harness.

Second case worth adding: symmetric double shear (0.25 / 0.50 / 0.25, no
spacer, +P/2 / −P / +P/2). `M_res` = 0 by symmetry, so `R_0 = R_L = 0` and the
peak moment has a clean closed form to check against.

## 7. Style notes

- Analyst-facing wording throughout. No introductory framing, no hedging
  padding. Terminology is standard aerospace structures.
- Conservative by default; any less-conservative path must be opt-in and
  labelled with its basis.
- The Method section at the bottom of the page is part of the deliverable, not
  decoration. **If the mechanics change, update it in the same commit.** It
  currently documents §3 and the §6 worked example.
- Design tokens are the CSS custom properties at the top. Use them; do not
  hard-code new colours.
- The joint elevation is schematic in the horizontal direction only — bolt
  width and plate reach are fixed pixel values. The vertical (station) axis is
  dimensionally true. Do not let anyone "fix" the horizontal scale without
  realising the diameter-to-grip ratio makes it useless.
