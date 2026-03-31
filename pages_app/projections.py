import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core import info_metric, info_section, render_page_title


@st.cache_data(ttl=3600, show_spinner=False)
def _run_monte_carlo(
    portfolio_returns: pd.Series,
    current_value: float,
    horizons_years: tuple = (1, 3, 5, 10),
    monthly_contribution: float = 0.0,
    n_sims: int = 500,
    seed: int = 42,
) -> dict:
    result: dict = {}
    if portfolio_returns is None or portfolio_returns.empty or len(portfolio_returns) < 60:
        return result
    rng = np.random.default_rng(seed)
    r = pd.to_numeric(portfolio_returns, errors="coerce").dropna().values
    for h in horizons_years:
        n_months = h * 12
        paths = np.zeros((n_sims, n_months + 1))
        paths[:, 0] = current_value
        for m in range(n_months):
            sampled = rng.choice(r, size=(n_sims, 21), replace=True)
            monthly_r = (1 + sampled).prod(axis=1) - 1
            paths[:, m + 1] = paths[:, m] * (1 + monthly_r) + monthly_contribution
        pcts = np.percentile(paths, [10, 25, 50, 75, 90], axis=0)
        result[h] = pd.DataFrame(
            {"p10": pcts[0], "p25": pcts[1], "p50": pcts[2], "p75": pcts[3], "p90": pcts[4]},
            index=range(n_months + 1),
        )
    return result


def _goal_contribution(current_value: float, target_value: float, years: int, expected_annual_return: float) -> float:
    if years <= 0 or target_value <= 0:
        return 0.0
    n = years * 12
    r = (1 + expected_annual_return) ** (1.0 / 12) - 1
    fv_pv = current_value * (1 + r) ** n
    if fv_pv >= target_value:
        return 0.0
    if r == 0:
        return (target_value - fv_pv) / n
    return float((target_value - fv_pv) * r / ((1 + r) ** n - 1))

_HORIZONS = (1, 3, 5, 10, 15, 20, 25, 30)
_HORIZON_LABELS = {
    1: "1 Year", 3: "3 Years", 5: "5 Years", 10: "10 Years",
    15: "15 Years", 20: "20 Years", 25: "25 Years", 30: "30 Years",
}


def _build_fan_chart(mc_data: dict, horizon: int, current_value: float, base_currency: str, monthly_contribution: float) -> go.Figure | None:
    if horizon not in mc_data:
        return None

    df = mc_data[horizon]
    months = df.index.tolist()
    ccy = base_currency

    fig = go.Figure()

    # Shaded bands
    fig.add_trace(go.Scatter(
        x=months + months[::-1],
        y=df["p90"].tolist() + df["p10"].tolist()[::-1],
        fill="toself",
        fillcolor="rgba(243,167,18,0.08)",
        line=dict(color="rgba(0,0,0,0)"),
        name="P10–P90",
        hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=months + months[::-1],
        y=df["p75"].tolist() + df["p25"].tolist()[::-1],
        fill="toself",
        fillcolor="rgba(243,167,18,0.18)",
        line=dict(color="rgba(0,0,0,0)"),
        name="P25–P75",
        hoverinfo="skip",
    ))

    # Percentile lines
    fig.add_trace(go.Scatter(
        x=months, y=df["p10"],
        mode="lines", line=dict(color="#888", dash="dot", width=1),
        name="P10", hovertemplate="Month %{x}<br>P10: %{y:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=months, y=df["p90"],
        mode="lines", line=dict(color="#888", dash="dot", width=1),
        name="P90", hovertemplate="Month %{x}<br>P90: %{y:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=months, y=df["p50"],
        mode="lines", line=dict(color="#f3a712", width=2),
        name="Median", hovertemplate="Month %{x}<br>Median: %{y:,.0f}<extra></extra>",
    ))

    # Starting value reference
    fig.add_hline(y=current_value, line_dash="dash", line_color="#4db8ff", line_width=1,
                  annotation_text=f"Current: {ccy} {current_value:,.0f}", annotation_position="top left")

    fig.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=420,
        margin=dict(t=30, b=20, l=20, r=20),
        xaxis_title="Month",
        yaxis_title=f"Portfolio Value ({ccy})",
        legend=dict(orientation="h", y=1.08, x=0.0),
    )
    return fig


def render_projections_page(ctx):
    render_page_title("Projections")

    portfolio_returns = ctx.get("portfolio_returns")
    current_value = float(ctx.get("total_portfolio_value", 0.0))
    base_currency = ctx.get("base_currency", "USD")

    if portfolio_returns is None or portfolio_returns.empty or len(portfolio_returns) < 60:
        st.warning("Need at least 60 days of return history to run Monte Carlo projections.")
        return

    ann_return = float((1 + portfolio_returns).prod() ** (252 / len(portfolio_returns)) - 1)
    ann_vol = float(portfolio_returns.std() * np.sqrt(252))

    c1, c2, c3 = st.columns(3)
    info_metric(c1, "Current Portfolio", f"{base_currency} {current_value:,.2f}", "Starting value for projections.")
    info_metric(c2, "Historical Ann. Return", f"{ann_return:.2%}", "Used as baseline for goal planning.")
    info_metric(c3, "Historical Ann. Volatility", f"{ann_vol:.2%}", "Used for fan chart width.")

    # ── Monte Carlo ────────────────────────────────────────────────────────────
    info_section(
        "Monte Carlo Projection",
        "Bootstrap simulation (500 paths) using your actual historical daily returns. "
        "The fan shows P10/P90 (outer band) and P25/P75 (inner band) with the median line.",
    )

    col_contrib, col_horizon = st.columns([2, 1])
    with col_contrib:
        monthly_contribution = st.number_input(
            f"Monthly Contribution ({base_currency})",
            min_value=0.0,
            value=0.0,
            step=100.0,
            format="%.2f",
            key="proj_monthly_contrib",
            help="Additional amount added to the portfolio each month.",
        )
    with col_horizon:
        selected_horizon = st.selectbox(
            "Time Horizon",
            options=list(_HORIZON_LABELS.keys()),
            format_func=lambda x: _HORIZON_LABELS[x],
            index=2,
            key="proj_horizon",
        )

    mc_data = _run_monte_carlo(
        portfolio_returns=portfolio_returns,
        current_value=current_value,
        horizons_years=_HORIZONS,
        monthly_contribution=monthly_contribution,
        n_sims=500,
    )

    fan_fig = _build_fan_chart(mc_data, selected_horizon, current_value, base_currency, monthly_contribution)
    if fan_fig is not None:
        st.plotly_chart(fan_fig, use_container_width=True, key="projections_fan_chart")

    if selected_horizon in mc_data:
        df_h = mc_data[selected_horizon]
        final = df_h.iloc[-1]
        n_months = selected_horizon * 12

        st.markdown(f"**Projected values in {_HORIZON_LABELS[selected_horizon]}:**")
        r1, r2, r3, r4, r5 = st.columns(5)
        info_metric(r1, "Pessimistic (P10)", f"{base_currency} {final['p10']:,.0f}", "Worst 10% of simulated outcomes.")
        info_metric(r2, "Conservative (P25)", f"{base_currency} {final['p25']:,.0f}", "Bottom quartile of outcomes.")
        info_metric(r3, "Median (P50)", f"{base_currency} {final['p50']:,.0f}", "Middle outcome across all simulations.")
        info_metric(r4, "Optimistic (P75)", f"{base_currency} {final['p75']:,.0f}", "Top quartile of outcomes.")
        info_metric(r5, "Best Case (P90)", f"{base_currency} {final['p90']:,.0f}", "Top 10% of simulated outcomes.")

    # ── Goal-Based Planning ────────────────────────────────────────────────────
    info_section(
        "Goal-Based Planning",
        "How much do you need to contribute monthly to reach a target portfolio value?",
    )

    g1, g2, g3 = st.columns(3)
    with g1:
        target_value = st.number_input(
            f"Target Portfolio Value ({base_currency})",
            min_value=0.0,
            value=max(current_value * 2.0, current_value + 1000.0),
            step=1000.0,
            format="%.2f",
            key="proj_target_value",
        )
    with g2:
        goal_years = st.number_input(
            "Time Horizon (years)",
            min_value=1,
            max_value=40,
            value=10,
            step=1,
            key="proj_goal_years",
        )
    with g3:
        expected_return = st.number_input(
            "Expected Annual Return",
            min_value=0.0,
            max_value=0.50,
            value=max(round(ann_return, 3), 0.05),
            step=0.005,
            format="%.3f",
            key="proj_expected_return",
            help="Use historical return as a starting point.",
        )

    required_pmt = _goal_contribution(
        current_value=current_value,
        target_value=float(target_value),
        years=int(goal_years),
        expected_annual_return=float(expected_return),
    )

    if required_pmt <= 0.0:
        st.success(
            f"Your current portfolio of {base_currency} {current_value:,.2f} is already on track to reach "
            f"{base_currency} {target_value:,.2f} in {goal_years} years at {expected_return:.1%} annual return — "
            f"no additional contributions needed."
        )
    else:
        g_a, g_b, g_c = st.columns(3)
        info_metric(g_a, f"Monthly Contribution Needed ({base_currency})", f"{required_pmt:,.2f}",
                    f"To reach {base_currency} {target_value:,.0f} in {goal_years} years at {expected_return:.1%}/yr.")
        info_metric(g_b, f"Annual Contribution ({base_currency})", f"{required_pmt * 12:,.2f}",
                    "Monthly amount × 12.")
        total_contributions = required_pmt * goal_years * 12
        total_final = target_value
        growth = total_final - current_value - total_contributions
        info_metric(g_c, f"Expected Investment Growth ({base_currency})", f"{growth:,.2f}",
                    "Target minus starting value minus total contributions.")
