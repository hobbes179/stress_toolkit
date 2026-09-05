"""
apps/beam_line/styles.py

Page CSS for the Beam Diagrams module.

Composition follows the bolt module: a dense engineering-report page rather
than the toolkit's stock card furniture, because this module also has one
screen of content that has to be readable all at once. Class names are
prefixed `bl-` so they cannot collide with the toolkit's `tk-` components or
the bolt module's `bb-`. Injected once per page, after `inject_css()`.

Every colour comes from `ui.theme`. There is a test asserting no hex literal
appears in this file.
"""

from __future__ import annotations

from ui.theme import BEAM_PALETTE, THEME

# The stack editor lives in the sidebar and needs room for two number inputs
# side by side. Streamlit drops the stepper buttons from `st.number_input`
# when a column gets narrow -- the bolt module measured that threshold in a
# browser and landed on this width. Same widgets, same constraint, same width.
SIDEBAR_WIDTH = "30rem"


def beam_css() -> str:
    """The page stylesheet, as a `<style>` block ready for `st.markdown`."""
    t = THEME
    c = BEAM_PALETTE

    return f"""<style>
section[data-testid="stSidebar"] {{ width:{SIDEBAR_WIDTH} !important; }}
section[data-testid="stSidebar"] > div {{ width:{SIDEBAR_WIDTH} !important; }}

/* ---- page header ------------------------------------------------- */
.bl-header {{
  display:flex; align-items:baseline; gap:16px; flex-wrap:wrap;
  padding-bottom:12px; margin:0 0 18px;
  border-bottom:2px solid {t.text};
}}
.bl-header h1 {{
  font-size:23px; font-weight:600; letter-spacing:-.01em;
  margin:0; padding:0; color:{t.text};
}}
.bl-header p {{
  margin:0; color:{t.muted}; font-size:14px; max-width:58ch; line-height:1.5;
}}

/* ---- section label ------------------------------------------------ */
.bl-h2 {{
  font-size:13px; font-weight:600; color:{t.muted};
  margin:0 0 10px; letter-spacing:.01em;
}}

/* ---- card ---------------------------------------------------------- */
.bl-card {{
  background:{t.bg3}; border:1px solid {t.border}; border-radius:3px;
  padding:16px 16px 18px; margin-bottom:16px;
}}
.bl-card > .bl-h2:first-child {{ margin-top:0; }}
.bl-note {{
  font-size:12px; color:{t.muted}; line-height:1.6; margin:10px 0 0;
  max-width:82ch;
}}

/* ---- figure -------------------------------------------------------- */
.bl-fig svg {{ display:block; width:100%; height:auto; }}

/* ---- peak / reaction results grid ---------------------------------- */
.bl-res {{
  display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr));
  margin:0; padding:0;
}}
.bl-res > div {{
  border-top:1px solid {t.rule_soft}; border-left:1px solid {t.rule_soft};
  margin:-1px 0 0 -1px; padding:10px 12px;
}}
.bl-res dt {{ font-size:12px; color:{t.muted}; margin:0 0 3px; }}
.bl-res dd {{
  margin:0; font-size:18px; font-weight:600; color:{t.text};
  font-variant-numeric:tabular-nums; letter-spacing:-.01em;
}}
.bl-res dd small {{
  font-size:12.5px; color:{t.muted}; font-weight:400; letter-spacing:0;
}}
.bl-res dd.bl-shear   {{ color:{c['shear']}; }}
.bl-res dd.bl-moment  {{ color:{c['moment']}; }}
.bl-res dd.bl-deflect {{ color:{c['deflect']}; }}

/* ---- reaction table ------------------------------------------------ */
.bl-tbl {{
  width:100%; border-collapse:collapse; font-size:13px;
  font-variant-numeric:tabular-nums;
}}
.bl-tbl th {{
  text-align:right; font-weight:600; color:{t.muted}; font-size:11.5px;
  padding:0 10px 6px 0; border-bottom:1px solid {t.border};
  white-space:nowrap;
}}
.bl-tbl th:first-child, .bl-tbl td:first-child {{ text-align:left; }}
.bl-tbl td {{
  text-align:right; padding:6px 10px 6px 0;
  border-bottom:1px solid {t.rule_soft}; color:{t.text};
}}
.bl-tbl td.bl-dim {{ color:{t.muted}; }}
.bl-tbl tfoot td {{
  border-bottom:0; border-top:1px solid {t.border};
  font-weight:600; color:{t.muted};
}}

/* ---- banners ------------------------------------------------------- */
.bl-banner {{
  border-left:3px solid {t.fail_fg}; background:{t.fail_bg};
  border-radius:3px; padding:12px 14px; margin:0 0 16px;
  font-size:13.5px; line-height:1.6; color:{t.text};
}}
.bl-banner b {{ font-weight:600; }}
/* Inside the figure card, under the SVG. Sits below the plots so that
   appearing or disappearing cannot move them. */
.bl-excl {{ margin:14px 0 0; }}
.bl-banner.bl-warn {{
  border-left-color:{t.warn_fg}; background:{t.amber_bg}; color:{t.text2};
}}

/* ---- model strip: what assumption is in force ---------------------- */
.bl-model {{
  border-left:3px solid {t.border}; background:{t.bg2};
  border-radius:3px; padding:10px 13px; margin:0 0 14px;
  font-size:12.5px; line-height:1.6; color:{t.muted};
}}
.bl-model b {{ font-weight:600; color:{t.text}; }}
.bl-model .bl-tag {{
  font-size:11px; font-weight:600; letter-spacing:.04em;
  text-transform:none; color:{t.muted}; margin-right:8px;
}}
.bl-model.bl-inherited {{ border-left-color:{t.accent}; }}
.bl-model.bl-inherited .bl-tag {{ color:{t.accent}; }}

/* ---- method section ------------------------------------------------ */
.bl-method {{ margin-top:8px; }}
.bl-method .bl-lead {{ margin:0 0 4px; color:{t.muted}; max-width:80ch; }}
.bl-mgrid {{
  display:grid; grid-template-columns:1fr 1fr; gap:0 34px; margin-top:6px;
}}
@media (max-width:1100px) {{
  .bl-mgrid {{ grid-template-columns:1fr; gap:0; }}
}}
.bl-method h3 {{
  font-size:12.5px; font-weight:600; color:{t.text};
  margin:18px 0 7px; letter-spacing:.01em;
}}
.bl-method p {{
  margin:0 0 9px; font-size:13px; line-height:1.65; color:{t.text2};
  max-width:74ch;
}}
.bl-method i {{ font-style:italic; }}
.bl-method b {{ font-weight:600; color:{t.text}; }}
.bl-method ul {{ margin:0 0 9px; padding-left:18px; }}
.bl-method li {{
  font-size:13px; line-height:1.6; color:{t.text2}; margin-bottom:4px;
}}
.bl-eq {{
  background:{t.bg2}; border-radius:3px; padding:8px 12px;
  margin:0 0 10px; font-size:13px; color:{t.text};
  border-left:2px solid {t.border}; overflow-x:auto;
}}

/* ---- sidebar row furniture ----------------------------------------- */
.bl-row-rule {{
  border-top:1px solid {t.rule_soft}; margin:2px 0 6px;
}}
.bl-row-tag {{
  font-size:11px; font-weight:600; color:{t.muted}; letter-spacing:.02em;
  margin:0 0 -6px;
}}
</style>"""
