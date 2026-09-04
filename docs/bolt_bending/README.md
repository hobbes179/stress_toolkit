# Bolt Bending — source material

Archive of the standalone tool this module was ported from. Neither file is
executed by the toolkit; both are kept for traceability.

| File | What it is |
|---|---|
| `index.html` | The original single-file browser tool. Self-contained: inline CSS and vanilla JS, hand-built SVG, no dependencies, works offline. This is the reference implementation the Python port was checked against. |
| `HANDOFF.md` | The original specification — architecture, mechanics, known defects, enhancement tracks, and the §6 verification case. |

## Reading these

`HANDOFF.md` is still the authoritative statement of the **mechanics** and of
the **enhancement backlog**. Where it describes *file layout* — "one file, no
build step, no framework, `index.html` is the filename" — those constraints
applied to the standalone deliverable and **do not apply to the ported
module**. The port's own conventions are in `apps/bolt_bending/CLAUDE.md`.

Two items in `HANDOFF.md` §4 are flagged "fix these first". Their status:

- **§4.1 force imbalance** — **fixed in the port.** `BoltAnalysis.balanced`
  gates `Margins.valid`, and the page suppresses every stress and margin when
  the loads do not close. Tolerance is a pure ratio, `|ΣP| > 0.005·max|Pᵢ|`,
  replacing the ad hoc JS test that mixed an absolute 0.5 lbf floor with a
  scaled term.
- **§4.2 variable section** — **not fixed.** Deferred by the owner
  (2026-09-03) on the assumption that no threads fall in the bending region.
  The section is constant and the critical station is selected by max|M|. The
  assumption is stated in the kernel docstring, on the Margins tab, and in the
  Method section. See `apps/bolt_bending/CLAUDE.md` for the backlog.

## Verification

The §6 verification case is asserted station by station in
`tests/bolt_bending/test_kernel.py`, along with the standing arithmetic check
that both diagrams close at the nut. The port reproduces every published
number: `M_res` = −60 lb·in, `R_L` = +56.60 lbf, peak `M` = 278.7 lb·in at
x = 0.546 in, `f_b` = 90.8 ksi, `MS_b` = `MS_c` = +1.64.

The second case named in §6 — symmetric double shear, where `M_res` = 0 and
the peak moment has the closed form `P(2·t_outer + t_inner)/8` — is also
asserted, as §6 suggested.
