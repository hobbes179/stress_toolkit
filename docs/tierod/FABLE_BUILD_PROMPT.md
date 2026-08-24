# Build Prompt — Tie-Rod Layout Optimizer

**Target:** New module in `stress_toolkit` (Streamlit, Python)
**Units:** IPS throughout (lb, in, psi)
**References:** MMPDS-01, Bruhn, Euler/Johnson column theory

---

## 1. What this tool does

Given a set of rigid bodies connected by tie rods to each other and to ground, find the
rod attachment geometry that minimizes the governing load ratio (maximizes the minimum
margin of safety) across a full sweep of load orientations, subject to the layout being
mechanism-free.

Optionally, enforce **fail-safe**: no single rod failure may create a mechanism.

The engineer supplies the bodies, the surfaces where rods may attach, and which rod
connects which pair of surfaces. The tool places the attachment points within those
surfaces and reports margins, governing load directions, and layout quality.

---

## 2. Platform and integration

- Streamlit module following the existing `apps/<module>/render()` pattern
- Shared `library/` for the analysis kernel; keep the kernel importable and free of any
  Streamlit dependency so it can be unit-tested and later reused
- Plotly for all visualization
- `numpy` / `scipy` for linear algebra and optimization
- No Excel. A spreadsheet export may be added later; do not design around it

---

## 3. Data model

A starting `model.py` is attached. Build on it, with the changes noted in §3.4.

### 3.1 Body

```
Body:
    id
    is_ground: bool          # ground is a FLAG, not a subclass
    origin, R                # body datum placed in global space
    mass, cg                 # body-local; ignored when is_ground
    inertia                  # reserved, see §7.3
    clearance                # obstruction primitive, see §3.3
```

**Ground semantics.** A ground body contributes no DOF block to the assembled stiffness
matrix and no inertial term to the load sweep. It is otherwise a full participant: it has
a frame, it holds regions, it renders. Retain `mass`/`cg` on the record and gray them out
in the UI when grounded — toggling ground must not destroy data.

Requirements:
- **N bodies**, not three. Nothing may be hardcoded to a fixed count.
- **Multiple ground bodies** must work (two separate hard structures).
- **Zero ground bodies** must be handled gracefully: free-free, expected nullity exactly 6.
  This is a legitimate diagnostic mode (checking whether a subassembly is internally
  rigid), not an error.

### 3.2 Region — where a rod end may attach

A region is a bounded manifold of dimension `d ∈ {0,1,2}` embedded in R³, defined in the
**body-local** frame of its parent body. `d` is exactly the number of design variables
that rod end contributes.

| Primitive | d | Parameters |
|---|---|---|
| `FixedPoint` | 0 | — |
| `Segment` | 1 | s |
| `CircleArc` | 1 | θ |
| `PlanarPatch` | 2 | u, v |
| `Annulus` | 2 | ρ, θ |
| `CylindricalBand` | 2 | θ, z |
| `SphericalPatch` | 2 | θ, φ |

Every region exposes the same interface:

```
bounds()      -> [(lo, hi)] * d
point(q)      -> (3,)      body-local position
jacobian(q)   -> (3, d)    dr/dq
```

A body may carry any number of regions.

**Orientation.** Each region stores a full local frame `(e1, e2, e3)`. Assume alignment
with the global axes for now — expose an X/Y/Z or XY/YZ/ZX dropdown that *populates* the
stored triad. Nothing downstream may branch on the dropdown value; arbitrary orientation
must later be a UI addition, not a kernel refactor. `Body.R` stays identity for now but
must exist and be applied.

Note `e3` sets the plane a `CircleArc` lies in (sign irrelevant), and sets the axis and
the `z_min`/`z_max` sense for a `CylindricalBand` (sign matters).

**Optional bracket standoff.** A per-end scalar `h` offsetting the pin point from the
surface along the local outward direction:

```
p_pin = p_surface + h * n_out
```

Default `h = 0`. Include it — a 2 in standoff on a 20 in moment arm is a 10% lever error.

### 3.3 Body clearance primitives

`Body.clearance` must be a real type, not a placeholder. Provide `Sphere`, `Cylinder`,
`Box`, each oriented in space (axis-aligned for now, same dropdown pattern), each exposing:

```
outward(p)                 -> (3,) unit outward normal at a boundary point
distance_to_segment(a, b)  -> float
```

These drive non-penetration (§8.2). Keep bodies to convex primitives — it keeps the
constraint closed-form and differentiable. A mesh-based check would lose gradients and
force derivative-free optimization.

### 3.4 Changes from the attached `model.py`

- **Remove** `Region.mount_axis()`, `Region.misalign_limit_deg`, `CircleArc.axis_mode`.
  These wrongly modelled the rod as constrained to a cone about the surface normal.
  Rods are two-force members on spherical bearings at both ends; the rod axis is
  routinely far from the surface normal and must not be constrained to it.
- **Add** the clearance primitive types of §3.3.
- **Add** the optional standoff `h` per rod end.

### 3.5 Rod and Assembly

```
RodEnd:  region_id, q (length == region.d; empty for FixedPoint), h
Rod:     id, end_a, end_b, E, A, I, Fcy, end_fixity=1.0,
         P_tension_allow (vendor rated; None -> compute), Ftu, A_net
```

Rods are two-force members, spherical bearing both ends, carrying axial load only and no
moment. `end_fixity = 1.0` (pinned-pinned) is the correct default for the column allowable.

**Topology — which pair of regions a rod spans — is a user input, not a design variable.**
It carries manufacturing and access consequences. The optimizer places `q` within the
declared topology. Make it cheap to define several candidate topologies and compare them
side by side.

`Assembly.design_vector_layout()` must skip `d = 0` ends, so a rod anchored to an existing
fitting contributes zero variables with no special-casing.

---

## 4. Analysis kernel

### 4.1 Conventions

Rod *i* runs from point `a` on body *p* to point `b` on body *q*:

```
v = b - a ,  L = |v| ,  û = v / L
P > 0 is TENSION
```

Tension applies `+P û` to body *p* at `a`, and `-P û` to body *q* at `b`.

### 4.2 Assembly

Each body keeps its own datum; rotations are about that datum. Global DOF vector `U`
stacks `[d_p ; θ_p]` for free bodies only, `n_dof = 6 * n_free`.

Rod *i* contributes a column `Ĝ_i ∈ R^{n_dof}`:

```
block for body p (the 'a' end):   + [ û ; a × û ]
block for body q (the 'b' end):   - [ û ; b × û ]
ground bodies:                      no block
```

Then:

```
δ_i = -Ĝ_iᵀ U
k_i = A_i E_i / L_i
K   = Ĝ K_d Ĝᵀ                (n_dof × n_dof)
K U = F
P   = -K_d Ĝᵀ U
```

with equilibrium `Ĝ P = -F`.

**Note this corrects an earlier draft that had `K u = -F`.** Two sign errors cancelled in
the rod loads but inverted the reported displacement, which is the check on the
small-displacement assumption.

Properties the implementation must exhibit:

- `K` is `6·n_free` square regardless of rod count. At 10 free bodies it is 60×60 — dense
  inversion is fine. Do not reach for sparse solvers without evidence.
- When statically determinate, `P = -Ĝ⁻¹F`, **independent of every `k_i`**.
- Factor `K⁻¹` once per geometry; every load case is then a small matrix product.

### 4.3 Load influence matrix

```
G = -K_d Ĝᵀ K⁻¹              (N × n_dof)
```

`P = G F`. This is the object the orientation sweep is built on (§7).

---

## 5. Mechanism and degeneracy detection

This is half the success criterion. Treat it as a first-class feature, not a guard clause.

### 5.1 Graph pre-check (run first)

Nodes = bodies, edges = rods. If a free body lies in a connected component containing no
ground body, report **that body by name** as unsupported. With a dozen bodies,
"Body 4 is not connected to ground" is worth far more than "K is rank deficient by 6."

### 5.2 Rank check

```
rank(K) must equal 6 * n_free
```

Use SVD. Report nullity against expectation. Shortfall = number of independent mechanism
modes.

### 5.3 Mechanism mode animation — required feature

When `rank(K) < 6·n_free`, take the null vectors of `K` from the SVD, interpret each as a
rigid-body displacement per free body, and **animate the bodies along that mode** with
rods drawn in.

Do not report "singular." Show the motion the layout permits. This is the single highest
value output the tool produces and is the main reason this is a web app rather than a
spreadsheet.

### 5.4 Geometric degeneracy checks (interpretable, run alongside the numerics)

State these against a common global reference:

- **All rod lines intersecting a common line** ⟹ free rotation about that line.
  Proof sketch: a rod's screw is a property of its line, so the moment may be taken about
  either endpoint. With the origin on line L (direction ê), every intersection point is
  `t_i ê`, so `m_i = t_i (ê × û_i) ⊥ ê`. No rod can generate moment about ê.
- **Special case worth its own message:** all ground-side attachments collinear. This is a
  guaranteed mechanism for any number of rods in any arrangement, and body-to-body rods do
  not help — the assembly rotates about that line as a rigid unit. A baseplate idealized as
  a *line* rather than a *plane* falls straight into this.
- **All rod lines concurrent at a point** ⟹ all three rotations free about that point
  (every `m_i = 0`).
- **All rod lines parallel** ⟹ no reaction perpendicular to that direction.

Rank deficiency says the design is broken; these say *why*.

### 5.5 Conditioning

`K` mixes units — translation blocks are force/length, rotation blocks force·length. A
condition number on raw `K` is meaningless. Non-dimensionalize with a characteristic
length `L_c` (suggest max attachment radius) before computing any conditioning metric,
and use true singular values from SVD.

Impose `σ_min(K̃) ≥ σ_floor` as an optimization constraint. Without it the optimizer will
find near-singular layouts that score well numerically and are structurally fragile.

---

## 6. Allowables

### 6.1 Tension

The spherical bearing is typically the weakest link in the assembly, so vendor rated load
is the primary input:

- **Primary:** user-entered `P_tension_allow` per rod
- **Fallback:** `A_net * Ftu`

Display which source is active per rod.

### 6.2 Compression — Euler/Johnson

```
ρ      = sqrt(I / A)
L'     = L / sqrt(c)                    c = end_fixity, default 1.0
λ      = L' / ρ
λ_crit = π sqrt(2E / Fcy)

λ ≤ λ_crit  (Johnson):  F_c = Fcy [ 1 - Fcy λ² / (4 π² E) ]
λ > λ_crit  (Euler):    F_c = π² E / λ²

P_comp_allow = F_c * A
```

Both branches give `Fcy/2` at `λ_crit` — verify continuity in test.

**`P_comp_allow` is a function of `L`, and `L` is a design variable.** Lengthening a rod to
improve its direction degrades its own compression allowable. This coupling is why the
objective must be on load *ratio*, not load.

### 6.3 Load ratio

```
LR = P / P_tension_allow     if P >= 0
LR = |P| / P_comp_allow      if P < 0
MS = 1/LR - 1
```

Report per rod: governing case, governing sense (T/C), LR, MS.

---

## 7. Load orientation sweep

The design target is robustness across a full sweep of load orientations. This has a
closed form — **do not sample the sphere.**

### 7.1 Inertial load map

For free body *p* with mass `m_p` and CG at `c_p` (body-local), under acceleration of
magnitude `a` in unit direction `n̂`:

```
W_p = m_p [ I₃ ; [c_p]× ]              (6 × 3)
W   = vstack over free bodies          (n_dof × 3)
F(n̂) = a · W n̂
```

`F` is linear in `n̂`. That is the property that makes this closed-form.

### 7.2 Exact worst case

```
T = G W                                 (N × 3)

max over all orientations:  |P_i| = a · ‖ row_i(T) ‖₂
worst direction:            n̂*_i = row_i(T) / ‖ row_i(T) ‖₂
```

One matrix product, one row norm per rod. No discretization error. `n̂*_i` is the
diagnostic that tells the engineer *why* a rod governs.

**Consequence:** a symmetric sweep loads every rod to ±|P_i|, so both senses reach full
magnitude and only `min(P_tension_allow, P_comp_allow)` matters. For tie rods that is
almost always compression. **A full-sweep design is a buckling-driven design.**

### 7.3 Scope question to resolve before building

`W` above assumes **pure translational** acceleration. If angular acceleration is in
scope, the sweep still has closed form but `W` maps a 6-vector of accelerations, and
"unit magnitude" over a mixed linear/angular space requires a characteristic length to be
well defined. The `Body.inertia` field is reserved for this. Confirm scope — it is much
cheaper to build in now than to retrofit.

### 7.4 Capability polytope

Each rod imposes `|row_i(T)·n̂| ≤ P_allow_i / (m a)`, so the set of survivable load vectors
is a **polytope**. Directional capability:

```
a_max(n̂) = min_i  P_allow_i / ( m |row_i(T)·n̂| )
```

Maximizing its inscribed radius *is* the minimax objective. Compute and plot it anyway —
for an omnidirectional design it shows the weak directions directly rather than as a
scalar.

---

## 8. Optimization

### 8.1 Objective

Epigraph minimax on load ratio:

```
minimize   t
s.t.       t ≥  P_ij / P_tension_allow_i        for all rods i, cases j
           t ≥ -P_ij / P_comp_allow_i(L_i)      for all rods i, cases j
MS_min = 1/t - 1
```

**Write these as two separate one-sided constraints, never as
`max(tension_ratio, compression_ratio)`.** The `max` puts a kink at `P = 0` that stalls
gradient methods. Two smooth one-sided constraints give the identical feasible set.

**Secondary objective (lexicographic):** having converged on minimax, minimize
utilization spread `max LR - min LR` among solutions within tolerance of the optimum. A
slack rod is not a structural problem but it is a robustness signal — under nominal
stiffness assumptions it carries little, and if the backup compliance estimate is off it
may carry a lot.

### 8.2 Constraints

| Constraint | Form |
|---|---|
| Non-penetration | `û · n_out(p) ≥ sin α` at the 'a' end; `-û · n_out(p) ≥ sin α` at the 'b' end |
| Rod-rod clearance | min distance between rod segments ≥ limit |
| Rod length | `L_min ≤ L_i ≤ L_max` |
| Region keep-outs | inequalities in `(u,v)` parameter space |
| Conditioning | `σ_min(K̃) ≥ σ_floor` |
| Parameter bounds | from `region.bounds()` |

**On non-penetration:** for a **convex** body the half-space test is exact, not an
approximation — leaving a convex set in an outward direction means never re-entering it.
It is a half-space, not a cone: a rod leaving a cylinder's side and heading steeply down
to the plate passes trivially; one heading down and *inward* under the body fails. That is
exactly the discrimination wanted.

`α = 0` is pure non-penetration. `α > 0` is an optional manufacturability knob keeping
rods off near-tangent, which would require a tall eccentric bracket. It has nothing to do
with the bearing.

**Edge case:** at a body edge (a circle exactly on a cylinder rim) the supporting normals
span a cone and the correct test is a disjunction — `û·r̂ ≥ 0` **or** `û·ẑ ≥ 0` — which is
non-smooth. Either keep regions off rims or fall back to the distance test there.

### 8.3 Solver

- Gradient-based primary (SLSQP or trust-constr), multistart with bounds from `bounds()`
- Derivative-free verification run (differential evolution) from the converged point; a
  material improvement means the primary found a local minimum
- Seed from a hand-laid engineering baseline, not a random or null geometry

### 8.4 Layout efficiency diagnostic

Rigorous lower bounds on achievable peak load, for reporting how much room is left:

```
max_i |P_i| ≥ |F| / N
max_i |P_i| ≥ |M| / (N · d_max)          d_max = max perpendicular distance to rod line
```

Both hold simultaneously. Report `η = bound / achieved`. `η` near 1 means further geometry
optimization is wasted effort — spend it on sections or load path instead.

---

## 9. Fail-safe design — notes

A user toggle. When on, the layout must remain mechanism-free after **any single rod
failure**. Implementation approach is open; the following are requirements and hazards,
not a prescribed algorithm.

### 9.1 Framing

The most economical framing found so far: **fail-safe is not a mode, it is more cases.**

```
cases = {intact} ∪ {failure_1 ... failure_N}
```

Failure state *j* is the assembly with rod *j* deleted. Everything downstream is unchanged
— the closed-form sweep still holds per state (`T⁽ʲ⁾ = G⁽ʲ⁾W`), so the exact orientation
envelope is preserved, just N+1 times over. For 13 rods and 2 free bodies that is 14
solves of a 12×12 per objective evaluation. Negligible.

If a cheaper or cleaner formulation exists, use it — but it must preserve the exact
orientation envelope rather than falling back to sampling.

### 9.2 Hard requirements (necessary conditions — check and surface immediately on toggle)

Body *p*'s DOF are constrained only by rods touching body *p*. Five constraints can never
fix six DOF regardless of what the rest of the assembly does. Therefore:

```
every free body needs ≥ 7 rod attachments
N ≥ 6 · n_free + 1
```

For two free bodies: **13 rods minimum, and 14 unless at least one rod is body-to-body**
(a body-to-body rod counts as an attachment on both bodies). Against 12 for intact-only.

Surface this in the UI the moment the toggle flips. Discovering it after a failed
optimization run is a bad experience.

### 9.3 Characterization and diagnostic

Rod *j* is critical exactly when its screw is not in the span of the others — equivalently
when it participates in no **self-stress state** (rod forces in internal equilibrium under
zero external load). Self-stress states are the null space of `Ĝ` on the rod-index side:

```
Ns   = null_space(Ĝ)              # (N, r),  r = N - 6·n_free,  orthonormal
rho  = norm(Ns, axis=1)           # rho[j]**2 in [0, 1],  sum(rho**2) == r
```

`rho[j]**2` is the diagonal of the projector onto the self-stress space — the classical
redundancy contribution of rod *j*. Zero means statically determinate in that rod, hence
critical. One means fully redundant.

It is smooth and bounded, and it tells the engineer *which* rods carry the fail-safety
rather than merely whether the layout has it. Report it per rod whether or not the toggle
is on.

### 9.4 Numerical hazard — do not skip

The optimizer will step into regions where some failure state is singular and the recovered
loads blow up to `inf`/`NaN`, killing the run. A barrier is required:

```
σ_min(G̃⁽ʲ⁾) ≥ σ_floor    for every failure state j
```

on the **normalized** screw matrix (§5.5). This covers "no mechanism" and "not
near-mechanism" in one constraint and keeps the solver out of the blow-up region.

### 9.5 Damage factors

Damaged-structure cases are normally assessed against a lower factor than intact.
Checking failure states against the same ultimate criteria as intact will drive the layout
absurdly conservative.

**The case record must carry a per-case `factor` field from the start.** Intact at the
ultimate factor; failure states at whatever the fail-safe criteria specify. The value is
company-specific and user-supplied — the field is not optional.

### 9.6 Generalization (nearly free — build it in)

Define failure cases as **subsets** of rods to remove rather than singletons. Defaults to
one rod per case, but the same loop then covers "this bracket fails and takes three rods
with it," which is often the more realistic threat than a single rod letting go.

### 9.7 Expected behavior

What gets harder is the optimization landscape, not the cost per evaluation. The feasible
set shrinks substantially and the optimum frequently sits near a boundary where some
failure state is close to singular. **Multistart matters more with the toggle on than
off** — budget for it.

---

## 10. Visualization

Plotly, interactive 3D. Camera orbit/zoom/pan is native. There are no 3D drag handles in
Plotly — object manipulation is via controls, not the mouse. This is accepted; the
optimizer moves the points in anger and the sliders are for probing.

### 10.1 Scene contents

| Element | Trace |
|---|---|
| Bodies | `Mesh3d`/`Surface`, translucent, from `Body.clearance` |
| 2-D regions | `Surface`, from `region.point(q)` on a grid |
| 1-D regions | `Scatter3d` lines, from `region.point(q)` swept |
| Rods | `Scatter3d` lines, **colored by load ratio** |
| CG markers | `Scatter3d` markers |
| Worst-case direction | `Cone` per selected rod, along `n̂*_i` |
| Capability polytope | separate `Mesh3d` view |

**The `point()` that feeds the optimizer is the same function that feeds the mesh.**
Never write geometry twice.

### 10.2 Controls

One slider per design variable, ranges taken from `region.bounds()`. A `PlanarPatch` end
gets two sliders, a `CircleArc` end gets one, a `FixedPoint` end gets none — the UI
generates itself from the model with no per-type code.

### 10.3 Implementation details that will otherwise bite

- **`uirevision` is mandatory.** Streamlit reruns the whole script on every widget change.
  Without a constant `uirevision` in the layout the camera resets on every slider tick and
  the tool is unusable. This is the most common way Streamlit + Plotly 3D goes wrong.
- **`scene.aspectmode = 'data'`.** Otherwise axes normalize independently and geometry
  renders distorted — rod angles look wrong, which is exactly what the engineer is judging
  by eye.
- **Split static from dynamic traces.** Bodies, regions and CG markers never move during
  optimization. Cache them; rebuild only rod traces per rerun. The solve is microseconds;
  figure serialization is the only real cost.

---

## 11. Traceability

**The optimizer output is a geometry, not a stress result.** Solver iteration history is
not auditable and must not appear in any certification document.

```
optimize -> extract converged parameters -> re-run through the clean kernel -> Report page
```

The Report page must be a single-pass evaluation with fully traceable intermediates
(screws, K, K⁻¹, rod loads, allowables, margins), reproducible by hand from the equations
in §4 and §6. That is the deliverable; the optimization is a design aid.

---

## 12. Validation

Golden-value tests with closed-form expected results, as pytest plus an in-app Validation
page.

| # | Case | Expected |
|---|---|---|
| V1 | Single rod along +X, unit axial load | `P = F` |
| V2 | Symmetric 3-rod tripod, half-angle θ, vertical load | `P_i = F / (3 cos θ)` |
| V3 | 6-rod hexapod, one body, nonsingular | matches hand equilibrium |
| V4 | **V3 with all `A·E` randomly scaled** | **loads unchanged** — proves determinate independence and that the redundant path reduces correctly. Highest-value test in the set. |
| V5 | Symmetric 4-rod redundant, equal k, symmetric load | equal loads |
| V6 | V5 with one rod stiffness doubled | load shifts in known proportion |
| V7 | 5 rods, one free body | mechanism detected, no numerical output |
| V8 | All ground attachments collinear | mechanism flagged; null vector is rotation about that line |
| V9 | Column allowable at `λ = λ_crit` | both branches return `Fcy/2` |
| V10 | 3 rods, pure vertical load, angle free | optimizer recovers vertical, `P = F/3` |
| V11 | Two free bodies, body-to-body rods, N ground rods | rank = 12; per-body graph check passes |
| V12 | Zero ground bodies | nullity exactly 6, reported as expected not as error |
| V13 | Statically determinate layout | every `rho[j]**2 == 0`; fail-safe toggle reports infeasible |
| V14 | Known redundant layout | `sum(rho**2) == N - 6·n_free` |
| V15 | Closed-form sweep vs. dense sampled sphere | agreement to solver tolerance |

V4, V7, V8 and V15 are the tests that catch failure modes with real consequences.

---

## 13. Phase plan

| Phase | Content | Gate |
|---|---|---|
| **0** | Data model, kernel, multi-body assembly, rank + graph + geometric degeneracy checks, mechanism-mode animation, static Plotly scene | V1–V8, V11, V12 pass |
| **1** | Allowables, load ratio, MS, closed-form orientation sweep, worst-direction reporting | V9, V15 pass |
| **2** | Optimization: objective, constraints, multistart | V10 passes |
| **3** | Fail-safe toggle, self-stress diagnostic, per-case factors | V13, V14 pass |
| **4** | Capability polytope, efficiency diagnostic, utilization spread, Report page | two independent solver paths agree |
| **5** | Section selection from catalog; backup structure compliance bounding | — |

**Phase 0 ships alone and is independently useful.** A correct multi-body rod-load
extractor with mechanism-mode visualization has standalone value regardless of whether the
optimization layer is ever built. Do not hold it hostage to later phases.

---

## 14. Deferred

- Spherical bearing free play (deadband in redundant layouts — nonlinear)
- Installation preload / turnbuckle locked-in load: `K U = F + Ĝ K_d δ₀`
- Fit-up tolerance stack effects
- Flexible bodies
- Backup structure compliance (series stiffness at rod ends)
- Fatigue / damage tolerance
- Arbitrary (non-axis-aligned) primitive orientation — UI only, kernel already supports
- Load case CSV import, PDF report export
- Excel port

---

## 15. Decisions to confirm before building

1. Angular acceleration in the sweep (§7.3) — in or out?
2. Fail-safe damage factor (§9.5) — value, or user-input only?
3. Rod section: fixed per rod, or a design variable snapped to a catalog?
4. Backup structure compliance — Phase 5 as listed, or needed earlier? Redundant load
   distribution is sensitive to it and rigid-backup alone is not a defensible basis for a
   redundant installation.
5. Default `σ_floor` and `α` values, or expose both as user settings?
