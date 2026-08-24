"""
Example assemblies for the tie-rod module.

Pure model construction — no Streamlit, no Plotly — so the app, the tests and
a bare Python session all load the same geometry.

`demo_assembly()` is the push-1 definition-of-done model: two cylinders on a
baseplate with twelve rods. `collinear_plate()` is the deliberate failure case
from the Session 4 gate checklist — a baseplate idealized as a LINE rather than
a plane, which is a guaranteed mechanism and animates as rotation about that
line.
"""

from __future__ import annotations

import numpy as np

from library.tierod.clearance import Box, Cylinder
from library.tierod.model import (
    Annulus,
    Assembly,
    Body,
    CircleArc,
    CylindricalBand,
    FixedPoint,
    PlanarPatch,
    Rod,
    RodEnd,
    frame_from_axis,
    frame_from_plane,
)

# 0.375 dia alloy-steel rod
ROD_PROPS = dict(
    E=29.0e6,
    A=0.1104,
    I=9.71e-4,
    Fcy=180.0e3,
    Ftu=180.0e3,
    Fty=163.0e3,
    A_net=0.0775,
)

_TANK_R = 5.0
_TANK_H = 30.0


def demo_assembly() -> Assembly:
    """Two cylinders on a baseplate, twelve rods, two free bodies."""
    e1, e2, e3 = frame_from_plane("XY")

    plate = Body(
        id="plate",
        is_ground=True,
        origin=np.array([0.0, 0.0, -0.5]),
        mass=400.0,   # retained though grounded — the toggle must not clear it
        cg=np.zeros(3),
        g_factor=6.0,
        clearance=Box(
            origin=np.zeros(3), e1=e1, e2=e2, e3=e3, half_extents=(24.0, 16.0, 0.5)
        ),
    )

    bodies = {plate.id: plate}
    regions: dict = {}
    rods: dict = {}

    for tag, x in (("a", -10.0), ("b", 10.0)):
        bodies[f"tank_{tag}"] = Body(
            id=f"tank_{tag}",
            origin=np.array([x, 0.0, 0.0]),
            mass=50.0,
            cg=np.array([0.0, 0.0, 0.5 * _TANK_H]),
            g_factor=6.0,
            clearance=Cylinder(
                origin=np.zeros(3),
                e1=e1,
                e2=e2,
                e3=e3,
                radius=_TANK_R,
                z_min=0.0,
                z_max=_TANK_H,
            ),
        )
        regions[f"foot_{tag}"] = Annulus(
            id=f"foot_{tag}",
            body_id="plate",
            origin=np.array([x, 0.0, 0.5]),
            e1=e1,
            e2=e2,
            e3=e3,
            r_inner=_TANK_R + 2.0,
            r_outer=_TANK_R + 6.0,
        )
        regions[f"band_{tag}"] = CylindricalBand(
            id=f"band_{tag}",
            body_id=f"tank_{tag}",
            origin=np.zeros(3),
            e1=e1,
            e2=e2,
            e3=e3,
            radius=_TANK_R,
            z_min=4.0,
            z_max=26.0,
        )
        for k in range(6):
            th = 2.0 * np.pi * k / 6.0
            z = 22.0 if k % 2 == 0 else 8.0
            rods[f"rod_{tag}{k}"] = Rod(
                id=f"rod_{tag}{k}",
                end_a=RodEnd(region_id=f"band_{tag}", q=np.array([th, z]), h=0.75),
                end_b=RodEnd(
                    region_id=f"foot_{tag}", q=np.array([_TANK_R + 4.0, th + 0.5])
                ),
                **ROD_PROPS,
            )

    return Assembly(bodies=bodies, regions=regions, rods=rods)


def collinear_plate(n_rods: int = 6) -> Assembly:
    """The gate's failure case: every ground attachment on ONE line.

    A pipe slung from a rail. Because every ground point lies ON the rail line,
    rotating the whole assembly about that line leaves every rod length
    unchanged — a guaranteed mechanism for any number of rods in any
    arrangement, which body-to-body rods cannot fix. This is exactly what
    happens when a baseplate is idealized as a line rather than a plane.

    Tuned to nullity EXACTLY 1 so the animation shows that single rotation and
    nothing else. Note the body-side attachments have to be non-coplanar to get
    there: a first attempt hung a flat pad off the rail and landed at nullity 3
    — coplanar attachments plus a collinear ground is doubly degenerate, and
    the extra modes muddy the demonstration.
    """
    e1, e2, e3 = frame_from_plane("XY")
    ax1, ax2, ax3 = frame_from_axis("X")      # e3 = +X, the pipe axis
    radius, height = 2.5, 9.0

    rail = Body(
        id="rail",
        is_ground=True,
        clearance=Box(
            origin=np.zeros(3), e1=e1, e2=e2, e3=e3, half_extents=(9.0, 0.4, 0.4)
        ),
    )
    pipe = Body(
        id="pipe",
        origin=np.array([0.0, 0.0, height]),
        mass=80.0,
        cg=np.zeros(3),
        g_factor=4.0,
        clearance=Cylinder(
            origin=np.zeros(3), e1=ax1, e2=ax2, e3=ax3,
            radius=radius, z_min=-6.0, z_max=6.0,
        ),
    )
    regions: dict = {
        "shell": CylindricalBand(
            id="shell", body_id="pipe", origin=np.zeros(3),
            e1=ax1, e2=ax2, e3=ax3, radius=radius, z_min=-6.0, z_max=6.0,
        )
    }
    rods: dict = {}
    for k in range(n_rods):
        t = -6.0 + 12.0 * k / (n_rods - 1)
        rid = f"anchor{k}"
        regions[rid] = FixedPoint(
            id=rid, body_id="rail", origin=np.array([t, 0.0, 0.0]),
            e1=e1, e2=e2, e3=e3,
        )
        theta = np.pi + (k - (n_rods - 1) / 2.0) * 0.55
        rods[f"tie{k}"] = Rod(
            id=f"tie{k}",
            end_a=RodEnd(region_id="shell", q=np.array([theta, t * 0.8])),
            end_b=RodEnd(region_id=rid, q=np.zeros(0)),
            **ROD_PROPS,
        )
    return Assembly(bodies={b.id: b for b in (rail, pipe)}, regions=regions, rods=rods)


def mixed_region_assembly() -> Assembly:
    """One of each region dimension (2-D, 1-D, 0-D) on a single body.

    Used to check that the scene and the sliders generate themselves from
    `ndim` and `bounds()` with no per-type code.
    """
    e1, e2, e3 = frame_from_plane("XY")
    body = Body(
        id="body",
        origin=np.array([0.0, 0.0, 6.0]),
        mass=25.0,
        cg=np.zeros(3),
        clearance=Box(
            origin=np.zeros(3), e1=e1, e2=e2, e3=e3, half_extents=(4.0, 4.0, 1.0)
        ),
    )
    ground = Body(
        id="ground",
        is_ground=True,
        clearance=Box(
            origin=np.zeros(3), e1=e1, e2=e2, e3=e3, half_extents=(8.0, 8.0, 0.4)
        ),
    )
    regions = {
        "patch2d": PlanarPatch(
            id="patch2d",
            body_id="body",
            origin=np.array([-4.0, -4.0, 1.0]),
            e1=e1,
            e2=e2,
            e3=e3,
            width=8.0,
            height=8.0,
        ),
        "arc1d": CircleArc(
            id="arc1d",
            body_id="ground",
            origin=np.array([0.0, 0.0, 0.4]),
            e1=e1,
            e2=e2,
            e3=e3,
            radius=7.0,
        ),
        "fixed0d": FixedPoint(
            id="fixed0d",
            body_id="ground",
            origin=np.array([0.0, 0.0, 0.4]),
            e1=e1,
            e2=e2,
            e3=e3,
        ),
    }
    rods = {
        "r_patch": Rod(
            id="r_patch",
            end_a=RodEnd(region_id="patch2d", q=np.array([0.2, 0.3])),
            end_b=RodEnd(region_id="arc1d", q=np.array([0.5])),
            **ROD_PROPS,
        ),
        "r_fixed": Rod(
            id="r_fixed",
            end_a=RodEnd(region_id="fixed0d", q=np.zeros(0)),
            end_b=RodEnd(region_id="patch2d", q=np.array([0.8, 0.7])),
            **ROD_PROPS,
        ),
    }
    return Assembly(
        bodies={b.id: b for b in (body, ground)}, regions=regions, rods=rods
    )


EXAMPLES = {
    "Demo — 2 cylinders on a baseplate (12 rods)": demo_assembly,
    "Mechanism — baseplate idealized as a line": collinear_plate,
    "Mixed regions — 2-D / 1-D / 0-D": mixed_region_assembly,
}

DEFAULT_EXAMPLE = "Demo — 2 cylinders on a baseplate (12 rods)"


__all__ = [
    "ROD_PROPS",
    "demo_assembly",
    "collinear_plate",
    "mixed_region_assembly",
    "EXAMPLES",
    "DEFAULT_EXAMPLE",
]
