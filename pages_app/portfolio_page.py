import numpy as np
import plotly.graph_objects as go
import streamlit as st

from app_core import (
    info_metric,
    info_section,
    render_page_title,
)


def _normalize_weight_map(weight_map, tickers):
    clean = {t: max(float(weight_map.get(t, 0.0)), 0.0) for t in tickers}
    total = float(sum(clean.values()))
    if total <= 0:
        equal = 1.0 / len(tickers) if tickers else 0.0
        return {t: equal for t in tickers}
    return {t: v / total for t, v in clean.items()}


def _get_max_sharpe_target_map(ctx, df):
    tickers = df["Ticker"].tolist()

    if ctx.get("max_sharpe_row") is None or not ctx.get("usable"):
        raw = df.set_index("Ticker")["Target Weight"].to_dict()
        return _normalize_weight_map(raw, tickers), "Policy Target"

    usable = list(ctx["usable"])
    arr = np.array(ctx["max_sharpe_row"]["Weights"], dtype=float)

    raw = {ticker: 0.0 for ticker in tickers}
    if len(arr) == len(usable):
        for ticker, weight in zip(usable, arr):
            raw[ticker] = float(weight)

    return _normalize_weight_map(raw, tickers), "Max Sharpe Frontier"


def _build_weights_vs_target_chart(ctx):
    df = ctx["df"].copy()
    target_map, source_label = _get_max_sharpe_target_map(ctx, df)

    fig = go.Figure()
    fig.add_bar(
        x=df["Ticker"],
        y=df["Weight %"],
        name="Actual %",
    )
    fig.add_bar(
        x=df["Ticker"],
        y=[float(target_map.get(t, 0.0)) * 100.0 for t in df["Ticker"]],
        name="Max Sharpe %",
    )

    fig.update_layout(
        barmode="group",
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=360,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Ticker",
        yaxis_title="Weight %",
        legend=dict(orientation="h", y=1.08, x=0.0),
    )
    return fig, source_label


def render_portfolio_page(ctx):
    render_page_title("Portfolio")

    c1, c2, c3, c4 = st.columns(4)
    info_metric(c1, "Total Portfolio", f"{ctx['base_currency']} {ctx['total_portfolio_value']:,.2f}", "Holdings plus cash.")
    info_metric(c2, "Invested Capital", f"{ctx['base_currency']} {ctx['invested_capital']:,.2f}", "Estimated invested capital.")
    info_metric(c3, "Unrealized PnL", f"{ctx['base_currency']} {ctx['unrealized_pnl']:,.2f}", "Open profit and loss.")
    info_metric(c4, "Realized PnL", f"{ctx['base_currency']} {ctx['realized_pnl']:,.2f}", "Closed profit and loss.")

    left, right = st.columns(2)

    with left:
        info_section("Allocation", "Current portfolio allocation by market value.")
        st.plotly_chart(ctx["fig_pie"], use_container_width=True, key="portfolio_allocation_chart_v2")

    with right:
        fig_weights, source_label = _build_weights_vs_target_chart(ctx)
        info_section(
            "Weights vs Target",
            f"Actual weights compared against target source: {source_label}.",
        )
        st.plotly_chart(fig_weights, use_container_width=True, key="portfolio_weights_vs_target_chart_v2")

    info_section("Cash Balances", "Cash balances by currency converted to the base currency.")
    st.dataframe(ctx["cash_display_df"], use_container_width=True, height=240)

    info_section("Portfolio Snapshot", "Current holdings, values, and performance metrics.")
    st.dataframe(ctx["display_df"], use_container_width=True, height=360)