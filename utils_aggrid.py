import streamlit as st
import pandas as pd


def show_aggrid(df, height=400, key=None):
    """Renders a DataFrame using Streamlit's native dataframe component."""
    if df is None or not isinstance(df, pd.DataFrame):
        return
    st.dataframe(df, use_container_width=True, height=height)
