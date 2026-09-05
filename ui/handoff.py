"""
ui/handoff.py

A one-way snapshot of the section the analyst last had on screen in the Beam
Section Stress module, so another module can offer it as a starting point
instead of making them retype E and I.

WHY A MIRROR AND NOT THE WIDGET KEYS
------------------------------------
Streamlit garbage-collects a widget's `session_state` entry once the widget
stops being instantiated. Navigating from one page in `pages/` to another
means the first page's widgets are not rendered on that run, so their state is
dropped -- reading `st.session_state["dim_0_I-Beam / W-Shape"]` from a
different page gets nothing, reliably. A PLAIN key (one that never backs a
widget) is not collected, so the publishing page copies what it built into one
and the consuming page reads that.

WHAT THIS DELIBERATELY IS NOT
-----------------------------
It is a snapshot, not a live link. The consuming module must show what it
picked up and let the analyst override it, never silently inherit a section
that was chosen for a different purpose. It is also a within-session
convenience only: a browser that opens the consuming page first sees nothing,
which is why every consumer needs its own working default.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

import streamlit as st

# Plain (non-widget) session key. Anything under a `handoff::` prefix is
# module-to-module state and must never be used as a widget key.
SECTION_KEY = "handoff::section"

# Bumped when the payload shape changes. A browser still holding a session
# from a previous deploy will fail the version check and be ignored rather
# than crashing the consumer on a missing field.
SCHEMA = 1


@dataclass(frozen=True)
class SectionSnapshot:
    """Everything another module needs to reuse a section, in library units.

    `E` is in psi, not Msi -- the material library stores Msi and every
    consumer wants psi, so the conversion happens once, here.
    """

    schema: int
    shape: str
    material: str
    E: float
    Iy: float
    Iz: float
    area: float

    @property
    def label(self) -> str:
        return f"{self.shape}, {self.material}"


def publish_section(shape: str, material_name: str, E_msi: Optional[float],
                    Iy: float, Iz: float, area: float) -> None:
    """Called by the producing page once its section is built.

    Silently does nothing if the material has no modulus, because a snapshot
    without E cannot give a consumer the EI it came for.
    """
    if not E_msi or E_msi <= 0:
        return
    snap = SectionSnapshot(SCHEMA, str(shape), str(material_name),
                           float(E_msi) * 1.0e6, float(Iy), float(Iz),
                           float(area))
    st.session_state[SECTION_KEY] = asdict(snap)


def read_section() -> Optional[SectionSnapshot]:
    """Return the published snapshot, or None if there is not a usable one.

    Shape-checked rather than presence-checked: Streamlit Cloud redeploys
    under live sessions, so a browser may be holding a payload written by an
    older version of this file.
    """
    raw: Any = st.session_state.get(SECTION_KEY)
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return None
    try:
        snap = SectionSnapshot(**raw)
    except TypeError:
        return None
    if snap.E <= 0 or (snap.Iy <= 0 and snap.Iz <= 0):
        return None
    return snap
