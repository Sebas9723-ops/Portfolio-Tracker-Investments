import io

import pandas as pd
import streamlit as st

# ── Empty state ───────────────────────────────────────────────────────────────
_EMPTY_HTML = (
    '<div style="display:flex;flex-direction:column;align-items:center;'
    'justify-content:center;padding:2.5rem 1rem;color:#6b7f96;'
    "font-family:'IBM Plex Mono',monospace;border:1px dashed #1e2535;"
    'border-radius:6px;background:#0d0d0d;gap:0.4rem;">'
    '<span style="font-size:1.6rem;">📊</span>'
    '<span style="font-size:0.82rem;">No data available</span>'
    "</div>"
)

# ── Column auto-formatting rules (keywords → printf format) ──────────────────
_FMT_RULES: list[tuple[tuple[str, ...], str]] = [
    # percentages
    (
        ("weight %", "% ", " %", "pct", "alloc", "deviation", "gap %",
         "day δ%", "month δ%", "recommended weight", "return %",
         "unrealized pnl %", "target %"),
        "%.2f %%",
    ),
    # money / price
    (
        ("value", "pnl", "cost", "capital", "invested", "cash", "price",
         "gross", "trade to", "1m ago", "prev close", "day δ", "month δ",
         "30d", "snapshot", "contribution"),
        "%.2f",
    ),
    # shares / quantity
    (("shares", "qty", "quantity"), "%.4f"),
    # ratios / scores
    (("sharpe", "sortino", "ratio", "beta", "alpha", "score", "var", "cvar",
      "tracking"), "%.3f"),
]


def _build_column_config(df: pd.DataFrame) -> dict:
    cfg: dict = {}
    for col in df.columns:
        cl = col.lower()
        # Skip non-numeric columns
        if not pd.to_numeric(df[col], errors="coerce").notna().any():
            continue
        for keywords, fmt in _FMT_RULES:
            if any(k in cl for k in keywords):
                cfg[col] = st.column_config.NumberColumn(col, format=fmt)
                break
    return cfg


def show_aggrid(df, height: int = 400, key: str | None = None, show_export: bool = True):
    """
    Drop-in replacement for the original show_aggrid.

    Renders a DataFrame with:
    - Auto-detected column formatting (%, currency, shares, ratios)
    - Empty-state placeholder when df is None / empty
    - Optional CSV + Excel download buttons (requires a unique `key`)
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        st.markdown(_EMPTY_HTML, unsafe_allow_html=True)
        return

    col_cfg = _build_column_config(df)

    st.dataframe(
        df,
        use_container_width=True,
        height=height,
        column_config=col_cfg if col_cfg else None,
        hide_index=True,
    )

    # Export buttons — only when a unique key is provided to avoid key conflicts
    if not show_export or not key:
        return

    _key = key.replace(" ", "_")
    c_csv, c_xlsx, _ = st.columns([1, 1, 8])

    csv_bytes = df.to_csv(index=False).encode("utf-8")
    c_csv.download_button(
        "↓ CSV",
        data=csv_bytes,
        file_name=f"{_key}.csv",
        mime="text/csv",
        key=f"_exp_csv_{_key}",
        use_container_width=True,
    )

    try:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Data")
        c_xlsx.download_button(
            "↓ Excel",
            data=buf.getvalue(),
            file_name=f"{_key}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"_exp_xlsx_{_key}",
            use_container_width=True,
        )
    except Exception:
        pass
