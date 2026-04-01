from app_core import render_page_title, render_investment_horizon_section, render_financial_independence_section
import streamlit as st


def render_investment_horizon_page(ctx):
    render_page_title("Investment Horizon")

    tab1, tab2 = st.tabs(["Projection Scenarios", "Financial Independence"])

    with tab1:
        render_investment_horizon_section(
            total_value=ctx.get("investments_net_worth", ctx["total_portfolio_value"]),
            base_currency=ctx["base_currency"],
            portfolio_returns=ctx["portfolio_returns"],
        )

    with tab2:
        render_financial_independence_section(
            total_value=ctx["total_portfolio_value"],
            base_currency=ctx["base_currency"],
            portfolio_returns=ctx["portfolio_returns"],
            non_portfolio_cash_value=float(ctx.get("non_portfolio_cash_value", 0.0)),
        )
