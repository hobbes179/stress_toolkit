"""
tests/test_layout_api.py

Guards the element-width API the whole app renders through.

WHY THIS EXISTS
---------------
Streamlit replaced the boolean `use_container_width` with a string `width`
("stretch" / "content") and is removing the boolean element by element --
`use_column_width` is already gone from `st.image` (1.61). A removal lands as
a `TypeError` at render time, in production, on Streamlit Cloud, which installs
the newest release at build time. There is no local warning first, because the
developer's pin is whatever they happened to install.

Two of the app's call sites made this worse than a rename. `st.page_link` and
`st.download_button` default to `width="content"`, not `"stretch"`, so simply
dropping the deprecated argument would have silently shrunk the landing-page
CTA and the CSV button rather than raising. `ui/styles.py` styles
`[data-testid="stPageLink"] a` as a full-width filled button that completes the
module card above it, so that shrink would have been a visible layout break on
every screen size. Hence: every site passes `width=` explicitly, and these
tests hold that line.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent

# Every element the app sizes. The value is the default `width` Streamlit
# gives it -- recorded so the "content" ones stay visibly distinct from the
# "stretch" ones in this file, which is the whole trap.
SIZED_ELEMENTS = {
    "dataframe": "stretch",
    "pyplot": "stretch",
    "plotly_chart": "stretch",
    "page_link": "content",
    "download_button": "content",
    "button": "content",
}


def _app_sources() -> list[Path]:
    """Every first-party Python file, excluding tests and caches."""
    out: list[Path] = []
    for p in ROOT.rglob("*.py"):
        parts = p.relative_to(ROOT).parts
        if parts[0] in {"tests", ".git"} or "__pycache__" in parts:
            continue
        out.append(p)
    return out


def test_the_deprecated_container_width_argument_is_gone_everywhere():
    """The regression guard. Reintroducing it anywhere re-arms the removal."""
    offenders = [
        f"{p.relative_to(ROOT)}:{i}"
        for p in _app_sources()
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if "use_container_width" in line
    ]
    assert not offenders, (
        "use_container_width is deprecated and is being removed element by "
        "element upstream. Use width=\"stretch\" / width=\"content\".\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("name", sorted(SIZED_ELEMENTS))
def test_the_installed_streamlit_accepts_the_width_argument(name):
    """Validates the >=1.49 floor in requirements.txt.

    `width` landed on st.dataframe and st.pyplot in 1.49 (1.46 covered most
    other elements). Below that floor every call site in the app is a
    TypeError, so the floor is load-bearing, not cosmetic.
    """
    fn = getattr(st, name)
    assert "width" in inspect.signature(fn).parameters, (
        f"st.{name} has no `width` parameter -- the streamlit floor in "
        f"requirements.txt is too low for the form the app calls."
    )


@pytest.mark.parametrize("name,default", sorted(SIZED_ELEMENTS.items()))
def test_the_assumed_width_defaults_still_hold(name, default):
    """The app passes width explicitly precisely so it does not depend on
    these -- but if a default flips, the docstring above is wrong and the
    reasoning future readers inherit is wrong with it."""
    got = inspect.signature(getattr(st, name)).parameters["width"].default
    assert got == default, f"st.{name} width default moved: {default} -> {got}"


def test_the_streamlit_dependency_is_bounded():
    """An unbounded major lets Cloud change the runtime under a deployed app."""
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    line = next(ln for ln in req.splitlines()
                if ln.strip().startswith("streamlit"))
    assert re.search(r"<\s*2", line), (
        f"streamlit needs an upper bound; found: {line!r}")
    assert re.search(r">=\s*1\.(49|[5-9]\d)", line), (
        f"streamlit floor must be >=1.49 for the width= API; found: {line!r}")


# ══════════════════════════════════════════════════════════════════════════
# Render
# ══════════════════════════════════════════════════════════════════════════
# The pages carrying the migrated call sites. The beam-section page had no
# headless render test before this one; `streamlit run` starting without error
# only proves the module imports, since the script body does not execute until
# a browser connects.
AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

MIGRATED_PAGES = ["Home.py", "pages/1_Beam_Section_Stress.py"]


@pytest.mark.parametrize("page", MIGRATED_PAGES)
def test_the_migrated_pages_render_without_exceptions(page):
    at = AppTest.from_file(page, default_timeout=180).run()
    assert not at.exception, [str(e.value) for e in at.exception]
