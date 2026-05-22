"""
pages/2_Material_Library.py

Streamlit page wrapper for the Material Library module.

Streamlit auto-discovers files in the pages/ directory and adds them to
the sidebar navigation. The numeric prefix controls display order.

The actual UI lives in apps/material_library/app.py.
"""

import streamlit as st
from apps.material_library.app import render

st.set_page_config(
    page_title="Material Library",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

render()
