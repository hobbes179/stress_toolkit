"""
Tie-rod layout analysis — load cases.

A **case is a unit direction** `n_hat` plus a per-case `factor`. Every case has
the same magnitude by construction: the sweep varies direction only, never
magnitude. Load size lives on the body, as a scalar load factor `Body.g_factor`.

    W_p = m_p G_p [I3 ; [c_p]x]      (6x3, free bodies only)
    W   = vstack(W_p)                 (n_dof x 3)
    F_c = W n_hat_c                   applied load for case c
    P_c = G F_c = T n_hat_c ,  T = G W    (N x n_cases in one matmul)

One direction is shared by every body (the same acceleration vector acts on the
whole assembly). Per-body directions would make W block-structured; that is the
only thing that would change, and it is not needed now.

Exact envelope
--------------
F is linear in n_hat and ||n_hat|| = 1, so the true worst case over ALL
directions is closed-form:

    max |P_i| = || row_i(T) ||_2      at   n_hat*_i = row_i(T) / || row_i(T) ||_2

The enumerated direction set is a readable SAMPLE of that sphere. It can only
under-predict the closed form, never exceed it, with equality exactly when a
sampled direction lands on `n_hat*_i`. Report the closed form as the governing
value and cite the nearest named direction for interpretation — do not treat
the enumerated maximum as the envelope.

Direction sets
--------------
`DIRECTION_SETS` is a registry, so adding a finer sweep later is a new entry,
not a refactor. Nothing downstream may branch on which set is in use: the
kernel and sweep see only a (3, n_cases) matrix of unit columns.

`LoadCase.factor` is a per-case multiplier, defaulting to 1.0. It exists from
Session 1 because the fail-safe damage factor (Phase 3) is company-specific and
user-supplied: intact cases at the ultimate factor, failure states at whatever
the fail-safe criteria specify. Never hardcode it. The factor scales the load,
NOT the direction — `direction` always stays a unit vector.

Pure numpy — no Streamlit.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, product

import numpy as np

AXIS_NAMES = ("X", "Y", "Z")
_UNIT_TOL = 1e-12


@dataclass
class LoadCase:
    """One load case: a unit acceleration direction and a load factor.

    `direction` is normalized on construction, so a `LoadCase` can never hold a
    non-unit vector. `name` is a label only — nothing branches on it.
    """

    id: str
    name: str
    direction: np.ndarray
    factor: float = 1.0

    def __post_init__(self) -> None:
        d = np.asarray(self.direction, dtype=float).reshape(-1)
        if d.size != 3:
            raise ValueError(f"direction must be a 3-vector, got {d.size} entries")
        n = float(np.linalg.norm(d))
        if n < _UNIT_TOL:
            raise ValueError("the zero vector is not a load direction")
        self.direction = d / n
        self.factor = float(self.factor)

    def load(self, W: np.ndarray) -> np.ndarray:
        """Applied load for this case: F = factor * W @ n_hat."""
        return self.factor * (W @ self.direction)


# ----------------------------------------------------------------------
# Naming (cube sets — a label for a sign pattern, not a magnitude)
# ----------------------------------------------------------------------


def case_name(sign_vector) -> str:
    """(1, -1, 0) -> '+X-Y'. Axis order is always X, Y, Z.

    The name records which axes the direction leans on and in which sense. It
    is NOT a statement of magnitude: '+X+Y' is the unit vector at 45 degrees,
    not one full factor on each of X and Y.
    """
    s = np.asarray(sign_vector, dtype=int).reshape(-1)
    return "".join(
        f"{'+' if s[i] > 0 else '-'}{AXIS_NAMES[i]}" for i in range(3) if s[i] != 0
    )


def parse_case_name(name: str) -> np.ndarray:
    """'+X-Y' -> the unit direction [1, -1, 0]/sqrt(2). Inverse of `case_name`
    up to normalization."""
    text = str(name).strip().upper()
    if not text or len(text) % 2 != 0:
        raise ValueError(f"malformed case name {name!r}")
    s = np.zeros(3)
    for sign_ch, axis_ch in zip(text[0::2], text[1::2]):
        if sign_ch not in "+-" or axis_ch not in AXIS_NAMES:
            raise ValueError(f"malformed case name {name!r}")
        i = AXIS_NAMES.index(axis_ch)
        if s[i] != 0:
            raise ValueError(f"axis {axis_ch} repeats in case name {name!r}")
        s[i] = 1.0 if sign_ch == "+" else -1.0
    if not np.any(s):
        raise ValueError(f"case name {name!r} has no active axis")
    return s / np.linalg.norm(s)


# ----------------------------------------------------------------------
# Direction sets
# ----------------------------------------------------------------------


def _cube_sign_patterns(max_active: int) -> list[np.ndarray]:
    """Sign patterns with 1..max_active active axes, in a stable order:
    singles first, then pairs, then triples; axes ascend, '+' before '-'."""
    out: list[np.ndarray] = []
    for n_active in range(1, max_active + 1):
        for axes in combinations(range(3), n_active):
            for signs in product((1, -1), repeat=n_active):
                s = np.zeros(3)
                for axis, sign in zip(axes, signs):
                    s[axis] = float(sign)
                out.append(s)
    return out


def axes6() -> list[tuple[str, np.ndarray]]:
    """The 6 axis directions: +-X, +-Y, +-Z."""
    return [(case_name(s), s.copy()) for s in _cube_sign_patterns(1)]


def cube26() -> list[tuple[str, np.ndarray]]:
    """26 directions: 6 face, 12 edge, 8 corner normals of a cube, normalized.

    A coarse but well-spread and highly readable sweep of the sphere — every
    direction has an engineer-legible name. Refine by adding a set here, not by
    changing anything downstream.
    """
    return [(case_name(s), s / np.linalg.norm(s)) for s in _cube_sign_patterns(3)]


DIRECTION_SETS = {
    "axes6": axes6,
    "cube26": cube26,
}

DEFAULT_DIRECTION_SET = "cube26"


# ----------------------------------------------------------------------
# Case construction
# ----------------------------------------------------------------------


def cases_from_directions(
    directions,
    names=None,
    factor: float = 1.0,
    prefix: str = "C",
) -> list[LoadCase]:
    """Build cases from any iterable of 3-vectors. Directions are normalized,
    so a caller supplying unnormalized vectors still gets a unit-magnitude set.

    This is the escape hatch for a custom sweep (a geodesic sphere, a set of
    measured flight vectors) without touching the registry.
    """
    dirs = [np.asarray(d, dtype=float).reshape(-1) for d in directions]
    if names is None:
        names = [f"{prefix}{i + 1:03d}" for i in range(len(dirs))]
    names = list(names)
    if len(names) != len(dirs):
        raise ValueError(f"got {len(dirs)} directions but {len(names)} names")
    return [
        LoadCase(id=f"{prefix}{i + 1:02d}", name=nm, direction=d, factor=factor)
        for i, (nm, d) in enumerate(zip(names, dirs))
    ]


def generate_cases(
    set_name: str = DEFAULT_DIRECTION_SET, factor: float = 1.0
) -> list[LoadCase]:
    """The default sweep: every case a unit direction, stable order and naming.

    Ids are 'C01', 'C02', ... in generation order.
    """
    try:
        builder = DIRECTION_SETS[set_name]
    except KeyError:
        raise ValueError(
            f"unknown direction set {set_name!r}; have {sorted(DIRECTION_SETS)}"
        ) from None
    pairs = builder()
    return cases_from_directions(
        [d for _, d in pairs], names=[nm for nm, _ in pairs], factor=factor
    )


def direction_matrix(cases: list[LoadCase], weighted: bool = False) -> np.ndarray:
    """N: (3, n_cases), one unit column per case.

    `F = W @ N` gives every case's applied load in one matmul, and `P = T @ N`
    every case's rod loads. With `weighted=True` each column is scaled by that
    case's `factor` — the columns are then loads, not directions, and are no
    longer unit length.
    """
    if not cases:
        return np.zeros((3, 0))
    N = np.column_stack([c.direction for c in cases])
    if weighted:
        N = N * np.array([c.factor for c in cases], dtype=float)
    return N


def case_by_name(cases: list[LoadCase], name: str) -> LoadCase:
    for c in cases:
        if c.name == name:
            return c
    raise KeyError(f"no load case named {name!r}")


def case_by_id(cases: list[LoadCase], case_id: str) -> LoadCase:
    for c in cases:
        if c.id == case_id:
            return c
    raise KeyError(f"no load case with id {case_id!r}")


def nearest_case(cases: list[LoadCase], direction) -> tuple[LoadCase, float]:
    """The enumerated case closest to `direction`, and the angle to it in
    degrees.

    Used to label the closed-form worst direction `n_hat*_i` with a name the
    engineer recognizes. The angle is the honest measure of how well the
    enumerated set covers that rod's actual worst case.
    """
    d = np.asarray(direction, dtype=float).reshape(-1)
    n = float(np.linalg.norm(d))
    if n < _UNIT_TOL:
        raise ValueError("cannot find the nearest case to the zero vector")
    d = d / n
    dots = np.array([float(c.direction @ d) for c in cases])
    i = int(np.argmax(dots))
    angle = float(np.degrees(np.arccos(min(1.0, max(-1.0, dots[i])))))
    return cases[i], angle


__all__ = [
    "AXIS_NAMES",
    "LoadCase",
    "case_name",
    "parse_case_name",
    "axes6",
    "cube26",
    "DIRECTION_SETS",
    "DEFAULT_DIRECTION_SET",
    "cases_from_directions",
    "generate_cases",
    "direction_matrix",
    "case_by_name",
    "case_by_id",
    "nearest_case",
]
