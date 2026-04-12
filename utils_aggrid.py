import streamlit as st

_PNL_KEYWORDS = ("return", "pnl", "p&l", "gain", "loss", "performance")
_DRIFT_KEYWORD = "drift"

_PNL_JS = """
function(params) {
    if (params.value === null || params.value === undefined || params.value === '') return {};
    var num = parseFloat(String(params.value).replace('%','').replace(',',''));
    if (isNaN(num)) return {};
    if (num > 0) return { color: '#00ff88', fontWeight: '700' };
    if (num < 0) return { color: '#ff4444', fontWeight: '700' };
    return { color: '#888888' };
}
"""

_DRIFT_JS = """
function(params) {
    if (params.value === null || params.value === undefined || params.value === '') return {};
    var num = Math.abs(parseFloat(String(params.value).replace('%','').replace(',','')));
    if (isNaN(num)) return {};
    if (num < 5) return { color: '#00ff88', fontWeight: '700' };
    if (num < 15) return { color: '#f5a623', fontWeight: '700' };
    return { color: '#ff4444', fontWeight: '700' };
}
"""


def show_aggrid(df, height=400, key=None):
    """Render a DataFrame using AgGrid dark theme with conditional formatting.
    Falls back gracefully to st.dataframe if AgGrid is unavailable."""
    import pandas as pd
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        st.dataframe(df if df is not None else pd.DataFrame(),
                     use_container_width=True, height=height)
        return

    try:
        # Lazy import so a missing/broken package doesn't crash the page
        from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

        pnl_style  = JsCode(_PNL_JS)
        drift_style = JsCode(_DRIFT_JS)

        gb = GridOptionsBuilder.from_dataframe(df)
        gb.configure_pagination(enabled=False)
        gb.configure_default_column(resizable=True, sortable=True, filter=True)

        for col in df.columns:
            col_lower = col.lower()
            if col_lower == _DRIFT_KEYWORD or _DRIFT_KEYWORD in col_lower:
                gb.configure_column(col, cellStyle=drift_style)
            elif any(kw in col_lower for kw in _PNL_KEYWORDS):
                gb.configure_column(col, cellStyle=pnl_style)

        grid_options = gb.build()
        grid_options["domLayout"] = "normal"

        AgGrid(
            df,
            gridOptions=grid_options,
            theme="dark",
            height=height,
            allow_unsafe_jscode=True,
            key=key,
        )
    except Exception:
        # Guaranteed fallback — always shows data even if AgGrid fails
        st.dataframe(df, use_container_width=True, height=height)
