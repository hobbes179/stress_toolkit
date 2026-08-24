"""
Tie-rod layout analysis — mechanism and degeneracy detection (build prompt §5).

Pure numpy. **Never imports Streamlit.**

This is half the success criterion of the tool, so it is built as a feature and
not as a guard clause. Three layers, in the order they should be read:

1. **Graph pre-check** (§5.1, run first). Nodes are bodies, edges are rods. A
   free body in a connected component with no ground body is unsupported, and
   is reported BY NAME. With a dozen bodies, "body_4 is not connected to
   ground" is worth far more than "K is rank deficient by 6".

2. **Rank check** (§5.2), on the NON-DIMENSIONALIZED screws. `Ghat` mixes units
   — translation rows dimensionless, moment rows carrying a length — so any
   spectrum taken on the raw matrix is meaningless. Nullity is reported against
   an expectation: normally 0, but exactly 6 when there are no ground bodies,
   which is a legitimate "is this subassembly internally rigid?" diagnostic and
   NOT an error.

3. **Geometric checks** (§5.4), which say *why*. Rank deficiency says the design
   is broken; these say what is wrong with it.

The null vectors are the product, not a by-product: each one is returned as a
per-body rigid displacement field ready to animate. Do not report "singular" —
show the motion the layout permits.

Nothing here re-derives the characteristic length or the rank: `Assembled`
already carries `L_c`, `nondim_screws()` and `rank`, built in Session 2 because
`influence()` is unsafe without them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from library.tierod.kernel import Assembled, assemble
from library.tierod.model import Assembly, Vec3

_RANK_TOL = 1e-9      # relative to the largest singular value
_ANGLE_TOL = 1e-7     # for direction equality, up to sign
_REL_LEN_TOL = 1e-7   # geometric tolerances, relative to L_c


# ----------------------------------------------------------------------
# Rigid motions and mechanism modes — the animation payload
# ----------------------------------------------------------------------


@dataclass
class RigidMotion:
    """One free body's share of a mode: translation of its datum plus a
    small-angle rotation about that datum.

    A point p on the body moves by `d + theta x (p - datum)`.
    """

    d: Vec3
    theta: Vec3

    def is_pure_translation(self, tol: float = 1e-9) -> bool:
        return float(np.linalg.norm(self.theta)) <= tol

    def axis_line(self, datum: Vec3, tol: float = 1e-9):
        """The line this motion rotates about, as `(point, direction)`.

        Returns None for a pure translation (no axis) and for a screw motion
        (rotation with a translation along the axis), which is a real
        distinction: only a pure rotation has a stationary line.

        From `d = theta x (datum - c)`, the point of the axis closest to the
        datum is `c = datum - (d x theta)/|theta|^2`.
        """
        norm = float(np.linalg.norm(self.theta))
        if norm <= tol:
            return None
        axis = self.theta / norm
        if abs(float(self.d @ axis)) > tol * max(1.0, float(np.linalg.norm(self.d))):
            return None  # screw motion: advances along the axis as it turns
        point = np.asarray(datum, dtype=float) - np.cross(self.d, self.theta) / norm**2
        return point, axis


@dataclass
class MechanismMode:
    """One independent zero-energy motion of the layout.

    `vector` is in physical DOF units, normalized so that

        max over free bodies of ( |d| + L_c |theta| )  ==  1

    i.e. the amplitude passed to `displace` is roughly the largest motion in
    inches anywhere within the characteristic radius. Normalizing on ATTACHMENT
    point motion would be more direct but is not robust: in a concurrent layout
    every attachment point sits on the rotation axis and does not move at all,
    which would leave the mode unscaled. `max_point_displacement` still reports
    the real attachment-point motion, and is legitimately 0.0 in that case.
    """

    index: int
    singular_value: float
    vector: np.ndarray
    per_body: dict[str, RigidMotion]
    datums: dict[str, Vec3] = field(default_factory=dict)
    max_point_displacement: float = 0.0

    def displace(self, body_id: str, points: np.ndarray, amplitude: float = 1.0):
        """Displacement of `points` (3, n) on `body_id` under this mode.

        The same rigid field the scene should animate:
        `amplitude * (d + theta x (p - datum))`.
        """
        if body_id not in self.per_body:
            raise KeyError(
                f"{body_id!r} is not a free body in this mode; "
                f"have {sorted(self.per_body)}"
            )
        motion = self.per_body[body_id]
        pts = np.asarray(points, dtype=float).reshape(3, -1)
        rel = pts - self.datums[body_id][:, None]
        return amplitude * (motion.d[:, None] + np.cross(motion.theta, rel, axis=0))

    def common_axis(self, tol: float = 1e-7):
        """`(point, direction)` when EVERY free body rotates about one shared
        line — a rigid rotation of the whole assembly. None otherwise.

        This is what makes the V8 message specific: the assembly turns about
        the ground-attachment line as a unit.
        """
        axes = []
        for body_id, motion in self.per_body.items():
            if motion.is_pure_translation(tol) and np.linalg.norm(motion.d) <= tol:
                continue  # this body does not move; it constrains nothing
            line = motion.axis_line(self.datums[body_id], tol)
            if line is None:
                return None
            axes.append(line)
        if not axes:
            return None
        point0, dir0 = axes[0]
        for point, direction in axes[1:]:
            if abs(abs(float(direction @ dir0)) - 1.0) > tol:
                return None
            offset = (point - point0) - dir0 * ((point - point0) @ dir0)
            if float(np.linalg.norm(offset)) > tol * max(
                1.0, float(np.linalg.norm(point0))
            ):
                return None
        return point0, dir0


# ----------------------------------------------------------------------
# Graph pre-check
# ----------------------------------------------------------------------


@dataclass
class GraphCheck:
    ok: bool
    components: list[list[str]]
    unsupported: list[str]
    message: str


def body_graph(assembly: Assembly) -> GraphCheck:
    """Connectivity of bodies through rods (§5.1).

    A free body in a component containing no ground body cannot be held by
    anything, whatever the rest of the assembly does. Reported by name.

    When there are NO ground bodies at all, nothing is "unsupported" — that is
    the free-free diagnostic mode, and saying "not connected to ground" would
    be noise. The rank check handles it.
    """
    parent = {body_id: body_id for body_id in assembly.bodies}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    for rod in assembly.rods.values():
        body_a = assembly.regions[rod.end_a.region_id].body_id
        body_b = assembly.regions[rod.end_b.region_id].body_id
        union(body_a, body_b)

    groups: dict[str, list[str]] = {}
    for body_id in assembly.bodies:
        groups.setdefault(find(body_id), []).append(body_id)
    components = [sorted(g) for g in groups.values()]
    components.sort()

    any_ground = any(b.is_ground for b in assembly.bodies.values())
    unsupported: list[str] = []
    if any_ground:
        for comp in components:
            if any(assembly.bodies[b].is_ground for b in comp):
                continue
            unsupported.extend(b for b in comp if not assembly.bodies[b].is_ground)
    unsupported.sort()

    if not any_ground:
        message = (
            "No ground bodies: this is a free-free check of internal rigidity, "
            "so connectivity to ground is not applicable."
        )
    elif unsupported:
        names = ", ".join(unsupported)
        message = (
            f"Not connected to ground: {names}. "
            f"No arrangement of the remaining rods can support "
            f"{'these bodies' if len(unsupported) > 1 else 'this body'}."
        )
    else:
        message = "Every free body is connected to ground."

    return GraphCheck(
        ok=not unsupported,
        components=components,
        unsupported=unsupported,
        message=message,
    )


# ----------------------------------------------------------------------
# Null modes
# ----------------------------------------------------------------------


def null_modes(asm: Assembled) -> list[MechanismMode]:
    """The independent zero-energy motions, as per-body rigid displacements.

    `null(K) == null(Ghat^T)` because `K = Ghat K_d Ghat^T` with `K_d` positive
    definite, so the modes are the left singular vectors of the screw matrix
    past its rank. The SVD is taken on the NON-DIMENSIONALIZED screws, then the
    vector is mapped back to physical DOF (rotation components carry 1/L_c).
    """
    if asm.n_dof == 0:
        return []
    G_tilde = asm.nondim_screws()
    if asm.n_rods == 0:
        U = np.eye(asm.n_dof)
        s = np.zeros(0)
        rank = 0
    else:
        U, s, _ = np.linalg.svd(G_tilde)
        rank = int(np.count_nonzero(s > _RANK_TOL * s[0])) if s.size else 0

    modes: list[MechanismMode] = []
    datums = {
        body_id: np.asarray(_datum(asm, body_id), dtype=float)
        for body_id in asm.body_order
    }
    for i in range(rank, asm.n_dof):
        x = U[:, i]
        v = _to_physical(x, asm)
        per_body = {}
        for slot, body_id in enumerate(asm.body_order):
            block = v[6 * slot : 6 * slot + 6]
            per_body[body_id] = RigidMotion(d=block[:3].copy(), theta=block[3:].copy())
        scale = _mode_scale(per_body, asm.L_c)
        if scale > 0.0:
            v = v / scale
            for body_id, motion in per_body.items():
                per_body[body_id] = RigidMotion(motion.d / scale, motion.theta / scale)
        modes.append(
            MechanismMode(
                index=len(modes),
                singular_value=float(s[i]) if i < s.size else 0.0,
                vector=v,
                per_body=per_body,
                datums=datums,
                max_point_displacement=_max_attachment_motion(asm, per_body, datums),
            )
        )
    return modes


def _datum(asm: Assembled, body_id: str) -> Vec3:
    return asm.body_datums[body_id]


def _to_physical(x: np.ndarray, asm: Assembled) -> np.ndarray:
    """Map a null vector of the non-dimensionalized screws back to [d ; theta].

    `G_tilde = S Ghat` with S dividing the moment rows by L_c, so
    `G_tilde^T x = 0` means `Ghat^T (S x) = 0`: the physical mode is `S x`,
    i.e. the rotation components divided by L_c.
    """
    v = np.asarray(x, dtype=float).copy()
    for slot in range(asm.n_free):
        v[6 * slot + 3 : 6 * slot + 6] /= asm.L_c
    return v


def _mode_scale(per_body, L_c: float) -> float:
    """Normalization for a mode: the largest `|d| + L_c |theta|` over bodies.

    Always positive for a nonzero mode, which attachment-point motion is not
    (see `MechanismMode`), so every mode ends up comparably scaled.
    """
    return max(
        (
            float(np.linalg.norm(m.d)) + L_c * float(np.linalg.norm(m.theta))
            for m in per_body.values()
        ),
        default=0.0,
    )


def _max_attachment_motion(asm: Assembled, per_body, datums) -> float:
    """Largest displacement of any rod attachment point under the mode.

    Informational: 0.0 when every attachment sits on the mode's rotation axis.
    """
    worst = 0.0
    slots = {body_id: i for i, body_id in enumerate(asm.body_order)}
    for j, rod_id in enumerate(asm.rod_ids):
        for body_id, point in (
            (asm.rod_body_a[j], asm.points_a[:, j]),
            (asm.rod_body_b[j], asm.points_b[:, j]),
        ):
            if body_id not in slots:
                continue
            motion = per_body[body_id]
            disp = motion.d + np.cross(motion.theta, point - datums[body_id])
            worst = max(worst, float(np.linalg.norm(disp)))
    return worst


def rigid_rotation_mode(asm: Assembled, point, axis) -> np.ndarray:
    """DOF vector for a rigid rotation of EVERY free body about one line.

    Needed because an SVD null-space basis is arbitrary within the null space:
    when the nullity is 2 or more, a physically meaningful motion such as
    "the whole assembly turns about the ground line" is generally a
    COMBINATION of the returned basis vectors and appears in none of them. To
    assert or animate a named motion, build it explicitly and confirm it lies
    in the null space (its elongations vanish).
    """
    e = np.asarray(axis, dtype=float)
    e = e / np.linalg.norm(e)
    c = np.asarray(point, dtype=float)
    v = np.zeros(asm.n_dof)
    for slot, body_id in enumerate(asm.body_order):
        o = asm.body_datums[body_id]
        v[6 * slot : 6 * slot + 3] = np.cross(e, o - c)
        v[6 * slot + 3 : 6 * slot + 6] = e
    return v


# ----------------------------------------------------------------------
# Geometric degeneracy checks
#
# These cover the four interpretable cases named in §5.4. They are not a
# complete degeneracy classifier and are not meant to be: a layout can be rank
# deficient through a subtler line-complex degeneracy that is none of these
# (the 6-6 rotary hexapod is the standard example — six rods all tangent to a
# common hyperboloid, rank 3, yet not parallel, not concurrent, and with its
# ground attachments on a circle). For those the animated null modes are the
# diagnosis, which is what §5.3 says is the highest-value output anyway.
# ----------------------------------------------------------------------


@dataclass
class GeometricFinding:
    kind: str            # collinear_ground | concurrent | parallel | common_line
    message: str
    axis: Vec3 | None = None
    point: Vec3 | None = None


def _fit_line(points: np.ndarray):
    """Best-fit line through columns of `points` (3, n): `(centroid, direction,
    max_offset)`."""
    centroid = points.mean(axis=1)
    rel = points - centroid[:, None]
    # rel is (3, n): the principal DIRECTION in 3-space is the first left
    # singular vector. Vt's rows live in point-index space, not in R^3.
    U, _, _ = np.linalg.svd(rel, full_matrices=False)
    direction = U[:, 0]
    along = direction[:, None] * (direction @ rel)
    max_offset = float(np.max(np.linalg.norm(rel - along, axis=0)))
    return centroid, direction, max_offset


def _fit_concurrency_point(points: np.ndarray, units: np.ndarray):
    """Least-squares point closest to every rod LINE, with the worst residual.

    A point p is on rod i's line iff `(a_i - p) x u_i == 0`, which is linear in
    p, so this is one least-squares solve rather than a search.
    """
    n = points.shape[1]
    A = np.zeros((3 * n, 3))
    b = np.zeros(3 * n)
    for j in range(n):
        S = np.array(
            [
                [0.0, -units[2, j], units[1, j]],
                [units[2, j], 0.0, -units[0, j]],
                [-units[1, j], units[0, j], 0.0],
            ]
        )
        A[3 * j : 3 * j + 3] = S
        b[3 * j : 3 * j + 3] = S @ points[:, j]
    p, *_ = np.linalg.lstsq(A, b, rcond=None)
    residual = max(
        float(np.linalg.norm(np.cross(points[:, j] - p, units[:, j])))
        for j in range(n)
    )
    return p, residual


def geometric_findings(
    asm: Assembled, modes=(), assembly: Assembly | None = None
) -> list[GeometricFinding]:
    """Interpretable causes, run alongside the numerics (§5.4)."""
    findings: list[GeometricFinding] = []
    if asm.n_rods == 0:
        return findings
    tol = _REL_LEN_TOL * max(1.0, asm.L_c)

    # -- all rod lines parallel: nothing reacts across that direction --
    u0 = asm.units[:, 0]
    if all(abs(abs(float(asm.units[:, j] @ u0)) - 1.0) < _ANGLE_TOL
           for j in range(asm.n_rods)):
        findings.append(
            GeometricFinding(
                kind="parallel",
                message=(
                    f"All {asm.n_rods} rod lines are parallel to "
                    f"[{u0[0]:.3f}, {u0[1]:.3f}, {u0[2]:.3f}], so the layout can "
                    f"react no load perpendicular to that direction."
                ),
                axis=u0.copy(),
            )
        )

    # -- all rod lines concurrent: every moment about that point is zero --
    point, residual = _fit_concurrency_point(asm.points_a, asm.units)
    if residual < tol and asm.n_rods >= 2:
        findings.append(
            GeometricFinding(
                kind="concurrent",
                message=(
                    f"All {asm.n_rods} rod lines pass through "
                    f"[{point[0]:.3f}, {point[1]:.3f}, {point[2]:.3f}]. No rod can "
                    f"generate a moment about that point, so all three rotations "
                    f"about it are free."
                ),
                point=point,
            )
        )

    # -- all GROUND-side attachments collinear: its own message (§5.4) --
    ground_pts = _ground_attachment_points(asm)
    if ground_pts.shape[1] >= 2:
        centroid, direction, offset = _fit_line(ground_pts)
        # self-check the theorem rather than trusting the fit: rotating every
        # free body about that line must stretch no rod at all
        rigid = rigid_rotation_mode(asm, centroid, direction)
        stretch = float(np.max(np.abs(asm.G_hat.T @ rigid))) if asm.n_rods else 0.0
        if offset < tol and stretch < tol:
            findings.append(
                GeometricFinding(
                    kind="collinear_ground",
                    message=(
                        f"All {ground_pts.shape[1]} ground-side attachments are "
                        f"collinear about "
                        f"[{direction[0]:.3f}, {direction[1]:.3f}, {direction[2]:.3f}]. "
                        f"This is a guaranteed mechanism for any number of rods in "
                        f"any arrangement: the whole assembly rotates about that "
                        f"line as a rigid unit, and body-to-body rods do not help. "
                        f"A baseplate idealized as a line rather than a plane lands "
                        f"here."
                    ),
                    axis=direction,
                    point=centroid,
                )
            )

    # -- rod lines meeting a common line: free rotation about it --
    for mode in modes:
        axis = mode.common_axis()
        if axis is None:
            continue
        c, e = axis
        if any(
            abs(float(e @ np.cross(asm.points_a[:, j] - c, asm.units[:, j]))) > tol
            for j in range(asm.n_rods)
        ):
            continue
        if any(f.kind == "collinear_ground" and _same_axis(f.axis, e)
               for f in findings):
            continue  # already said, more specifically
        findings.append(
            GeometricFinding(
                kind="common_line",
                message=(
                    f"Every rod line meets the line through "
                    f"[{c[0]:.3f}, {c[1]:.3f}, {c[2]:.3f}] along "
                    f"[{e[0]:.3f}, {e[1]:.3f}, {e[2]:.3f}], so no rod can generate a "
                    f"moment about it and rotation about that line is free."
                ),
                axis=e,
                point=c,
            )
        )
        break

    return findings


def _same_axis(a, b) -> bool:
    if a is None or b is None:
        return False
    return abs(abs(float(np.asarray(a) @ np.asarray(b))) - 1.0) < _ANGLE_TOL


def _ground_attachment_points(asm: Assembled) -> np.ndarray:
    cols = []
    free = set(asm.body_order)
    for j in range(asm.n_rods):
        if asm.rod_body_a[j] not in free:
            cols.append(asm.points_a[:, j])
        if asm.rod_body_b[j] not in free:
            cols.append(asm.points_b[:, j])
    if not cols:
        return np.zeros((3, 0))
    return np.column_stack(cols)


# ----------------------------------------------------------------------
# The report
# ----------------------------------------------------------------------


@dataclass
class MechanismReport:
    ok: bool
    n_dof: int
    rank: int
    nullity: int
    expected_nullity: int
    free_free: bool
    graph: GraphCheck
    modes: list[MechanismMode]
    findings: list[GeometricFinding]
    singular_values: np.ndarray
    sigma_min: float
    messages: list[str]

    def summary(self) -> str:
        return "\n".join(self.messages)


def check(assembly: Assembly, assembled: Assembled | None = None) -> MechanismReport:
    """Run all three layers and return one report.

    `ok` means the layout is usable: every free body reaches ground, and the
    nullity matches expectation — which is 0 normally and exactly 6 for a
    free-free assembly, where the six rigid-body modes are the expected answer
    rather than a fault.
    """
    asm = assembled if assembled is not None else assemble(assembly)
    graph = body_graph(assembly)

    free_free = not any(b.is_ground for b in assembly.bodies.values())
    expected_nullity = 6 if (free_free and asm.n_dof >= 6) else 0

    s = asm.screw_singular_values()
    rank = asm.rank
    nullity = asm.n_dof - rank
    sigma_min = float(s[asm.n_dof - 1]) if s.size >= asm.n_dof else 0.0

    modes = null_modes(asm)
    findings = geometric_findings(asm, modes=modes, assembly=assembly)

    messages: list[str] = []
    if not graph.ok:
        messages.append(graph.message)

    if free_free:
        if nullity == expected_nullity:
            messages.append(
                f"Free-free check: no ground bodies, and the nullity is exactly "
                f"{expected_nullity} — the six rigid-body motions of the whole "
                f"assembly. This subassembly is internally rigid."
            )
        else:
            messages.append(
                f"Free-free check: nullity {nullity} against the {expected_nullity} "
                f"rigid-body motions expected with no ground, so "
                f"{nullity - expected_nullity} internal mechanism"
                f"{'s' if nullity - expected_nullity != 1 else ''} exist beyond "
                f"them. This subassembly is not internally rigid."
            )
    elif nullity == 0:
        messages.append(
            f"No mechanism: rank {rank} of {asm.n_dof} free-body DOF, with "
            f"{asm.n_rods} rods."
        )
    else:
        messages.append(
            f"Mechanism: rank {rank} against {asm.n_dof} free-body DOF, so "
            f"{nullity} independent rigid-body motion"
            f"{'s are' if nullity != 1 else ' is'} unrestrained."
        )

    messages.extend(f.message for f in findings)
    ok = graph.ok and nullity == expected_nullity

    return MechanismReport(
        ok=ok,
        n_dof=asm.n_dof,
        rank=rank,
        nullity=nullity,
        expected_nullity=expected_nullity,
        free_free=free_free,
        graph=graph,
        modes=modes,
        findings=findings,
        singular_values=s,
        sigma_min=sigma_min,
        messages=messages,
    )


__all__ = [
    "RigidMotion",
    "rigid_rotation_mode",
    "MechanismMode",
    "GraphCheck",
    "GeometricFinding",
    "MechanismReport",
    "body_graph",
    "null_modes",
    "geometric_findings",
    "check",
]
