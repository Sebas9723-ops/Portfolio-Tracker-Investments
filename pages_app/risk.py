import plotly.graph_objects as go
import streamlit as st

from app_core import render_page_title, info_section, info_metric


def _fmt_pct(v, decimals=2) -> str:
    try:
        return f"{float(v):.{decimals}%}"
    except Exception:
        return "—"


def _render_var_section(ctx):
    vc = ctx.get("var_cvar", {})
    if not vc:
        st.info("Not enough return history to compute VaR (minimum 30 observations required).")
        return

    n_obs = vc.get("n_observations", 0)
    if n_obs < 252:
        st.caption(f"Note: based on {n_obs} daily observations — results stabilize with >252 days.")

    info_section(
        "Value at Risk — Historical",
        "Worst expected daily loss at 95% and 99% confidence based on actual return distribution.",
    )
    c1, c2, c3, c4 = st.columns(4)
    info_metric(c1, "VaR 95% (1-day)", _fmt_pct(vc.get("hist_var_95")), "You lose more than this only 5% of days.")
    info_metric(c2, "CVaR 95% (1-day)", _fmt_pct(vc.get("hist_cvar_95")), "Average loss on the worst 5% of days.")
    info_metric(c3, "VaR 99% (1-day)", _fmt_pct(vc.get("hist_var_99")), "You lose more than this only 1% of days.")
    info_metric(c4, "CVaR 99% (1-day)", _fmt_pct(vc.get("hist_cvar_99")), "Average loss on the worst 1% of days.")

    info_section(
        "Value at Risk — Parametric (Normal)",
        "VaR/CVaR assuming normally distributed returns — faster but underestimates tail risk.",
    )
    p1, p2, p3, p4 = st.columns(4)
    info_metric(p1, "VaR 95% (1-day)", _fmt_pct(vc.get("param_var_95")), "Parametric 95% VaR.")
    info_metric(p2, "CVaR 95% (1-day)", _fmt_pct(vc.get("param_cvar_95")), "Parametric 95% CVaR.")
    info_metric(p3, "VaR 99% (1-day)", _fmt_pct(vc.get("param_var_99")), "Parametric 99% VaR.")
    info_metric(p4, "CVaR 99% (1-day)", _fmt_pct(vc.get("param_cvar_99")), "Parametric 99% CVaR.")

    # Annual approximation (sqrt of time rule)
    ccy = ctx.get("base_currency", "USD")
    port_val = float(ctx.get("total_portfolio_value", 0.0))
    if port_val > 0:
        info_section(
            "Annual VaR Approximation",
            f"Daily VaR scaled to annual terms (√252 rule) in {ccy}.",
        )
        a1, a2, a3, a4 = st.columns(4)
        ann_var_95 = float(vc.get("hist_var_95", 0)) * (252 ** 0.5) * port_val
        ann_cvar_95 = float(vc.get("hist_cvar_95", 0)) * (252 ** 0.5) * port_val
        ann_var_99 = float(vc.get("hist_var_99", 0)) * (252 ** 0.5) * port_val
        ann_cvar_99 = float(vc.get("hist_cvar_99", 0)) * (252 ** 0.5) * port_val
        info_metric(a1, f"Annual VaR 95% ({ccy})", f"{ann_var_95:,.2f}", "Estimated annual loss at 95%.")
        info_metric(a2, f"Annual CVaR 95% ({ccy})", f"{ann_cvar_95:,.2f}", "Estimated annual tail loss at 95%.")
        info_metric(a3, f"Annual VaR 99% ({ccy})", f"{ann_var_99:,.2f}", "Estimated annual loss at 99%.")
        info_metric(a4, f"Annual CVaR 99% ({ccy})", f"{ann_cvar_99:,.2f}", "Estimated annual tail loss at 99%.")


def render_risk_page(ctx):
    render_page_title("Risk")

    c1, c2, c3, c4 = st.columns(4)
    info_metric(c1, "Volatility", _fmt_pct(ctx["volatility"]), "Annualized volatility.")
    info_metric(c2, "Max Drawdown", _fmt_pct(ctx["max_drawdown"]), "Maximum drawdown over the sample.")
    info_metric(c3, "Stress PnL", f"{ctx['base_currency']} {ctx['stress_pnl']:,.2f}", "PnL under the configured stress scenario.")
    info_metric(c4, "Stress Return", _fmt_pct(ctx["stress_return"]), "Return under the configured stress scenario.")

    _render_var_section(ctx)

    info_section("Correlation Matrix", "Pairwise correlation between all portfolio assets. Red = negative, Blue = positive.")
    fig_corr = ctx.get("fig_correlation")
    if fig_corr is not None:
        st.plotly_chart(fig_corr, use_container_width=True, key="risk_correlation_heatmap")
    else:
        st.info("Need at least 2 assets with return history to build correlation matrix.")

    info_section("Stress Test", "Current value versus stressed value under the selected shocks.")
    st.plotly_chart(ctx["fig_stress"], use_container_width=True, key="risk_stress_chart")

    info_section("Stress Table", "Per-position stress-test detail.")
    st.dataframe(ctx["stress_df"], use_container_width=True, height=360)

    if not ctx["rolling_df"].empty and "Rolling Drawdown" in ctx["rolling_df"].columns:
        info_section("Rolling Drawdown", "Rolling drawdown history of the portfolio.")
        dd_fig = go.Figure()
        dd_fig.add_scatter(
            x=ctx["rolling_df"].index,
            y=ctx["rolling_df"]["Rolling Drawdown"],
            name="Rolling Drawdown",
            fill="tozeroy",
            fillcolor="rgba(244,67,54,0.15)",
            line=dict(color="#f44336"),
            hovertemplate="%{x|%Y-%m-%d}<br>Drawdown: %{y:.2%}<extra></extra>",
        )
        dd_fig.update_layout(
            paper_bgcolor="#0b0f14",
            plot_bgcolor="#0b0f14",
            font=dict(color="#e6e6e6"),
            height=320,
            margin=dict(t=20, b=20, l=20, r=20),
            yaxis=dict(tickformat=".0%"),
        )
        st.plotly_chart(dd_fig, use_container_width=True, key="risk_rolling_drawdown_chart")
