import plotly.graph_objects as go
import streamlit as st

from app_core import info_metric, info_section, render_page_title


def _compute_relative_metrics(ctx):
    portfolio_returns = ctx.get("portfolio_returns")
    benchmark_returns = ctx.get("resolved_benchmark_returns")

    if portfolio_returns is None or portfolio_returns.empty or benchmark_returns is None or benchmark_returns.empty:
        return None

    aligned = (
        portfolio_returns.rename("Portfolio")
        .to_frame()
        .join(benchmark_returns.rename("VOO"), how="inner")
        .dropna()
    )

    if aligned.empty:
        return None

    bench_var = aligned["VOO"].var()
    beta = None
    alpha = None
    tracking_error = None
    information_ratio = None

    if bench_var > 0:
        beta = float(aligned.cov().loc["Portfolio", "VOO"] / bench_var)

    p_mean = float(aligned["Portfolio"].mean() * 252)
    b_mean = float(aligned["VOO"].mean() * 252)

    if beta is not None:
        alpha = float(p_mean - beta * b_mean)

    excess = aligned["Portfolio"] - aligned["VOO"]
    tracking_error = float(excess.std() * 252**0.5) if not excess.empty else None

    if tracking_error and tracking_error > 0:
        information_ratio = float((excess.mean() * 252) / tracking_error)

    return {
        "alpha": alpha,
        "beta": beta,
        "tracking_error": tracking_error,
        "information_ratio": information_ratio,
        "aligned": aligned,
    }


def _build_performance_chart_pct(ctx):
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

    rel = _compute_relative_metrics(ctx)

    alpha_txt = "—" if rel is None or rel["alpha"] is None else f"{rel['alpha']:.2%}"
    beta_txt = "—" if rel is None or rel["beta"] is None else f"{rel['beta']:.2f}"
    te_txt = "—" if rel is None or rel["tracking_error"] is None else f"{rel['tracking_error']:.2%}"
    ir_txt = "—" if rel is None or rel["information_ratio"] is None else f"{rel['information_ratio']:.2f}"

    c1, c2, c3, c4 = st.columns(4)
    info_metric(c1, "Alpha", alpha_txt, "Annualized alpha versus VOO.")
    info_metric(c2, "Beta", beta_txt, "Portfolio beta versus VOO.")
    info_metric(c3, "Tracking Error", te_txt, "Annualized tracking error versus VOO.")
    info_metric(c4, "Information Ratio", ir_txt, "Information ratio versus VOO.")

    perf_fig = _build_performance_chart_pct(ctx)
    if perf_fig is not None:
        info_section(
            "Performance",
            "Portfolio and VOO cumulative performance shown in percentage terms. Legend includes latest cumulative values.",
        )
        st.plotly_chart(
            perf_fig,
            use_container_width=True,
            key="analytics_performance_pct_chart_fixed_v2",
        )

    rolling_fig = _build_rolling_metrics_chart(ctx.get("rolling_df"))
    if rolling_fig is not None:
        info_section(
            "Rolling Metrics",
            "Rolling volatility, Sharpe, beta, and drawdown over time.",
        )
        st.plotly_chart(
            rolling_fig,
            use_container_width=True,
            key="analytics_rolling_metrics_chart_fixed_v2",
        )