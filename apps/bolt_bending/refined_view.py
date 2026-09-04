"""
apps/bolt_bending/refined_view.py

HTML blocks for the refined bearing distribution. Pure — no Streamlit import;
the page owns presentation, this owns markup. Styling comes from `styles.py`.

The refinement reads the SAME layer and bolt data as the baseline and adds one
input (plate material). It is a **toggle on the one page**, not a second tab:
there is one set of results at a time, and `model_strip_html()` states which
bearing assumption produced them. Turning the toggle off restores the baseline
exactly — the refinement provably degenerates to it (see `refined.py`).

`supplement()` returns the blocks that only make sense when the refinement is
active: the baseline-vs-refined comparison, the verdict, the per-plate table,
the documented basis for k, and the limits. The figure is NOT among them — the
page's main figure already draws whichever model is in force.
"""

from __future__ import annotations

from apps.bolt_bending.plotting import Group, fmt, sig
from library.bolt_bending.kernel import Allowables, BoltSection, Margins, margins
from library.bolt_bending.refined import RefinedResult

# Beyond this the model and Huth disagree enough to warrant a look rather than
# a shrug. The published fastener-flexibility formulas routinely differ by ~2x
# among themselves, so the band is deliberately wide.
CROSS_CHECK_BAND = (0.5, 2.0)


def _pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def model_strip_html(r: RefinedResult | None) -> str:
    """The bearing assumption currently in force, in words, above the results.

    Rendered in BOTH states. A toggle that silently changes the peak moment by
    15% is a trap; this is what keeps it honest, and it is why the explanation
    lives here rather than only inside the refinement's own blocks.

    Args:
        r: The refined result when the refinement is active, else None for the
           uniform baseline.
    """
    if r is None:
        return (
            '<div class="bb-model">'
            '<span class="bb-tag">Bearing model</span>'
            "<b>Uniform &mdash; baseline.</b> Each plate's load spreads evenly "
            "over its own thickness. That is equivalent to assuming the bolt "
            "is <b>rigid across the thickness</b> and cannot tilt in the hole, "
            "so it presses evenly. Conservative on a long grip, where a real "
            "bolt bends and bearing concentrates toward the shear planes. "
            "<i>Refine bearing distribution</i> in the sidebar relaxes it."
            "</div>"
        )
    return (
        '<div class="bb-model bb-model-refined">'
        '<span class="bb-tag">Bearing model</span>'
        "<b>Refined &mdash; beam on an elastic foundation.</b> The bolt is "
        "allowed to bend within each hole, so bearing concentrates toward the "
        "shear planes and the effective moment arm shortens. Peak moment "
        f"<b>{sig(r.refined.M_max.M)}</b> against <b>{sig(r.baseline.M_max.M)}"
        f"</b> lb&middot;in uniform &mdash; a <b>{_pct(r.conservatism_recovered)}"
        "</b> change. This is a <b>less-conservative</b> result: quote it with "
        "the basis and limits below, never on its own."
        "</div>"
    )


def headline_html(r: RefinedResult, m_base: Margins, m_ref: Margins) -> str:
    """The six-cell comparison grid: baseline against refined."""
    if not m_base.valid:
        cells = [("Peak moment, baseline", "&mdash;", "bb-void", ""),
                 ("Peak moment, refined", "&mdash;", "bb-void", ""),
                 ("Conservatism recovered", "&mdash;", "bb-void", ""),
                 ("MS bending, baseline", "&mdash;", "bb-void", ""),
                 ("MS bending, refined", "&mdash;", "bb-void", ""),
                 ("Governing &beta;&middot;t", f"{r.max_beta_t:.2f}", "", "")]
    else:
        cells = [
            ("Peak moment, baseline", sig(r.baseline.M_max.M), "",
             " <small>lb&middot;in</small>"),
            ("Peak moment, refined", sig(r.refined.M_max.M), "",
             " <small>lb&middot;in</small>"),
            ("Conservatism recovered", _pct(r.conservatism_recovered), "", ""),
            ("MS bending, baseline", f"{m_base.MS_bending:+.2f}", "", ""),
            ("MS bending, refined", f"{m_ref.MS_bending:+.2f}", "", ""),
            ("Governing &beta;&middot;t", f"{r.max_beta_t:.2f}", "", ""),
        ]
    body = "".join(
        f"<div><dt>{lab}</dt><dd class='{cls}'>{val}{unit}</dd></div>"
        for lab, val, cls, unit in cells)
    return f'<dl class="bb-res">{body}</dl>'


def verdict_html(r: RefinedResult) -> str:
    """Say plainly whether the refinement is worth anything on this joint."""
    bt = r.max_beta_t
    if not r.refinement_is_material:
        return (
            '<div class="bb-card"><div class="bb-h2">Verdict</div>'
            f'<p class="bb-note" style="font-size:13.5px;margin-top:0;">'
            f"&beta;&middot;t = <b>{bt:.2f}</b> on the governing plate. Below "
            "about 1 the bolt is stiff over the plate's thickness and bearing "
            "really is near-uniform, so the refinement changes the answer by "
            f"only {_pct(r.conservatism_recovered)}. <b>Use the baseline</b> "
            "&mdash; it is already the right model here.</p></div>"
        )
    return (
        '<div class="bb-card"><div class="bb-h2">Verdict</div>'
        f'<p class="bb-note" style="font-size:13.5px;margin-top:0;">'
        f"&beta;&middot;t = <b>{bt:.2f}</b> on the governing plate, so the "
        "bolt tilts appreciably within the hole and uniform bearing is "
        f"carrying <b>{_pct(r.conservatism_recovered)}</b> of unnecessary "
        "moment. The characteristic decay length is "
        f"<b>{fmt(r.plates[0].characteristic_length, 3)} in</b> against plate "
        "thicknesses of "
        + ", ".join(fmt(p.t, 3) for p in r.plates)
        + " in. This is a real, defensible reduction &mdash; but it is a "
        "<b>less-conservative</b> result, so it must be quoted with its basis "
        "and its assumptions, both stated below.</p></div>"
    )


def plates_html(r: RefinedResult) -> str:
    """Per-plate diagnostics.

    The material and `k` columns appear only on a mixed stack. On a uniform
    one they would repeat the same value down the table and bury the columns
    that vary; the single `k` is stated once in the basis card instead.
    """
    mixed = r.mixed_stack
    extra_head = ("<th>material</th><th>k, Msi</th>" if mixed else "")
    rows = "".join(
        f"<tr><td>{p.index}</td><td>{fmt(p.t, 3)}</td>"
        f"<td>{sig(p.P)}</td>"
        + (f"<td>{p.material or '&mdash;'}</td><td>{p.k_msi:.1f}</td>"
           if mixed else "")
        + f"<td>{p.beta:.2f}</td>"
        f"<td>{fmt(p.characteristic_length, 3)}</td>"
        f"<td><b>{p.beta_t:.2f}</b></td>"
        f"<td>{'peaks' if p.beta_t > 1.0 else 'near-uniform'}</td></tr>"
        for p in r.plates)
    note = (
        "&beta; = (k/4EI)<sup>1/4</sup>. 1/&beta; is the distance over which "
        "the bolt's deflection decays inside a plate: when it is short "
        "compared with the plate thickness, bearing concentrates toward the "
        "shear plane and the moment arm shortens.")
    if mixed:
        note += (
            " <b>This stack mixes materials</b>, so each plate sits on its own "
            "bed and peaks at its own rate &mdash; the stiffer plate draws its "
            "bearing in harder. There is no single k for the joint.")
    return (
        '<div class="bb-card"><div class="bb-h2">Per-plate bearing</div>'
        '<table class="bb-wex"><thead><tr>'
        "<th>plate</th><th>t, in</th><th>P, lbf</th>" + extra_head +
        "<th>&beta;, 1/in</th>"
        "<th>1/&beta;, in</th><th>&beta;&middot;t</th><th>bearing</th>"
        "</tr></thead><tbody>" + rows + "</tbody></table>"
        f'<p class="bb-note">{note}</p></div>'
    )


def basis_html(r: RefinedResult) -> str:
    """The documented basis for k, plus the independent Huth cross-check."""
    ratio = r.cross_check_ratio
    if ratio is None:
        cross = ("<p class='bb-note'>Cross-check unavailable: needs two plates "
                 "carrying opposing loads.</p>")
    else:
        lo, hi = CROSS_CHECK_BAND
        if lo <= ratio <= hi:
            mark, tone = "&#10003;", "bb-ok"
            verdict = (
                f"within the expected band &mdash; the derived k reproduces "
                f"the published lumped compliance to {ratio:.2f}&times;.")
        else:
            mark, tone = "!", "bb-warn"
            verdict = (
                f"<b>outside the {lo:g}&ndash;{hi:g}&times; band</b>. Treat "
                "the refined numbers with caution and check the plate "
                "material and thicknesses.")
        cross = (
            f'<ul class="bb-checks"><li class="{tone}">'
            f'<span class="bb-mark">{mark}</span><span>'
            f"Model compliance <b>{r.model_C:.3e}</b> vs Huth "
            f"<b>{r.huth_C:.3e}</b> in/lb &mdash; ratio <b>{ratio:.2f}</b>, "
            f"{verdict}</span></li></ul>")

    if r.mixed_stack:
        headline = (
            '<div class="bb-eq">k<sub>i</sub> = E<sub>plate,i</sub> &nbsp; '
            "[lb/in per in], per plate &mdash; see the table above</div>"
            '<p class="bb-note" style="font-size:13px;margin-top:6px;">'
            "The plates name different materials, so each gets its own bed. "
            f"The governing plate is on <b>{r.basis.k_msi:.1f} Msi</b>; the "
            "cross-check below uses each plate's own modulus.</p>")
    else:
        headline = (
            f'<div class="bb-eq">k = E<sub>plate</sub> = '
            f"{r.basis.k_msi:.1f} Msi &nbsp; [lb/in per in]</div>")

    return (
        '<div class="bb-card"><div class="bb-h2">Basis for k</div>'
        + headline
        + f'<p class="bb-note" style="font-size:13px;">'
        f"<b>{r.basis.citation}.</b> {r.basis.note}</p>"
        '<div class="bb-h2" style="margin-top:16px">'
        "Independent cross-check &mdash; Huth (ASTM STP 927, 1986)</div>"
        + cross +
        '<p class="bb-note">&#9888; VERIFY &mdash; the Huth exponent and '
        "coefficient are the commonly quoted bolted-metallic constants and "
        "have not been checked against the paper. The cross-check is a sanity "
        "test on k, never an input to it: the two come from independent "
        "sources by design, and the published formulas routinely differ by "
        "about 2&times; among themselves.</p></div>"
    )


def caveats_html(r: RefinedResult) -> str:
    items = [
        (r.trustworthy,
         f"Solve residual {r.residual:.1e}; each plate's solved load is "
         f"within {r.load_error:.1e} of the value entered, before the strips "
         f"were normalised onto it."
         + ("" if r.trustworthy else
            " <b>The solve did not satisfy the load split it was given</b> "
            "&mdash; do not use these numbers.")),
        (False,
         "<b>Close-fit assumption.</b> The elastic bed is linear and "
         "two-sided, so a negative reaction means the bolt bearing on the far "
         "side of the hole. Valid for a close-fit bolt; a sloppy clearance fit "
         "takes up the gap first and this will over-predict the restraint."),
        (False,
         "<b>No plastic bearing.</b> At ultimate the plate yields locally and "
         "redistributes, which this elastic model does not capture."),
        (False,
         "<b>The load split is still your input.</b> It is statically "
         "indeterminate; this refines only the distribution within each plate."),
    ]
    rows = "".join(
        f'<li class="{"bb-ok" if ok else "bb-warn"}">'
        f'<span class="bb-mark">{"&#10003;" if ok else "!"}</span>'
        f"<span>{txt}</span></li>"
        for ok, txt in items)
    return (
        '<div class="bb-card"><div class="bb-h2">Assumptions and limits</div>'
        f'<ul class="bb-checks">{rows}</ul></div>'
    )


def groups(r: RefinedResult) -> list[Group]:
    """The physical layers, so the figure annotates by plate rather than by
    strip. Without this the figure draws one station tick per strip — 24 per
    plate — instead of one per layer. Passed to `joint_diagram_svg` by the
    page whenever the refined analysis is the one being drawn."""
    groups, x, n = [], 0.0, 0
    for sg in r.baseline.segments:
        if sg.kind == "plate":
            n += 1
        groups.append(Group(x0=sg.x0, x1=sg.x1, kind=sg.kind,
                            index=n if sg.kind == "plate" else 0, P=sg.P))
        x = sg.x1
    return groups


def figure_note_html() -> str:
    """Caption appended to the page's main figure when the refinement is on.

    There is only one figure — the toggle swaps what it draws — so this says
    what changed rather than asking the reader to compare two pictures.
    """
    return (
        '<p class="bb-note" style="margin-top:8px;">Each plate is drawn as its '
        "solved strips rather than one uniform block: the load on a plate is "
        "unchanged, but it now concentrates toward the shear planes instead of "
        "spreading evenly through the thickness. That shorter effective arm is "
        "the whole refinement.</p>"
    )


def supplement(r: RefinedResult, section: BoltSection,
               allow: Allowables) -> list[str]:
    """Blocks that only apply when the refinement is active, in display order.

    The figure is deliberately absent — the page's main figure already draws
    the refined distribution, so repeating it here would show the same picture
    twice. `model_strip_html()` and `figure_note_html()` carry the explanation
    that used to sit on the tab's intro card.
    """
    m_base = margins(r.baseline, section, allow)
    m_ref = margins(r.refined, section, allow)
    return [
        headline_html(r, m_base, m_ref),
        verdict_html(r),
        plates_html(r),
        basis_html(r),
        caveats_html(r),
    ]
