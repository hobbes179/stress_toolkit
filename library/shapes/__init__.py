"""Cross-section shape library for the Stress Toolkit."""

from library.shapes.shapes import (
    Section,
    KeyPoint,
    SHAPE_REGISTRY,
    SHAPE_NAMES,
    make_section,
    # individual shape classes (for direct import if needed)
    Rectangle, Circle, Ellipse,
    RectTube, CircularTube,
    IBeam, TBeam, LBeam, CBeam, ZBeam,
    PlusCross,
)

__all__ = [
    "Section", "KeyPoint", "SHAPE_REGISTRY", "SHAPE_NAMES", "make_section",
    "Rectangle", "Circle", "Ellipse",
    "RectTube", "CircularTube",
    "IBeam", "TBeam", "LBeam", "CBeam", "ZBeam",
    "PlusCross",
]
