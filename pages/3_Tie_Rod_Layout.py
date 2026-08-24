"""
pages/3_Tie_Rod_Layout.py

Streamlit page wrapper for the Tie-Rod Layout module.

Streamlit auto-discovers files in the pages/ directory and adds them to the
sidebar navigation. The numeric prefix controls display order.

The actual UI lives in apps/tierod/render.py — this file only sets the page
config and delegates to that render() function.
"""

import streamlit as st
from apps.tierod.render import render

st.set_page_config(
    page_title="Tie-Rod Layout",
    page_icon="🔩",
    layout="wide",
    initial_sidebar_state="expanded",
)

render()
