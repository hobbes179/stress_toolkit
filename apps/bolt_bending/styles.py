"""
apps/bolt_bending/styles.py

Page CSS for the Bolt Bending module.

This is the original standalone tool's stylesheet (archived at
`docs/bolt_bending/index.html`), with its design tokens remapped onto the
toolkit's `THEME` / `BOLT_PALETTE`. The original's composition — a dense
two-column engineering-report layout, a six-cell results grid, tinted
equation blocks — was better than the toolkit's default page furniture for
this content, so it is reproduced rather than replaced.

Token mapping from the original:

    --paper      -> THEME.bg          --shear   -> BOLT_PALETTE["shear"]
    --panel      -> THEME.bg3         --moment  -> BOLT_PALETTE["moment"]
    --ink        -> THEME.text        --warn    -> THEME.warn_fg
    --muted      -> THEME.muted       --ok      -> THEME.pass_fg
    --rule       -> THEME.border      --field   -> THEME.bg2
    --rule-soft  -> THEME.rule_soft

Class names are prefixed `bb-` so they cannot collide with the toolkit's
`tk-` components. Injected once per page, after `inject_css()`.
"""

from __future__ import annotations

from ui.theme import BOLT_PALETTE, THEME


def bolt_css() -> str:
    """The page stylesheet, as a `<style>` block ready for `st.markdown`."""
    t = THEME
    c = BOLT_PALETTE

    return f"""<style>
/* ── page header ─────────────────────────────────────────────────── */
.bb-header {{
  display:flex; align-items:baseline; gap:16px; flex-wrap:wrap;
  padding-bottom:12px; margin:0 0 18px;
  border-bottom:2px solid {t.text};
}}
.bb-header h1 {{
  font-size:23px; font-weight:600; letter-spacing:-.01em;
  margin:0; padding:0; color:{t.text};
}}
.bb-header p {{
  margin:0; color:{t.muted}; font-size:14px; max-width:56ch; line-height:1.5;
}}

/* ── section label, the original's h2 ────────────────────────────── */
.bb-h2 {{
  font-size:13px; font-weight:600; color:{t.muted};
  margin:0 0 10px; letter-spacing:.01em;
}}

/* ── card ─────────────────────────────────────────────────────────── */
.bb-card {{
  background:{t.bg3}; border:1px solid {t.border}; border-radius:3px;
  padding:16px 16px 18px;
}}
.bb-card > .bb-h2:first-child {{ margin-top:0; }}
.bb-card .bb-note {{
  font-size:12px; color:{t.muted}; margin:10px 0 0; line-height:1.55;
}}

/* Streamlit's bordered container, restyled to match .bb-card. Used for the
   one block that cannot be raw HTML — the stack editor is a live widget. */
div[data-testid="stVerticalBlockBorderWrapper"] {{
  background:{t.bg3}; border:1px solid {t.border} !important;
  border-radius:3px; padding:14px 16px 16px;
}}

/* ── peak-moment callout ─────────────────────────────────────────── */
.bb-peak {{
  font-size:15px; margin:12px 2px 0; color:{t.text};
  font-variant-numeric:tabular-nums;
}}
.bb-peak b {{ font-weight:600; }}

/* ── results grid — the original's .res ──────────────────────────── */
.bb-res {{
  display:grid; grid-template-columns:repeat(auto-fit,minmax(148px,1fr));
  gap:1px; background:{t.border}; border:1px solid {t.border};
  border-radius:3px; overflow:hidden; margin:0;
}}
.bb-res > div {{ background:{t.bg3}; padding:11px 13px; }}
.bb-res dt {{ font-size:12px; color:{t.muted}; margin:0 0 3px; font-weight:400; }}
.bb-res dd {{
  margin:0; font-size:19px; letter-spacing:-.01em; color:{t.text};
  font-variant-numeric:tabular-nums;
}}
.bb-res dd small {{ font-size:12.5px; color:{t.muted}; letter-spacing:0; }}
.bb-res dd.bb-void {{ color:{t.muted}; }}
.bb-res dd.bb-neg  {{ color:{c['moment']}; }}

/* ── screening checks ────────────────────────────────────────────── */
.bb-checks {{ list-style:none; margin:0; padding:0; font-size:13.5px; }}
.bb-checks li {{
  display:flex; gap:9px; padding:6px 0;
  border-top:1px solid {t.rule_soft}; color:{t.text2}; line-height:1.5;
}}
.bb-checks li:first-child {{ border-top:0; }}
.bb-checks b {{ font-weight:600; font-variant-numeric:tabular-nums; }}
.bb-checks .bb-mark {{
  flex:0 0 auto; width:13px; text-align:center; font-weight:700;
}}
.bb-checks .bb-ok   .bb-mark {{ color:{t.pass_fg}; }}
.bb-checks .bb-warn .bb-mark {{ color:{t.warn_fg}; }}
.bb-checks .bb-ok span:last-child {{ color:{t.muted}; }}

/* ── imbalance banner ────────────────────────────────────────────── */
.bb-banner {{
  background:{t.warn_bg}; border:1px solid {t.warn_fg};
  border-left-width:3px; border-radius:3px;
  padding:11px 14px; margin:0 0 16px; font-size:13.5px;
  color:{t.text}; line-height:1.55;
}}
.bb-banner b {{ font-weight:600; }}

/* ── method section ──────────────────────────────────────────────── */
.bb-method {{ margin-top:8px; }}
.bb-method .bb-lead {{ margin:0 0 4px; color:{t.muted}; max-width:80ch; }}
.bb-mgrid {{
  display:grid; grid-template-columns:1fr 1fr; gap:8px 44px; margin-top:6px;
}}
@media (max-width:1100px) {{ .bb-mgrid {{ grid-template-columns:1fr; gap:0; }} }}
.bb-method h3 {{
  font-size:13.5px; font-weight:600; margin:22px 0 8px; padding-bottom:5px;
  border-bottom:1px solid {t.rule_soft}; color:{t.text};
}}
.bb-method p {{
  margin:0 0 11px; max-width:74ch; font-size:14.5px;
  color:{t.text2}; line-height:1.6;
}}
.bb-method i {{ font-style:italic; }}
.bb-method b {{ font-weight:600; color:{t.text}; }}
.bb-eq {{
  background:{t.bg2}; border-left:2px solid {c['shear']};
  padding:9px 13px; margin:0 0 11px; font-size:15px; color:{t.text};
  font-variant-numeric:tabular-nums; overflow-x:auto;
}}
.bb-wex {{
  width:100%; border-collapse:collapse; margin:0 0 12px; font-size:13.5px;
  font-variant-numeric:tabular-nums; color:{t.text2};
}}
.bb-wex th {{
  padding:0 10px 5px 0; border-bottom:1px solid {t.border};
  text-align:left; font-weight:500; color:{t.muted};
}}
.bb-wex td {{ padding:5px 10px 5px 0; border-bottom:1px solid {t.rule_soft}; }}
.bb-wex tr.bb-hi td {{ background:{t.amber_bg}; font-weight:600; color:{t.text}; }}

/* ── the figure ──────────────────────────────────────────────────── */
.bb-fig svg {{ display:block; width:100%; height:auto; }}

/* ── page measure ────────────────────────────────────────────────────
   The original is a centred 1180px column, not a full-bleed dashboard.
   Streamlit ships max-width:none here, so the content stretches to the
   window and the two-column layout falls apart on a wide monitor. */
div[data-testid="stMainBlockContainer"] {{
  max-width:1180px; margin:0 auto; padding:26px 20px 72px;
}}

/* ── tighten Streamlit's default vertical rhythm on this page ─────
   The original is engineering-report dense; Streamlit's stock spacing
   pushes the same content onto two screens. Scoped by stMain — there is
   no `section.main` in this DOM, so that selector matched nothing. */
div[data-testid="stMain"] div[data-testid="stVerticalBlock"] {{ gap:0.5rem; }}
div[data-testid="stSidebarUserContent"] div[data-testid="stVerticalBlock"] {{
  gap:0.35rem;
}}
div[data-testid="stSidebarUserContent"] {{ padding-top:1.1rem; }}
div[data-testid="stWidgetLabel"] p {{ font-size:12.5px; color:{t.muted}; }}
div[data-testid="stNumberInputField"] {{
  font-variant-numeric:tabular-nums; font-size:13.5px;
}}
div[data-testid="stDataFrameResizable"] {{ font-variant-numeric:tabular-nums; }}
div[data-testid="stCaptionContainer"] p {{ font-size:12px; line-height:1.55; }}
</style>"""
