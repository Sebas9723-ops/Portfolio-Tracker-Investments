import plotly.graph_objects as go
import streamlit as st

from app_core import info_metric, info_section, render_page_title


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


def _render_risk_budget(ctx):
    risk_budget_df = ctx.get("risk_budget_df")
    if risk_budget_df is None or risk_budget_df.empty:
        return

    info_section(
        "Risk Budgeting — Component VaR",
        "How much each asset contributes to total portfolio VaR (95%, annualized). "
        "Component VaR sums to total VaR. Risk Contribution % shows each asset's relative share.",
    )
    st.dataframe(risk_budget_df, use_container_width=True, hide_index=True)

    fig = go.Figure()
    fig.add_bar(
        x=risk_budget_df["Ticker"],
        y=risk_budget_df["Risk Contribution %"],
        marker_color="#f3a712",
        text=[f"{v:.1f}%" for v in risk_budget_df["Risk Contribution %"]],
        textposition="outside",
    )
    fig.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=320,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Ticker",
        yaxis_title="Risk Contribution %",
    )
    st.plotly_chart(fig, use_container_width=True, key="risk_budget_chart")


def _render_fixed_income(ctx):
    fi_df = ctx.get("fixed_income_df")
    if fi_df is None or fi_df.empty:
        return

    info_section(
        "Fixed Income Analytics",
        "Duration and rate sensitivity for bond ETFs in the portfolio. "
        "DV01 = dollar value change per 1bp rate move. Rate +1% = estimated impact of a 100bps parallel shift.",
    )
    st.dataframe(fi_df, use_container_width=True, hide_index=True)


def _render_compliance(ctx):
    rules = ctx.get("compliance_results")
    if not rules:
        return

    info_section(
        "Compliance / Mandate Monitor",
        "IPS constraint checks — green = within policy limits, red = breach.",
    )

    cols = st.columns(len(rules))
    for i, rule in enumerate(rules):
        passed = rule["Status"] == "PASS"
        color = "#00c853" if passed else "#ff1744"
        label = rule["Rule"]
        value = rule["Value"]
        threshold = rule["Threshold"]
        status_icon = "✓ PASS" if passed else "✗ FAIL"
        cols[i].markdown(
            f"<div style='text-align:center;padding:10px 6px;border-radius:6px;"
            f"background:#1a1f2e;border:2px solid {color}'>"
            f"<div style='color:{color};font-size:16px;font-weight:bold'>{status_icon}</div>"
            f"<div style='color:#e6e6e6;font-size:13px;margin:4px 0'>{label}</div>"
            f"<div style='color:#f3a712;font-size:15px;font-weight:bold'>{value}</div>"
            f"<div style='color:#888;font-size:11px'>Limit: {threshold}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown("")
    st.caption(
        "Limits: Max Concentration ≤ constraint setting | Min Bonds ≥ constraint setting | "
        "Max Drawdown ≤ 25% | Tracking Error ≤ 15% | Daily VaR 95% ≤ 3%"
    )


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

    _render_risk_budget(ctx)
    _render_fixed_income(ctx)
    _render_compliance(ctx)
