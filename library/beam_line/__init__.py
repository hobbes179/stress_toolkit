"""Line-beam analysis library -- shear, moment, slope and deflection along a
straight prismatic beam with arbitrary supports, releases and loads.

Pure engineering math; nothing here imports Streamlit.

    model     the problem statement and its validation
    solver    direct-stiffness solve -> nodal DOF and reactions
    diagrams  exact piecewise-polynomial V, M, theta, delta + peaks

Sign conventions are stated once, in `model`, and are used unchanged by all
three. The short version: x left to right, everything transverse positive UP,
moments positive counterclockwise, and the bending moment plotted is the
ordinary sagging-positive one.
"""

from library.beam_line.diagrams import (
    CLOSURE_TOL,
    RESIDUAL_TOL,
    Diagrams,
    Extremum,
    Piece,
    build,
)
from library.beam_line.envelope import (
    MAX_ENVELOPE_LOADS,
    Envelope,
    load_envelope,
)
from library.beam_line.model import (
    POSITION_TOL,
    Beam,
    DistributedLoad,
    Hinge,
    PointLoad,
    PointMoment,
    Restraint,
    Support,
    validate,
)
from library.beam_line.solver import (
    SINGULAR_RATIO,
    Reaction,
    SolveResult,
    element_EI,
    intensity_at,
    solve,
)

__all__ = [
    "analyse",
    # envelope
    "MAX_ENVELOPE_LOADS",
    "Envelope",
    "load_envelope",
    # model
    "POSITION_TOL",
    "Beam",
    "DistributedLoad",
    "Hinge",
    "PointLoad",
    "PointMoment",
    "Restraint",
    "Support",
    "validate",
    # solver
    "SINGULAR_RATIO",
    "Reaction",
    "SolveResult",
    "element_EI",
    "intensity_at",
    "solve",
    # diagrams
    "CLOSURE_TOL",
    "RESIDUAL_TOL",
    "Diagrams",
    "Extremum",
    "Piece",
    "build",
]


def analyse(beam: Beam):
    """Convenience: validate, solve and recover the diagrams in one call.

    Returns `(errors, solution, diagrams)`. `errors` non-empty means the model
    is malformed and the other two are None. A stable solve with diagrams that
    do not close yields `diagrams.valid == False`, which the UI must treat the
    same way -- suppress the results.
    """
    errs = validate(beam)
    if errs:
        return errs, None, None
    sol = solve(beam)
    if not sol.stable:
        return [], sol, build(beam, sol)
    return [], sol, build(beam, sol)
