from app_core import render_page_title, render_status_bar, render_investment_horizon_section


def render_investment_horizon_page(ctx):
    render_page_title("Investment Horizon")

    render_status_bar(
        mode=ctx["mode"],
        base_currency=ctx["base_currency"],
        profile=ctx["profile"],
        tc_model=ctx["tc_model"],
        sheets_ok=(ctx["positions_sheet_available"] if ctx["mode"] == "Private" else True),
    )

    render_investment_horizon_section(
        total_value=ctx["total_value"],
        base_currency=ctx["base_currency"],
        portfolio_returns=ctx["portfolio_returns"],
    )