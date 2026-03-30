import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core import info_section, render_page_title


def _fmt_pct(v, decimals=1) -> str:
    try:
        return f"{float(v) * 100:.{decimals}f}%"
    except Exception:
        return ""


def _render_monthly_calendar(ctx):
    cal = ctx.get("monthly_calendar_df")
    if cal is None or cal.empty:
        st.info("Not enough return history to build the performance calendar (minimum ~20 trading days required).")
        return

    info_section(
        "Monthly Returns Calendar",
        "Each cell shows the portfolio return for that month. "
        "Green = positive, red = negative. YTD column is the compounded annual return.",
    )

    month_cols = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "YTD"]

    # Build display matrix
    rows_text = []
    rows_color = []
    y_labels = []

    for _, row in cal.iterrows():
        yr = int(row["Year"])
        y_labels.append(str(yr))
        text_row = []
        color_row = []
        for col in month_cols:
            val = row.get(col)
            if val is None or (isinstance(val, float) and np.isnan(val)):
                text_row.append("")
                color_row.append(0.0)
            else:
                text_row.append(_fmt_pct(val))
                color_row.append(float(val))
        rows_text.append(text_row)
        rows_color.append(color_row)

    z = np.array(rows_color)
    abs_max = max(abs(z[z != 0.0]).max() if (z != 0.0).any() else 0.01, 0.01)

    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=month_cols,
            y=y_labels,
            text=[[t for t in r] for r in rows_text],
            texttemplate="%{text}",
            colorscale=[
                [0.0, "#8b0000"],
                [0.5, "#1a1f2e"],
                [1.0, "#006400"],
            ],
            zmid=0,
            zmin=-abs_max,
            zmax=abs_max,
            showscale=False,
            hoverongaps=False,
        )
    )
    fig.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6", size=13),
        height=max(180, 60 * len(y_labels) + 80),
        margin=dict(t=20, b=20, l=60, r=20),
        xaxis=dict(side="top"),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Summary stats
    portfolio_returns = ctx.get("portfolio_returns", pd.Series(dtype=float))
    if not portfolio_returns.empty:
        monthly_vals = cal[["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]].values.flatten()
        monthly_vals = monthly_vals[~np.isnan(monthly_vals.astype(float))]
        if len(monthly_vals) > 0:
            pos = (monthly_vals > 0).sum()
            total_m = len(monthly_vals)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Positive Months", f"{pos} / {total_m}", f"{pos / total_m * 100:.0f}%")
            c2.metric("Best Month", _fmt_pct(monthly_vals.max()))
            c3.metric("Worst Month", _fmt_pct(monthly_vals.min()))
            c4.metric("Avg Monthly Return", _fmt_pct(monthly_vals.mean()))


def _render_drawdown_analysis(ctx):
    portfolio_returns = ctx.get("portfolio_returns", pd.Series(dtype=float))
    episodes = ctx.get("drawdown_episodes_df")

    info_section(
        "Drawdown Analysis",
        "Underwater chart shows portfolio value relative to its rolling peak. "
        "The table lists every distinct drawdown episode.",
    )

    # Underwater chart
    if not portfolio_returns.empty:
        cum = (1 + portfolio_returns).cumprod()
        rolling_max = cum.cummax()
        underwater = cum / rolling_max - 1

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=underwater.index,
                y=underwater.values * 100,
                fill="tozeroy",
                fillcolor="rgba(220,50,50,0.25)",
                line=dict(color="#dc3232", width=1),
                name="Drawdown %",
            )
        )
        fig.update_layout(
            xaxis_title="Date",
            yaxis_title="Drawdown (%)",
            paper_bgcolor="#0b0f14",
            plot_bgcolor="#0b0f14",
            font=dict(color="#e6e6e6"),
            height=300,
            margin=dict(t=20, b=20, l=60, r=20),
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)

    # Summary metrics
    max_dd = float(ctx.get("max_drawdown", 0.0))
    c1, c2, c3 = st.columns(3)
    c1.metric("Max Drawdown", _fmt_pct(max_dd))

    if episodes is not None and not episodes.empty:
        avg_dur = episodes["Duration (days)"].mean()
        c2.metric("Avg Drawdown Duration", f"{avg_dur:.0f} days")
        recovered = episodes[episodes["Recovery Date"].notna()]
        if not recovered.empty:
            avg_rec = recovered["Recovery (days)"].mean()
            c3.metric("Avg Recovery Time", f"{avg_rec:.0f} days")

    # Episode table
    if episodes is not None and not episodes.empty:
        st.markdown("#### All Drawdown Episodes")
        display = episodes.copy()

        display["Max Drawdown %"] = display["Max Drawdown %"].apply(lambda v: f"{v:.2f}%")
        display["Duration (days)"] = display["Duration (days)"].apply(
            lambda v: f"{int(v)}" if pd.notna(v) else "—"
        )
        display["Recovery (days)"] = display["Recovery (days)"].apply(
            lambda v: f"{int(v)}" if pd.notna(v) else "Ongoing"
        )
        display["Recovery Date"] = display["Recovery Date"].apply(
            lambda v: str(v) if pd.notna(v) else "Ongoing"
        )

        st.dataframe(display, use_container_width=True, hide_index=True)
    else:
        st.info("No distinct drawdown episodes detected in the available history.")


def render_performance_calendar_page(ctx):
    render_page_title("Performance Calendar & Drawdowns")
    tab1, tab2 = st.tabs(["Monthly Returns Calendar", "Drawdown Analysis"])
    with tab1:
        _render_monthly_calendar(ctx)
    with tab2:
        _render_drawdown_analysis(ctx)
