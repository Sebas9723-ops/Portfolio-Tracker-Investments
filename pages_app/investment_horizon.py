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

        if is_private:
            st.divider()
            if st.button("💾 Save as Defaults", key="ih_save_btn", help="Saves your current inputs so they pre-fill on every future session."):
                from app_core import save_user_settings_to_sheets
                # Merge with existing FI settings so we don't overwrite them
                existing = dict(user_settings) if user_settings else {}
                existing.update({
                    "monthly_contribution":  float(st.session_state.get("ih_monthly_contribution", 0.0)),
                    "ih_annual_return":      float(st.session_state.get("ih_annual_return", 8.0)),
                    "ih_horizon_years":      int(st.session_state.get("ih_horizon_years", 10)),
                    "ih_scenario_spread":    float(st.session_state.get("ih_scenario_spread", 3.0)),
                })
                try:
                    save_user_settings_to_sheets(existing)
                    st.cache_data.clear()
                    st.success(
                        f"Defaults saved — Return: {existing['ih_annual_return']:.1f}%, "
                        f"Horizon: {existing['ih_horizon_years']} yrs, "
                        f"Monthly: {ctx['base_currency']} {existing['monthly_contribution']:,.0f}"
                    )
                except Exception as e:
                    st.error(f"Could not save settings: {e}")

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
            if st.button("💾 Save as Defaults", key="fi_save_btn", help="Saves your current inputs so they pre-fill on every future session."):
                from app_core import save_user_settings_to_sheets
                existing = dict(user_settings) if user_settings else {}
                existing.update({
                    "monthly_contribution": float(st.session_state.get("fi_monthly_contribution", 500.0)),
                    "fi_target_withdrawal": float(st.session_state.get("fi_target_withdrawal", 3000.0)),
                    "fi_inflation_pct":     float(st.session_state.get("fi_inflation_pct", 3.0)),
                    "fi_swr_pct":           float(st.session_state.get("fi_swr_pct", 4.0)),
                    "fi_horizon_years":     int(st.session_state.get("fi_horizon_years", 30)),
                })
                try:
                    save_user_settings_to_sheets(existing)
                    st.cache_data.clear()
                    st.success(
                        f"Defaults saved — Monthly contribution: "
                        f"{ctx['base_currency']} {existing['monthly_contribution']:,.0f}"
                    )
                except Exception as e:
                    st.error(f"Could not save settings: {e}")
