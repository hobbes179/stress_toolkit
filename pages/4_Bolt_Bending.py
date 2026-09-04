"""
pages/4_Bolt_Bending.py

Streamlit page wrapper for the Bolt Bending module.

Streamlit auto-discovers files in the pages/ directory and adds them to the
sidebar navigation. The numeric prefix controls display order.

The actual UI lives in apps/bolt_bending/app.py — this file only sets the page
config and delegates to that render() function.
"""

import streamlit as st
from apps.bolt_bending.app import render

st.set_page_config(
    page_title="Bolt Bending",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded",
)

render()
