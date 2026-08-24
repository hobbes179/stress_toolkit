"""
Worked example assemblies for the tie-rod module.

Every geometry here was **probed numerically before it was written down** —
parameters swept, rank and interference measured, then the winning values
frozen. None of it is a plausible-looking guess. Two findings from that sweep
are recorded inline because they are easy to re-introduce:

* a hexapod whose base twist equals its top twist collapses to **rank 9 of
  18** — the paired rods become parallel and stop reacting rotation;
* two ground rings whose radii overlap put rods from different clusters
  through each other, which reads as a clearance failure rather than a
  modelling one until you look.

`EXAMPLES` maps display name to builder. `DEFAULT_EXAMPLE` is what the page
opens with.
"""

from __future__ import annotations

import numpy as np

from library.tierod.clearance import Box, Cylinder, Sphere
from library.tierod.model import (
    Assembly,
    Body,
    frame_from_axis,
    new_region,
    new_rod,
)

#: 0.375 in alloy-steel rod. One spec for every rod in every example, because
#: sizing is not what these demonstrate.
STEEL = dict(
    E=29.0e6, A=0.1104, I=9.71e-4, Fcy=180.0e3,
    Ftu=180.0e3, Fty=163.0e3, A_net=0.0775,
)

# Frozen geometry of the payload deck, from the parameter sweep.
_TANK_AT = np.array([-17.0, 0.0, 0.0])
_AV_AT = np.array([15.0, 13.0, 0.0])
_VS_AT = np.array([15.0, -13.0, 0.0])
_BASE_TANK = 13.0          # ground-ring radius under the tank
_BASE_POD = 9.0            # ground-ring radius under each small body
_TWIST = np.radians(14.0)  # base half-separation of each rod pair
_TOP_TWIST = np.radians(40.0)   # top half-separation — MUST differ from _TWIST


def _f(axis: str = "Z") -> dict:
    return dict(zip(("e1", "e2", "e3"), frame_from_axis(axis)))


def _wrap(theta: float) -> float:
    """Fold an angle into [0, 2*pi).

    Every angular region here is bounded [0, 2*pi], so `group - twist` at
    group 0 lands at -14 degrees and fails validation on construction. Wrapping
    is a presentation detail of how the angles are generated, not a licence to
    ignore the bounds.
    """
    return float(np.mod(theta, 2.0 * np.pi))


def _hexapod(a: Assembly, prefix: str, base: str, base_r: float,
             top: str, q_top) -> None:
    """Six rods in three twisted pairs — the classic determinate mount.

    Each pair leaves the ground ring at `group ± _TWIST` and arrives at
    `group ± _TOP_TWIST`. The two twists must differ: equal, the pair is a
    parallelogram, and the whole 18-DOF assembly drops to rank 9.
    """
    for k in range(6):
        side = 1 if k % 2 == 0 else -1
        group = 2.0 * np.pi * (k // 2) / 3.0
        a.add_rod(new_rod(
            a, f"{prefix}{k}", base, top,
            q_a=[base_r, _wrap(group + side * _TWIST)],
            q_b=q_top(group, side),
            **STEEL,
        ))


def payload_deck() -> Assembly:
    """Three payloads above a ground deck, tied down and tied to each other.

    The tool's own brief, as a model: *here is what we are holding down, here
    is where there is room to mount, where do the rods go?* A cylindrical
    tank, a boxed avionics tray and a spherical vessel sit above a flat deck,
    each on its own six-rod mount, with three more rods running body-to-body.

    Every region primitive that carries design freedom appears: an `Annulus`
    ground ring (2-D), a `CylindricalBand` around the tank (2-D), a
    `SphericalPatch` cap on the vessel (2-D).

    21 rods against 18 DOF, so it is **redundant by three** and can lose a rod
    without becoming a mechanism — unlike a bare 18-rod set, where every rod
    is critical by construction. Clash-free by measurement, not assertion.
    """
    a = Assembly({}, {}, {})

    deck = Body("deck", is_ground=True)
    deck.clearance = Box(origin=np.array([0.0, 0.0, -1.0]),
                         half_extents=(36.0, 27.0, 1.0), **_f())
    a.add_body(deck)

    tank = Body("tank", mass=420.0, origin=_TANK_AT, g_factor=3.0)
    tank.clearance = Cylinder(origin=np.zeros(3), radius=6.0,
                              z_min=10.0, z_max=26.0, **_f())
    a.add_body(tank)
    tank.snap_cg_to_shell()

    avionics = Body("avionics", mass=140.0, origin=_AV_AT, g_factor=3.0)
    avionics.clearance = Box(origin=np.array([0.0, 0.0, 15.0]),
                             half_extents=(5.0, 4.0, 4.0), **_f())
    a.add_body(avionics)
    avionics.snap_cg_to_shell()

    vessel = Body("vessel", mass=200.0, origin=_VS_AT, g_factor=3.0)
    vessel.clearance = Sphere(origin=np.array([0.0, 0.0, 16.0]), radius=5.0,
                              **_f())
    a.add_body(vessel)
    vessel.snap_cg_to_shell()

    # Ground rings. One per cluster, sized so that NO TWO OVERLAP: rings that
    # overlap let feet from different clusters land on the same ground and put
    # their rods through each other.
    a.add_region(new_region("Annulus", "deck_tank", "deck", axis="Z",
                            origin=_TANK_AT, r_inner=_BASE_TANK - 3.0,
                            r_outer=_BASE_TANK + 3.0))
    for name, at in (("deck_avionics", _AV_AT), ("deck_vessel", _VS_AT)):
        a.add_region(new_region("Annulus", name, "deck", axis="Z", origin=at,
                                r_inner=_BASE_POD - 2.5,
                                r_outer=_BASE_POD + 2.5))

    a.add_region(new_region("CylindricalBand", "tank_band", "tank", axis="Z",
                            radius=6.0, z_min=12.0, z_max=22.0))
    a.add_region(new_region("Annulus", "avionics_base", "avionics", axis="Z",
                            origin=[0.0, 0.0, 11.0], r_inner=3.0, r_outer=5.5))
    a.add_region(new_region("SphericalPatch", "vessel_cap", "vessel", axis="Z",
                            origin=[0.0, 0.0, 16.0], radius=5.0,
                            theta_min=0.0, theta_max=2.0 * np.pi,
                            phi_min=np.radians(100.0),
                            phi_max=np.radians(145.0)))

    _hexapod(a, "tk", "deck_tank", _BASE_TANK, "tank_band",
             lambda g, s: [_wrap(g + s * _TOP_TWIST), 17.0])
    _hexapod(a, "av", "deck_avionics", _BASE_POD, "avionics_base",
             lambda g, s: [4.2, _wrap(g + s * _TOP_TWIST)])
    _hexapod(a, "vs", "deck_vessel", _BASE_POD, "vessel_cap",
             lambda g, s: [_wrap(g + s * _TOP_TWIST), np.radians(125.0)])

    # Body-to-body ties. These are what take the layout past determinate: with
    # only the three hexapods it is exactly 18 rods for 18 DOF and every rod is
    # critical. Each one points at the body it reaches, so it clears the
    # hardware in between.
    a.add_rod(new_rod(a, "tie_tank_av", "tank_band", "avionics_base",
                      q_a=[_wrap(np.radians(22.0)), 20.0],
                      q_b=[5.0, np.radians(202.0)], **STEEL))
    a.add_rod(new_rod(a, "tie_tank_vs", "tank_band", "vessel_cap",
                      q_a=[_wrap(np.radians(-22.0)), 20.0],
                      q_b=[_wrap(np.radians(158.0)), np.radians(105.0)],
                      **STEEL))
    a.add_rod(new_rod(a, "tie_av_vs", "avionics_base", "vessel_cap",
                      q_a=[5.0, np.radians(270.0)],
                      q_b=[np.radians(90.0), np.radians(105.0)], **STEEL))
    return a


def mechanism_turntable() -> Assembly:
    """A layout that LOOKS restrained and is not — for the Mechanism tab.

    Six rods on a disc, every one of them radial and at the same height, so
    every rod line meets the axis and none has a tangential component.

    Measured, not assumed: **rank 3 of 6 — three free motions**, and the named
    findings are `concurrent` and `common_line`. Six rods restraining three
    degrees of freedom is a good illustration that counting rods proves
    nothing: this has the same rod count as a working hexapod and reacts half
    as much. Spin about Z is the obvious one; the other two are tilts, because
    rod lines that all cross the axis generate no moment about it either.

    This is the degeneracy the twist in `payload_deck` exists to avoid,
    isolated. It is geometric, not a shortage of rods — adding more radial
    spokes does not fix it.
    """
    a = Assembly({}, {}, {})
    base = Body("base", is_ground=True)
    base.clearance = Cylinder(origin=np.array([0.0, 0.0, -1.5]), radius=16.0,
                              z_min=0.0, z_max=1.5, **_f())
    a.add_body(base)

    disc = Body("turntable", mass=260.0, origin=np.zeros(3), g_factor=2.0)
    disc.clearance = Cylinder(origin=np.zeros(3), radius=9.0,
                              z_min=14.0, z_max=17.0, **_f())
    a.add_body(disc)
    disc.snap_cg_to_shell()

    a.add_region(new_region("Annulus", "base_ring", "base", axis="Z",
                            r_inner=11.0, r_outer=15.0))
    a.add_region(new_region("Annulus", "disc_ring", "turntable", axis="Z",
                            origin=[0.0, 0.0, 14.0], r_inner=5.0, r_outer=9.0))
    for k in range(6):
        theta = 2.0 * np.pi * k / 6.0
        a.add_rod(new_rod(a, f"spoke{k}", "base_ring", "disc_ring",
                          q_a=[13.0, theta], q_b=[7.0, theta], **STEEL))
    return a


def clash_gantry() -> Assembly:
    """A restrained layout whose rods run through the hardware — for the
    interference check.

    Rank is full and the load path is sound, so every strength number reports
    happily. It is still unbuildable: the cross-ties are routed straight
    through the mast. Nothing but the clearance check finds this, which is the
    point of having one.
    """
    a = Assembly({}, {}, {})
    pad = Body("pad", is_ground=True)
    pad.clearance = Box(origin=np.array([0.0, 0.0, -1.0]),
                        half_extents=(18.0, 18.0, 1.0), **_f())
    a.add_body(pad)

    mast = Body("mast", mass=300.0, origin=np.zeros(3), g_factor=2.0)
    mast.clearance = Cylinder(origin=np.zeros(3), radius=5.0, z_min=0.0,
                              z_max=24.0, **_f())
    a.add_body(mast)
    mast.snap_cg_to_shell()

    a.add_region(new_region("Annulus", "pad_ring", "pad", axis="Z",
                            r_inner=10.0, r_outer=15.0))
    a.add_region(new_region("CylindricalBand", "mast_low", "mast", axis="Z",
                            radius=5.0, z_min=4.0, z_max=9.0))
    a.add_region(new_region("CylindricalBand", "mast_high", "mast", axis="Z",
                            radius=5.0, z_min=17.0, z_max=22.0))

    for k in range(6):
        side = 1 if k % 2 == 0 else -1
        group = 2.0 * np.pi * (k // 2) / 3.0
        a.add_rod(new_rod(a, f"stay{k}", "pad_ring", "mast_high",
                          q_a=[12.5, _wrap(group + side * _TWIST)],
                          q_b=[_wrap(group + side * _TOP_TWIST), 19.5],
                          **STEEL))
    # Two cross-ties taken straight across the mast rather than around it.
    for k, theta in enumerate((0.0, 2.0 * np.pi / 3.0)):
        a.add_rod(new_rod(a, f"cross{k}", "mast_low", "mast_low",
                          q_a=[_wrap(theta), 6.5],
                          q_b=[_wrap(theta + np.pi), 6.5], **STEEL))
    return a


EXAMPLES = {
    "Payload deck — 3 bodies, 21 rods": payload_deck,
    "Mechanism — radial spokes on a turntable": mechanism_turntable,
    "Interference — cross-ties through the mast": clash_gantry,
}

DEFAULT_EXAMPLE = "Payload deck — 3 bodies, 21 rods"

#: Kept as an alias: `demo_assembly` is the name the construction tests use for
#: "the representative model", and it should follow the default example rather
#: than pinning a particular geometry.
demo_assembly = payload_deck


__all__ = [
    "EXAMPLES",
    "DEFAULT_EXAMPLE",
    "STEEL",
    "payload_deck",
    "mechanism_turntable",
    "clash_gantry",
    "demo_assembly",
]
