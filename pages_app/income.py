import pandas as pd
import plotly.express as px
import streamlit as st

from app_core import render_page_title, info_section, info_metric


ESTIMATED_YIELD_MAP = {
    "SCHD": 0.0360,
    "VOO": 0.0130,
    "VWCE.DE": 0.0150,
    "IWDA.AS": 0.0150,
    "BND": 0.0320,
    "AGG": 0.0310,
    "IEF": 0.0280,
    "TLT": 0.0360,
    "IGLN.L": 0.0000,
    "GLD": 0.0000,
    "IAU": 0.0000,
    "ICHN.AS": 0.0000,
}


def render_income_page(ctx):
    render_page_title("Income")

    df = ctx["df"].copy()

    if df.empty:
        st.info("No portfolio data available.")
        return

    income_df = df[["Ticker", "Name", "Value"]].copy()

    income_df["Estimated Yield"] = income_df["Ticker"].map(
        lambda x: ESTIMATED_YIELD_MAP.get(str(x).upper(), 0.0)
    )
    income_df["Estimated Annual Income"] = income_df["Value"] * income_df["Estimated Yield"]
    income_df["Estimated Monthly Income"] = income_df["Estimated Annual Income"] / 12

    annual_income = float(income_df["Estimated Annual Income"].sum())
    monthly_income = float(income_df["Estimated Monthly Income"].sum())
    portfolio_value = float(ctx["total_portfolio_value"])

    portfolio_yield = annual_income / portfolio_value if portfolio_value > 0 else 0.0

    c1, c2, c3 = st.columns(3)
    info_metric(
        c1,
        "Estimated Annual Income",
        f"{ctx['base_currency']} {annual_income:,.2f}",
        "Estimated annual portfolio income based on approximate distribution yields.",
    )
    info_metric(
        c2,
        "Estimated Monthly Income",
        f"{ctx['base_currency']} {monthly_income:,.2f}",
        "Estimated monthly portfolio income based on approximate distribution yields.",
    )
    info_metric(
        c3,
        "Portfolio Yield",
        f"{portfolio_yield:.2%}",
        "Estimated annual income divided by total portfolio value.",
    )

    info_section(
        "Income Breakdown",
        "Estimated income contribution by position using approximate trailing yields."
    )

    display_df = income_df.copy()
    display_df["Estimated Yield %"] = (display_df["Estimated Yield"] * 100).round(2)
    display_df["Estimated Annual Income"] = display_df["Estimated Annual Income"].round(2)
    display_df["Estimated Monthly Income"] = display_df["Estimated Monthly Income"].round(2)
    display_df["Value"] = display_df["Value"].round(2)

    st.dataframe(
        display_df[
            [
                "Ticker",
                "Name",
                "Value",
                "Estimated Yield %",
                "Estimated Annual Income",
                "Estimated Monthly Income",
            ]
        ],
        use_container_width=True,
        height=360,
    )

    chart_df = display_df[display_df["Estimated Annual Income"] > 0].copy()

    if chart_df.empty:
        st.info("No income-producing assets detected with the current estimate map.")
        return

    info_section(
        "Income Chart",
        "Estimated annual income by holding."
    )

    fig = px.bar(
        chart_df.sort_values("Estimated Annual Income", ascending=False),
        x="Ticker",
        y="Estimated Annual Income",
        color="Name",
    )
    fig.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=380,
        margin=dict(t=20, b=20, l=20, r=20),
        showlegend=False,
        xaxis_title="Ticker",
        yaxis_title=f"Estimated Annual Income ({ctx['base_currency']})",
    )
    st.plotly_chart(fig, use_container_width=True)

    monthly_df = pd.DataFrame(
        {
            "Month": [
                "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
            ],
            "Estimated Income": [monthly_income] * 12,
        }
    )

    info_section(
        "Monthly Income View",
        "Simple equalized monthly view of the estimated annual income."
    )

    month_fig = px.line(
        monthly_df,
        x="Month",
        y="Estimated Income",
        markers=True,
    )
    month_fig.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=320,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Month",
        yaxis_title=f"Estimated Income ({ctx['base_currency']})",
        showlegend=False,
    )
    st.plotly_chart(month_fig, use_container_width=True)