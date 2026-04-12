import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

_PNL_KEYWORDS = ("return", "pnl", "p&l", "gain", "loss", "performance")
_DRIFT_KEYWORD = "drift"

_PNL_CELL_STYLE = JsCode("""
function(params) {
    if (params.value === null || params.value === undefined || params.value === '') return {};
    var num = parseFloat(String(params.value).replace('%','').replace(',',''));
    if (isNaN(num)) return {};
    if (num > 0) return { color: '#00ff88', fontWeight: '700' };
    if (num < 0) return { color: '#ff4444', fontWeight: '700' };
    return { color: '#888888' };
}
""")

_DRIFT_CELL_STYLE = JsCode("""
function(params) {
    if (params.value === null || params.value === undefined || params.value === '') return {};
    var num = Math.abs(parseFloat(String(params.value).replace('%','').replace(',','')));
    if (isNaN(num)) return {};
    if (num < 5) return { color: '#00ff88', fontWeight: '700' };
    if (num < 15) return { color: '#f5a623', fontWeight: '700' };
    return { color: '#ff4444', fontWeight: '700' };
}
""")


def show_aggrid(df, height=400, key=None):
    """Render a DataFrame using AgGrid with Bloomberg dark theme and conditional formatting.
    Falls back to st.dataframe if AgGrid fails."""
    try:
        import pandas as pd
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            st.dataframe(df, use_container_width=True, height=height)
            return

        gb = GridOptionsBuilder.from_dataframe(df)
        gb.configure_pagination(enabled=False)
        gb.configure_default_column(resizable=True, sortable=True, filter=True)

        for col in df.columns:
            col_lower = col.lower()
            if col_lower == _DRIFT_KEYWORD or _DRIFT_KEYWORD in col_lower:
                gb.configure_column(col, cellStyle=_DRIFT_CELL_STYLE)
            elif any(kw in col_lower for kw in _PNL_KEYWORDS):
                gb.configure_column(col, cellStyle=_PNL_CELL_STYLE)

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
        st.dataframe(df, use_container_width=True, height=height)
