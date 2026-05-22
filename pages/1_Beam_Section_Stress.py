"""
pages/1_Beam_Section_Stress.py

Streamlit page wrapper for the Beam Section module.

Streamlit auto-discovers files in the pages/ directory and adds them to
the sidebar navigation. The numeric prefix controls display order.

The actual UI lives in apps/beam_section/app.py — this file only sets the
page config and delegates to that render() function.
"""

import streamlit as st
from apps.beam_section.app import render

st.set_page_config(
    page_title="Beam Section Stress",
    page_icon="📐",
    layout="wide",
    initial_sidebar_state="expanded",
)

render()
