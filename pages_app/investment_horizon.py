from app_core import render_page_title, render_investment_horizon_section


def render_investment_horizon_page(ctx):
    render_page_title("Investment Horizon")
    render_investment_horizon_section(
        total_value=ctx["total_portfolio_value"],
        base_currency=ctx["base_currency"],
        portfolio_returns=ctx["portfolio_returns"],
    )