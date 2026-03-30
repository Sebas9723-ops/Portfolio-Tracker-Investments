import plotly.graph_objects as go
import streamlit as st

from app_core import info_metric, info_section, render_page_title, compute_twr


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


def _fmt(v, fmt=".2%", fallback="—") -> str:
    try:
        return format(float(v), fmt)
    except Exception:
        return fallback


def _render_extended_ratios(ctx):
    er = ctx.get("extended_ratios", {})
    if not er:
        return
    info_section(
        "Extended Ratios",
        "Sortino penalizes only downside volatility. Calmar = return / max drawdown. "
        "Upside/Downside Capture vs VOO. Omega = gain potential / loss potential.",
    )
    c1, c2, c3, c4, c5 = st.columns(5)
    info_metric(c1, "Sortino", _fmt(er.get("sortino"), ".2f"), "Return per unit of downside risk.")
    info_metric(c2, "Calmar", _fmt(er.get("calmar"), ".2f"), "Annualized return / |max drawdown|.")
    info_metric(c3, "Upside Capture", _fmt(er.get("upside_capture"), ".1f") + "%" if er.get("upside_capture") is not None else "—", "% of benchmark upside captured.")
    info_metric(c4, "Downside Capture", _fmt(er.get("downside_capture"), ".1f") + "%" if er.get("downside_capture") is not None else "—", "% of benchmark downside suffered.")
    info_metric(c5, "Omega", _fmt(er.get("omega"), ".2f"), "Gain potential over loss potential above risk-free rate.")


def _render_returns_comparison(ctx):
    mwr = ctx.get("mwr_result", {})
    twr_result: dict = {}

    # TWR — computed lazily from snapshots
    try:
        from pages_app.portfolio_history import load_portfolio_snapshots, filter_snapshots_for_context
        snaps = load_portfolio_snapshots()
        if not snaps.empty:
            filtered = filter_snapshots_for_context(snaps, ctx.get("mode"), ctx.get("base_currency"))
            twr_result = compute_twr(filtered, ctx.get("transactions_df"))
    except Exception:
        pass

    twr_val = twr_result.get("twr")
    mwr_val = mwr.get("mwr")
    n_periods = twr_result.get("n_periods", 0)
    n_tx = mwr.get("n_transactions", 0)
    start = twr_result.get("start_date", "—")
    end = twr_result.get("end_date", "—")

    info_section(
        "Return Measures",
        "TWR (Time-Weighted) is the institutional standard — eliminates the effect of cash flow timing. "
        "MWR (Money-Weighted / IRR) reflects your actual investor experience including when you deployed capital.",
    )
    c1, c2, c3, c4 = st.columns(4)
    info_metric(c1, "TWR", _fmt(twr_val) if twr_val is not None else "—", f"Chain-linked over {n_periods} snapshots ({start} → {end}).")
    info_metric(c2, "MWR (IRR)", _fmt(mwr_val) if mwr_val is not None else "—", f"Annualized IRR from {n_tx} transactions.")
    info_metric(c3, "Historical Return", _fmt(ctx.get("total_return")), "Cumulative return from price history.")
    excess = (twr_val or 0.0) - (mwr_val or 0.0) if twr_val is not None and mwr_val is not None else None
    info_metric(c4, "TWR − MWR", _fmt(excess) if excess is not None else "—", "Positive = timing helped; Negative = timing hurt.")


def _render_brinson(ctx):
    brinson_df = ctx.get("brinson_df")
    if brinson_df is None or brinson_df.empty:
        return

    info_section(
        "Brinson-Hood-Beebower Attribution",
        "Decomposes active return vs VOO benchmark per asset. "
        "Allocation = effect of over/underweighting. Selection = effect of asset return vs benchmark. "
        "Interaction = combined weight × return divergence.",
    )
    st.dataframe(brinson_df, use_container_width=True, height=300)

    fig = go.Figure()
    fig.add_bar(x=brinson_df["Ticker"], y=brinson_df["Allocation Effect"], name="Allocation")
    fig.add_bar(x=brinson_df["Ticker"], y=brinson_df["Selection Effect"], name="Selection")
    fig.add_bar(x=brinson_df["Ticker"], y=brinson_df["Interaction Effect"], name="Interaction")
    fig.update_layout(
        barmode="stack",
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=360,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Ticker",
        yaxis_title="Attribution (%)",
        legend=dict(orientation="h", y=1.08, x=0.0),
    )
    st.plotly_chart(fig, use_container_width=True, key="analytics_brinson_chart")


def _render_ff3(ctx):
    ff3 = ctx.get("ff3_result")
    if not ff3:
        return

    info_section(
        "Fama-French 3-Factor Exposure",
        "OLS regression of portfolio excess returns on Market (Mkt-RF), Size (SMB), and Value (HML) factors. "
        "Factors are proxied by IVV / IWM / IVE / IVW ETFs. t-stats shown as tooltip.",
    )
    c1, c2, c3, c4, c5 = st.columns(5)
    alpha_ann = float(ff3.get("alpha", 0))
    info_metric(c1, "FF3 Alpha (ann.)", _fmt(alpha_ann), f"t = {ff3.get('alpha_tstat', 0):.2f}")
    info_metric(c2, "Market β", _fmt(ff3.get("mkt_beta"), ".2f"), f"t = {ff3.get('mkt_tstat', 0):.2f}")
    info_metric(c3, "SMB β (Size)", _fmt(ff3.get("smb_beta"), ".2f"), f"t = {ff3.get('smb_tstat', 0):.2f}  (+) = small-cap tilt")
    info_metric(c4, "HML β (Value)", _fmt(ff3.get("hml_beta"), ".2f"), f"t = {ff3.get('hml_tstat', 0):.2f}  (+) = value tilt")
    info_metric(c5, "R²", _fmt(ff3.get("r_squared"), ".2%"), f"{ff3.get('n_obs', 0)} observations")
    st.caption(f"Factor proxy source: {ff3.get('source', 'ETF Proxy')}")


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

    _render_extended_ratios(ctx)
    _render_returns_comparison(ctx)
    _render_brinson(ctx)
    _render_ff3(ctx)

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