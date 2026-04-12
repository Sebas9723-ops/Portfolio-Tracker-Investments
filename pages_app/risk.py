import datetime
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import streamlit as st

from utils_aggrid import show_aggrid

from app_core import (
    build_correlation_heatmap,
    build_fx_exposure_summary,
    build_stress_test_table,
    check_mandate_compliance,
    compute_fixed_income_analytics,
    compute_risk_budget,
    compute_rolling_metrics,
    get_risk_free_rate,
    info_metric,
    info_section,
    render_page_title,
)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_stress(df: pd.DataFrame, equity_shock: float, bonds_shock: float, gold_shock: float):
    shocks = {"Equities": equity_shock, "Bonds": bonds_shock, "Gold": gold_shock}
    stress_df, current_tv, stressed_tv = build_stress_test_table(df, shocks)
    fig = go.Figure()
    fig.add_bar(x=stress_df["Ticker"], y=stress_df["Current Value"], name="Current Value")
    fig.add_bar(x=stress_df["Ticker"], y=stress_df["Stressed Value"], name="Stressed Value")
    fig.update_layout(
        barmode="group", paper_bgcolor="#0b0f14", plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"), height=340, margin=dict(t=20, b=20, l=20, r=20),
    )
    return stress_df, fig, current_tv, stressed_tv


@st.cache_data(ttl=300, show_spinner=False)
def _cached_rolling(portfolio_returns: pd.Series, benchmark_returns: pd.Series, window: int, rfr: float):
    return compute_rolling_metrics(portfolio_returns, benchmark_returns, rfr, window)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_risk_analytics(df: pd.DataFrame, asset_returns: pd.DataFrame, base_currency: str):
    weights = df.set_index("Ticker")["Weight"] if not df.empty else pd.Series(dtype=float)
    risk_budget_df = compute_risk_budget(asset_returns, weights)
    fixed_income_df = compute_fixed_income_analytics(df, base_currency)
    fig_corr = build_correlation_heatmap(asset_returns)
    fx_df = build_fx_exposure_summary(df, base_currency)
    return risk_budget_df, fixed_income_df, fig_corr, fx_df


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
        "Value at Risk (VaR / CVaR)",
        "How much you can lose in a single day at 95% and 99% confidence — and what the average looks like on those worst days.",
    )
    if n_obs < 252:
        st.caption(f"Based on {n_obs} daily observations — results stabilize with >252 days.")

    tab_hist, tab_param, tab_ann = st.tabs(["Historical", "Parametric (Normal)", "Annual (√252 rule)"])

    with tab_hist:
        c1, c2, c3, c4 = st.columns(4)
        info_metric(c1, "VaR 95%",  _fmt_pct(vc.get("hist_var_95")),  "On 95 of 100 days your loss is less than this.")
        info_metric(c2, "CVaR 95%", _fmt_pct(vc.get("hist_cvar_95")), "Average loss on the worst 5% of days.")
        info_metric(c3, "VaR 99%",  _fmt_pct(vc.get("hist_var_99")),  "On 99 of 100 days your loss is less than this.")
        info_metric(c4, "CVaR 99%", _fmt_pct(vc.get("hist_cvar_99")), "Average loss on the worst 1% of days.")

    with tab_param:
        p1, p2, p3, p4 = st.columns(4)
        info_metric(p1, "VaR 95%",  _fmt_pct(vc.get("param_var_95")),  "Parametric 95% VaR (assumes normal distribution).")
        info_metric(p2, "CVaR 95%", _fmt_pct(vc.get("param_cvar_95")), "Parametric 95% CVaR.")
        info_metric(p3, "VaR 99%",  _fmt_pct(vc.get("param_var_99")),  "Parametric 99% VaR.")
        info_metric(p4, "CVaR 99%", _fmt_pct(vc.get("param_cvar_99")), "Parametric 99% CVaR.")

    with tab_ann:
        ccy = ctx.get("base_currency", "USD")
        port_val = float(ctx.get("total_portfolio_value", 0.0))
        if port_val > 0:
            scale = 252 ** 0.5
            a1, a2, a3, a4 = st.columns(4)
            info_metric(a1, f"VaR 95% ({ccy})",  f"{float(vc.get('hist_var_95', 0)) * scale * port_val:,.2f}", "Daily VaR 95% × √252.")
            info_metric(a2, f"CVaR 95% ({ccy})", f"{float(vc.get('hist_cvar_95', 0)) * scale * port_val:,.2f}", "Daily CVaR 95% × √252.")
            info_metric(a3, f"VaR 99% ({ccy})",  f"{float(vc.get('hist_var_99', 0)) * scale * port_val:,.2f}", "Daily VaR 99% × √252.")
            info_metric(a4, f"CVaR 99% ({ccy})", f"{float(vc.get('hist_cvar_99', 0)) * scale * port_val:,.2f}", "Daily CVaR 99% × √252.")
        else:
            st.info("Portfolio value required for annualised amounts.")


def _render_risk_budget_data(risk_budget_df):
    if risk_budget_df is None or (hasattr(risk_budget_df, "empty") and risk_budget_df.empty):
        return
    info_section("Risk Budgeting — Component VaR",
                 "How much each asset contributes to total portfolio VaR.")
    show_aggrid(risk_budget_df, height=400, key="aggrid_risk_budget")
    fig = go.Figure()
    fig.add_bar(x=risk_budget_df["Ticker"], y=risk_budget_df["Risk Contribution %"],
                marker_color="#f3a712",
                text=[f"{v:.1f}%" for v in risk_budget_df["Risk Contribution %"]],
                textposition="outside")
    fig.update_layout(paper_bgcolor="#0b0f14", plot_bgcolor="#0b0f14",
                      font=dict(color="#e6e6e6"), height=300,
                      margin=dict(t=20, b=20, l=20, r=20))
    st.plotly_chart(fig, use_container_width=True, key="risk_budget_chart")


def _render_fixed_income_data(fi_df):
    if fi_df is None or (hasattr(fi_df, "empty") and fi_df.empty):
        return
    info_section("Fixed Income Analytics",
                 "Duration and rate sensitivity for bond ETFs. DV01 = value change per 1bp.")
    show_aggrid(fi_df, height=400, key="aggrid_risk_fixed_income")


def _render_compliance_data(rules):
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


def _render_fx_exposure_data(fx_df, base_ccy="USD"):
    if fx_df is None or fx_df.empty:
        return

    info_section(
        "FX Exposure",
        "Portfolio holdings grouped by native currency. Impact of 1% FX move shows potential gain/loss for non-base currencies.",
    )

    c1, c2 = st.columns([1, 1])

    with c1:
        pie_fig = px.pie(
            fx_df, names="Currency", values="Exposure",
            hole=0.4,
            color_discrete_sequence=["#f3a712", "#00c8ff", "#00e676", "#ce93d8", "#ff7043", "#aaa"],
        )
        pie_fig.update_traces(textposition="inside", textinfo="percent+label")
        pie_fig.update_layout(
            paper_bgcolor="#0b0f14", plot_bgcolor="#0b0f14",
            font=dict(color="#e6e6e6"), height=320,
            margin=dict(t=20, b=20, l=20, r=20),
            legend=dict(orientation="h", y=-0.1),
        )
        st.plotly_chart(pie_fig, use_container_width=True, key="risk_fx_exposure_pie")

    with c2:
        display = fx_df.copy()
        display["Exposure"] = display["Exposure"].map(lambda v: f"{v:,.2f}")
        display["Weight %"] = display["Weight %"].map(lambda v: f"{v:.2f}%")
        display["1% FX Move Impact"] = display["1% FX Move Impact"].map(
            lambda v: f"{v:,.2f} {base_ccy}" if v != 0 else f"Base ({base_ccy})"
        )
        show_aggrid(display, height=400, key="aggrid_risk_fx_exposure")


def _render_alert_summary(ctx):
    active_alerts = ctx.get("active_alerts")
    if active_alerts is None:
        return
    if not active_alerts:
        return

    info_section(
        "Alert Summary",
        "Active portfolio alerts triggered by current market conditions.",
    )

    alert_colors = {
        "BREACH": "#ff1744",
        "WARNING": "#ff7043",
        "INFO": "#00c8ff",
    }

    for alert in active_alerts:
        level = str(alert.get("level", "INFO")).upper()
        title = str(alert.get("title", alert.get("name", "Alert")))
        message = str(alert.get("message", alert.get("detail", "")))
        color = alert_colors.get(level, "#f3a712")
        st.markdown(
            f"<div style='padding:10px 14px;border-radius:6px;margin-bottom:8px;"
            f"background:#1a1f2e;border-left:4px solid {color}'>"
            f"<span style='color:{color};font-weight:bold;font-size:13px'>[{level}] {title}</span>"
            f"{'<br><span style=\"color:#aaa;font-size:12px\">' + message + '</span>' if message else ''}"
            f"</div>",
            unsafe_allow_html=True,
        )


def render_risk_page(ctx):
    render_page_title("Risk")

    # ── Sidebar controls (must be outside fragment in Streamlit 1.41+) ───────────
    with st.sidebar.expander("Stress Testing", expanded=False):
        st.number_input("Equities Shock", -1.0, 1.0, -0.10, 0.01, format="%.2f", key="risk_eq_shock")
        st.number_input("Bonds Shock",    -1.0, 1.0, -0.03, 0.01, format="%.2f", key="risk_bd_shock")
        st.number_input("Gold Shock",      -1.0, 1.0,  0.05, 0.01, format="%.2f", key="risk_gd_shock")
        st.slider("Rolling Window (days)", 21, 252, 63, 21, key="risk_roll_win")
        st.number_input("Max concentration", 0.05, 1.0, 0.40, 0.05, format="%.2f", key="risk_conc")
        st.number_input("Min bonds alloc",   0.00, 1.0, 0.05, 0.05, format="%.2f", key="risk_bonds")

    @st.fragment(run_every=900)
    def _live():
        st.caption(f"Last refreshed: {datetime.datetime.now().strftime('%H:%M:%S')}")

        equity_shock   = st.session_state.get("risk_eq_shock", -0.10)
        bonds_shock    = st.session_state.get("risk_bd_shock", -0.03)
        gold_shock     = st.session_state.get("risk_gd_shock",  0.05)
        rolling_window = st.session_state.get("risk_roll_win",  63)
        max_single_c   = st.session_state.get("risk_conc",      0.40)
        min_bonds_c    = st.session_state.get("risk_bonds",     0.05)

        df = ctx.get("df", pd.DataFrame())
        asset_returns = ctx.get("asset_returns")
        portfolio_returns = ctx.get("portfolio_returns", pd.Series(dtype=float))
        resolved_benchmark = ctx.get("resolved_benchmark_returns", pd.Series(dtype=float))
        base_currency = ctx.get("base_currency", "USD")

        # ── Compute (all cached) ──────────────────────────────────────────────────
        stress_df, fig_stress, current_tv, stressed_tv = _cached_stress(df, equity_shock, bonds_shock, gold_shock)
        stress_pnl = stressed_tv - current_tv
        stress_return = (stressed_tv / current_tv - 1) if current_tv > 0 else 0.0

        rolling_df = pd.DataFrame()
        if not portfolio_returns.empty and not resolved_benchmark.empty:
            rfr = float(ctx.get("risk_free_rate", get_risk_free_rate()))
            rolling_df = _cached_rolling(portfolio_returns, resolved_benchmark, rolling_window, rfr)

        risk_budget_df, fixed_income_df, fig_corr, fx_df = (None, None, None, None)
        if not df.empty and asset_returns is not None and not asset_returns.empty:
            risk_budget_df, fixed_income_df, fig_corr, fx_df = _cached_risk_analytics(df, asset_returns, base_currency)

        var_cvar = ctx.get("var_cvar", {})
        var_95 = abs(float((var_cvar or {}).get("hist_var_95", 0.0)))
        constraints = {"max_single_asset": max_single_c, "min_bonds": min_bonds_c, "min_gold": 0.0}
        compliance_results = check_mandate_compliance(
            df=df, max_drawdown=ctx.get("max_drawdown", 0.0),
            tracking_error=ctx.get("tracking_error", 0.0),
            var_cvar={"hist_var_95": -var_95}, constraints=constraints,
        )

        # ── Header metrics ────────────────────────────────────────────────────────
        c1, c2, c3, c4 = st.columns(4)
        info_metric(c1, "Volatility", _fmt_pct(ctx.get("volatility", 0)), "Annualized volatility.")
        info_metric(c2, "Max Drawdown", _fmt_pct(ctx.get("max_drawdown", 0)), "Maximum peak-to-trough drawdown.")
        info_metric(c3, "Stress PnL", f"{base_currency} {stress_pnl:,.2f}", "PnL under configured stress scenario.")
        info_metric(c4, "Stress Return", _fmt_pct(stress_return), "Return under configured stress scenario.")

        _render_var_section(ctx)

        info_section("Correlation Matrix", "Pairwise correlation between portfolio assets.")
        if fig_corr is not None:
            st.plotly_chart(fig_corr, use_container_width=True, key="risk_correlation_heatmap")
        else:
            st.info("Need at least 2 assets with return history.")

        info_section("Stress Test", "Per-position stressed values under configured shocks.")
        st.plotly_chart(fig_stress, use_container_width=True, key="risk_stress_chart")
        show_aggrid(stress_df, height=300, key="aggrid_risk_stress")

        if not rolling_df.empty and "Rolling Drawdown" in rolling_df.columns:
            info_section("Rolling Drawdown", "Rolling drawdown over time.")
            dd_fig = go.Figure()
            dd_fig.add_scatter(
                x=rolling_df.index, y=rolling_df["Rolling Drawdown"],
                fill="tozeroy", fillcolor="rgba(244,67,54,0.15)",
                line=dict(color="#f44336"),
                hovertemplate="%{x|%Y-%m-%d}<br>Drawdown: %{y:.2%}<extra></extra>",
            )
            dd_fig.update_layout(
                paper_bgcolor="#0b0f14", plot_bgcolor="#0b0f14",
                font=dict(color="#e6e6e6"), height=280,
                margin=dict(t=20, b=20, l=20, r=20),
                yaxis=dict(tickformat=".0%"),
            )
            st.plotly_chart(dd_fig, use_container_width=True, key="risk_rolling_drawdown_chart")

        # Pass computed data via ctx-like dicts to the sub-renderers
        _render_risk_budget_data(risk_budget_df)
        _render_fixed_income_data(fixed_income_df)
        _render_compliance_data(compliance_results)
        _render_fx_exposure_data(fx_df, base_currency)
        _render_alert_summary(ctx)

    _live()
