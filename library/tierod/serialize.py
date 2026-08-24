"""
JSON persistence for a tie-rod assembly.

Pure stdlib + numpy. **Never imports Streamlit.**

Without this the builder is a toy: every edit lives in `st.session_state` and
dies on the next reset. A saved assembly is also the unit a user emails to a
colleague and the input a Report page re-runs from, so the format is plain
readable JSON rather than a pickle — a pickle of a dataclass graph is neither
diffable nor safe to load from someone else's machine.

Design notes
------------
* **Type names come from the shared registries** (`model.REGION_TYPES`,
  `clearance.CLEARANCE_TYPES`), the same ones the builder dropdowns read. A
  primitive that can be built can therefore always be loaded, and the test that
  asserts the registries cover every subclass covers both directions at once.
* **The frame triad is written out in full**, not reconstructed from the axis
  name that happened to produce it. `frame_from_axis` is an input convenience;
  a region may be given any orthonormal triad, and re-deriving one from a
  dropdown value would silently rotate every such region on load.
* **`inf` is preserved.** `k_backup` defaults to infinity (a rigid backup) and
  `json` writes that as the bare token `Infinity`, which `json.loads` reads
  back. Coercing it to `null` would turn every rigid backup into a missing
  value; coercing it to a large float would change the stiffness.
* Round-trip fidelity is gated on the ANALYSIS matching, not on the fields
  matching — see `tests/tierod/test_construction.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from library.tierod.clearance import CLEARANCE_TYPES
from library.tierod.model import (
    REGION_TYPES,
    Assembly,
    Body,
    Rod,
    RodEnd,
)

__all__ = [
    "SCHEMA_VERSION",
    "to_dict",
    "from_dict",
    "dumps",
    "loads",
    "save",
    "load",
]

SCHEMA_VERSION = 1


def _vec(v) -> list:
    return [float(x) for x in np.asarray(v, dtype=float).reshape(-1)]


def _mat(m) -> list:
    return [[float(x) for x in row] for row in np.asarray(m, dtype=float)]


def _params(obj) -> dict:
    """The class-declared editable parameters, as plain JSON values."""
    out = {}
    for p in obj.PARAMS:
        value = getattr(obj, p.attr)
        out[p.attr] = _vec(value) if p.kind == "vec3" else float(value)
    return out


# ----------------------------------------------------------------------
# Encode
# ----------------------------------------------------------------------


def _clearance_to_dict(prim) -> dict | None:
    if prim is None:
        return None
    return {
        "type": type(prim).__name__,
        "origin": _vec(prim.origin),
        "e1": _vec(prim.e1),
        "e2": _vec(prim.e2),
        "e3": _vec(prim.e3),
        "params": _params(prim),
    }


def _body_to_dict(body: Body) -> dict:
    return {
        "is_ground": bool(body.is_ground),
        "origin": _vec(body.origin),
        "R": _mat(body.R),
        "mass": float(body.mass),
        "cg": _vec(body.cg),
        "g_factor": float(body.g_factor),
        "clearance": _clearance_to_dict(body.clearance),
    }


def _region_to_dict(region) -> dict:
    return {
        "type": type(region).__name__,
        "body_id": region.body_id,
        "origin": _vec(region.origin),
        "e1": _vec(region.e1),
        "e2": _vec(region.e2),
        "e3": _vec(region.e3),
        "params": _params(region),
    }


_ROD_SCALARS = (
    "E", "A", "I", "Fcy", "Ftu", "Fty", "A_net", "P_tension_allow",
    "end_fixity", "k_backup_a", "k_backup_b",
)


def _rod_to_dict(rod: Rod) -> dict:
    out = {
        "group": rod.group,
        "end_a": {"region_id": rod.end_a.region_id,
                  "q": _vec(rod.end_a.q), "h": float(rod.end_a.h)},
        "end_b": {"region_id": rod.end_b.region_id,
                  "q": _vec(rod.end_b.q), "h": float(rod.end_b.h)},
    }
    for name in _ROD_SCALARS:
        value = getattr(rod, name)
        out[name] = None if value is None else float(value)
    return out


def to_dict(assembly: Assembly) -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "bodies": {k: _body_to_dict(v) for k, v in assembly.bodies.items()},
        "regions": {k: _region_to_dict(v) for k, v in assembly.regions.items()},
        "rods": {k: _rod_to_dict(v) for k, v in assembly.rods.items()},
    }


def dumps(assembly: Assembly, indent: int = 2) -> str:
    return json.dumps(to_dict(assembly), indent=indent, sort_keys=True)


# ----------------------------------------------------------------------
# Decode
# ----------------------------------------------------------------------


def _build(registry: dict, payload: dict, what: str, **extra):
    type_name = payload.get("type")
    if type_name not in registry:
        raise ValueError(
            f"unknown {what} type {type_name!r}; this file needs a build that "
            f"has it. Known types: {sorted(registry)}"
        )
    cls = registry[type_name]
    return cls(
        origin=np.array(payload["origin"], dtype=float),
        e1=np.array(payload["e1"], dtype=float),
        e2=np.array(payload["e2"], dtype=float),
        e3=np.array(payload["e3"], dtype=float),
        **extra,
        **payload.get("params", {}),
    )


def from_dict(payload: dict) -> Assembly:
    version = payload.get("schema")
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported schema {version!r}: this build reads schema "
            f"{SCHEMA_VERSION}. A newer file cannot be half-read — some of it "
            f"would load and the rest would silently vanish."
        )

    bodies = {}
    for body_id, b in payload["bodies"].items():
        clearance = b.get("clearance")
        bodies[body_id] = Body(
            id=body_id,
            is_ground=bool(b["is_ground"]),
            origin=np.array(b["origin"], dtype=float),
            R=np.array(b["R"], dtype=float),
            mass=float(b["mass"]),
            cg=np.array(b["cg"], dtype=float),
            g_factor=float(b["g_factor"]),
            clearance=(
                None if clearance is None
                else _build(CLEARANCE_TYPES, clearance, "clearance")
            ),
        )

    regions = {
        region_id: _build(
            REGION_TYPES, r, "region", id=region_id, body_id=r["body_id"]
        )
        for region_id, r in payload["regions"].items()
    }

    rods = {}
    for rod_id, r in payload["rods"].items():
        scalars = {
            name: (None if r.get(name) is None else float(r[name]))
            for name in _ROD_SCALARS
        }
        rods[rod_id] = Rod(
            id=rod_id,
            end_a=RodEnd(r["end_a"]["region_id"], r["end_a"]["q"], r["end_a"]["h"]),
            end_b=RodEnd(r["end_b"]["region_id"], r["end_b"]["q"], r["end_b"]["h"]),
            group=r.get("group", "main"),
            **scalars,
        )

    return Assembly(bodies=bodies, regions=regions, rods=rods)


def loads(text: str) -> Assembly:
    return from_dict(json.loads(text))


# ----------------------------------------------------------------------
# Files
# ----------------------------------------------------------------------


def save(assembly: Assembly, path) -> Path:
    path = Path(path)
    path.write_text(dumps(assembly), encoding="utf-8")
    return path


def load(path) -> Assembly:
    return loads(Path(path).read_text(encoding="utf-8"))
