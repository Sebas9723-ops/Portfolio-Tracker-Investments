import streamlit as st
from app_core import render_page_title, render_investment_horizon_section, render_financial_independence_section


def render_investment_horizon_page(ctx):
    render_page_title("Investment Horizon")

    user_settings = ctx.get("user_settings", {})
    is_private = ctx.get("app_scope") == "private"

    tab1, tab2 = st.tabs(["Projection Scenarios", "Financial Independence"])

    with tab1:
        render_investment_horizon_section(
            total_value=ctx.get("investments_net_worth", ctx["total_portfolio_value"]),
            base_currency=ctx["base_currency"],
            portfolio_returns=ctx["portfolio_returns"],
            default_settings=user_settings,
        )

    with tab2:
        render_financial_independence_section(
            total_value=ctx["total_portfolio_value"],
            base_currency=ctx["base_currency"],
            portfolio_returns=ctx["portfolio_returns"],
            non_portfolio_cash_value=float(ctx.get("non_portfolio_cash_value", 0.0)),
            default_settings=user_settings,
        )

        if is_private:
            st.divider()
            if st.button("💾 Save as Defaults", help="Saves your current inputs so they pre-fill on every future session."):
                from app_core import save_user_settings_to_sheets
                settings_to_save = {
                    "monthly_contribution": float(st.session_state.get("fi_monthly_contribution", 500.0)),
                    "fi_target_withdrawal": float(st.session_state.get("fi_target_withdrawal", 3000.0)),
                    "fi_inflation_pct":     float(st.session_state.get("fi_inflation_pct", 3.0)),
                    "fi_swr_pct":           float(st.session_state.get("fi_swr_pct", 4.0)),
                    "fi_horizon_years":     int(st.session_state.get("fi_horizon_years", 30)),
                }
                try:
                    save_user_settings_to_sheets(settings_to_save)
                    st.cache_data.clear()
                    st.success(
                        f"Defaults saved — Monthly contribution: "
                        f"{ctx['base_currency']} {settings_to_save['monthly_contribution']:,.0f}"
                    )
                except Exception as e:
                    st.error(f"Could not save settings: {e}")
