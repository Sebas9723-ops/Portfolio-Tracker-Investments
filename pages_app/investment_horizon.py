import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core import (
    compute_milestone_eta,
    info_section,
    render_financial_independence_section,
    render_investment_horizon_section,
    render_page_title,
    save_user_settings_to_sheets,
    simulate_etf_dilution,
)


def render_investment_horizon_page(ctx):
    render_page_title("Investment Horizon")

    user_settings = ctx.get("user_settings", {})
    is_private = ctx.get("app_scope") == "private"
    ccy = ctx.get("base_currency", "USD")

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Projection Scenarios",
        "Financial Independence",
        "Dilution Simulator",
        "Contribution Settings",
        "Roadmap",
    ])

    # ── Tab 1: Projection Scenarios ───────────────────────────────────────────
    with tab1:
        render_investment_horizon_section(
            total_value=ctx.get("investments_net_worth", ctx["total_portfolio_value"]),
            base_currency=ccy,
            portfolio_returns=ctx["portfolio_returns"],
            default_settings=user_settings,
        )

        if is_private:
            st.divider()
            if st.button("💾 Save as Defaults", key="ih_save_btn"):
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
                        f"Monthly: {ccy} {existing['monthly_contribution']:,.0f}"
                    )
                except Exception as e:
                    st.error(f"Could not save settings: {e}")

    # ── Tab 2: Financial Independence ─────────────────────────────────────────
    with tab2:
        render_financial_independence_section(
            total_value=ctx["total_portfolio_value"],
            base_currency=ccy,
            portfolio_returns=ctx["portfolio_returns"],
            non_portfolio_cash_value=float(ctx.get("non_portfolio_cash_value", 0.0)),
            default_settings=user_settings,
        )

        if is_private:
            st.divider()
            if st.button("💾 Save as Defaults", key="fi_save_btn"):
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
                        f"{ccy} {existing['monthly_contribution']:,.0f}"
                    )
                except Exception as e:
                    st.error(f"Could not save settings: {e}")

    # ── Tab 3: Dilution Simulator ─────────────────────────────────────────────
    with tab3:
        info_section(
            "Contribution Dilution Simulator",
            "Projects how each ETF's weight evolves over time as you contribute monthly and semi-annually "
            "without selling. Cash is deployed to the most underweight ticker (buy-only rebalancing).",
        )

        df = ctx.get("df", pd.DataFrame())
        if df.empty:
            st.info("No portfolio data available.")
        else:
            monthly_default = float(user_settings.get("monthly_contribution", 100.0))
            semi_default = float(user_settings.get("semi_annual_contribution", 500.0))

            c1, c2, c3, c4 = st.columns(4)
            monthly = c1.number_input(f"Monthly contribution ({ccy})", 0.0, 100000.0, monthly_default, 50.0, format="%.0f", key="dil_monthly")
            semi = c2.number_input(f"Semi-annual extra ({ccy})", 0.0, 100000.0, semi_default, 100.0, format="%.0f", key="dil_semi")
            horizon_yrs = c3.number_input("Horizon (years)", 1, 30, 5, 1, key="dil_horizon")
            annual_return = c4.number_input("Expected annual return (%)", 0.0, 30.0, 8.0, 0.5, format="%.1f", key="dil_return") / 100.0

            horizon_months = int(horizon_yrs * 12)
            sim_df = simulate_etf_dilution(df, monthly, semi, horizon_months, annual_return)

            if sim_df.empty:
                st.info("Could not simulate — check portfolio data.")
            else:
                tickers = sim_df["Ticker"].unique().tolist()
                fig = go.Figure()
                for t in tickers:
                    t_data = sim_df[sim_df["Ticker"] == t]
                    fig.add_scatter(
                        x=t_data["Month"],
                        y=t_data["Weight"],
                        mode="lines",
                        name=t,
                        hovertemplate=f"{t}<br>Month %{{x}}: %{{y:.1%}}<extra></extra>",
                    )
                fig.update_layout(
                    paper_bgcolor="#0b0f14", plot_bgcolor="#0b0f14",
                    font=dict(color="#e6e6e6"), height=420,
                    margin=dict(t=20, b=20, l=20, r=20),
                    xaxis_title="Month",
                    yaxis=dict(tickformat=".0%", title="Weight"),
                    legend=dict(orientation="h", y=1.08),
                )
                st.plotly_chart(fig, use_container_width=True, key="dil_weight_chart")

                # Final state summary
                final = sim_df[sim_df["Month"] == horizon_months].copy()
                final_value = float(final["PortfolioValue"].iloc[0]) if not final.empty else 0.0
                st.caption(f"Projected portfolio value after {horizon_yrs} years: **{ccy} {final_value:,.0f}**")
                final["Weight"] = final["Weight"].map(lambda x: f"{x:.1%}")
                st.dataframe(
                    final[["Ticker", "Weight"]].reset_index(drop=True),
                    use_container_width=True,
                    hide_index=True,
                )

    # ── Tab 4: Contribution Settings ──────────────────────────────────────────
    with tab4:
        info_section(
            "Contribution Settings",
            "Configure your regular contributions. These values are used across the app "
            "(Projection Scenarios, Dilution Simulator, Roadmap) and saved to your account.",
        )

        monthly_val = float(user_settings.get("monthly_contribution", 0.0))
        semi_val = float(user_settings.get("semi_annual_contribution", 0.0))

        col1, col2 = st.columns(2)
        monthly_input = col1.number_input(
            f"Monthly contribution ({ccy})",
            min_value=0.0, max_value=100000.0,
            value=monthly_val, step=50.0, format="%.0f",
            key="contrib_monthly_input",
            help="Amount you invest every month.",
        )
        semi_input = col2.number_input(
            f"Semi-annual extra contribution ({ccy})",
            min_value=0.0, max_value=100000.0,
            value=semi_val, step=100.0, format="%.0f",
            key="contrib_semi_input",
            help="Extra lump sum you invest every 6 months.",
        )

        effective_monthly = monthly_input + semi_input / 6.0
        st.caption(f"Effective monthly average: **{ccy} {effective_monthly:,.0f}** (monthly + semi-annual amortized)")

        if is_private:
            if st.button("💾 Save Contribution Settings", key="contrib_save_btn"):
                existing = dict(user_settings) if user_settings else {}
                existing["monthly_contribution"] = monthly_input
                existing["semi_annual_contribution"] = semi_input
                try:
                    save_user_settings_to_sheets(existing)
                    st.cache_data.clear()
                    st.success(f"Saved — Monthly: {ccy} {monthly_input:,.0f} · Semi-annual: {ccy} {semi_input:,.0f}")
                except Exception as e:
                    st.error(f"Could not save: {e}")
        else:
            st.info("Log in to save settings.")

    # ── Tab 5: Roadmap ────────────────────────────────────────────────────────
    with tab5:
        info_section(
            "Roadmap Tracker",
            "Define personal milestones and track your progress. "
            "ETA is estimated based on current contributions and historical return.",
        )

        raw = user_settings.get("roadmap_milestones", "[]")
        try:
            milestones = json.loads(raw) if raw else []
        except Exception:
            milestones = []

        st.markdown("##### Define milestones (up to 5)")
        new_milestones = []
        for i in range(5):
            existing_m = milestones[i] if i < len(milestones) else {}
            col_l, col_t = st.columns([3, 2])
            label = col_l.text_input(
                f"Label {i + 1}", value=existing_m.get("label", ""),
                placeholder=f"e.g. Primer ${(i + 1) * 2000:,}", key=f"rm_label_{i}",
            )
            target = col_t.number_input(
                f"Target {i + 1} ({ccy})", min_value=0.0,
                value=float(existing_m.get("target", 0.0)),
                step=500.0, format="%.0f", key=f"rm_target_{i}",
            )
            if label.strip() and target > 0:
                new_milestones.append({"label": label.strip(), "target": target})

        if is_private:
            if st.button("💾 Save Milestones", key="rm_save_btn"):
                existing = dict(user_settings) if user_settings else {}
                existing["roadmap_milestones"] = json.dumps(new_milestones)
                try:
                    save_user_settings_to_sheets(existing)
                    st.cache_data.clear()
                    st.success("Milestones saved.")
                except Exception as e:
                    st.error(f"Could not save: {e}")

        display_milestones = new_milestones or milestones
        if not display_milestones:
            st.info("Add milestones above to track your progress.")
        else:
            st.divider()
            current_value = float(ctx.get("investments_net_worth", ctx.get("total_portfolio_value", 0.0)))
            monthly_c = float(user_settings.get("monthly_contribution", 0.0))
            semi_c = float(user_settings.get("semi_annual_contribution", 0.0))
            effective_monthly_c = monthly_c + semi_c / 6.0

            portfolio_returns = ctx.get("portfolio_returns", pd.Series(dtype=float))
            if not portfolio_returns.empty and len(portfolio_returns) >= 2:
                ann_return = float((1 + portfolio_returns).prod() ** (252 / len(portfolio_returns)) - 1)
                monthly_ret = float((1 + ann_return) ** (1 / 12) - 1)
            else:
                monthly_ret = 0.0

            for m in display_milestones:
                target = float(m["target"])
                lbl = m["label"]
                pct = min(current_value / target, 1.0) if target > 0 else 0.0
                remaining = max(target - current_value, 0.0)

                st.markdown(f"**{lbl}** — Target: {ccy} {target:,.0f}")
                st.progress(pct, text=f"{pct:.1%} · {ccy} {current_value:,.0f} / {ccy} {target:,.0f}")

                if current_value >= target:
                    st.success("Milestone reached!")
                else:
                    eta = compute_milestone_eta(current_value, target, effective_monthly_c, monthly_ret)
                    if np.isinf(eta) or eta > 1200:
                        st.caption(f"ETA: Increase contributions to reach this target. Still needed: {ccy} {remaining:,.0f}")
                    else:
                        eta_months = int(eta)
                        st.caption(
                            f"ETA: ~{eta_months} months ({eta_months / 12:.1f} years) · "
                            f"Still needed: {ccy} {remaining:,.0f}"
                        )
                st.markdown("")
