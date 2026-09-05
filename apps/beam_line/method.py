"""
apps/beam_line/method.py

The Method section -- the model, the sign conventions, the solution method,
the validity gate, and what is deliberately not modelled.

This is part of the deliverable, not decoration. If the mechanics in
`library/beam_line/` change, update this text in the SAME commit. It currently
documents the library as built.

Pure HTML. Nothing here is Streamlit-aware; styling comes from `styles.py`.
"""

from __future__ import annotations

_LEAD = (
    "Euler-Bernoulli line beam solved by the direct stiffness method, with "
    "shear, moment, slope and deflection recovered in closed form. Statically "
    "determinate and indeterminate beams are handled identically."
)


_COL_LEFT = """
<h3>1 &nbsp;Model and sign conventions</h3>
<p>A straight prismatic beam of span <i>L</i> lying along <i>x</i>, loaded
transversely in one plane. Every node carries two degrees of freedom &mdash;
transverse displacement <i>v</i> and rotation
<i>&theta;</i>&nbsp;=&nbsp;d<i>v</i>/d<i>x</i>. There is no axial degree of
freedom, so no axial force, no P&ndash;&Delta; effect, and no distinction
between a pin and a roller (&sect;2).</p>
<p>One convention is used by the solver, the diagrams and the figure alike:</p>
<div class="bl-eq"><i>x</i> &nbsp;left to right, 0 at the left end<br>
<i>v</i>, <i>P</i>, <i>w</i> &nbsp;positive <b>up</b><br>
<i>&theta;</i>, <i>M</i><sub>applied</sub> &nbsp;positive
<b>counterclockwise</b></div>
<p>A gravity load is therefore entered as a negative number, and its
deflection comes back negative. The plotted bending moment is the ordinary
<b>sagging-positive</b> one, so a simply supported beam under gravity shows
<i>M</i>&nbsp;&gt;&nbsp;0 across the whole span and a cantilever root shows
<i>M</i>&nbsp;&lt;&nbsp;0.</p>

<h3>2 &nbsp;Supports</h3>
<p>Each support restrains its two degrees of freedom independently, and each
one is free, rigid, or elastic:</p>
<ul>
<li><b>Pin / roller</b> &mdash; vertical only.</li>
<li><b>Fixed</b> &mdash; vertical and rotation.</li>
<li><b>Guided</b> &mdash; rotation only; the beam is free to slide vertically.</li>
<li><b>Spring</b> &mdash; a stiffness <i>k<sub>y</sub></i> (lb/in) or
<i>k<sub>&theta;</sub></i> (lb&middot;in/rad) rather than a rigid hold.</li>
</ul>
<p><b>A pin and a roller are the same support here.</b> Both restrain vertical
translation and nothing else, and with no axial degree of freedom in the model
there is nothing left for them to differ about &mdash; they give identical
reactions, diagrams and deflections. The module offers one restraint rather
than two symbols that compute the same answer.</p>
<p>A support may also be given a <b>prescribed movement</b> &mdash; settlement,
jig misalignment, growth of the structure it sits on. Against a rigid restraint
the beam is forced to that value; against a spring the far end of the spring
moves, so the force delivered is
<i>k<sub>y</sub></i>(<i>&Delta;</i>&nbsp;&minus;&nbsp;<i>v</i>). On a
determinate beam a settlement induces no internal load at all; on an
indeterminate one it induces real moments, which is the reason the input
exists.</p>

<h3>3 &nbsp;Internal hinges</h3>
<p>A hinge is a moment release: it transmits shear but not moment, so
<i>M</i>&nbsp;=&nbsp;0 there and the rotation is discontinuous across it. In
the assembly the node gets a <b>second rotation degree of freedom</b> &mdash;
elements to the left use one, elements to the right the other, and nothing
couples them.</p>
<p>Two consequences the tool enforces rather than lets you discover:
an applied moment cannot sit <i>on</i> a hinge (both sides hold
<i>M</i>&nbsp;=&nbsp;0, so nothing could equilibrate it), and a rotational
restraint cannot share a station with one.</p>

<h3>4 &nbsp;Solution</h3>
<p>Direct stiffness. Nodes are placed automatically at both ends, at every
support, at every hinge, at every point load and applied moment, and at both
ends of every distributed patch. Each element is the standard
Euler-Bernoulli beam:</p>
<div class="bl-eq"><b>k</b> = (<i>EI</i>/<i>L</i>&sup3;)
[12, 6<i>L</i>, &minus;12, 6<i>L</i>;
6<i>L</i>, 4<i>L</i>&sup2;, &minus;6<i>L</i>, 2<i>L</i>&sup2;;
&minus;12, &minus;6<i>L</i>, 12, &minus;6<i>L</i>;
6<i>L</i>, 2<i>L</i>&sup2;, &minus;6<i>L</i>, 4<i>L</i>&sup2;]</div>
<p>with consistent nodal loads for a linearly varying intensity
<i>w</i><sub>1</sub>&nbsp;&rarr;&nbsp;<i>w</i><sub>2</sub> obtained by
integrating the Hermite shape functions:</p>
<div class="bl-eq"><i>f</i> = [<i>L</i>(0.35<i>w</i><sub>1</sub> +
0.15<i>w</i><sub>2</sub>), &nbsp;
<i>L</i>&sup2;(3<i>w</i><sub>1</sub> + 2<i>w</i><sub>2</sub>)/60, &nbsp;
<i>L</i>(0.15<i>w</i><sub>1</sub> + 0.35<i>w</i><sub>2</sub>), &nbsp;
&minus;<i>L</i>&sup2;(2<i>w</i><sub>1</sub> + 3<i>w</i><sub>2</sub>)/60]</div>
<p>which collapses to the familiar
[<i>wL</i>/2, <i>wL</i>&sup2;/12, <i>wL</i>/2, &minus;<i>wL</i>&sup2;/12]
when the load is uniform.</p>
<p><b>There is no mesh refinement setting, and there does not need to be
one.</b> Euler-Bernoulli elements are exact at the nodes for these load types,
and &sect;6 recovers the interior of each element in closed form, so adding
nodes cannot change the answer. Refining the mesh is a null operation here,
not a convergence study.</p>

<h3>5 &nbsp;Reactions</h3>
<p>Taken as the structural residual at each supported degree of freedom,</p>
<div class="bl-eq"><b>R</b> = <b>K</b><sub>struct</sub><b>d</b> &minus;
<b>F</b><sub>applied</sub></div>
<p>evaluated with the spring stiffnesses left out of
<b>K</b><sub>struct</sub>, so an elastic support's force falls out of the same
expression as a rigid one's. Reactions are reported in the same convention as
the loads &mdash; positive up, positive counterclockwise &mdash; so loads and
reactions can be summed directly.</p>
"""


_COL_RIGHT = """
<h3>6 &nbsp;Diagrams</h3>
<p>Shear and moment come from statics, marching left to right and accumulating
the applied loads and the solved reactions:</p>
<div class="bl-eq"><i>V</i>(<i>x</i>) = &Sigma; <i>F</i>
&nbsp;&nbsp;&nbsp; <i>M</i>(<i>x</i>) = &Sigma; <i>F</i>&middot;(<i>x</i> &minus;
<i>a</i>) &minus; &Sigma; <i>M</i><sub>applied</sub></div>
<p>both sums taken over everything to the left of <i>x</i>.
<i>V</i>&nbsp;=&nbsp;d<i>M</i>/d<i>x</i> holds everywhere except across an
applied couple, where <i>M</i> steps by
&minus;<i>M</i><sub>applied</sub> and <i>V</i> is continuous.</p>
<p>Between two feature stations every quantity is a polynomial &mdash; degree 2
for <i>V</i>, 3 for <i>M</i>, 4 for <i>&theta;</i>, 5 for <i>v</i> &mdash; so
the tool carries the <b>coefficients</b> rather than a sample array. The peak
moment is then found by rooting <i>V</i>, which makes both its value and its
station exact. A sampled curve would instead report the largest of however
many samples were taken, wrong by up to half a sample interval and silently
dependent on that count.</p>

<h3>7 &nbsp;Slope and deflection</h3>
<p>Obtained by integrating the moment in closed form, piecewise:</p>
<div class="bl-eq"><i>&theta;</i>(<i>x</i>) = <i>&theta;</i><sub>0</sub> +
&int; <i>M</i>/<i>EI</i> d<i>x</i> &nbsp;&nbsp;&nbsp;
<i>v</i>(<i>x</i>) = <i>v</i><sub>0</sub> + &int; <i>&theta;</i> d<i>x</i></div>
<p>The integration constants are the solved rotation and deflection at
<i>x</i>&nbsp;=&nbsp;0, reset only at a hinge, where the rotation is genuinely
discontinuous. Because <i>EI</i> is applied per element the same integration
already supports a stepped beam; the interface exposes a single section
today.</p>
<p><i>EI</i> is entered directly, or taken from the section on the Beam Section
Stress page. That handoff is a <b>snapshot, not a live link</b> &mdash; it
reflects the section that page last built in this browser session, and it is
stated on screen so it is never inherited silently.</p>

<h3>8 &nbsp;Validity gate</h3>
<p>Results are suppressed unless three conditions hold. The first two are
closure of the integrated diagrams past the last support:</p>
<div class="bl-eq">|<i>V</i>(<i>L</i>)| / <i>V</i><sub>peak</sub>
&nbsp;&le;&nbsp; 10<sup>&minus;6</sup> &nbsp;&nbsp;&nbsp;
|<i>M</i>(<i>L</i>)| / <i>M</i><sub>peak</sub>
&nbsp;&le;&nbsp; 10<sup>&minus;6</sup></div>
<p>The third is that integrating &sect;7 forward from
<i>x</i>&nbsp;=&nbsp;0 reproduces the solved deflection at every node. That is
a genuine cross-check rather than a restatement: the integration uses the
solve only at the left end, so if the reactions were wrong the integrated curve
would miss the prescribed value at the far supports. A correct solve lands
around 10<sup>&minus;14</sup>, many orders inside the gate.</p>
<p>Summing the applied forces to zero is <b>necessary but not sufficient</b>,
which is why the gate is on the integrated diagrams and not on that sum.</p>

<h3>9 &nbsp;Mechanism detection</h3>
<p>An under-supported beam has a rigid-body mode, so its free-degree-of-freedom
stiffness matrix is singular. The matrix is scaled to a unit diagonal &mdash;
vertical and rotational terms otherwise differ by <i>L</i>&sup2; for reasons
that have nothing to do with stability &mdash; and its smallest singular value
compared with its largest. A genuine mechanism sits at the
10<sup>&minus;16</sup> floor while a real beam, even on deliberately soft
springs, sits many orders above, so the verdict does not turn on where in that
gap the threshold sits. The measured ratio is reported.</p>
<p>When the beam is a mechanism no diagram is drawn, because a plausible-looking
diagram is worse than none.</p>

<h3>10 &nbsp;Switched-off items</h3>
<p>Every support, load and release carries an include/exclude switch, so the
effect of one can be seen by flipping it rather than by deleting and
rebuilding it. Switching an item off removes it from the solve completely
&mdash; it is not scaled to zero, it is absent.</p>
<p>An excluded item is nonetheless <b>named in the results</b> and drawn
ghosted on the elevation. That is deliberate: these figures are screenshotted
into stress reports, and a load that is simply not in the picture is one
nobody notices is missing. If the notice above the figure is present, the
results below it are for a reduced model.</p>

<p><b>Locked scale.</b> With <i>Lock diagram scale</i> on, each panel is
scaled to the envelope of every ON/OFF combination of the loads, so switching
one off shrinks the curve instead of rescaling the axis under it. A dashed
rule marks the envelope whenever the current subset does not reach it &mdash;
that gap is the contribution of whatever is switched off.</p>
<p>The envelope is <b>exact and costs one solve per load</b>, not one per
combination. The response is linear in the loads, so at any station the
largest value any subset can reach is obtained by including exactly the loads
whose contribution is positive there:</p>
<div class="bl-eq">upper(<i>x</i>) = <i>V</i><sub>0</sub>(<i>x</i>) +
&Sigma;<sub><i>i</i></sub> max[<i>V<sub>i</sub></i>(<i>x</i>) &minus;
<i>V</i><sub>0</sub>(<i>x</i>), 0]</div>
<p>with <i>V</i><sub>0</sub> the response to no loads at all &mdash; which is
not necessarily zero, since an imposed settlement is present in every
combination including the empty one. Switching a <i>support</i> off changes
the structure rather than the load, and the response is not linear in that, so
a different support arrangement gets its own envelope.</p>

<h3>11 &nbsp;Not modelled</h3>
<p>Stated so nothing here is assumed by omission:</p>
<ul>
<li><b>Shear deformation.</b> Euler-Bernoulli, so plane sections stay plane
and normal. Deflections are under-predicted on deep, short spans &mdash;
roughly where <i>L</i>/<i>d</i>&nbsp;&lt;&nbsp;10 for metals. A Timoshenko
element would need <i>GA</i><sub>s</sub> and a shear form factor.</li>
<li><b>Axial force and P&ndash;&Delta;.</b> No axial degree of freedom, so no
beam-column interaction and no buckling of any kind &mdash; not Euler, not
lateral-torsional.</li>
<li><b>Torsion and out-of-plane loading.</b> One bending plane only.</li>
<li><b>Self-weight.</b> Not added automatically. Enter it as a distributed
load if it matters.</li>
<li><b>Plasticity, large deflection, and any nonlinearity.</b> Linear elastic
and small displacement throughout, so superposition holds and load cases can
be scaled.</li>
<li><b>Stress and margins of safety.</b> This module reports <i>V</i>,
<i>M</i> and <i>v</i>. Converting the peak moment into a stress and a margin
is the Beam Section Stress module's job &mdash; carry <i>M</i> across.</li>
</ul>
"""


def method_html() -> str:
    """The Method section, as a two-column HTML block."""
    return (
        '<div class="bl-method">'
        f'<p class="bl-lead">{_LEAD}</p>'
        f'<div class="bl-mgrid"><div>{_COL_LEFT}</div>'
        f'<div>{_COL_RIGHT}</div></div>'
        "</div>"
    )
