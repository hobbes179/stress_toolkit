"""
Physical interference between rods, bodies and each other.

The tool must never propose a layout that cannot be built. Until this module
existed it happily could: nothing checked whether a rod passed through a tank.

**Why the existing `distance_to_segment` could not do this job.** Every
clearance primitive already had a tested distance function, but
`distance_to_point` returns 0 for anything *not outside* — measured on a
cylinder of radius 3:

    a point on the surface   -> 0.0
    a point at the centre    -> 0.0
    a rod skimming the wall  -> 0.0
    a rod driven through it  -> 0.0

Since every legal rod *touches* the body it is bolted to, a "distance > 0"
rule rejects every valid layout and accepts every invalid one — exactly
backwards. What is needed is signed **penetration depth**: how far inside the
solid the rod actually goes. That is what this module adds.

Two checks, per the owner's scope decision (2026-08-23):

* **rod vs body** — no rod may pass through any body's clearance shell.
* **rod vs rod** — no two rods may occupy the same space, EXCEPT that rods
  sharing a pin are allowed to meet there (see `_trim_shared_ends`).

Rod-vs-region was deliberately excluded: regions sit on the bodies whose
shells are already checked.

**The asymmetry that makes rod-vs-body work.** A rod is bolted to two bodies,
so it touches them by construction — demanding a gap from the thing you are
bolted to is meaningless. So:

    the two bodies a rod attaches to   ->  depth must be ~0 (no interpenetration)
    every other body                  ->  gap must be >= min_gap

A rod chording straight through its own tank still has real depth and is still
caught; a rod sitting tangent to its own mounting face is not.

**Resolution, and where the correction applies.** Clearance along a rod is
sampled at `SAMPLES` points rather than solved in closed form. For pairs that
are not bolted together the sampled minimum is reduced by half the sample
spacing (`sample_margin`): a signed distance field is 1-Lipschitz, so that
makes the result a genuine *lower bound* — pessimistic by at most that much,
never optimistic. Raise `samples` to tighten it.

That correction is deliberately **not** applied to the body a rod is bolted
to. Applying it everywhere was the first version's bug: the endpoint sits
exactly on the surface at clearance 0, so subtracting the margin made every
legitimate rod look like it penetrated its own mounting face by exactly the
margin, and the shipped demo went from clean to twelve interferences.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from library.tierod.model import Assembly

#: Default minimum clearance between things that are not bolted together.
#: Not zero: real hardware needs wrench access, not tangency.
MIN_GAP_DEFAULT = 0.25

#: Samples along each rod when measuring penetration depth. See the module
#: docstring — this is a resolution limit, not an approximation to a tolerance.
SAMPLES = 33

#: A rod end sits ON the surface it bolts to, so depth there is 0 up to
#: floating point. Anything under this is contact, not interference.
DEPTH_TOL = 1e-7

#: Two rod ends closer than this are one pin, not two. See `_trim_shared_ends`.
_SHARED_PIN_TOL = 1e-6


# ----------------------------------------------------------------------
# Signed clearance -- one vectorized pass, no golden section
# ----------------------------------------------------------------------
#
# The obvious build of this module called the existing `distance_to_segment`
# for the non-penetrating cases. Measured: 0.38 ms per call, because it
# golden-sections a pure-Python distance function. That made one clearance
# check 6 ms against the 0.5 ms of `layout_metrics` it has to sit beside in
# the optimizer's inner loop -- a 12x tax that would have turned a four-minute
# search into fifty. So clearance is a closed-form signed distance field
# instead, evaluated on the whole sample grid at once.


def signed_clearance(prim, P):
    """Signed distance from each point of `P` (n, 3) to the solid.

    **Positive outside, negative inside** -- one number that answers both
    questions the check needs. An unsigned "depth" function was the first
    design and it could not tell a rod skimming a wall from one driven through
    the middle: plain distance is 0 for both.

    Exact and vectorized for all three primitives. Each is the standard convex
    signed-distance construction: the outside term is the norm of the positive
    part, the inside term is the largest (least negative) component.
    """
    from library.tierod.clearance import Box, Cylinder, Sphere

    P = np.atleast_2d(np.asarray(P, dtype=float))
    local = (P - prim.origin) @ prim.E          # (n, 3), primitive-local

    if isinstance(prim, Sphere):
        return np.linalg.norm(local, axis=1) - prim.radius

    if isinstance(prim, Cylinder):
        # Collapse to the 2-D (radial, axial) box of the cylinder's profile.
        half = 0.5 * (prim.z_max - prim.z_min)
        mid = 0.5 * (prim.z_max + prim.z_min)
        d = np.stack(
            [
                np.linalg.norm(local[:, :2], axis=1) - prim.radius,
                np.abs(local[:, 2] - mid) - half,
            ],
            axis=1,
        )
    elif isinstance(prim, Box):
        d = np.abs(local) - np.asarray(prim.half_extents, dtype=float)
    else:
        raise TypeError(
            f"no clearance rule for {type(prim).__name__}; add one here when "
            f"a new clearance primitive is introduced"
        )

    outside = np.linalg.norm(np.maximum(d, 0.0), axis=1)
    inside = np.minimum(np.max(d, axis=1), 0.0)
    return outside + inside


def depth_at_points(prim, P):
    """How far inside `prim` each point lies; 0 outside."""
    return np.maximum(0.0, -signed_clearance(prim, P))


def sample_margin(A, B, samples: int = SAMPLES):
    """How much a sampled minimum may over-report the true one, per segment.

    A signed distance field is 1-Lipschitz, so between two samples a spacing
    apart it can dip by at most half that. Subtracting this turns a sampled
    minimum into a genuine LOWER BOUND on the true clearance — pessimistic by
    at most this much, never optimistic.
    """
    A = np.atleast_2d(np.asarray(A, dtype=float))
    B = np.atleast_2d(np.asarray(B, dtype=float))
    return 0.5 * np.linalg.norm(B - A, axis=1) / max(int(samples) - 1, 1)


def segment_clearance(prim, A, B, samples: int = SAMPLES):
    """Sampled signed clearance for each segment A[i]-B[i]. Shape (n,).

    **Raw, uncorrected.** Apply `sample_margin` where a conservative bound is
    wanted — which is not everywhere, and getting that wrong was a real bug in
    the first version of this module: subtracting the margin unconditionally
    made every rod appear to penetrate the body it is BOLTED TO by exactly the
    margin, and the shipped demo went from clean to twelve interferences.

    The endpoints are sampled exactly (`linspace` includes 0 and 1), so a rod
    touching its own mounting face reads exactly 0 here. That is the number the
    attached-body test needs; the margin belongs only to the pairs whose
    minimum can fall between samples.
    """
    A = np.atleast_2d(np.asarray(A, dtype=float))
    B = np.atleast_2d(np.asarray(B, dtype=float))
    n, s = A.shape[0], int(samples)
    t = np.linspace(0.0, 1.0, s).reshape(1, -1, 1)
    P = A[:, None, :] + t * (B - A)[:, None, :]          # (n, s, 3)
    return signed_clearance(prim, P.reshape(-1, 3)).reshape(n, s).min(axis=1)


def segment_depth(prim, a, b, samples: int = SAMPLES) -> float:
    """Deepest penetration of one segment into `prim`. 0 if it stays out."""
    return float(max(0.0, -segment_clearance(prim, [a], [b], samples)[0]))


# ----------------------------------------------------------------------
# Segment to segment -- rod against rod
# ----------------------------------------------------------------------


def segment_gaps(P1, Q1, P2, Q2):
    """Closest approach for a whole batch of segment pairs. Shape (n,).

    Vectorized for the same reason as the clearance field: rod-vs-rod is
    O(N^2) pairs and it runs on every candidate. The branch-free `where` form
    is the scalar clamped algorithm with every branch evaluated and selected,
    which beats a Python loop well before the pair count gets large.
    """
    P1, Q1, P2, Q2 = (np.atleast_2d(np.asarray(v, dtype=float))
                      for v in (P1, Q1, P2, Q2))
    d1, d2, r = Q1 - P1, Q2 - P2, P1 - P2
    a = np.einsum("ij,ij->i", d1, d1)
    e = np.einsum("ij,ij->i", d2, d2)
    b = np.einsum("ij,ij->i", d1, d2)
    c = np.einsum("ij,ij->i", d1, r)
    f = np.einsum("ij,ij->i", d2, r)

    tiny = 1e-15
    a_s, e_s = np.maximum(a, tiny), np.maximum(e, tiny)
    denom = a * e - b * b
    safe = np.where(denom > tiny, denom, 1.0)
    s = np.clip(np.where(denom > tiny, (b * f - c * e) / safe, 0.0), 0.0, 1.0)
    t = (b * s + f) / e_s

    # Clamping t invalidates s, so re-solve s on each clamped branch.
    s_lo = np.clip(-c / a_s, 0.0, 1.0)
    s_hi = np.clip((b - c) / a_s, 0.0, 1.0)
    s = np.where(t < 0.0, s_lo, np.where(t > 1.0, s_hi, s))
    t = np.clip(t, 0.0, 1.0)

    # A degenerate segment has no direction to slide along; pin it to its end.
    s = np.where(a <= tiny, 0.0, s)
    t = np.where(e <= tiny, 0.0, t)
    return np.linalg.norm(
        (P1 + s[:, None] * d1) - (P2 + t[:, None] * d2), axis=1
    )


def segment_gap(p1, q1, p2, q2) -> float:
    """Closest approach between two finite segments."""
    return float(segment_gaps([p1], [q1], [p2], [q2])[0])


def _trim_shared_ends(A1, B1, A2, B2, required):
    """Pull co-mounted rods back from the pin they share. Returns the four
    trimmed endpoint arrays.

    **Two rods on one lug is normal hardware** — a bipod, a hexapod pair, any
    fitting that takes two eyes on a common bolt. Measured raw, such a pair has
    a gap of exactly zero and reads as a clash, which condemns most real
    layouts. (It condemned three shipped fixtures the moment the check went
    into the feasibility gate.)

    But co-mounted rods are not unconditionally fine either: two of them nearly
    collinear occupy the same space for their whole length. Straight segments
    from a common point diverge monotonically, so the honest question is how
    fast they separate — and the natural distance to ask it at is `required`
    itself, the clearance those rods need from each other anyway. Each rod is
    trimmed back by that much from the shared end and the gap measured on what
    is left. No new tolerance is invented: a pair that has diverged by then
    clears, and a near-parallel pair still reads as interfering.
    """
    A1, B1, A2, B2 = (np.array(v, dtype=float, copy=True) for v in (A1, B1, A2, B2))
    required = np.asarray(required, dtype=float)
    for e1, o1 in ((A1, B1), (B1, A1)):
        for e2, o2 in ((A2, B2), (B2, A2)):
            shared = np.linalg.norm(e1 - e2, axis=1) <= _SHARED_PIN_TOL
            if not shared.any():
                continue
            for end, other in ((e1, o1), (e2, o2)):
                d = other[shared] - end[shared]
                length = np.linalg.norm(d, axis=1, keepdims=True)
                # Never trim past the far end: a rod shorter than the clearance
                # it needs would otherwise invert.
                step = np.minimum(required[shared][:, None], 0.49 * length)
                end[shared] += np.divide(d, np.maximum(length, 1e-15)) * step
    return A1, B1, A2, B2


def rod_radius(rod) -> float:
    """Effective radius from the rod's section area.

    ASSUMPTION: solid round bar, `r = sqrt(A/pi)`. A tube of the same area is
    fatter than this says, so the check is unconservative for tubes. Pass an
    explicit radius where that matters.
    """
    return float(np.sqrt(max(float(rod.A), 0.0) / np.pi))


# ----------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Clash:
    """One interference, named at both ends so it can be acted on."""

    kind: str        # 'rod-body' | 'rod-rod'
    a: str
    b: str
    gap: float       # signed: negative is interpenetration
    required: float  # what this pair needed

    @property
    def shortfall(self) -> float:
        return self.required - self.gap

    def message(self) -> str:
        what = "passes through" if self.gap < 0 else "is too close to"
        return (
            f"{self.a} {what} {self.b}: gap {self.gap:+.3f} in, "
            f"needs {self.required:.3f} in"
        )


@dataclass(frozen=True)
class ClashReport:
    clashes: tuple = ()
    min_gap: float = float("inf")     # tightest clearance found anywhere
    n_checked: int = 0

    @property
    def ok(self) -> bool:
        return not self.clashes

    @property
    def worst_shortfall(self) -> float:
        """Inches by which the worst pair misses its requirement; 0 when clear."""
        return max((c.shortfall for c in self.clashes), default=0.0)

    @property
    def worst(self) -> Clash | None:
        return min(self.clashes, key=lambda c: c.gap) if self.clashes else None

    def summary(self) -> str:
        if self.ok:
            tight = ("" if not np.isfinite(self.min_gap)
                     else f" Tightest clearance {self.min_gap:.3f} in.")
            return f"No interference across {self.n_checked} pair(s).{tight}"
        return (
            f"{len(self.clashes)} interference(s) of {self.n_checked} pair(s) "
            f"checked. Worst: {self.worst.message()}"
        )


# ----------------------------------------------------------------------
# The check
# ----------------------------------------------------------------------


def check_clearance(assembly: Assembly, min_gap: float = MIN_GAP_DEFAULT,
                    samples: int = SAMPLES, radii=None) -> ClashReport:
    """Every rod against every body and every other rod.

    `radii` overrides the per-rod radius (`{rod_id: r}`); anything absent falls
    back to `rod_radius`.
    """
    rod_ids = sorted(assembly.rods)
    if not rod_ids:
        return ClashReport()

    ends, own = {}, {}
    for rod_id in rod_ids:
        rod = assembly.rods[rod_id]
        pa, pb, body_a, body_b = assembly.rod_endpoints(rod)
        ends[rod_id] = (np.asarray(pa, float), np.asarray(pb, float))
        own[rod_id] = {body_a, body_b}

    radii = dict(radii or {})
    for rod_id in rod_ids:
        radii.setdefault(rod_id, rod_radius(assembly.rods[rod_id]))

    A = np.array([ends[r][0] for r in rod_ids])
    B = np.array([ends[r][1] for r in rod_ids])

    clashes: list[Clash] = []
    tightest = float("inf")
    checked = 0

    # -- rod vs body ----------------------------------------------------
    for body in assembly.bodies.values():
        if body.clearance is None:
            continue
        # The shell is body-local, so bring the rods into that frame rather
        # than the shell into global -- otherwise an oriented body is wrong.
        A_local = (A - body.origin) @ body.R
        B_local = (B - body.origin) @ body.R
        raw = segment_clearance(body.clearance, A_local, B_local, samples)
        margin = sample_margin(A_local, B_local, samples)
        for j, rod_id in enumerate(rod_ids):
            checked += 1
            attached = body.id in own[rod_id]
            if attached:
                # Bolted to it: touching is the whole point, and the endpoint
                # is sampled exactly, so the RAW value is the right one. Only
                # real interpenetration counts. Applying the sampling margin
                # here would condemn every legitimate rod.
                gap = float(raw[j])
                if gap >= -DEPTH_TOL:
                    continue
            else:
                gap = float(raw[j] - margin[j])
            required = 0.0 if attached else float(min_gap) + radii[rod_id]
            tightest = min(tightest, gap)
            if gap < required:
                clashes.append(Clash("rod-body", rod_id, body.id, gap, required))

    # -- rod vs rod -----------------------------------------------------
    pairs = [(i, k) for i in range(len(rod_ids)) for k in range(i + 1, len(rod_ids))]
    if pairs:
        idx = np.array(pairs)
        i0, i1 = idx[:, 0], idx[:, 1]
        req = np.array([float(min_gap) + radii[rod_ids[i]] + radii[rod_ids[k]]
                        for i, k in pairs])
        A1, B1, A2, B2 = _trim_shared_ends(A[i0], B[i0], A[i1], B[i1], req)
        gaps = segment_gaps(A1, B1, A2, B2)
        for (i, k), gap, required in zip(pairs, gaps, req):
            checked += 1
            ra, rb = rod_ids[i], rod_ids[k]
            gap = float(gap)
            tightest = min(tightest, gap)
            if gap < required:
                clashes.append(Clash("rod-rod", ra, rb, gap, required))

    return ClashReport(tuple(clashes), tightest, checked)


def worst_gap(assembly: Assembly, min_gap: float = MIN_GAP_DEFAULT,
              samples: int = SAMPLES) -> float:
    """Shortfall of the worst offending pair: 0.0 when everything clears.

    One number in inches, so a feasibility gate and a smooth penalty can share
    the same measure instead of drifting apart.
    """
    report = check_clearance(assembly, min_gap=min_gap, samples=samples)
    return max((c.shortfall for c in report.clashes), default=0.0)


__all__ = [
    "DEPTH_TOL",
    "MIN_GAP_DEFAULT",
    "SAMPLES",
    "Clash",
    "ClashReport",
    "check_clearance",
    "depth_at_points",
    "sample_margin",
    "segment_clearance",
    "segment_gaps",
    "signed_clearance",
    "rod_radius",
    "segment_depth",
    "segment_gap",
    "worst_gap",
]
