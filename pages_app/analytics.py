import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core import info_metric, info_section, render_page_title


def _build_performance_chart_pct(ctx):
    portfolio_returns = ctx.get("portfolio_returns")
    benchmark_returns = ctx.get("benchmark_returns")

    if portfolio_returns is None or portfolio_returns.empty:
        return None

    fig = go.Figure()

    portfolio_cum = (1 + portfolio_returns).cumprod() - 1
    fig.add_scatter(
        x=portfolio_cum.index,
        y=portfolio_cum,
        mode="lines",
        name="Portfolio",
        hovertemplate="%{x|%Y-%m-%d}<br>Portfolio: %{y:.2%}<extra></extra>",
    )

    if benchmark_returns is not None and not benchmark_returns.empty:
        aligned = pd.concat(
            [portfolio_returns.rename("Portfolio"), benchmark_returns.rename("VOO")],
            axis=1,
        ).dropna()

        if not aligned.empty:
            voo_cum = (1 + aligned["VOO"]).cumprod() - 1
            fig.add_scatter(
                x=voo_cum.index,
                y=voo_cum,
                mode="lines",
                name="VOO",
                hovertemplate="%{x|%Y-%m-%d}<br>VOO: %{y:.2%}<extra></extra>",
            )

    fig.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=430,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Date",
        yaxis_title="Return",
        yaxis=dict(tickformat=".0%"),
        legend=dict(orientation="h", y=1.08, x=0.0),
    )
    return fig


def _build_rolling_metrics_chart(rolling_df):
    if rolling_df is None or rolling_df.empty:
        return None

    fig = go.Figure()

    if "Rolling Volatility" in rolling_df.columns:
        fig.add_scatter(
            x=rolling_df.index,
            y=rolling_df["Rolling Volatility"],
            mode="lines",
            name="Rolling Volatility",
            hovertemplate="%{x|%Y-%m-%d}<br>Rolling Volatility: %{y:.2%}<extra></extra>",
        )

    if "Rolling Sharpe" in rolling_df.columns:
        fig.add_scatter(
            x=rolling_df.index,
            y=rolling_df["Rolling Sharpe"],
            mode="lines",
            name="Rolling Sharpe",
            hovertemplate="%{x|%Y-%m-%d}<br>Rolling Sharpe: %{y:.2f}<extra></extra>",
        )

    if "Rolling Beta" in rolling_df.columns:
        fig.add_scatter(
            x=rolling_df.index,
            y=rolling_df["Rolling Beta"],
            mode="lines",
            name="Rolling Beta",
            hovertemplate="%{x|%Y-%m-%d}<br>Rolling Beta: %{y:.2f}<extra></extra>",
        )

    if "Rolling Drawdown" in rolling_df.columns:
        fig.add_scatter(
            x=rolling_df.index,
            y=rolling_df["Rolling Drawdown"],
            mode="lines",
            name="Rolling Drawdown",
            hovertemplate="%{x|%Y-%m-%d}<br>Rolling Drawdown: %{y:.2%}<extra></extra>",
        )

    fig.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=380,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Date",
        yaxis_title="Metric",
        legend=dict(orientation="h", y=1.08, x=0.0),
    )
    return fig


def render_analytics_page(ctx):
    render_page_title("Analytics")
    st.caption("BUILD CHECK ANALYTICS V1")

    c1, c2, c3, c4 = st.columns(4)
    info_metric(c1, "Alpha", f"{ctx['alpha']:.2%}", "Annualized alpha versus VOO.")
    info_metric(c2, "Beta", f"{ctx['beta']:.2f}", "Portfolio beta versus VOO.")
    info_metric(c3, "Tracking Error", f"{ctx['tracking_error']:.2%}", "Annualized tracking error versus VOO.")
    info_metric(c4, "Information Ratio", f"{ctx['information_ratio']:.2f}", "Information ratio versus VOO.")

    perf_fig = _build_performance_chart_pct(ctx)
    if perf_fig is not None:
        info_section(
            "Performance",
            "Portfolio and VOO cumulative performance shown in percentage terms.",
        )
        st.plotly_chart(perf_fig, use_container_width=True, key="analytics_performance_pct_chart_v2")

    rolling_fig = _build_rolling_metrics_chart(ctx.get("rolling_df"))
    if rolling_fig is not None:
        info_section(
            "Rolling Metrics",
            "Rolling volatility, Sharpe, beta, and drawdown over time.",
        )
        st.plotly_chart(rolling_fig, use_container_width=True, key="analytics_rolling_metrics_chart_v2")