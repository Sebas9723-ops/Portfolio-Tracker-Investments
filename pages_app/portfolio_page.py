import plotly.graph_objects as go
import streamlit as st

from app_core import info_metric, info_section, render_page_title


def _build_weights_vs_targets_chart(ctx):
    df = ctx["df"].copy()
    policy_map = ctx.get("policy_target_map", {})

    max_sharpe_map = {}
    if ctx.get("max_sharpe_row") is not None and ctx.get("usable"):
        usable = list(ctx["usable"])
        arr = ctx["max_sharpe_row"]["Weights"]
        max_sharpe_map = {t: 0.0 for t in df["Ticker"]}
        if len(arr) == len(usable):
            for ticker, weight in zip(usable, arr):
                max_sharpe_map[ticker] = float(weight)
    else:
        max_sharpe_map = dict(policy_map)

    fig = go.Figure()
    fig.add_bar(
        x=df["Ticker"],
        y=df["Weight %"],
        name="Current Weight %",
    )
    fig.add_bar(
        x=df["Ticker"],
        y=[float(policy_map.get(t, 0.0)) * 100.0 for t in df["Ticker"]],
        name="Policy Target %",
    )
    fig.add_bar(
        x=df["Ticker"],
        y=[float(max_sharpe_map.get(t, 0.0)) * 100.0 for t in df["Ticker"]],
        name="Max Sharpe %",
    )

    fig.update_layout(
        barmode="group",
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=390,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Ticker",
        yaxis_title="Weight %",
        legend=dict(orientation="h", y=1.08, x=0.0),
    )
    return fig


def _build_performance_vs_benchmark_chart(ctx):
    portfolio_returns = ctx.get("portfolio_returns")
    benchmark_returns = ctx.get("resolved_benchmark_returns")

    if portfolio_returns is None or portfolio_returns.empty:
        return None

    fig = go.Figure()
    portfolio_cum = (1 + portfolio_returns).cumprod() - 1
    fig.add_scatter(
        x=portfolio_cum.index,
        y=portfolio_cum,
        mode="lines",
        name=f"Portfolio ({portfolio_cum.iloc[-1]:.2%})",
        hovertemplate="%{x|%Y-%m-%d}<br>Portfolio: %{y:.2%}<extra></extra>",
    )

    if benchmark_returns is not None and not benchmark_returns.empty:
        aligned = (
            portfolio_returns.rename("Portfolio")
            .to_frame()
            .join(benchmark_returns.rename("VOO"), how="inner")
            .dropna()
        )

        if not aligned.empty:
            voo_cum = (1 + aligned["VOO"]).cumprod() - 1
            fig.add_scatter(
                x=voo_cum.index,
                y=voo_cum,
                mode="lines",
                name=f"VOO ({voo_cum.iloc[-1]:.2%})",
                hovertemplate="%{x|%Y-%m-%d}<br>VOO: %{y:.2%}<extra></extra>",
            )

    fig.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=420,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Date",
        yaxis_title="Return",
        yaxis=dict(tickformat=".0%"),
        legend=dict(orientation="h", y=1.08, x=0.0),
    )
    return fig


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
        st.plotly_chart(ctx["fig_pie"], use_container_width=True, key="portfolio_allocation_chart_fixed_v2")

    with right:
        info_section(
            "Weights vs Targets",
            "Current weight, policy target, and max Sharpe allocation shown side by side.",
        )
        st.plotly_chart(
            _build_weights_vs_targets_chart(ctx),
            use_container_width=True,
            key="portfolio_weights_targets_chart_fixed_v2",
        )

    perf_fig = _build_performance_vs_benchmark_chart(ctx)
    if perf_fig is not None:
        info_section(
            "Performance vs Benchmark",
            "Portfolio cumulative return versus VOO in percentage terms. Legend includes latest cumulative values.",
        )
        st.plotly_chart(
            perf_fig,
            use_container_width=True,
            key="portfolio_performance_vs_benchmark_fixed_v2",
        )

    info_section("Cash Balances", "Cash balances by currency converted to the base currency.")
    st.dataframe(ctx["cash_display_df"], use_container_width=True, height=240)

    info_section("Portfolio Snapshot", "Current holdings, values, and performance metrics.")
    st.dataframe(ctx["display_df"], use_container_width=True, height=360)