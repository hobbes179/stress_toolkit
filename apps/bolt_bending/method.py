"""
apps/bolt_bending/method.py

The Method section — the derivation, the assumptions, and the worked example,
written out so the whole analysis is reproducible with a calculator.

⚠️ This is part of the deliverable, not decoration. If the mechanics in
`library/bolt_bending/kernel.py` change, update this text in the SAME commit.
It currently documents the kernel as built plus the §6 verification case from
`docs/bolt_bending/HANDOFF.md`.

Carried over as HTML from the original standalone tool, in the two-column
layout it was written for — the equations are typeset with `.bb-eq` blocks and
the prose sits in measured columns. Markdown could not hold that. Styling
comes from `styles.py`; nothing here is Streamlit-aware.
"""

from __future__ import annotations

# ══════════════════════════════════════════════════════════════════════════
# Left column — model through peak location
# ══════════════════════════════════════════════════════════════════════════
_COL_LEFT = """
<h3>1 &nbsp;Model</h3>
<p>The bolt is treated as a straight beam whose axis <i>x</i> runs from the
head bearing face (<i>x</i>&nbsp;=&nbsp;0) to the nut face
(<i>x</i>&nbsp;=&nbsp;<i>L</i>), where <i>L</i> is the total grip. The only
transverse loads are the bearing pressures the plates apply to the shank, plus
the end pair that closes the residual moment (&sect;3). Bending is taken in a
single plane, so the problem is one-dimensional.</p>
<p>Each plate is assumed to bear <b>uniformly over its own thickness</b>. This
is the conservative baseline: real bearing peaks toward the shear planes, which
shortens the effective moment arm. Switching on <i>Refine bearing
distribution</i> replaces this one assumption &mdash; and only this one
&mdash; with a solved distribution (&sect;11); everything from &sect;3 onward
runs unchanged on whatever &sect;2 produces.</p>

<h3>2 &nbsp;Bearing intensity</h3>
<p>A plate of thickness <i>t<sub>i</sub></i> carrying transverse load
<i>P<sub>i</sub></i> applies a line load</p>
<div class="bb-eq"><i>w<sub>i</sub></i> = <i>P<sub>i</sub></i> /
<i>t<sub>i</sub></i> &nbsp;&nbsp;[lbf/in]</div>
<p>over the span it occupies, constant within the plate. Gaps and spacers get
<i>w</i>&nbsp;=&nbsp;0. They support nothing and simply carry shear across,
which is why a spacer adds moment arm at no benefit. The shaded blocks in the
joint elevation are these intensities, scaled to a common maximum.</p>
<p>Under the refined distribution a plate is subdivided into thin strips, each
with its own <i>w</i>, and the blocks then show that solved variation instead
of one constant value per plate. The strips still sum to the entered
<i>P<sub>i</sub></i> exactly, so &sect;3 onward is unaffected.</p>

<h3>3 &nbsp;Equilibrium</h3>
<p>Force balance requires the plate loads to sum to zero:</p>
<div class="bb-eq">&Sigma; <i>P<sub>i</sub></i> = 0</div>
<p>Moment balance is a separate condition and is <i>not</i> automatic. Taking
moments about the head face,</p>
<div class="bb-eq"><i>M</i><sub>res</sub> = &Sigma; <i>P<sub>i</sub></i> &middot;
<span style="border-top:1px solid currentColor;">x</span><sub><i>i</i></sub>,&nbsp;&nbsp;
<span style="border-top:1px solid currentColor;">x</span><sub><i>i</i></sub> =
<i>x</i><sub>0,<i>i</i></sub> + <i>t<sub>i</sub></i>/2</div>
<p>A symmetric double-shear stack gives <i>M</i><sub>res</sub>&nbsp;=&nbsp;0 on
its own. Any asymmetry &mdash; an offset spacer, unequal thicknesses &mdash;
leaves a residue that must be reacted at the ends of the grip. The tool closes
it with an equal and opposite pair applied at <i>x</i>&nbsp;=&nbsp;0 and
<i>x</i>&nbsp;=&nbsp;<i>L</i>:</p>
<div class="bb-eq"><i>R<sub>L</sub></i> = &minus;<i>M</i><sub>res</sub> /
<i>L</i>,&nbsp;&nbsp; <i>R</i><sub>0</sub> = &minus;<i>R<sub>L</sub></i></div>
<p>Their resultant is a <b>pure couple of magnitude
<i>M</i><sub>res</sub></b>. That resultant is the only thing being asserted;
the split into two lateral forces is a bookkeeping device for delivering it.
It adds no net force, and both diagrams then close at the nut. Unchecking the
option drops the pair so you can see the raw imbalance.</p>

<p class="bb-note" style="font-size:13px;"><b>&#9888; ASSUMPTION &mdash; how
that couple is physically supplied.</b> It is <i>not</i> the head and nut
bearing sideways: nothing at the underside of a head can react a lateral
force, because there is no surface for it to push against. What reacts the
residual moment in a preloaded joint is the <b>redistribution of clamp
pressure across the head and nut undersides</b>. As the bolt tries to tilt,
the annular contact pressure shifts toward one edge &mdash; and that shift is
a moment, requiring no change in bolt tension while the annulus stays in
contact. For a 3/8 hex head the annulus carries roughly
0.10&thinsp;&middot;&thinsp;<i>P</i><sub>clamp</sub> lb&middot;in before the
light-side edge lifts; past that the contact collapses to one side and the
bolt does pick up axial tension. That is prying, and it is not modelled here.
</p>

<p class="bb-note" style="font-size:13px;">A force pair and an end moment are
equivalent globally but <b>not locally</b> &mdash; the pair injects shear at
the ends (<i>V</i>(0)&nbsp;=&nbsp;<i>R</i><sub>0</sub>&nbsp;&ne;&nbsp;0) where
an end moment would not. On the verification case the three defensible
closures of the same <i>M</i><sub>res</sub> give peak
|<i>M</i>|&nbsp;=&nbsp;<b>278.7</b> (force pair, used here), <b>250.0</b> (end
moment at the head alone) and <b>280.0</b> lb&middot;in (end moments split
head and nut) &mdash; about a 12% spread, with this model near the top of it.
It is deliberately not offered as a setting: the analyst's lever is the loads,
not the closure idealisation.</p>

<h3>4 &nbsp;Closure is checked, and failing it voids the margins</h3>
<p><i>R</i><sub>0</sub>&nbsp;=&nbsp;&minus;<i>R<sub>L</sub></i> adds no net
force, so that construction restores equilibrium <b>only if
&Sigma;<i>P</i> is already zero</b>. When &Sigma;<i>P</i>&nbsp;&ne;&nbsp;0 the
shear diagram does not return to zero at the nut,
<i>M</i>(<i>L</i>)&nbsp;&ne;&nbsp;0, and every margin is meaningless.</p>
<p><b>&Sigma;<i>P</i>&nbsp;=&nbsp;0 is necessary but not sufficient</b>, so the
integrated diagrams are tested as well. A layer carrying load with <i>zero
thickness</i> is given <i>w</i>&nbsp;=&nbsp;0 &mdash; its load counts in
&Sigma;<i>P</i> and in <i>M</i><sub>res</sub> but applies no bearing, so the
sum can balance while the diagrams never close. All three must hold:</p>
<div class="bb-eq">|&Sigma;<i>P</i>| &le; &epsilon;,&nbsp;&nbsp;
|<i>V</i>(<i>L</i>)| &le; &epsilon;,&nbsp;&nbsp;
|<i>M</i>(<i>L</i>)| &le; &epsilon;<i>L</i>,&nbsp;&nbsp; with &nbsp;
&epsilon; = 0.005 &middot; max|<i>P<sub>i</sub></i>|</div>
<p>The moment tolerance is scaled by the grip rather than by
max|<i>M</i>|&nbsp;&mdash; when the diagram is wrong, max|<i>M</i>| is inflated
and would slacken its own tolerance. <i>M</i>(<i>L</i>) is tested only when the
end pair is applied, since it is meant to be non-zero otherwise.</p>
<p>Failing any of them suppresses every stress and margin on the page rather
than printing a number an analyst could paste into a report. Physically a
non-zero &Sigma;<i>P</i> means something outside the model is reacting the
difference: friction at the faying surfaces from clamp-up, restraint outside
the grip, or &mdash; most often &mdash; an input error such as a missing layer
or a sign flip. It is <i>not</i> reacted at the head or nut, which bear
axially on the plate faces and have nothing to push against laterally.</p>

<h3>5 &nbsp;Integration</h3>
<p>Within a segment of constant <i>w</i>, starting at <i>x</i><sub>0</sub> with
known <i>V</i><sub>0</sub> and <i>M</i><sub>0</sub>, let
<i>u</i>&nbsp;=&nbsp;<i>x</i>&nbsp;&minus;&nbsp;<i>x</i><sub>0</sub>:</p>
<div class="bb-eq"><i>V</i>(<i>u</i>) = <i>V</i><sub>0</sub> + <i>w u</i></div>
<div class="bb-eq"><i>M</i>(<i>u</i>) = <i>M</i><sub>0</sub> +
<i>V</i><sub>0</sub> <i>u</i> + &frac12; <i>w u</i><sup>2</sup></div>
<p>Start with <i>V</i>&nbsp;=&nbsp;<i>R</i><sub>0</sub> and
<i>M</i>&nbsp;=&nbsp;0 at the head, walk the segments in order, and carry the
end values of one into the next. Shear is piecewise linear; moment is piecewise
quadratic. Add <i>R<sub>L</sub></i> to the shear at the nut and it returns to
zero.</p>

<h3>6 &nbsp;Locating the peak</h3>
<p>Peak moment sits where shear crosses zero. Inside a segment with
<i>w</i>&nbsp;&ne;&nbsp;0 that is</p>
<div class="bb-eq"><i>u</i>* = &minus;<i>V</i><sub>0</sub> / <i>w</i>,&nbsp;&nbsp;
valid if 0 &lt; <i>u</i>* &lt; segment length</div>
<p>Evaluate <i>M</i> at every <i>u</i>*, at every segment boundary, and at both
ends, then take the largest magnitude. Nothing else needs checking &mdash; a
quadratic has no other stationary points. A gap has <i>w</i>&nbsp;=&nbsp;0 and
so contains no interior peak, but it is where the moment climbs fastest at
constant slope.</p>
"""


# ══════════════════════════════════════════════════════════════════════════
# Right column — section, margins, worked example, exclusions
# ══════════════════════════════════════════════════════════════════════════
_COL_RIGHT = """
<h3>7 &nbsp;Section properties</h3>
<p>Round solid section of diameter <i>d</i>:</p>
<div class="bb-eq"><i>Z</i> = &pi; <i>d</i><sup>3</sup> / 32,&nbsp;&nbsp;
<i>A</i> = &pi; <i>d</i><sup>2</sup> / 4</div>
<p><b>&#9888; The section is constant along the bolt</b>, so the critical
station is selected by max|<i>M</i>|, not by max|<i>M</i>/<i>Z</i>|. That is
valid only when no thread runout, undercut, or diameter change falls inside the
bending region. If threads do reach the peak moment, enter the thread minor
diameter as the section diameter &mdash; conservative everywhere, exact
nowhere. On long grips with spacers this is a common trap, because the peak
often lands well inboard of where the shank ends.</p>

<h3>8 &nbsp;Stresses and margins</h3>
<div class="bb-eq"><i>f<sub>b</sub></i> = <i>M</i><sub>max</sub> /
<i>Z</i>,&nbsp;&nbsp; <i>f<sub>s</sub></i> = &kappa; <i>V</i><sub>max</sub> / <i>A</i></div>
<p>Bending is checked against a modulus of rupture, not against
<i>F<sub>tu</sub></i> directly. A solid round has a fully plastic shape factor
of 1.7; <i>k</i>&nbsp;=&nbsp;1.5 is the usual defensible working value, and
MMPDS bending MOR curves are better still where they exist.</p>
<div class="bb-eq"><i>F<sub>b</sub></i> = <i>k</i> <i>F<sub>tu</sub></i></div>
<div class="bb-eq">MS<sub>b</sub> = <i>F<sub>b</sub></i> /
(<i>f<sub>b</sub></i> &middot; FF) &minus; 1</div>
<div class="bb-eq">MS<sub>s</sub> = <i>F<sub>su</sub></i> /
(<i>f<sub>s</sub></i> &middot; FF) &minus; 1</div>
<p>FF is the fitting factor. <b>The shear basis depends on what <i>F<sub>su</sub></i> is.</b> An MMPDS-01 Table 8.1.4 fastener allowable is tabulated as ultimate load over the shank area &mdash; already an average &mdash; so <i>V</i>/<i>A</i> is the matching basis and no factor applies. A <i>material</i> shear strength is not: on a solid round the parabolic distribution peaks at 4/3 of the average, and the check must be against that peak. The tool picks the factor from the selected material&rsquo;s category and states it on the Strength card whenever it is not 1.0.</p>

<h3>9 &nbsp;Combined check</h3>
<p>Peak moment and peak shear almost never coincide, so pairing the two maxima
is both wrong and needlessly harsh. The tool evaluates the interaction at
<b>every station</b> and reports the worst:</p>
<div class="bb-eq"><i>R<sub>b</sub></i> = <i>M</i>(<i>x</i>)&middot;FF /
(<i>Z F<sub>b</sub></i>),&nbsp;&nbsp; <i>R<sub>s</sub></i> =
&kappa; <i>V</i>(<i>x</i>)&middot;FF / (<i>A F<sub>su</sub></i>)</div>
<p>&kappa; is the same shear basis factor as &sect;8 &mdash; it must appear in
both, or the interaction and the standalone shear check would disagree about
the same station.</p>
<div class="bb-eq">MS<sub>c</sub> = 1 / &radic;( max[ <i>R<sub>b</sub></i><sup>2</sup>
+ <i>R<sub>s</sub></i><sup>2</sup> ] ) &minus; 1</div>

<h3>10 &nbsp;Worked example</h3>
<p>The default stack, by hand. Plates 1&ndash;3 at 0.250, 0.500 and 0.250 in
carrying +1000, &minus;2000 and +1000 lbf, with a 0.060 in spacer after
plate 1. <i>L</i>&nbsp;=&nbsp;1.060 in, so every plate runs at
|<i>w</i>|&nbsp;=&nbsp;4000 lbf/in.</p>
<p>&Sigma;<i>P</i>&nbsp;=&nbsp;0. Moments about the head give
<i>M</i><sub>res</sub>&nbsp;=&nbsp;1000(0.125) &minus; 2000(0.560) +
1000(0.935) = &minus;60 lb&middot;in, hence
<i>R<sub>L</sub></i>&nbsp;=&nbsp;+56.60 and
<i>R</i><sub>0</sub>&nbsp;=&nbsp;&minus;56.60 lbf.</p>
<table class="bb-wex">
  <thead><tr><th><i>x</i>, in</th><th>station</th><th><i>V</i>, lbf</th>
  <th><i>M</i>, in&middot;lbf</th></tr></thead>
  <tbody>
    <tr><td>0</td><td>head</td><td>&minus;56.6</td><td>0</td></tr>
    <tr><td>0.250</td><td>end plate 1</td><td>943.4</td><td>110.8</td></tr>
    <tr><td>0.310</td><td>end spacer</td><td>943.4</td><td>167.5</td></tr>
    <tr class="bb-hi"><td>0.546</td><td><i>V</i> = 0, plate 2</td><td>0</td>
    <td>278.7</td></tr>
    <tr><td>0.810</td><td>end plate 2</td><td>&minus;1056.6</td><td>139.2</td></tr>
    <tr><td>1.060</td><td>nut, after <i>R<sub>L</sub></i></td><td>0</td><td>0</td></tr>
  </tbody>
</table>
<p>With <i>d</i>&nbsp;=&nbsp;0.315 in: <i>Z</i>&nbsp;=&nbsp;0.003069
in<sup>3</sup> and <i>A</i>&nbsp;=&nbsp;0.07793 in<sup>2</sup>. Then
<i>f<sub>b</sub></i>&nbsp;=&nbsp;278.7/0.003069&nbsp;=&nbsp;90.8 ksi against
<i>F<sub>b</sub></i>&nbsp;=&nbsp;1.5(160)&nbsp;=&nbsp;240 ksi, giving
MS<sub>b</sub>&nbsp;=&nbsp;+1.64. Shear at the peak-moment station is zero, so
the combined margin lands at the same +1.64.</p>
<p><b>Both diagrams close at the nut, which is the arithmetic check worth doing
every time.</b> If <i>M</i>(<i>L</i>) is not zero, the load split or the
residual moment has been mishandled. This case is asserted station by station
in <code>tests/bolt_bending/test_kernel.py</code>.</p>

<h3>11 &nbsp;What is not included</h3>
<p>No credit is taken for clamp-up, which genuinely stiffens the joint and
reduces bolt bending but is hard to quantify by hand. No axial load, preload or
prying &mdash; note that the &sect;3 couple is supplied by clamp pressure
redistributing under the head, which is only available while the joint stays
preloaded and the contact annulus stays closed.</p>
<p><b>Bearing peaking is available, but off by default.</b> The uniform
bearing of &sect;1 is the conservative baseline; the <i>refined bearing
distribution</i> in the sidebar replaces it with a beam on an elastic
foundation, which does let the bolt tilt in the hole and does shorten the
effective arm. It is an elastic, close-fit model: it captures neither the
plastic bearing redistribution behind the ESDU 91008 reduced arm nor the
Melcon &amp; Hoblit treatment of AFFDL-TR-69-42, and it does not decide the
load split. Its basis and its limits are printed with its results.</p>
<p>The load split between shear planes is an <b>input, not a result</b>. It is
statically indeterminate and should come from relative plate stiffness or a
bounding sensitivity study. Plate bearing, shear-out, net section and lug
strength are all separate checks &mdash; a bolt-bending tool that ignores them
can hand back a comfortable margin on the wrong failure mode.</p>
"""


# The opening claim is only true of the baseline. The refined pass assembles
# and solves a linear system, so promising "no solver" while it is running
# would be a false statement about the numbers on the same page.
_LEAD_BASELINE = (
    "Everything below is reproducible with a calculator. The tool does no "
    "iteration and calls no solver &mdash; it evaluates closed-form "
    "expressions segment by segment."
)
_LEAD_REFINED = (
    "&sect;3 onward is reproducible with a calculator, and is what the tool "
    "evaluates segment by segment. <b>&sect;1&ndash;2 are not, while the "
    "refined bearing distribution is on:</b> the bearing intensity is solved "
    "from a beam on an elastic foundation (one linear system, no iteration) "
    "rather than assumed uniform. The uniform baseline below is still "
    "computed &mdash; it is the comparison shown above."
)


def method_html(refined: bool = False) -> str:
    """The full Method section, two columns, ready for `st.markdown`.

    Args:
        refined: Whether the refined bearing distribution is the model in
            force. Changes only the lead paragraph, which otherwise claims the
            tool calls no solver — untrue while the refined pass is running.
    """
    lead = _LEAD_REFINED if refined else _LEAD_BASELINE
    return (
        '<div class="bb-method">'
        '<div class="bb-h2">Method</div>'
        f'<p class="bb-lead">{lead}</p>'
        '<div class="bb-mgrid">'
        f"<div>{_COL_LEFT}</div>"
        f"<div>{_COL_RIGHT}</div>"
        "</div></div>"
    )
