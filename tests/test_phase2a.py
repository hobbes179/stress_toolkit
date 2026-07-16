"""
tests/test_phase2a.py

Geometry gate for Phase 2 sub-step A: midline skeletons for the open
thin-walled catalog shapes (design handoff §2.1). This gate validates the
skeleton geometry only; the shear-flow solver it feeds is exercised by the
Phase 2B gate (shear-center + τ-profile goldens).

Checks per open thin-walled shape:
  • a skeleton exists (nodes + segments populated, no closed cells)
  • every segment midpoint lies inside the section polygon
  • the skeleton is a single connected tree
  • all wall thicknesses are positive
  • Σ(segment length × thickness) ≈ section area (loose — junction overlaps
    and the centerline idealization make this approximate, not exact)
"""
from __future__ import annotations

import numpy as np
import pytest

from library.shapes import SHAPE_REGISTRY, make_section
from library.shapes.geometry import point_in_section


OPEN_SHAPES = [
    name for name, cls in SHAPE_REGISTRY.items()
    if cls.category == "Open thin-walled"
]


def _connected(n_nodes: int, segments) -> bool:
    """Union-find: True if all nodes are in one connected component."""
    parent = list(range(n_nodes))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for seg in segments:
        ra, rb = find(seg.n1), find(seg.n2)
        if ra != rb:
            parent[ra] = rb
    roots = {find(i) for i in range(n_nodes)}
    return len(roots) == 1


@pytest.mark.parametrize("shape_name", OPEN_SHAPES)
def test_skeleton_present_and_open(shape_name):
    sec = make_section(shape_name, list(SHAPE_REGISTRY[shape_name].dim_defaults))
    g = sec.geometry()
    assert g.nodes is not None and len(g.nodes) >= 2, f"{shape_name}: no nodes"
    assert len(g.segments) >= 1, f"{shape_name}: no segments"
    assert g.cells == (), f"{shape_name}: open section must have no closed cells"
    assert g.is_thin_walled is True


@pytest.mark.parametrize("shape_name", OPEN_SHAPES)
def test_segment_midpoints_inside_polygon(shape_name):
    sec = make_section(shape_name, list(SHAPE_REGISTRY[shape_name].dim_defaults))
    g = sec.geometry()
    for seg in g.segments:
        p1 = g.nodes[seg.n1]
        p2 = g.nodes[seg.n2]
        mid = (p1 + p2) / 2.0
        assert point_in_section(mid[0], mid[1], g.outer, g.voids), (
            f"{shape_name}: segment {seg.n1}-{seg.n2} midpoint {mid} "
            f"is not inside the section polygon"
        )
        assert seg.t > 0.0, f"{shape_name}: segment {seg.n1}-{seg.n2} t<=0"


@pytest.mark.parametrize("shape_name", OPEN_SHAPES)
def test_skeleton_connected(shape_name):
    sec = make_section(shape_name, list(SHAPE_REGISTRY[shape_name].dim_defaults))
    g = sec.geometry()
    assert _connected(len(g.nodes), g.segments), f"{shape_name}: disconnected skeleton"


@pytest.mark.parametrize("shape_name", OPEN_SHAPES)
def test_skeleton_wall_area_matches_section_area(shape_name):
    sec = make_section(shape_name, list(SHAPE_REGISTRY[shape_name].dim_defaults))
    g = sec.geometry()
    wall_area = 0.0
    for seg in g.segments:
        L = float(np.linalg.norm(g.nodes[seg.n2] - g.nodes[seg.n1]))
        wall_area += L * seg.t
    ratio = wall_area / sec.area()
    # Centerline idealization + junction double-counting keep this within
    # ~15% for the default (not truly thin) proportions.
    assert 0.85 < ratio < 1.20, f"{shape_name}: Σ(L·t)/A = {ratio:.3f}"
