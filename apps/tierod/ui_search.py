"""
Layout-search UI — generate layouts from scratch, compare them, adopt one.

This is the tab that answers the question the owner actually posed: *"here's
what we're trying to hold down, here are some places where we have room to
mount some rods. Where can we tie them together to make it work and meet
fail-safe requirements?"* The engine (`library/tierod/optimize.py`) has existed
since Session 8; until now nothing in the app called it.

Same split as the rest of the module: **pure helpers** carry the rules,
`trade_figure` builds a Plotly figure with no Streamlit import, and the
`*_tab` / widget functions are Streamlit only.

Three things this file exists to get right:

1. **The search is expensive** — roughly 5 s per candidate, so a 50-candidate
   run is four minutes. It must never run on a rerun. It runs on a button, the
   result is parked in session state, and the cost is ESTIMATED AND SHOWN
   before the button is pressed.

2. **A parked result goes stale when the geometry moves.** A trade curve
   computed against regions the user has since resized is a confident lie.
   `geometry_fingerprint` covers bodies and regions but deliberately NOT rods
   — the rods are what the search replaces, so changing them does not
   invalidate anything.

3. **Adopting is destructive.** It deletes every rod in the live model and
   installs the candidate's. Everything that can fail is checked first
   (`adoptable`), so the removal only begins once the install is guaranteed;
   a half-adopted model would be worse than a refused one.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from library.tierod import failsafe as fs
from library.tierod import optimize as opt
from library.tierod import serialize

FEASIBLE_COLOR = "#1E8449"
INFEASIBLE_COLOR = "#C0392B"
KNEE_COLOR = "#E67E22"
LENGTH_COLOR = "#2E86DE"

#: Measured on the demo geometry: 50 candidates in 258 s. Used only to warn
#: before a long run, never to decide anything.
SECONDS_PER_CANDIDATE = 5.2

_RESULT_KEY = "tierod::search::result"
_STAMP_KEY = "tierod::search::stamp"


# ----------------------------------------------------------------------
# Pure helpers
# ----------------------------------------------------------------------


def geometry_fingerprint(assembly) -> str:
    """Hash of the bodies and regions — the part a search space is made of.

    Rods are excluded on purpose: the search replaces them, so editing or
    adopting rods must not mark an existing result stale. Editing a region
    must.
    """
    payload = serialize.to_dict(assembly)
    payload.pop("rods", None)
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def searchable(assembly) -> list[str]:
    """Reasons this model cannot be searched. Empty means go.

    Each reason names the thing to add, because "cannot search" on its own
    sends the user back to a builder tab with no idea what is missing.
    """
    problems = []
    if not [b for b in assembly.bodies.values() if not b.is_ground]:
        problems.append(
            "no free body — everything is ground, so there is nothing to hold "
            "down and no DOF to restrain"
        )
    if not [b for b in assembly.bodies.values() if b.is_ground]:
        problems.append(
            "no ground body — a free-free model has six null modes by "
            "definition and no layout can restrain it"
        )
    if not opt.topology_options(assembly):
        problems.append(
            "no cross-body region pair — a rod must span two bodies, so at "
            "least two bodies need a mountable region"
        )
    return problems


def n_range_floor(assembly, criteria=None) -> int:
    """The counting bound below which no arrangement can work.

    **Which bound depends on the fail-safe setting**, and getting this wrong
    costs the user a whole rod count: `6·n_free` merely restrains everything
    (every rod critical), while `6·n_free + 1` is the least that can lose one.
    Quoting the fail-safe bound while fail-safe is off hides the count that
    would have worked.

    A floor, not a promise: the offered topology can demand more, and the
    search discovers that by finding nothing down there.
    """
    n_free = len([b for b in assembly.bodies.values() if not b.is_ground])
    require = True if criteria is None else criteria.require_single_failure
    return (
        fs.min_rods_for_single_failure(n_free) if require
        else fs.min_rods_for_mechanism_free(n_free)
    )


def floor_hint(chosen: int, floor: int, require_single_failure: bool) -> str:
    """What to say about a rod-count floor the user has typed past.

    Advisory only — it never rewrites the number. A recomputed default that
    silently overwrote a deliberate entry would be the worse bug.
    """
    why = ("survive losing any one rod" if require_single_failure
           else "restrain every degree of freedom")
    if chosen < floor:
        return (
            f"⚠️ Below the counting bound: {floor} rods is the least that can "
            f"{why} for this model, so counts under {floor} will come back "
            f"infeasible. Left as you set it."
        )
    if chosen > floor:
        return (
            f"The counting bound for these settings is {floor}. Starting at "
            f"{chosen} skips {chosen - floor} count(s) that might have worked."
        )
    return f"{floor} is the counting bound: the least that can {why} here."


@dataclass(frozen=True)
class Budget:
    """What a run will cost, before it is started."""

    n_candidates: int
    seconds: float
    counts: tuple

    def message(self) -> str:
        if not self.n_candidates:
            return "Nothing to search — no rod count in range is buildable."
        mins = self.seconds / 60.0
        span = (f"{self.counts[0]}" if len(self.counts) == 1
                else f"{self.counts[0]}–{self.counts[-1]}")
        return (
            f"{self.n_candidates} layouts across rod counts {span} — "
            f"roughly {mins:.1f} min. The page is blocked while it runs."
        )


def budget(space, n_range, n_symmetric: int, n_random: int) -> Budget:
    """Estimate a run, from the search's OWN plan rather than a copy of it.

    `opt.plan_counts` / `opt.plan_size` are what `search` iterates, so the
    quote cannot drift from what actually runs. Re-deriving the skip rule here
    is how an estimate goes quietly stale.
    """
    counts = tuple(opt.plan_counts(space, n_range))
    total = opt.plan_size(space, n_range, n_symmetric, n_random)
    return Budget(total, total * SECONDS_PER_CANDIDATE, counts)


def trade_rows(result) -> list[dict]:
    """`SearchResult.trade_curve()`, formatted for a table.

    `None` becomes an em dash rather than 0: a rod count that found nothing
    has no slenderness, and printing 0 would read as the best row in the table.
    """
    out = []
    for row in result.trade_curve():
        out.append(
            {
                "rods": row["n_rods"],
                "feasible": "yes" if row["feasible"] else "no",
                "max λ": _fmt(row["max_lambda"], 0),
                "Σ length (in)": _fmt(row["total_length"], 1),
                "σ_min": _fmt(row["sigma_min"], 3),
                "past the knee": (
                    "—" if row["n_euler"] is None
                    else f"{row['n_euler']} of {row['n_rods']}"
                ),
                "why not": row["reason"],
            }
        )
    return out


def _fmt(value, digits: int) -> str:
    if value is None or not np.isfinite(value):
        return "—"
    return f"{value:.{digits}f}"


def candidate_label(candidate) -> str:
    """One line that identifies a candidate in a picker.

    Leads with rod count and slenderness because those are the two numbers the
    choice is actually made on.
    """
    return (
        f"{candidate.n_rods} rods · max λ {candidate.metrics.max_lambda:.0f} · "
        f"Σ {candidate.metrics.total_length:.0f} in · {candidate.seed_kind} seed"
    )


def candidate_rows(result, limit: int = 12) -> list[dict]:
    """The gallery table: the ranked candidates, best first."""
    rows = []
    for rank, cand in enumerate(result.candidates[:limit], start=1):
        m = cand.metrics
        rows.append(
            {
                "rank": rank,
                "rods": cand.n_rods,
                "feasible": "yes" if cand.feasible else "no",
                "max λ": _fmt(m.max_lambda, 0),
                "Σ length (in)": _fmt(m.total_length, 1),
                "σ_min": _fmt(m.sigma_min, 3),
                "min ρ²": _fmt(m.rho2_min, 4),
                "seed": cand.seed_kind,
            }
        )
    return rows


def metrics_summary(metrics, criteria=None) -> dict:
    """Headline numbers for one layout, already worded.

    `λ_crit` travels with `max λ` everywhere it is shown. A slenderness with no
    knee to compare it against is not interpretable.
    """
    verdict = fs.feasible(metrics, criteria)
    return {
        "rods": metrics.n_rods,
        "max λ": f"{metrics.max_lambda:.0f}  (knee {metrics.lambda_crit:.0f})",
        "past the knee": f"{metrics.n_euler} of {metrics.n_rods}",
        "Σ length (in)": f"{metrics.total_length:.1f}",
        "σ_min": f"{metrics.sigma_min:.3f}",
        "single-rod loss": (
            "survives any one loss" if metrics.survives_single_loss
            else f"{len(metrics.critical)} critical rod(s)"
        ),
        "verdict": "feasible" if verdict.ok else "; ".join(verdict.reasons),
    }


def trade_figure(result) -> go.Figure:
    """Rod count against slenderness and total length — the headline output.

    Two y-axes because the two costs of complexity move in opposite
    directions and the whole point is to see that: more rods buy lower
    slenderness, and on a well-conditioned space they shorten the total rod as
    well. Infeasible counts are drawn on the axis as red markers rather than
    dropped, so a floor the topology imposes is visible instead of implied by
    a gap.
    """
    rows = result.trade_curve()
    fig = go.Figure()

    good = [r for r in rows if r["feasible"]]
    bad = [r for r in rows if not r["feasible"]]

    if good:
        fig.add_trace(
            go.Scatter(
                x=[r["n_rods"] for r in good],
                y=[r["max_lambda"] for r in good],
                mode="lines+markers", name="max λ",
                line=dict(color=FEASIBLE_COLOR, width=3),
                marker=dict(size=10),
                hovertemplate="%{x} rods<br>max λ %{y:.0f}<extra></extra>",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=[r["n_rods"] for r in good],
                y=[r["total_length"] for r in good],
                mode="lines+markers", name="Σ length (in)", yaxis="y2",
                line=dict(color=LENGTH_COLOR, width=2, dash="dot"),
                marker=dict(size=7),
                hovertemplate="%{x} rods<br>Σ %{y:.0f} in<extra></extra>",
            )
        )
        knee = result.candidates[0].metrics.lambda_crit
        if np.isfinite(knee):
            fig.add_hline(
                y=knee, line=dict(color=KNEE_COLOR, dash="dash", width=2),
                annotation_text=f"buckling knee λ_crit = {knee:.0f}",
                annotation_position="top right",
            )

    if bad:
        fig.add_trace(
            go.Scatter(
                x=[r["n_rods"] for r in bad], y=[0] * len(bad),
                mode="markers", name="infeasible",
                marker=dict(color=INFEASIBLE_COLOR, size=13, symbol="x"),
                hovertext=[r["reason"] for r in bad],
                hovertemplate="%{x} rods — %{hovertext}<extra></extra>",
            )
        )

    fig.update_layout(
        xaxis=dict(title="rods", dtick=1),
        yaxis=dict(title="max slenderness λ", rangemode="tozero"),
        yaxis2=dict(title="Σ length (in)", overlaying="y", side="right",
                    rangemode="tozero", showgrid=False),
        legend=dict(orientation="h", y=1.12, x=0),
        margin=dict(l=60, r=60, t=40, b=50),
        height=420,
        uirevision="tierod-trade",
    )
    return fig


# ----------------------------------------------------------------------
# Adoption
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class AdoptReport:
    removed: tuple
    added: tuple

    def message(self) -> str:
        return (
            f"Adopted the layout: removed {len(self.removed)} rod(s), "
            f"installed {len(self.added)}."
        )


def adoptable(assembly, candidate) -> list[str]:
    """Reasons this candidate cannot be written into `assembly`.

    A search result parked in session state can outlive the geometry it was
    computed against. Installing rods that name a deleted region would produce
    a model that fails `validate()` with no way back except Reset.
    """
    problems = []
    missing = sorted(
        {
            end.region_id
            for rod in candidate.assembly.rods.values()
            for end in (rod.end_a, rod.end_b)
            if end.region_id not in assembly.regions
        }
    )
    if missing:
        problems.append(
            f"the layout attaches to region(s) {', '.join(missing)}, which the "
            f"model no longer has"
        )
    for rod_id in sorted(candidate.assembly.rods):
        rod = candidate.assembly.rods[rod_id]
        for tag in ("a", "b"):
            end = rod.end_a if tag == "a" else rod.end_b
            region = assembly.regions.get(end.region_id)
            if region is None:
                continue
            if end.q.size != region.ndim:
                problems.append(
                    f"{rod_id} end {tag} carries {end.q.size} parameter(s) but "
                    f"region {region.id} now has {region.ndim} — the region "
                    f"changed type since the search ran"
                )
            elif not region.in_bounds(end.q):
                problems.append(
                    f"{rod_id} end {tag} sits outside region {region.id}, "
                    f"which has been resized since the search ran"
                )
    return problems


def adopt(assembly, candidate) -> AdoptReport:
    """Replace every rod in `assembly` with the candidate's. Destructive.

    Ordered so that everything able to fail happens BEFORE the first deletion:
    the blockers are checked, then the replacement rods are built, and only
    then are the existing rods removed. A model left with no rods because the
    install failed halfway would be worse than a refusal.
    """
    blockers = adoptable(assembly, candidate)
    if blockers:
        raise ValueError("cannot adopt this layout — " + "; ".join(blockers))

    new_rods = [copy.deepcopy(candidate.assembly.rods[r])
                for r in sorted(candidate.assembly.rods)]
    removed = sorted(assembly.rods)
    for rod_id in removed:
        assembly.remove_rod(rod_id)
    for rod in new_rods:
        assembly.add_rod(rod)
    assembly.validate()
    return AdoptReport(tuple(removed), tuple([r.id for r in new_rods]))


# ----------------------------------------------------------------------
# Widget renderers — Streamlit only
# ----------------------------------------------------------------------


def criteria_inputs() -> fs.Criteria:
    """The feasibility gate, as inputs. Nothing here is hardcoded downstream."""
    c1, c2, c3 = st.columns(3)
    require = c1.checkbox(
        "Require single-failure tolerance", value=True,
        key="tierod::s::failsafe",
        help="Every rod must be losable without creating a mechanism "
             "(ρ² > 0 for all of them). Off, the search only avoids "
             "mechanisms in the intact layout.",
    )
    floor = c2.number_input(
        "σ_min floor", value=0.05, min_value=0.0, max_value=1.0, step=0.01,
        format="%g", key="tierod::s::sigma",
        help="Conditioning of the non-dimensionalized screw matrix. This is a "
             "CONSTRAINT, not a diagnostic: shorter rods mean smaller moment "
             "arms, and without a floor the search walks straight off the "
             "short-rod cliff into a near-mechanism.",
    )
    cap = c3.number_input(
        "Hard λ cap (0 = none)", value=0.0, min_value=0.0, step=10.0,
        format="%g", key="tierod::s::lamcap",
        help="Optional. Rejects any layout with a rod more slender than this.",
    )
    return fs.Criteria(
        sigma_floor=float(floor),
        require_single_failure=bool(require),
        max_lambda=float(cap) if cap > 0 else None,
    )


def _space_inputs(assembly) -> opt.LayoutSpace:
    space = opt.space_from(assembly)
    labels = {t: f"{t[0]} ↔ {t[1]}" for t in space.topologies}
    st.caption(
        f"{len(space.topologies)} cross-body region pair(s) available. The "
        "search picks only from these — it does not invent access that does "
        "not exist. Same-body pairs are excluded: such a rod contributes a "
        "column of exactly zero."
    )
    chosen = st.multiselect(
        "Allowed rod paths", space.topologies, default=space.topologies,
        format_func=labels.get, key="tierod::s::topos",
    )
    return space.restrict(chosen) if chosen else space


def _run_with_progress(space, criteria, n_range, seeds: int, total: int):
    """Run the search with the best-so-far layout drawn as it goes.

    Minutes of blocking work with nothing on screen is indistinguishable from
    a hang, and — the owner's actual complaint — you cannot see what is being
    made. So the scene is redrawn **only when the best improves**, which is a
    handful of times per run rather than once per candidate: enough to watch
    the layout take shape, cheap enough not to slow the thing down.
    """
    from apps.tierod import ui_scene

    bar = st.progress(0.0, text=f"0 of {total}")
    caption = st.empty()
    scene = st.empty()
    state = {"best": None, "shown": 0}

    def on_candidate(candidate, done, _total):
        bar.progress(
            min(done / max(total, 1), 1.0),
            text=f"{done} of {total} · {candidate.n_rods} rods · "
                 f"{candidate.seed_kind} seed",
        )
        best = state["best"]
        if not candidate.feasible or (
            best is not None and candidate.objective >= best.objective
        ):
            return
        state["best"] = candidate
        state["shown"] += 1
        m = candidate.metrics
        caption.markdown(
            f"**Best so far** — {candidate.n_rods} rods · max λ "
            f"{m.max_lambda:.0f} (knee {m.lambda_crit:.0f}) · "
            f"Σ {m.total_length:.0f} in · σ_min {m.sigma_min:.3f}"
        )
        scene.plotly_chart(
            ui_scene.build_figure(candidate.assembly), width="stretch",
            key=f"tierod-live-{state['shown']}",
        )

    result = opt.search(
        space, criteria, n_range=n_range, n_symmetric=seeds, n_random=seeds,
        on_candidate=on_candidate,
    )
    bar.empty()
    caption.empty()
    scene.empty()
    return result


def search_tab(assembly, state_key: str) -> None:
    problems = searchable(assembly)
    if problems:
        st.error(
            "This model cannot be searched yet:\n\n"
            + "\n".join(f"- {p}" for p in problems)
            + "\n\nBuild the missing pieces in the **Build** tab."
        )
        return

    st.caption(
        "Generates layouts from scratch and ranks them by "
        "`(max λ, Σ length, rod count)` behind a hard feasibility gate. It is "
        "a **stochastic local method**: it finds a good layout, not a proof of "
        "the optimum, and two runs can land in different places."
    )

    space = _space_inputs(assembly)
    criteria = criteria_inputs()

    floor = n_range_floor(assembly, criteria)
    c1, c2, c3 = st.columns(3)
    lo = int(c1.number_input(
        "Fewest rods", value=int(floor), min_value=1, step=1,
        key="tierod::s::lo",
        help="The bottom of the range to sweep. It defaults to the counting "
             "bound, which moves with the fail-safe setting.",
    ))
    hi = int(c2.number_input(
        "Most rods", value=int(floor) + 4, min_value=1, step=1,
        key="tierod::s::hi",
        help="The top of the range. Every count from fewest to most is "
             "searched independently — the span is the width of the trade "
             "curve, and cost is linear in it.",
    ))
    seeds = int(c3.number_input(
        "Seeds per count", value=6, min_value=1, max_value=24, step=1,
        key="tierod::s::seeds",
        help="Half symmetric (a spread × twist grid), half random. More seeds "
             "is the only lever on a local method's quality.",
    ))
    st.caption(floor_hint(lo, floor, criteria.require_single_failure))

    if hi < lo:
        st.error("‘Most rods’ is below ‘fewest rods’ — nothing to search.")
        return

    n_range = range(lo, hi + 1)
    est = budget(space, n_range, seeds, seeds)
    st.info(est.message())

    if st.button("Run the search", type="primary", width="stretch",
                 disabled=est.n_candidates == 0, key="tierod::s::run"):
        st.session_state[_RESULT_KEY] = _run_with_progress(
            space, criteria, n_range, seeds, est.n_candidates
        )
        st.session_state[_STAMP_KEY] = geometry_fingerprint(assembly)
        st.rerun()

    result = st.session_state.get(_RESULT_KEY)
    if result is None:
        st.caption("No search has been run yet.")
        return

    if st.session_state.get(_STAMP_KEY) != geometry_fingerprint(assembly):
        st.warning(
            "The geometry has changed since this search ran, so these layouts "
            "were fitted to regions that no longer look like this. Run it "
            "again before trusting the numbers or adopting anything."
        )

    _results(result, assembly, state_key)


def _results(result, assembly, state_key: str) -> None:
    import pandas as pd

    best = result.best
    st.markdown("#### What each extra rod buys")
    if best is None:
        st.error(
            f"No feasible layout in {result.n_evaluated} tries. The trade "
            f"table below gives the reason at each rod count — usually either "
            f"a mechanism (too few rods for the offered paths) or a σ_min "
            f"floor the geometry cannot reach."
        )
    st.plotly_chart(trade_figure(result), width="stretch", key="tierod-trade")
    st.dataframe(pd.DataFrame(trade_rows(result)), width="stretch",
                 hide_index=True)

    if best is None:
        return

    st.markdown("#### Candidates")
    st.caption(
        f"{len(result.feasible_candidates)} feasible of {result.n_evaluated} "
        f"evaluated, ranked by the objective."
    )
    st.dataframe(pd.DataFrame(candidate_rows(result)), width="stretch",
                 hide_index=True)

    picks = result.feasible_candidates
    labels = [f"#{i + 1}  {candidate_label(c)}" for i, c in enumerate(picks)]
    idx = labels.index(
        st.selectbox("Inspect a layout", labels, key="tierod::s::pick")
    )
    chosen = picks[idx]

    summary = metrics_summary(chosen.metrics, result.criteria)
    cols = st.columns(4)
    for col, key in zip(cols, ("rods", "max λ", "Σ length (in)", "σ_min")):
        col.metric(key, summary[key])
    st.caption(
        f"Past the knee: **{summary['past the knee']}** · "
        f"{summary['single-rod loss']} · {summary['verdict']}"
    )

    from apps.tierod import ui_scene

    st.plotly_chart(
        ui_scene.build_figure(chosen.assembly), width="stretch",
        key=f"tierod-cand-{idx}",
    )

    st.markdown("#### Adopt")
    blockers = adoptable(assembly, chosen)
    if blockers:
        st.error(
            "This layout can no longer be written into the model:\n\n"
            + "\n".join(f"- {b}" for b in blockers)
        )
        return
    st.warning(
        f"Adopting replaces all {len(assembly.rods)} rod(s) in the live model "
        f"with these {chosen.n_rods}. Download the current model from the "
        f"**Build** tab first if you want it back."
    )
    if st.button("Adopt this layout", width="stretch", key="tierod::s::adopt"):
        report = adopt(assembly, chosen)
        st.session_state["tierod::b::note"] = report.message()
        from apps.tierod import ui_build

        for key in ui_build.stale_keys(list(st.session_state.keys())):
            st.session_state.pop(key, None)
        st.rerun()


__all__ = [
    "AdoptReport",
    "Budget",
    "SECONDS_PER_CANDIDATE",
    "adopt",
    "adoptable",
    "budget",
    "candidate_label",
    "candidate_rows",
    "floor_hint",
    "criteria_inputs",
    "geometry_fingerprint",
    "metrics_summary",
    "n_range_floor",
    "search_tab",
    "searchable",
    "trade_figure",
    "trade_rows",
]
