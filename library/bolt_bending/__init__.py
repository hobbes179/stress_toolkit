"""Bolt-bending analysis library — shear and moment along a bolt in a
multi-layer joint. Pure engineering math; nothing here imports Streamlit.

`kernel` is the uniform-bearing baseline; `refined` is the opt-in
beam-on-elastic-foundation pass over it. The refined model reduces to the
baseline exactly in the rigid-bolt limit, so it is a correction to the
baseline rather than an alternative to it."""

from library.bolt_bending.kernel import (
    IMBALANCE_TOL,
    Allowables,
    BoltAnalysis,
    BoltSection,
    Check,
    Layer,
    Margins,
    Segment,
    Station,
    analyse,
    default_stack,
    margins,
    screening_checks,
    symmetric_double_shear,
)
from library.bolt_bending.refined import (
    LOAD_ERROR_WARN,
    RESIDUAL_WARN,
    FoundationBasis,
    PlateBearing,
    RefinedResult,
    huth_compliance,
    refined_analysis,
    tate_rosenfeld_k,
)

__all__ = [
    "IMBALANCE_TOL",
    "Allowables",
    "BoltAnalysis",
    "BoltSection",
    "Check",
    "Layer",
    "Margins",
    "Segment",
    "Station",
    "analyse",
    "default_stack",
    "margins",
    "screening_checks",
    "symmetric_double_shear",
    # refined bearing distribution
    "LOAD_ERROR_WARN",
    "RESIDUAL_WARN",
    "FoundationBasis",
    "PlateBearing",
    "RefinedResult",
    "huth_compliance",
    "refined_analysis",
    "tate_rosenfeld_k",
]
