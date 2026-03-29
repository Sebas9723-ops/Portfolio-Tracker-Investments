import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core import (
    build_contribution_suggestion,
    build_rebalancing_table,
    info_metric,
    info_section,
    render_page_title,
)


def _severity_rank(level: str) -> int:
    mapping = {"Critical": 0, "Warning": 1, "Info": 2}
    return mapping.get(level, 99)


def _severity_colors(level: str):
    if level == "Critical":
        return "#ef4444", "#2a1113"
    if level == "Warning":
        return "#f3a712", "#21180d"
    return "#60a5fa", "#0e1a29"


def _render_alert_cards(alerts: list[dict]):
    if not alerts:
        st.success("No active alerts. Portfolio is within the configured monitoring rules.")
        return

    st.markdown("")

    for alert in alerts:
        border, bg = _severity_colors(alert["Level"])
        st.markdown(
            f"""
            <div style="
                border:1px solid {border};
                border-left:4px solid {border};
                background:{bg};
                border-radius:6px;
                padding:10px 12px;
                margin-bottom:10px;
            ">
                <div style="font-weight:800; color:{border}; text-transform:uppercase; font-size:13px; letter-spacing:0.4px;">
                    {alert["Level"]} · {alert["Title"]}
                </div>
                <div style="color:#d7dee7; font-size:13px; margin-top:4px; line-height:1.35;">
                    {alert["Detail"]}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _build_phase3_alerts(
    ctx,
    tolerance_pct: float,
    cash_idle_pct: float,
    concentration_pct: float,
):
    alerts = []
    df = ctx["df"].copy()

    if df.empty:
        return alerts

    for _, row in df.iterrows():
        ticker = str(row["Ticker"])
        name = str(row["Name"])
        current_weight = float(row["Weight %"])
        target_weight = float(row["Target %"])
        deviation = float(row["Deviation %"])

        if abs(deviation) > tolerance_pct:
            if deviation > 0:
                title = f"{ticker} is overweight"
                detail = (
                    f"{name} is {deviation:.2f}% above target "
                    f"({current_weight:.2f}% vs {target_weight:.2f}%)."
                )
            else:
                title = f"{ticker} is underweight"
                detail = (
                    f"{name} is {abs(deviation):.2f}% below target "
                    f"({current_weight:.2f}% vs {target_weight:.2f}%)."
                )

            level = "Critical" if abs(deviation) >= tolerance_pct * 1.8 else "Warning"
            alerts.append({"Level": level, "Title": title, "Detail": detail})

        if current_weight > concentration_pct:
            alerts.append(
                {
                    "Level": "Warning",
                    "Title": f"{ticker} concentration risk",
                    "Detail": (
                        f"{name} represents {current_weight:.2f}% of invested assets, "
                        f"above the concentration threshold of {concentration_pct:.2f}%."
                    ),
                }
            )

    total_portfolio_value = float(ctx["total_portfolio_value"])
    cash_total_value = float(ctx["cash_total_value"])
    cash_pct = (cash_total_value / total_portfolio_value * 100) if total_portfolio_value > 0 else 0.0

    if cash_pct > cash_idle_pct:
        alerts.append(
            {
                "Level": "Info" if cash_pct < cash_idle_pct * 1.5 else "Warning",
                "Title": "Idle cash is elevated",
                "Detail": (
                    f"Cash represents {cash_pct:.2f}% of total portfolio value, "
                    f"above the monitoring threshold of {cash_idle_pct:.2f}%."
                ),
            }
        )

    if float(ctx["volatility"]) > 0.20:
        alerts.append(
            {
                "Level": "Info",
                "Title": "Portfolio volatility is elevated",
                "Detail": (
                    f"Annualized volatility is {ctx['volatility']:.2%}. "
                    "Review concentration, target weights and diversification."
                ),
            }
        )

    if float(ctx["max_drawdown"]) < -0.15:
        alerts.append(
            {
                "Level": "Info",
                "Title": "Drawdown monitor triggered",
                "Detail": (
                    f"Observed maximum drawdown is {ctx['max_drawdown']:.2%}. "
                    "Consider whether your current allocation still matches your risk profile."
                ),
            }
        )

    alerts = sorted(alerts, key=lambda x: (_severity_rank(x["Level"]), x["Title"]))
    return alerts


def _build_band_monitor_table(df: pd.DataFrame, tolerance_pct: float, base_currency: str):
    work = df.copy()

    work["Lower Band %"] = work["Target %"] - tolerance_pct
    work["Upper Band %"] = work["Target %"] + tolerance_pct

    def _status(row):
        current = float(row["Weight %"])
        low = float(row["Lower Band %"])
        high = float(row["Upper Band %"])

        if current < low:
            return "Buy / Add"
        if current > high:
            return "Trim / Sell"
        return "Within Band"

    work["Status"] = work.apply(_status, axis=1)

    holdings_total = float(work["Value"].sum())
    work[f"Trade To Target ({base_currency})"] = (
        (work["Target %"] - work["Weight %"]) / 100.0 * holdings_total
    )

    out = work[
        [
            "Ticker",
            "Name",
            "Weight %",
            "Target %",
            "Deviation %",
            "Lower Band %",
            "Upper Band %",
            f"Trade To Target ({base_currency})",
            "Status",
        ]
    ].copy()

    numeric_cols = [
        "Weight %",
        "Target %",
        "Deviation %",
        "Lower Band %",
        "Upper Band %",
        f"Trade To Target ({base_currency})",
    ]
    for col in numeric_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce").round(2)

    out = out.sort_values("Deviation %", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)
    return out


def _build_current_vs_proposed_figure(
    df_current: pd.DataFrame,
    proposed_weight_map: dict[str, float],
):
    tickers = df_current["Ticker"].tolist()
    current_weights = df_current["Weight %"].tolist()
    target_weights = df_current["Target %"].tolist()
    proposed_weights = [float(proposed_weight_map.get(t, 0.0)) for t in tickers]

    fig = go.Figure()
    fig.add_bar(x=tickers, y=current_weights, name="Current %")
    fig.add_bar(x=tickers, y=target_weights, name="Target %")
    fig.add_bar(x=tickers, y=proposed_weights, name="Proposed %")

    fig.update_layout(
        barmode="group",
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=390,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Ticker",
        yaxis_title="Weight %",
    )
    return fig


def _build_contribution_engine(
    ctx,
    contribution_amount: float,
    min_trade_value: float,
):
    suggestion_df = build_contribution_suggestion(ctx["df"], contribution_amount).copy()

    if suggestion_df.empty:
        return suggestion_df, {}, 0.0, 0.0, 0.0

    suggestion_df["Decision"] = np.where(
        suggestion_df["Suggested Buy Value"] >= min_trade_value,
        "Execute",
        "Hold",
    )
    suggestion_df["Executed Buy Value"] = np.where(
        suggestion_df["Decision"] == "Execute",
        suggestion_df["Suggested Buy Value"],
        0.0,
    )
    suggestion_df["Executed Shares"] = np.where(
        suggestion_df["Decision"] == "Execute",
        suggestion_df["Suggested Shares"],
        0.0,
    )

    current_value_map = ctx["df"].set_index("Ticker")["Value"].to_dict()
    target_weight_map = ctx["df"].set_index("Ticker")["Target %"].to_dict()

    proposed_value_map = {}
    for _, row in suggestion_df.iterrows():
        ticker = str(row["Ticker"])
        current_value = float(current_value_map.get(ticker, 0.0))
        proposed_value_map[ticker] = current_value + float(row["Executed Buy Value"])

    executed_total = float(suggestion_df["Executed Buy Value"].sum())
    residual_cash = float(contribution_amount - executed_total)
    proposed_total = float(sum(proposed_value_map.values()))

    proposed_weight_map = {}
    if proposed_total > 0:
        for ticker, value in proposed_value_map.items():
            proposed_weight_map[ticker] = value / proposed_total * 100.0
    else:
        for ticker in current_value_map:
            proposed_weight_map[ticker] = 0.0

    compare_rows = []
    current_abs_gap = 0.0
    proposed_abs_gap = 0.0

    for ticker, current_value in current_value_map.items():
        current_weight = float(ctx["df"].set_index("Ticker").loc[ticker, "Weight %"])
        target_weight = float(target_weight_map.get(ticker, 0.0))
        proposed_weight = float(proposed_weight_map.get(ticker, 0.0))

        current_dev = current_weight - target_weight
        proposed_dev = proposed_weight - target_weight

        current_abs_gap += abs(current_dev)
        proposed_abs_gap += abs(proposed_dev)

        compare_rows.append(
            {
                "Ticker": ticker,
                "Current Weight %": round(current_weight, 2),
                "Target Weight %": round(target_weight, 2),
                "Proposed Weight %": round(proposed_weight, 2),
                "Current Deviation %": round(current_dev, 2),
                "Proposed Deviation %": round(proposed_dev, 2),
            }
        )

    compare_df = pd.DataFrame(compare_rows).sort_values(
        "Current Deviation %",
        key=lambda s: s.abs(),
        ascending=False,
    ).reset_index(drop=True)

    gap_closed_pct = (
        (current_abs_gap - proposed_abs_gap) / current_abs_gap * 100.0
        if current_abs_gap > 0
        else 0.0
    )

    return suggestion_df, proposed_weight_map, executed_total, residual_cash, gap_closed_pct, compare_df


def _build_full_rebalance_engine(
    ctx,
    tolerance_pct: float,
    min_trade_value: float,
    max_cost_pct: float,
    allow_sells: bool,
):
    df = ctx["df"].copy()
    target_weight_map = df.set_index("Ticker")["Target Weight"].to_dict()

    proposal_df = build_rebalancing_table(
        df_current=df,
        target_weight_map=target_weight_map,
        base_currency=ctx["base_currency"],
        tc_model=ctx["tc_model"],
        tc_params=ctx["tc_params"],
    ).copy()

    if proposal_df.empty:
        return proposal_df, {}, 0.0, 0.0, 0.0, 0.0

    current_dev_map = df.set_index("Ticker")["Deviation %"].to_dict()

    proposal_df["Current Deviation %"] = proposal_df["Ticker"].map(current_dev_map).fillna(0.0)
    proposal_df["Abs Trade Value"] = proposal_df["Value Delta"].abs()
    proposal_df["Estimated Cost %"] = np.where(
        proposal_df["Abs Trade Value"] > 0,
        proposal_df["Estimated Cost"] / proposal_df["Abs Trade Value"] * 100.0,
        0.0,
    )

    decisions = []
    reasons = []

    for _, row in proposal_df.iterrows():
        deviation = abs(float(row["Current Deviation %"]))
        trade_value = abs(float(row["Value Delta"]))
        cost_pct = float(row["Estimated Cost %"])
        action = str(row["Action"])

        if action == "Hold":
            decisions.append("Hold")
            reasons.append("Already near target")
        elif deviation <= tolerance_pct:
            decisions.append("Hold")
            reasons.append("Inside tolerance band")
        elif trade_value < min_trade_value:
            decisions.append("Hold")
            reasons.append("Below minimum trade value")
        elif (action == "Sell") and (not allow_sells):
            decisions.append("Skip")
            reasons.append("Sell trades disabled")
        elif cost_pct > max_cost_pct:
            decisions.append("Skip")
            reasons.append("Estimated cost too high")
        else:
            decisions.append("Execute")
            reasons.append("Meets all rebalance rules")

    proposal_df["Decision"] = decisions
    proposal_df["Reason"] = reasons

    current_value_map = df.set_index("Ticker")["Value"].to_dict()
    target_weight_pct_map = df.set_index("Ticker")["Target %"].to_dict()

    proposed_value_map = {}
    for _, row in proposal_df.iterrows():
        ticker = str(row["Ticker"])
        current_value = float(current_value_map.get(ticker, 0.0))
        target_value = float(row["Target Value"])

        if row["Decision"] == "Execute":
            proposed_value_map[ticker] = target_value
        else:
            proposed_value_map[ticker] = current_value

    proposed_total = float(sum(proposed_value_map.values()))
    proposed_weight_map = {}

    if proposed_total > 0:
        for ticker, value in proposed_value_map.items():
            proposed_weight_map[ticker] = value / proposed_total * 100.0
    else:
        for ticker in current_value_map:
            proposed_weight_map[ticker] = 0.0

    proposal_df["Proposed Weight %"] = proposal_df["Ticker"].map(proposed_weight_map).fillna(0.0)
    proposal_df["Target Weight %"] = proposal_df["Ticker"].map(target_weight_pct_map).fillna(0.0)
    proposal_df["Post-Trade Deviation %"] = proposal_df["Proposed Weight %"] - proposal_df["Target Weight %"]

    executed_df = proposal_df[proposal_df["Decision"] == "Execute"].copy()
    turnover = (
        float(executed_df["Abs Trade Value"].sum()) / float(df["Value"].sum()) * 100.0
        if float(df["Value"].sum()) > 0
        else 0.0
    )
    total_cost = float(executed_df["Estimated Cost"].sum())
    net_cash_flow = float(executed_df["Net Cash Flow"].sum())

    current_abs_gap = float(df["Deviation %"].abs().sum())
    proposed_abs_gap = float(proposal_df["Post-Trade Deviation %"].abs().sum())
    gap_closed_pct = (
        (current_abs_gap - proposed_abs_gap) / current_abs_gap * 100.0
        if current_abs_gap > 0
        else 0.0
    )

    proposal_df = proposal_df[
        [
            "Ticker",
            "Action",
            "Decision",
            "Reason",
            "Current Weight %",
            "Target Weight %",
            "Current Deviation %",
            "Post-Trade Deviation %",
            "Current Value",
            "Target Value",
            "Value Delta",
            "Estimated Cost",
            "Estimated Cost %",
            "Net Cash Flow",
            "Current Shares",
            "Target Shares",
            "Shares Delta",
        ]
    ].copy()

    numeric_cols = [
        "Current Weight %",
        "Target Weight %",
        "Current Deviation %",
        "Post-Trade Deviation %",
        "Current Value",
        "Target Value",
        "Value Delta",
        "Estimated Cost",
        "Estimated Cost %",
        "Net Cash Flow",
        "Current Shares",
        "Target Shares",
        "Shares Delta",
    ]
    for col in numeric_cols:
        proposal_df[col] = pd.to_numeric(proposal_df[col], errors="coerce").round(4 if "Shares" in col else 2)

    return proposal_df, proposed_weight_map, turnover, total_cost, net_cash_flow, gap_closed_pct


def render_rebalancing_page(ctx):
    render_page_title("Rebalance Center")

    if ctx["df"].empty:
        st.info("No portfolio data available.")
        return

    info_section(
        "Phase 3 Control Center",
        "Monitor deviations, generate contribution plans, compare current versus proposed portfolios, and apply rebalance rules before acting manually in your broker."
    )

    c1, c2, c3 = st.columns(3)
    tolerance_pct = c1.number_input(
        "Tolerance Band (%)",
        min_value=0.5,
        max_value=15.0,
        value=3.0,
        step=0.5,
    )
    min_trade_value = c2.number_input(
        f"Minimum Trade Value ({ctx['base_currency']})",
        min_value=0.0,
        value=250.0,
        step=50.0,
    )
    max_cost_pct = c3.number_input(
        "Max Cost / Trade (%)",
        min_value=0.1,
        max_value=10.0,
        value=2.0,
        step=0.1,
    )

    c4, c5, c6 = st.columns(3)
    cash_idle_pct = c4.number_input(
        "Cash Idle Alert (%)",
        min_value=1.0,
        max_value=50.0,
        value=8.0,
        step=1.0,
    )
    concentration_pct = c5.number_input(
        "Concentration Alert (%)",
        min_value=5.0,
        max_value=100.0,
        value=35.0,
        step=1.0,
    )
    allow_sells = c6.checkbox("Allow Sell Trades In Proposal", value=True)

    alerts = _build_phase3_alerts(
        ctx=ctx,
        tolerance_pct=float(tolerance_pct),
        cash_idle_pct=float(cash_idle_pct),
        concentration_pct=float(concentration_pct),
    )

    info_section(
        "Alerts Engine",
        "Automatic alerts based on tolerance bands, concentration, cash drag and high-level risk conditions."
    )
    _render_alert_cards(alerts)

    band_df = _build_band_monitor_table(
        df=ctx["df"],
        tolerance_pct=float(tolerance_pct),
        base_currency=ctx["base_currency"],
    )

    out_of_band_count = int((band_df["Status"] != "Within Band").sum())
    max_dev = float(band_df["Deviation %"].abs().max()) if not band_df.empty else 0.0
    cash_pct = (
        float(ctx["cash_total_value"]) / float(ctx["total_portfolio_value"]) * 100.0
        if float(ctx["total_portfolio_value"]) > 0
        else 0.0
    )

    m1, m2, m3 = st.columns(3)
    info_metric(
        m1,
        "Alerts",
        str(len(alerts)),
        "Number of active portfolio monitoring alerts.",
    )
    info_metric(
        m2,
        "Out Of Band Positions",
        str(out_of_band_count),
        "Positions currently outside the configured tolerance band.",
    )
    info_metric(
        m3,
        "Max Deviation",
        f"{max_dev:.2f}%",
        "Largest absolute deviation versus target weight.",
    )

    m4, m5, m6 = st.columns(3)
    info_metric(
        m4,
        "Cash Ratio",
        f"{cash_pct:.2f}%",
        "Cash as a percentage of total portfolio value.",
    )
    info_metric(
        m5,
        "Current Return",
        f"{ctx['total_return']:.2%}",
        "Cumulative portfolio return over the available sample.",
    )
    info_metric(
        m6,
        "Current Sharpe",
        f"{ctx['sharpe']:.2f}",
        "Current portfolio Sharpe ratio.",
    )

    info_section(
        "Tolerance Monitor",
        "Current weights, target weights, tolerance bands and estimated value needed to move each position back to target."
    )
    st.dataframe(band_df, use_container_width=True, height=360)

    st.markdown("---")

    info_section(
        "Contribution Engine",
        "Allocate new cash without necessarily selling. This is the preferred low-friction method to reduce deviations."
    )

    contribution_amount = st.number_input(
        f"New Contribution Amount ({ctx['base_currency']})",
        min_value=0.0,
        value=0.0,
        step=100.0,
    )

    contribution_df, contribution_weight_map, executed_total, residual_cash, contribution_gap_closed, contribution_compare_df = _build_contribution_engine(
        ctx=ctx,
        contribution_amount=float(contribution_amount),
        min_trade_value=float(min_trade_value),
    )

    if contribution_amount <= 0:
        st.info("Enter a positive contribution amount to generate a contribution plan.")
    else:
        c1, c2, c3 = st.columns(3)
        info_metric(
            c1,
            "Executed Contribution",
            f"{ctx['base_currency']} {executed_total:,.2f}",
            "Amount effectively allocated after applying minimum trade rules.",
        )
        info_metric(
            c2,
            "Residual Cash",
            f"{ctx['base_currency']} {residual_cash:,.2f}",
            "Contribution amount left unallocated because proposed trades were below the minimum trade value.",
        )
        info_metric(
            c3,
            "Gap Closed",
            f"{contribution_gap_closed:.2f}%",
            "Reduction in total absolute deviation achieved by the contribution plan.",
        )

        contribution_display = contribution_df.copy()
        if not contribution_display.empty:
            contribution_display["Suggested Buy Value"] = pd.to_numeric(contribution_display["Suggested Buy Value"], errors="coerce").round(2)
            contribution_display["Executed Buy Value"] = pd.to_numeric(contribution_display["Executed Buy Value"], errors="coerce").round(2)
            contribution_display["Price"] = pd.to_numeric(contribution_display["Price"], errors="coerce").round(2)
            contribution_display["Suggested Shares"] = pd.to_numeric(contribution_display["Suggested Shares"], errors="coerce").round(4)
            contribution_display["Executed Shares"] = pd.to_numeric(contribution_display["Executed Shares"], errors="coerce").round(4)

            st.dataframe(
                contribution_display[
                    [
                        "Ticker",
                        "Name",
                        "Current Value",
                        "Target Value After Contribution",
                        "Suggested Buy Value",
                        "Executed Buy Value",
                        "Price",
                        "Suggested Shares",
                        "Executed Shares",
                        "Decision",
                    ]
                ],
                use_container_width=True,
                height=320,
            )

            fig_contribution_compare = _build_current_vs_proposed_figure(
                df_current=ctx["df"],
                proposed_weight_map=contribution_weight_map,
            )
            st.plotly_chart(fig_contribution_compare, use_container_width=True)

            st.dataframe(contribution_compare_df, use_container_width=True, height=260)

    st.markdown("---")

    info_section(
        "Full Rebalance Proposal",
        "Generate a target-based rebalance plan using your transaction cost model and rule filters."
    )

    full_proposal_df, proposed_weight_map, turnover, total_cost, net_cash_flow, rebalance_gap_closed = _build_full_rebalance_engine(
        ctx=ctx,
        tolerance_pct=float(tolerance_pct),
        min_trade_value=float(min_trade_value),
        max_cost_pct=float(max_cost_pct),
        allow_sells=bool(allow_sells),
    )

    p1, p2, p3, p4 = st.columns(4)
    info_metric(
        p1,
        "Turnover",
        f"{turnover:.2f}%",
        "Executed trade value divided by current invested holdings value.",
    )
    info_metric(
        p2,
        "Estimated Cost",
        f"{ctx['base_currency']} {total_cost:,.2f}",
        "Total estimated transaction cost for trades marked Execute.",
    )
    info_metric(
        p3,
        "Net Cash Flow",
        f"{ctx['base_currency']} {net_cash_flow:,.2f}",
        "Positive means the proposal would release cash. Negative means it would consume cash.",
    )
    info_metric(
        p4,
        "Gap Closed",
        f"{rebalance_gap_closed:.2f}%",
        "Reduction in total absolute deviation achieved by the executable rebalance proposal.",
    )

    st.dataframe(full_proposal_df, use_container_width=True, height=360)

    fig_rebalance_compare = _build_current_vs_proposed_figure(
        df_current=ctx["df"],
        proposed_weight_map=proposed_weight_map,
    )
    st.plotly_chart(fig_rebalance_compare, use_container_width=True)

    info_section(
        "Execution Summary",
        "Manual order checklist generated from the proposal. Use this to place orders manually in your broker."
    )

    execute_df = full_proposal_df[full_proposal_df["Decision"] == "Execute"].copy()

    if execute_df.empty:
        st.info("No trades qualified for execution under the current rules.")
    else:
        order_rows = []
        for _, row in execute_df.iterrows():
            ticker = str(row["Ticker"])
            action = str(row["Action"])
            shares_delta = float(row["Shares Delta"])
            abs_shares = abs(shares_delta)

            order_rows.append(
                {
                    "Ticker": ticker,
                    "Order Side": "BUY" if action == "Buy" else "SELL",
                    "Suggested Shares": round(abs_shares, 4),
                    "Estimated Trade Value": round(abs(float(row["Value Delta"])), 2),
                    "Estimated Cost": round(float(row["Estimated Cost"]), 2),
                }
            )

        orders_df = pd.DataFrame(order_rows)
        st.dataframe(orders_df, use_container_width=True, height=240)