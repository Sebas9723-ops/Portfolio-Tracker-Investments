import datetime
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core import (
    build_recommended_shares_table,
    compute_black_litterman,
    compute_risk_parity_weights,
    get_default_constraints,
    info_metric,
    info_section,
    optimize_max_sharpe,
    optimize_min_vol,
    render_page_title,
    simulate_constrained_efficient_frontier,
    weights_table,
)


@st.cache_data(ttl=900, show_spinner=False)
def _cached_frontier(asset_returns: pd.DataFrame, max_single: float, min_bonds: float, min_gold: float, rfr: float, n: int):
    constraints = {"max_single_asset": max_single, "min_bonds": min_bonds, "min_gold": min_gold}
    frontier = simulate_constrained_efficient_frontier(asset_returns, asset_returns.columns.tolist(), constraints, rfr, n)
    computed_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return frontier, computed_at


@st.cache_data(ttl=900, show_spinner=False)
def _cached_risk_parity(asset_returns: pd.DataFrame):
    return compute_risk_parity_weights(asset_returns)


def _render_risk_parity(ctx, rp):
    if rp is None:
        return

    info_section(
        "Risk Parity (Equal Risk Contribution)",
        "ERC portfolio: each asset contributes the same percentage of total portfolio volatility. "
        "No return forecasts required — purely volatility-based.",
    )

    tickers = rp["tickers"]
    weights = rp["weights"]
    rc = rp["risk_contributions"]
    port_vol = rp["portfolio_vol"]

    df_ctx = ctx.get("df", pd.DataFrame())
    current_weights = {}
    if not df_ctx.empty and "Ticker" in df_ctx.columns and "Weight" in df_ctx.columns:
        tot = df_ctx["Weight"].sum()
        if tot > 0:
            for _, row in df_ctx.iterrows():
                current_weights[str(row["Ticker"])] = float(row["Weight"]) / tot

    # Side-by-side weight comparison
    fig = go.Figure()
    erc_w = [weights.get(t, 0) for t in tickers]
    cur_w = [current_weights.get(t, 0) for t in tickers]
    fig.add_bar(x=tickers, y=cur_w, name="Current", marker_color="#4db8ff",
                hovertemplate="%{x}<br>Current: %{y:.1%}<extra></extra>")
    fig.add_bar(x=tickers, y=erc_w, name="ERC Target", marker_color="#f3a712",
                hovertemplate="%{x}<br>ERC: %{y:.1%}<extra></extra>")
    fig.update_layout(
        barmode="group",
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=320,
        margin=dict(t=20, b=20, l=20, r=20),
        yaxis=dict(tickformat=".0%"),
        legend=dict(orientation="h", y=1.08),
    )
    st.plotly_chart(fig, use_container_width=True, key="rp_weights_chart")

    # Summary table
    rows = [
        {
            "Ticker": t,
            "Current Weight": f"{current_weights.get(t, 0):.2%}",
            "ERC Weight": f"{weights.get(t, 0):.2%}",
            "Δ": f"{weights.get(t, 0) - current_weights.get(t, 0):+.2%}",
            "Risk Contribution": f"{rc.get(t, 0):.2%}",
        }
        for t in tickers
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(
        f"ERC Portfolio Volatility: **{port_vol:.2%}** annualized. "
        "Each asset contributes ~equal risk share."
    )

    # Recommended shares
    erc_weights_arr = np.array([weights.get(t, 0) for t in tickers])
    erc_rec = build_recommended_shares_table(erc_weights_arr, tickers, df_ctx)
    if erc_rec is not None and not erc_rec.empty:
        with st.expander("ERC Recommended Shares", expanded=False):
            st.dataframe(erc_rec, use_container_width=True, hide_index=True)


def _render_black_litterman(ctx, usable):
    asset_returns = ctx.get("asset_returns")
    df = ctx.get("df", pd.DataFrame())

    if asset_returns is None or asset_returns.empty or not usable or df.empty:
        return

    info_section(
        "Black-Litterman Optimization",
        "Posterior expected returns blending CAPM equilibrium (reverse-optimized from current weights) "
        "with your investor views. Add views to tilt the portfolio away from equilibrium.",
    )

    # Derive current weights from df
    weight_col = df.set_index("Ticker").reindex(usable)["Weight"].fillna(0)
    total_w = weight_col.sum()
    current_weights = (weight_col.values / total_w) if total_w > 0 else np.ones(len(usable)) / len(usable)

    risk_free_rate = float(ctx.get("risk_free_rate", 0.02))

    # Views management
    if "bl_views" not in st.session_state:
        st.session_state["bl_views"] = []

    with st.expander("Add Investor Views (optional)", expanded=False):
        st.caption("Specify your expected annual return for an asset. Confidence 0–1 (higher = stronger view).")
        v1, v2, v3, v4 = st.columns([2, 2, 2, 1])
        with v1:
            view_ticker = st.selectbox("Ticker", usable, key="bl_view_ticker")
        with v2:
            view_return = st.number_input("Expected Annual Return", -0.5, 1.0, 0.10, 0.01,
                                          format="%.2f", key="bl_view_return")
        with v3:
            view_conf = st.number_input("Confidence", 0.01, 0.99, 0.50, 0.05,
                                        format="%.2f", key="bl_view_conf")
        with v4:
            st.write("")
            st.write("")
            if st.button("Add View", key="bl_add_view"):
                st.session_state["bl_views"].append({
                    "ticker": view_ticker,
                    "expected_return": float(view_return),
                    "confidence": float(view_conf),
                })
                st.rerun()

        if st.session_state["bl_views"]:
            views_df = pd.DataFrame(st.session_state["bl_views"])
            st.dataframe(views_df, use_container_width=True, hide_index=True)
            if st.button("Clear All Views", key="bl_clear_views"):
                st.session_state["bl_views"] = []
                st.rerun()

    bl = compute_black_litterman(
        asset_returns=asset_returns,
        current_weights=current_weights,
        tickers=usable,
        views=st.session_state.get("bl_views", []),
        risk_free_rate=risk_free_rate,
    )

    if bl is None:
        st.info("Black-Litterman requires at least 2 assets with return history.")
        return

    eq_returns = bl["equilibrium_returns"]
    post_returns = bl["posterior_returns"]

    # Side-by-side chart
    fig = go.Figure()
    fig.add_bar(x=usable, y=[eq_returns.get(t, 0) for t in usable],
                name="Equilibrium (CAPM)", marker_color="#4db8ff",
                hovertemplate="%{x}<br>Equilibrium: %{y:.2%}<extra></extra>")
    fig.add_bar(x=usable, y=[post_returns.get(t, 0) for t in usable],
                name="BL Posterior", marker_color="#f3a712",
                hovertemplate="%{x}<br>Posterior: %{y:.2%}<extra></extra>")
    fig.update_layout(
        barmode="group",
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=380,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Asset",
        yaxis_title="Expected Annual Return",
        yaxis=dict(tickformat=".1%"),
        legend=dict(orientation="h", y=1.08, x=0.0),
    )
    st.plotly_chart(fig, use_container_width=True, key="bl_returns_chart")

    # Summary table
    cw_map = dict(zip(usable, current_weights))
    rows = [
        {
            "Ticker": t,
            "Equilibrium Return": f"{eq_returns.get(t, 0):.2%}",
            "BL Posterior Return": f"{post_returns.get(t, 0):.2%}",
            "Δ vs Equilibrium": f"{post_returns.get(t, 0) - eq_returns.get(t, 0):+.2%}",
            "Current Weight": f"{cw_map.get(t, 0.0):.2%}",
        }
        for t in usable
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if st.session_state.get("bl_views"):
        st.caption(
            f"Posterior blends equilibrium with {len(st.session_state['bl_views'])} investor "
            f"view(s). tau=0.05, lambda=2.5."
        )
    else:
        st.caption("No views added -- posterior equals CAPM equilibrium. Add views above to see BL adjustment.")


def _annualized_voo_return(ctx):
    benchmark_returns = ctx.get("benchmark_returns")
    if benchmark_returns is None or benchmark_returns.empty:
        return None
    return float(benchmark_returns.mean() * 252)


def render_optimization_page(ctx):
    render_page_title("Optimization")

    asset_returns = ctx.get("asset_returns")
    df = ctx.get("df", pd.DataFrame())

    if asset_returns is None or asset_returns.empty or df.empty:
        st.info("Not enough data to build the efficient frontier.")
        return

    # ── Sidebar controls ──────────────────────────────────────────────────────
    with st.sidebar.expander("Optimization Settings", expanded=False):
        profile = ctx.get("profile", "Balanced")
        defaults = get_default_constraints(profile)
        max_single_asset = st.number_input("Max single-asset weight", 0.05, 1.00, float(defaults["max_single_asset"]), 0.01, format="%.2f")
        min_bonds = st.number_input("Min bonds", 0.00, 1.00, float(defaults["min_bonds"]), 0.01, format="%.2f")
        min_gold = st.number_input("Min gold", 0.00, 1.00, float(defaults["min_gold"]), 0.01, format="%.2f")
        rfr = st.number_input("Risk-free rate", 0.00, 0.20, 0.02, 0.005, format="%.3f")

    # ── Compute frontier (cached) ─────────────────────────────────────────────
    frontier, frontier_computed_at = _cached_frontier(asset_returns, max_single_asset, min_bonds, min_gold, rfr, 2000)

    if frontier is None or frontier.empty:
        st.info("Not enough data to build the efficient frontier.")
        return

    usable = asset_returns.columns.tolist()
    mean_returns = asset_returns.mean() * 252
    cov_matrix = asset_returns.cov() * 252

    current_weights = (
        df.set_index("Ticker").loc[usable, "Weight"]
        / max(df.set_index("Ticker").loc[usable, "Weight"].sum(), 1e-12)
    ).values

    current_return = float(current_weights @ mean_returns.values)
    current_vol = float(np.sqrt(current_weights @ cov_matrix.values @ current_weights.T))
    current_sharpe = float((current_return - rfr) / current_vol) if current_vol > 0 else 0.0

    # Exact optimization (primary) — falls back to Monte Carlo best if scipy fails
    _opt_constraints = {"max_single_asset": max_single_asset, "min_bonds": min_bonds, "min_gold": min_gold}
    max_sharpe_row = optimize_max_sharpe(asset_returns, usable, _opt_constraints, rfr)
    min_vol_row    = optimize_min_vol(asset_returns, usable, _opt_constraints, rfr)
    if max_sharpe_row is None:
        max_sharpe_row = frontier.loc[frontier["Sharpe"].idxmax()]
    if min_vol_row is None:
        min_vol_row = frontier.loc[frontier["Volatility"].idxmin()]

    max_x = max(
        frontier["Volatility"].max(),
        current_vol,
        float(max_sharpe_row["Volatility"]),
        float(min_vol_row["Volatility"]),
    ) * 1.1

    cml_x = np.linspace(0, max_x, 100)
    cml_y = rfr + float(max_sharpe_row["Sharpe"]) * cml_x

    fig_frontier = go.Figure()
    fig_frontier.add_trace(
        go.Scatter(
            x=frontier["Volatility"],
            y=frontier["Return"],
            mode="markers",
            marker=dict(size=5, color=frontier["Sharpe"], colorscale="Viridis", showscale=True),
            name="Simulated Portfolios",
        )
    )
    fig_frontier.add_trace(go.Scatter(x=cml_x, y=cml_y, mode="lines", name="Capital Market Line"))
    fig_frontier.add_trace(
        go.Scatter(
            x=[current_vol],
            y=[current_return],
            mode="markers+text",
            text=["Current"],
            textposition="top center",
            name="Current Portfolio",
        )
    )
    fig_frontier.add_trace(
        go.Scatter(
            x=[max_sharpe_row["Volatility"]],
            y=[max_sharpe_row["Return"]],
            mode="markers+text",
            text=["Max Sharpe"],
            textposition="top center",
            name="Max Sharpe",
        )
    )
    fig_frontier.add_trace(
        go.Scatter(
            x=[min_vol_row["Volatility"]],
            y=[min_vol_row["Return"]],
            mode="markers+text",
            text=["Min Vol"],
            textposition="bottom center",
            name="Min Volatility",
        )
    )
    fig_frontier.update_layout(
        xaxis_title="Volatility",
        yaxis_title="Expected Return",
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=430,
        margin=dict(t=20, b=20, l=20, r=20),
    )

    # ── Render ────────────────────────────────────────────────────────────────
    voo_return = _annualized_voo_return(ctx)

    c1, c2, c3, c4 = st.columns(4)
    info_metric(c1, "Current Return", f"{current_return:.2%}", "Expected annualized return of the current portfolio.")
    info_metric(c2, "VOO Return", "-" if voo_return is None else f"{voo_return:.2%}", "Annualized VOO return over the same historical window.")
    info_metric(c3, "Current Volatility", f"{current_vol:.2%}", "Expected annualized volatility of the current portfolio.")
    info_metric(c4, "Current Sharpe", f"{current_sharpe:.2f}", "Sharpe ratio of the current portfolio.")

    info_section(
        "Efficient Frontier",
        "Simulated efficient frontier, current portfolio, max Sharpe portfolio, and minimum volatility portfolio.",
    )
    st.caption(f"Last computed: {frontier_computed_at} · Refreshes every 15 min · Use Sync Private Data to force refresh")
    st.plotly_chart(fig_frontier, use_container_width=True, key="optimization_frontier_chart_v2")

    ms_weights = max_sharpe_row["Weights"]
    mv_weights = min_vol_row["Weights"]

    ms_table = weights_table(ms_weights, usable)
    mv_table = weights_table(mv_weights, usable)

    ms_rec = build_recommended_shares_table(ms_weights, usable, ctx["df"])
    mv_rec = build_recommended_shares_table(mv_weights, usable, ctx["df"])

    left, right = st.columns(2)

    with left:
        info_section("Max Sharpe Weights", "Recommended weights from the maximum Sharpe portfolio.")
        st.dataframe(ms_table, use_container_width=True, height=260)

        info_section("Max Sharpe Shares", "Recommended shares to move the current portfolio toward the maximum Sharpe allocation.")
        st.dataframe(ms_rec, use_container_width=True, height=300)

    with right:
        info_section("Min Volatility Weights", "Recommended weights from the minimum volatility portfolio.")
        st.dataframe(mv_table, use_container_width=True, height=260)

        info_section("Min Volatility Shares", "Recommended shares to move the current portfolio toward the minimum volatility allocation.")
        st.dataframe(mv_rec, use_container_width=True, height=300)

    rp = _cached_risk_parity(asset_returns)
    _render_risk_parity(ctx, rp)
    _render_black_litterman(ctx, usable)
