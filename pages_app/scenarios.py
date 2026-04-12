import plotly.graph_objects as go
import streamlit as st

from app_core import info_metric, info_section, render_page_title, run_historical_scenarios
from utils_aggrid import show_aggrid


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_scenarios(df, current_total_value: float):
    return run_historical_scenarios(df, current_total_value)


def render_scenarios_page(ctx):
    render_page_title("Scenarios")

    df = ctx.get("df")
    total_value = float(ctx.get("total_portfolio_value", ctx.get("total_value", 0.0)))
    scenarios_df = _cached_scenarios(df, total_value) if df is not None and not df.empty else None

    if scenarios_df is None or scenarios_df.empty:
        st.info("Scenarios unavailable — no portfolio data.")
        return

    ccy = ctx.get("base_currency", "USD")
    current_total = total_value

    info_section(
        "Historical Crisis Scenarios",
        "Applies approximate peak-to-trough market shocks from major historical crises to the current portfolio. "
        "Assets are bucketed into Equities, Bonds, and Gold.",
    )

    # Summary metrics (worst scenario)
    worst = scenarios_df.loc[scenarios_df["Scenario Return %"].idxmin()]
    best = scenarios_df.loc[scenarios_df["Scenario Return %"].idxmax()]

    c1, c2, c3 = st.columns(3)
    info_metric(
        c1, "Worst Scenario",
        f"{worst['Scenario']} ({worst['Scenario Return %']:.1f}%)",
        f"Portfolio loss: {ccy} {worst['Scenario PnL']:,.0f}",
    )
    info_metric(
        c2, "Best Scenario",
        f"{best['Scenario']} ({best['Scenario Return %']:.1f}%)",
        f"Portfolio gain: {ccy} {best['Scenario PnL']:,.0f}",
    )
    info_metric(
        c3, "Current Portfolio",
        f"{ccy} {current_total:,.2f}",
        "Starting value for all scenario projections.",
    )

    # Scenario return bar chart
    colors = ["#f44336" if v < 0 else "#4caf50" for v in scenarios_df["Scenario Return %"]]
    fig = go.Figure()
    fig.add_bar(
        x=scenarios_df["Scenario"],
        y=scenarios_df["Scenario Return %"],
        marker_color=colors,
        text=[f"{v:.1f}%" for v in scenarios_df["Scenario Return %"]],
        textposition="outside",
        hovertemplate="%{x}<br>Return: %{y:.1f}%<extra></extra>",
    )
    fig.add_hline(y=0, line_color="#888", line_width=1)
    fig.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=380,
        margin=dict(t=40, b=20, l=20, r=20),
        xaxis_title="Scenario",
        yaxis_title="Portfolio Return %",
        yaxis=dict(tickformat=".1f"),
        title=dict(text="Portfolio Return Under Each Scenario", font=dict(color="#f3a712")),
    )
    st.plotly_chart(fig, use_container_width=True, key="scenarios_return_chart")

    # PnL bar chart
    info_section("Scenario PnL", f"Estimated portfolio loss/gain in {ccy}.")
    pnl_colors = ["#f44336" if v < 0 else "#4caf50" for v in scenarios_df["Scenario PnL"]]
    fig2 = go.Figure()
    fig2.add_bar(
        x=scenarios_df["Scenario"],
        y=scenarios_df["Scenario PnL"],
        marker_color=pnl_colors,
        text=[f"{ccy} {v:,.0f}" for v in scenarios_df["Scenario PnL"]],
        textposition="outside",
        hovertemplate="%{x}<br>PnL: %{y:,.0f}<extra></extra>",
    )
    fig2.add_hline(y=0, line_color="#888", line_width=1)
    fig2.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=360,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Scenario",
        yaxis_title=f"PnL ({ccy})",
    )
    st.plotly_chart(fig2, use_container_width=True, key="scenarios_pnl_chart")

    # Detail table
    info_section("Scenario Detail", "Full table with shocked portfolio values per scenario.")
    display = scenarios_df.copy()
    display["Scenario PnL"] = display["Scenario PnL"].map(lambda v: f"{ccy} {v:,.2f}")
    display["Current Value"] = display["Current Value"].map(lambda v: f"{ccy} {v:,.2f}")
    display["Shocked Value"] = display["Shocked Value"].map(lambda v: f"{ccy} {v:,.2f}")
    display["Scenario Return %"] = display["Scenario Return %"].map(lambda v: f"{v:.2f}%")
    show_aggrid(display, height=400, key="aggrid_scenarios_detail")
