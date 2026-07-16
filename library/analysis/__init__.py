"""
library/analysis — solver-agnostic section analysis engines.

Pure engineering math over section geometry. No Streamlit, no matplotlib.
"""

from library.analysis.polygon_props import (
    PolygonProps,
    polygon_section_props,
)

__all__ = ["PolygonProps", "polygon_section_props"]
