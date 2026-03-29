import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core import (
    build_rebalancing_table,
    info_metric,
    info_section,
    render_page_title,
)


def _normalize_weight_map(weight_map: dict[str, float], tickers: list[str]) -> dict[str, float]:
    clean = {t: max(float(weight_map.get(t, 0.0)), 0.0) for t in tickers}
    total = float(sum(clean.values()))
    if total <= 0:
        equal = 1.0 / len(tickers) if tickers else 0.0
        return {t: equal for t in tickers}
    return {t: v / total for t, v in clean.items()}


def _available_models(ctx) -> list[str]:
    models = ["Strategic Target"]
    if ctx.get("max_sharpe_row") is not None and ctx.get("usable"):
        models.append("Max Sharpe Frontier")
    if ctx.get("min_vol_row") is not None and ctx.get("usable"):
        models.append("Min Volatility Frontier")
    return models


def _recommended_weight_map(ctx, df: pd.DataFrame, model_name: str) -> dict[str, float]:
    tickers = df["Ticker"].tolist()

    if model_name == "Strategic Target":
        raw = df.set_index("Ticker")["Target Weight"].to_dict()
        return _normalize_weight_map(raw, tickers)

    usable = list(ctx.get("usable", []))
    if not usable:
        raw = df.set_index("Ticker")["Target Weight"].to_dict()
        return _normalize_weight_map(raw, tickers)

    if model_name == "Max Sharpe Frontier" and ctx.get("max_sharpe_row") is not None:
        arr = np.array(ctx["max_sharpe_row"]["Weights"], dtype=float)
        if len(arr) == len(usable):
            raw = {ticker: float(weight) for ticker, weight in zip(usable, arr)}
            return _normalize_weight_map(raw, tickers)

    if model_name == "Min Volatility Frontier" and ctx.get("min_vol_row") is not None:
        arr = np.array(ctx["min_vol_row"]["Weights"], dtype=float)
        if len(arr) == len(usable):
            raw = {ticker: float(weight) for ticker, weight in zip(usable, arr)}
            return _normalize_weight_map(raw, tickers)

    raw = df.set_index("Ticker")["Target Weight"].to_dict()
    return _normalize_weight_map(raw, tickers)


def _portfolio_stats_from_weight_map(ctx, recommended_map: dict[str, float]) -> dict[str, float]:
    asset_returns = ctx.get("asset_returns")
    if asset_returns is None or asset_returns.empty:
        return {"return": 0.0, "volatility": 0.0, "sharpe": 0.0}

    usable = [c for c in asset_returns.columns if c in recommended_map]
    if len(usable) < 2:
        return {"return": 0.0, "volatility": 0.0, "sharpe": 0.0}

    weights = np.array([float(recommended_map.get(t, 0.0)) for t in usable], dtype=float)
    total = float(weights.sum())
    if total <= 0:
        return {"return": 0.0, "volatility": 0.0, "sharpe": 0.0}

    weights = weights / total
    mean_returns = asset_returns[usable].mean() * 252
    cov_matrix = asset_returns[usable].cov() * 252

    exp_return = float(weights @ mean_returns.values)
    exp_vol = float(np.sqrt(weights @ cov_matrix.values @ weights.T))
    rf = float(ctx.get("risk_free_rate", 0.0))
    exp_sharpe = float((exp_return - rf) / exp_vol) if exp_vol > 0 else 0.0

    return {"return": exp_return, "volatility": exp_vol, "sharpe": exp_sharpe}


def _build_monitor_table(
    df: pd.DataFrame,
    recommended_map: dict[str, float],
    tolerance_pct: float,
    base_currency: str,
) -> pd.DataFrame:
    work = df.copy()
    holdings_total = float(work["Value"].sum()) if not work.empty else 0.0

    work["Recommended Weight %"] = work["Ticker"].map(
        lambda t: float(recommended_map.get(str(t), 0.0)) * 100.0
    )
    work["Gap %"] = work["Weight %"] - work["Recommended Weight %"]
    work["Lower Band %"] = work["Recommended Weight %"] - tolerance_pct
    work["Upper Band %"] = work["Recommended Weight %"] + tolerance_pct

    def _action(row):
        current_weight = float(row["Weight %"])
        lower_band = float(row["Lower Band %"])
        upper_band = float(row["Upper Band %"])
        if current_weight > upper_band:
            return "Trim / Sell"
        if current_weight < lower_band:
            return "Buy / Add"
        return "Within Band"

    work["Action"] = work.apply(_action, axis=1)

    if holdings_total > 0:
        work[f"Trade To Recommended ({base_currency})"] = (
            (work["Recommended Weight %"] - work["Weight %"]) / 100.0 * holdings_total
        )
    else:
        work[f"Trade To Recommended ({base_currency})"] = 0.0

    out = work[
        [
            "Ticker",
            "Name",
            "Weight %",
            "Target %",
            "Recommended Weight %",
            "Gap %",
            "Lower Band %",
            "Upper Band %",
            f"Trade To Recommended ({base_currency})",
            "Action",
        ]
    ].copy()

    for col in [
        "Weight %",
        "Target %",
        "Recommended Weight %",
        "Gap %",
        "Lower Band %",
        "Upper Band %",
        f"Trade To Recommended ({base_currency})",
    ]:
        out[col] = pd.to_numeric(out[col], errors="coerce").round(2)

    out = out.sort_values("Gap %", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)
    return out


def _build_alerts(
    ctx,
    monitor_df: pd.DataFrame,
    concentration_alert_pct: float,
    cash_alert_pct: float,
) -> list[dict]:
    alerts = []

    if monitor_df.empty:
        return alerts

    for _, row in monitor_df.iterrows():
        ticker = str(row["Ticker"])
        name = str(row["Name"])
        gap_pct = float(row["Gap %"])
        current_weight = float(row["Weight %"])
        recommended_weight = float(row["Recommended Weight %"])
        action = str(row["Action"])

        if action != "Within Band":
            level = "Critical" if abs(gap_pct) >= 6.0 else "Warning"
            alerts.append(
                {
                    "level": level,
                    "title": f"{ticker} requires action",
                    "detail": (
                        f"{name} is at {current_weight:.2f}% versus a recommended weight of "
                        f"{recommended_weight:.2f}%. Gap: {gap_pct:+.2f}%."
                    ),
                }
            )

        if current_weight > concentration_alert_pct:
            alerts.append(
                {
                    "level": "Warning",
                    "title": f"{ticker} concentration risk",
                    "detail": (
                        f"{name} represents {current_weight:.2f}% of holdings, above the "
                        f"concentration threshold of {concentration_alert_pct:.2f}%."
                    ),
                }
            )

    total_portfolio_value = float(ctx["total_portfolio_value"])
    cash_total_value = float(ctx["cash_total_value"])
    cash_pct = (cash_total_value / total_portfolio_value * 100.0) if total_portfolio_value > 0 else 0.0

    if cash_pct > cash_alert_pct:
        alerts.append(
            {
                "level": "Info" if cash_pct < cash_alert_pct * 1.5 else "Warning",
                "title": "Idle cash is elevated",
                "detail": (
                    f"Cash is {cash_pct:.2f}% of total portfolio value, above the "
                    f"monitoring threshold of {cash_alert_pct:.2f}%."
                ),
            }
        )

    if float(ctx["max_drawdown"]) < -0.15:
        alerts.append(
            {
                "level": "Info",
                "title": "Drawdown monitor triggered",
                "detail": f"Observed maximum drawdown is {ctx['max_drawdown']:.2%}.",
            }
        )

    if float(ctx["volatility"]) > 0.20:
        alerts.append(
            {
                "level": "Info",
                "title": "Volatility is elevated",
                "detail": f"Current annualized volatility is {ctx['volatility']:.2%}.",
            }
        )

    order = {"Critical": 0, "Warning": 1, "Info": 2}
    return sorted(alerts, key=lambda x: (order.get(x["level"], 9), x["title"]))


def _render_alert_cards(alerts: list[dict]):
    if not alerts:
        st.success("No active alerts. The portfolio is within the configured monitoring thresholds.")
        return

    color_map = {
        "Critical": ("#ef4444", "#2a1113"),
        "Warning": ("#f3a712", "#21180d"),
        "Info": ("#60a5fa", "#0e1a29"),
    }

    for alert in alerts:
        border, bg = color_map.get(alert["level"], ("#60a5fa", "#0e1a29"))
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
                    {alert["level"]} · {alert["title"]}
                </div>
                <div style="color:#d7dee7; font-size:13px; margin-top:4px; line-height:1.35;">
                    {alert["detail"]}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _build_compare_figure(
    df: pd.DataFrame,
    recommended_map: dict[str, float],
    proposed_weight_map: dict[str, float] | None = None,
) -> go.Figure:
    tickers = df["Ticker"].tolist()
    current_weights = df["Weight %"].tolist()
    policy_targets = df["Target %"].tolist()
    recommended_weights = [float(recommended_map.get(t, 0.0)) * 100.0 for t in tickers]

    fig = go.Figure()
    fig.add_bar(x=tickers, y=current_weights, name="Current Weight %")
    fig.add_bar(x=tickers, y=policy_targets, name="Policy Target %")
    fig.add_bar(x=tickers, y=recommended_weights, name="Recommended Weight %")

    if proposed_weight_map is not None:
        proposed_weights = [float(proposed_weight_map.get(t, 0.0)) * 100.0 for t in tickers]
        fig.add_bar(x=tickers, y=proposed_weights, name="Proposed Weight %")

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


def _build_trade_proposal(
    ctx,
    recommended_map: dict[str, float],
    tolerance_pct: float,
    min_trade_value: float,
    max_cost_pct: float,
    allow_sells: bool,
):
    df = ctx["df"].copy()

    proposal = build_rebalancing_table(
        df_current=df,
        target_weight_map=recommended_map,
        base_currency=ctx["base_currency"],
        tc_model=ctx["tc_model"],
        tc_params=ctx["tc_params"],
    ).copy()

    if proposal.empty:
        return proposal, {}, 0.0, 0.0, 0.0, 0.0, 0

    current_gap_map = (
        df.assign(_recommended=df["Ticker"].map(lambda t: float(recommended_map.get(t, 0.0)) * 100.0))
        .assign(_gap=lambda x: x["Weight %"] - x["_recommended"])
        .set_index("Ticker")["_gap"]
        .to_dict()
    )

    current_value_map = df.set_index("Ticker")["Value"].to_dict()

    proposal["Current Gap %"] = proposal["Ticker"].map(current_gap_map).fillna(0.0)
    proposal["Abs Trade Value"] = proposal["Value Delta"].abs()
    proposal["Estimated Cost %"] = np.where(
        proposal["Abs Trade Value"] > 0,
        proposal["Estimated Cost"] / proposal["Abs Trade Value"] * 100.0,
        0.0,
    )

    decisions = []
    reasons = []

    for _, row in proposal.iterrows():
        action = str(row["Action"])
        gap_pct = abs(float(row["Current Gap %"]))
        trade_value = abs(float(row["Value Delta"]))
        cost_pct = float(row["Estimated Cost %"])

        if action == "Hold":
            decisions.append("Hold")
            reasons.append("Already near recommended weight")
        elif gap_pct <= tolerance_pct:
            decisions.append("Hold")
            reasons.append("Inside tolerance band")
        elif trade_value < min_trade_value:
            decisions.append("Hold")
            reasons.append("Below minimum trade value")
        elif action == "Sell" and not allow_sells:
            decisions.append("Skip")
            reasons.append("Sell trades disabled")
        elif cost_pct > max_cost_pct:
            decisions.append("Skip")
            reasons.append("Estimated cost too high")
        else:
            decisions.append("Execute")
            reasons.append("Approved by rebalance rules")

    proposal["Decision"] = decisions
    proposal["Reason"] = reasons

    proposed_value_map = {}
    for _, row in proposal.iterrows():
        ticker = str(row["Ticker"])
        current_value = float(current_value_map.get(ticker, 0.0))
        value_delta = float(row["Value Delta"])
        if row["Decision"] == "Execute":
            proposed_value_map[ticker] = max(current_value + value_delta, 0.0)
        else:
            proposed_value_map[ticker] = current_value

    total_proposed = float(sum(proposed_value_map.values()))
    proposed_weight_map = {}
    if total_proposed > 0:
        for ticker, value in proposed_value_map.items():
            proposed_weight_map[ticker] = value / total_proposed
    else:
        for ticker in current_value_map:
            proposed_weight_map[ticker] = 0.0

    proposal["Proposed Weight %"] = proposal["Ticker"].map(lambda t: float(proposed_weight_map.get(t, 0.0)) * 100.0)
    proposal["Recommended Weight %"] = proposal["Ticker"].map(lambda t: float(recommended_map.get(t, 0.0)) * 100.0)
    proposal["Post-Trade Gap %"] = proposal["Proposed Weight %"] - proposal["Recommended Weight %"]

    execute_df = proposal[proposal["Decision"] == "Execute"].copy()
    turnover = (
        float(execute_df["Abs Trade Value"].sum()) / float(df["Value"].sum()) * 100.0
        if float(df["Value"].sum()) > 0
        else 0.0
    )
    total_cost = float(execute_df["Estimated Cost"].sum())
    net_cash_flow = float(execute_df["Net Cash Flow"].sum())
    trade_count = int(len(execute_df))

    current_abs_gap = float(np.abs(df["Weight %"] - df["Ticker"].map(lambda t: float(recommended_map.get(t, 0.0)) * 100.0)).sum())
    proposed_abs_gap = float(np.abs(proposal["Post-Trade Gap %"]).sum())
    gap_closed_pct = (
        (current_abs_gap - proposed_abs_gap) / current_abs_gap * 100.0
        if current_abs_gap > 0
        else 0.0
    )

    keep_cols = [
        "Ticker",
        "Action",
        "Decision",
        "Reason",
        "Current Weight %",
        "Recommended Weight %",
        "Current Gap %",
        "Proposed Weight %",
        "Post-Trade Gap %",
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
    proposal = proposal[keep_cols].copy()

    for col in [
        "Current Weight %",
        "Recommended Weight %",
        "Current Gap %",
        "Proposed Weight %",
        "Post-Trade Gap %",
        "Current Value",
        "Target Value",
        "Value Delta",
        "Estimated Cost",
        "Estimated Cost %",
        "Net Cash Flow",
    ]:
        proposal[col] = pd.to_numeric(proposal[col], errors="coerce").round(2)

    for col in ["Current Shares", "Target Shares", "Shares Delta"]:
        proposal[col] = pd.to_numeric(proposal[col], errors="coerce").round(4)

    return proposal, proposed_weight_map, turnover, total_cost, net_cash_flow, gap_closed_pct, trade_count


def _estimate_contribution_needed_without_selling(
    df: pd.DataFrame,
    recommended_map: dict[str, float],
) -> tuple[float | None, str]:
    if df.empty:
        return 0.0, "No holdings data."

    total_current = float(df["Value"].sum())
    required_contribution = 0.0

    for _, row in df.iterrows():
        ticker = str(row["Ticker"])
        current_value = float(row["Value"])
        recommended_weight = float(recommended_map.get(ticker, 0.0))

        if current_value <= 1e-12:
            continue

        if recommended_weight <= 1e-12:
            return None, f"{ticker} has a positive current value but a zero recommended weight."

        contribution_for_ticker = current_value / recommended_weight - total_current
        required_contribution = max(required_contribution, contribution_for_ticker)

    return max(required_contribution, 0.0), ""


def _build_contribution_plan(
    ctx,
    recommended_map: dict[str, float],
    contribution_amount: float,
    min_trade_value: float,
    allow_sells: bool,
):
    df = ctx["df"].copy()

    if contribution_amount <= 0 or df.empty:
        return pd.DataFrame(), {}, 0.0, 0.0, 0.0, 0.0, "-"

    current_value_map = df.set_index("Ticker")["Value"].to_dict()
    current_price_map = df.set_index("Ticker")["Price"].to_dict()
    current_weight_map = df.set_index("Ticker")["Weight %"].to_dict()
    name_map = df.set_index("Ticker")["Name"].to_dict()

    total_current = float(df["Value"].sum())
    total_after = total_current + float(contribution_amount)

    rows = []

    if allow_sells:
        for ticker in df["Ticker"].tolist():
            current_value = float(current_value_map.get(ticker, 0.0))
            recommended_weight = float(recommended_map.get(ticker, 0.0))
            target_value_after = recommended_weight * total_after
            trade_value = target_value_after - current_value
            price = float(current_price_map.get(ticker, 0.0))
            trade_shares = abs(trade_value) / price if price > 0 else 0.0

            if abs(trade_value) < 1e-9:
                action = "Hold"
            elif trade_value > 0:
                action = "Buy"
            else:
                action = "Sell"

            decision = "Execute" if (abs(trade_value) >= min_trade_value and action != "Hold") else "Hold"

            executed_trade_value = trade_value if decision == "Execute" else 0.0
            proposed_value = current_value + executed_trade_value

            rows.append(
                {
                    "Ticker": ticker,
                    "Name": str(name_map.get(ticker, ticker)),
                    "Current Weight %": float(current_weight_map.get(ticker, 0.0)),
                    "Recommended Weight %": recommended_weight * 100.0,
                    "Current Value": current_value,
                    "Target Value After Contribution": target_value_after,
                    "Action": action,
                    "Trade Value": trade_value,
                    "Executed Trade Value": executed_trade_value,
                    "Reference Price": price,
                    "Trade Shares": trade_shares if decision == "Execute" else 0.0,
                    "Decision": decision,
                    "Proposed Value": proposed_value,
                }
            )

    else:
        positive_gap_total = 0.0
        temp_rows = []

        for ticker in df["Ticker"].tolist():
            current_value = float(current_value_map.get(ticker, 0.0))
            recommended_weight = float(recommended_map.get(ticker, 0.0))
            target_value_after = recommended_weight * total_after
            positive_gap = max(target_value_after - current_value, 0.0)

            temp_rows.append(
                {
                    "Ticker": ticker,
                    "Name": str(name_map.get(ticker, ticker)),
                    "Current Weight %": float(current_weight_map.get(ticker, 0.0)),
                    "Recommended Weight %": recommended_weight * 100.0,
                    "Current Value": current_value,
                    "Target Value After Contribution": target_value_after,
                    "Positive Gap": positive_gap,
                    "Reference Price": float(current_price_map.get(ticker, 0.0)),
                }
            )
            positive_gap_total += positive_gap

        for row in temp_rows:
            if positive_gap_total > 0:
                suggested_buy_value = contribution_amount * float(row["Positive Gap"]) / positive_gap_total
            else:
                suggested_buy_value = contribution_amount * float(row["Recommended Weight %"]) / 100.0

            action = "Buy" if suggested_buy_value > 1e-9 else "Hold"
            decision = "Execute" if (suggested_buy_value >= min_trade_value and action != "Hold") else "Hold"
            executed_trade_value = suggested_buy_value if decision == "Execute" else 0.0
            proposed_value = float(row["Current Value"]) + executed_trade_value
            price = float(row["Reference Price"])
            trade_shares = executed_trade_value / price if price > 0 else 0.0

            rows.append(
                {
                    "Ticker": row["Ticker"],
                    "Name": row["Name"],
                    "Current Weight %": row["Current Weight %"],
                    "Recommended Weight %": row["Recommended Weight %"],
                    "Current Value": row["Current Value"],
                    "Target Value After Contribution": row["Target Value After Contribution"],
                    "Action": action,
                    "Trade Value": suggested_buy_value,
                    "Executed Trade Value": executed_trade_value,
                    "Reference Price": price,
                    "Trade Shares": trade_shares,
                    "Decision": decision,
                    "Proposed Value": proposed_value,
                }
            )

    plan_df = pd.DataFrame(rows)

    total_proposed = float(plan_df["Proposed Value"].sum())
    proposed_weight_map = {}
    if total_proposed > 0:
        for _, row in plan_df.iterrows():
            proposed_weight_map[str(row["Ticker"])] = float(row["Proposed Value"]) / total_proposed
    else:
        for ticker in df["Ticker"].tolist():
            proposed_weight_map[ticker] = 0.0

    plan_df["Proposed Weight %"] = plan_df["Ticker"].map(
        lambda t: float(proposed_weight_map.get(t, 0.0)) * 100.0
    )
    plan_df["Post-Plan Gap %"] = plan_df["Proposed Weight %"] - plan_df["Recommended Weight %"]

    buy_value = float(plan_df.loc[plan_df["Executed Trade Value"] > 0, "Executed Trade Value"].sum())
    sell_value = float(abs(plan_df.loc[plan_df["Executed Trade Value"] < 0, "Executed Trade Value"].sum()))
    net_external_contribution = buy_value - sell_value
    residual_contribution = float(contribution_amount - net_external_contribution)

    current_abs_gap = float(np.abs(df["Weight %"] - df["Ticker"].map(lambda t: float(recommended_map.get(t, 0.0)) * 100.0)).sum())
    proposed_abs_gap = float(np.abs(plan_df["Post-Plan Gap %"]).sum())
    gap_closed_pct = (
        (current_abs_gap - proposed_abs_gap) / current_abs_gap * 100.0
        if current_abs_gap > 0
        else 0.0
    )

    top_priority = "-"
    execute_df = plan_df[plan_df["Decision"] == "Execute"].copy()
    if not execute_df.empty:
        top_priority = str(execute_df.iloc[0]["Ticker"])

    plan_df = plan_df[
        [
            "Ticker",
            "Name",
            "Action",
            "Decision",
            "Current Weight %",
            "Recommended Weight %",
            "Current Value",
            "Target Value After Contribution",
            "Trade Value",
            "Executed Trade Value",
            "Reference Price",
            "Trade Shares",
            "Proposed Weight %",
            "Post-Plan Gap %",
        ]
    ].copy()

    for col in [
        "Current Weight %",
        "Recommended Weight %",
        "Current Value",
        "Target Value After Contribution",
        "Trade Value",
        "Executed Trade Value",
        "Reference Price",
        "Proposed Weight %",
        "Post-Plan Gap %",
    ]:
        plan_df[col] = pd.to_numeric(plan_df[col], errors="coerce").round(2)

    plan_df["Trade Shares"] = pd.to_numeric(plan_df["Trade Shares"], errors="coerce").round(4)
    plan_df = plan_df.sort_values("Executed Trade Value", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)

    return (
        plan_df,
        proposed_weight_map,
        buy_value,
        sell_value,
        residual_contribution,
        gap_closed_pct,
        top_priority,
    )


def _render_manual_orders(title: str, df_orders: pd.DataFrame):
    info_section(title, "Manual order checklist to place trades in your broker.")

    if df_orders.empty:
        st.info("No trades qualified for execution under the current rules.")
        return

    st.dataframe(df_orders, use_container_width=True, height=240)


def render_rebalancing_page(ctx):
    render_page_title("Rebalance Center")

    if ctx["df"].empty:
        st.info("No portfolio data available.")
        return

    info_section(
        "Professional Rebalance Engine",
        "This page combines diagnostics, efficient-frontier recommendations, contribution planning, and trade proposal logic in a single professional workflow."
    )

    models = _available_models(ctx)
    default_model_index = models.index("Max Sharpe Frontier") if "Max Sharpe Frontier" in models else 0

    c1, c2, c3 = st.columns(3)
    model_name = c1.selectbox("Recommendation Model", models, index=default_model_index)
    tolerance_pct = c2.number_input("Tolerance Band (%)", min_value=0.5, max_value=15.0, value=3.0, step=0.5)
    concentration_alert_pct = c3.number_input("Concentration Alert (%)", min_value=5.0, max_value=100.0, value=35.0, step=1.0)

    c4, c5, c6 = st.columns(3)
    cash_alert_pct = c4.number_input("Cash Alert (%)", min_value=1.0, max_value=50.0, value=8.0, step=1.0)
    min_trade_value = c5.number_input(
        f"Minimum Trade Value ({ctx['base_currency']})",
        min_value=0.0,
        value=250.0,
        step=50.0,
    )
    max_cost_pct = c6.number_input("Max Cost / Trade (%)", min_value=0.1, max_value=10.0, value=2.0, step=0.1)

    allow_sells_proposal = st.checkbox("Allow Sell Trades In Trade Proposal", value=True)

    recommended_map = _recommended_weight_map(ctx, ctx["df"], model_name)
    recommendation_stats = _portfolio_stats_from_weight_map(ctx, recommended_map)

    monitor_df = _build_monitor_table(
        df=ctx["df"],
        recommended_map=recommended_map,
        tolerance_pct=float(tolerance_pct),
        base_currency=ctx["base_currency"],
    )

    alerts = _build_alerts(
        ctx=ctx,
        monitor_df=monitor_df,
        concentration_alert_pct=float(concentration_alert_pct),
        cash_alert_pct=float(cash_alert_pct),
    )

    current_target_equal_current = bool(
        np.allclose(
            ctx["df"]["Weight %"].values,
            ctx["df"]["Target %"].values,
            atol=0.01,
        )
    )

    if model_name == "Strategic Target" and current_target_equal_current:
        st.warning(
            "Your current policy target is effectively equal to the current allocation. "
            "That is why Weight % and Policy Target % look the same. "
            "Use an efficient-frontier model to generate a different recommendation."
        )

    m1, m2, m3, m4 = st.columns(4)
    info_metric(m1, "Current Return", f"{ctx['current_return']:.2%}", "Current portfolio expected return from the efficient-frontier input set.")
    info_metric(m2, "Current Volatility", f"{ctx['current_vol']:.2%}", "Current portfolio expected volatility from the efficient-frontier input set.")
    info_metric(m3, "Current Sharpe", f"{ctx['current_sharpe']:.2f}", "Current portfolio Sharpe ratio from the efficient-frontier input set.")
    info_metric(m4, "Active Alerts", str(len(alerts)), "Number of active portfolio alerts.")

    m5, m6, m7, m8 = st.columns(4)
    info_metric(m5, "Recommended Return", f"{recommendation_stats['return']:.2%}", "Expected return of the selected recommendation model.")
    info_metric(m6, "Recommended Volatility", f"{recommendation_stats['volatility']:.2%}", "Expected volatility of the selected recommendation model.")
    info_metric(m7, "Recommended Sharpe", f"{recommendation_stats['sharpe']:.2f}", "Sharpe ratio of the selected recommendation model.")
    info_metric(
        m8,
        "Out Of Band",
        str(int((monitor_df["Action"] != "Within Band").sum())),
        "Positions currently outside the tolerance band versus the selected recommendation model.",
    )

    info_section(
        "Portfolio Alerts",
        "Actionable alerts for deviations, concentration, cash drag, and broad risk conditions."
    )
    _render_alert_cards(alerts)

    left, right = st.columns([1.15, 1.0])

    with left:
        info_section(
            "Current vs Policy vs Recommended",
            "Professional comparison between current allocation, policy target, and the selected recommended allocation."
        )
        fig_compare = _build_compare_figure(ctx["df"], recommended_map)
        st.plotly_chart(fig_compare, use_container_width=True, key="rebalance_compare_chart_v2")

    with right:
        info_section(
            "Efficient Frontier Snapshot",
            "Frontier already computed by the app and used here as a recommendation engine."
        )
        if ctx.get("fig_frontier") is not None:
            st.plotly_chart(ctx["fig_frontier"], use_container_width=True, key="rebalance_frontier_chart_v2")
        else:
            st.info("Efficient frontier is not available for the current data set.")

    info_section(
        "Deviation Monitor",
        "Current weights, policy targets, recommended weights, tolerance bands, and estimated value required to move each position toward the selected recommendation."
    )
    st.dataframe(monitor_df, use_container_width=True, height=360)

    proposal_df, proposed_weight_map, turnover, total_cost, net_cash_flow, gap_closed_pct, trade_count = _build_trade_proposal(
        ctx=ctx,
        recommended_map=recommended_map,
        tolerance_pct=float(tolerance_pct),
        min_trade_value=float(min_trade_value),
        max_cost_pct=float(max_cost_pct),
        allow_sells=bool(allow_sells_proposal),
    )

    info_section(
        "Trade Proposal",
        "Institutional-style rebalance proposal filtered by tolerance bands, minimum trade size, sell permissions, and estimated transaction cost."
    )

    p1, p2, p3, p4 = st.columns(4)
    info_metric(p1, "Trades To Execute", str(trade_count), "Number of trades that passed the proposal rules.")
    info_metric(p2, "Turnover", f"{turnover:.2f}%", "Trade value divided by invested holdings value.")
    info_metric(p3, "Estimated Cost", f"{ctx['base_currency']} {total_cost:,.2f}", "Estimated total transaction cost.")
    info_metric(p4, "Gap Closed", f"{gap_closed_pct:.2f}%", "Reduction in total absolute allocation gap if all approved trades are executed.")

    p5, p6 = st.columns(2)
    info_metric(p5, "Net Cash Flow", f"{ctx['base_currency']} {net_cash_flow:,.2f}", "Positive means the proposal releases cash. Negative means it consumes cash.")
    info_metric(p6, "Model", model_name, "Recommendation model currently driving the proposal.")

    st.dataframe(proposal_df, use_container_width=True, height=360)

    fig_proposed = _build_compare_figure(ctx["df"], recommended_map, proposed_weight_map=proposed_weight_map)
    st.plotly_chart(fig_proposed, use_container_width=True, key="rebalance_proposed_chart_v2")

    execute_df = proposal_df[proposal_df["Decision"] == "Execute"].copy()
    if not execute_df.empty:
        manual_orders_df = pd.DataFrame(
            {
                "Ticker": execute_df["Ticker"],
                "Side": np.where(execute_df["Action"] == "Buy", "BUY", "SELL"),
                "Suggested Shares": execute_df["Shares Delta"].abs().round(4),
                f"Estimated Trade Value ({ctx['base_currency']})": execute_df["Value Delta"].abs().round(2),
                f"Estimated Cost ({ctx['base_currency']})": execute_df["Estimated Cost"].round(2),
            }
        )
    else:
        manual_orders_df = pd.DataFrame()

    _render_manual_orders("Manual Orders From Trade Proposal", manual_orders_df)

    info_section(
        "Contribution Plan",
        "Enter a contribution amount and receive a professional buy or buy/sell plan using the selected recommendation model."
    )

    cp1, cp2 = st.columns(2)
    contribution_amount = cp1.number_input(
        f"Contribution Amount ({ctx['base_currency']})",
        min_value=0.0,
        value=0.0,
        step=100.0,
    )
    allow_sells_contribution = cp2.checkbox("Allow Sell Trades In Contribution Plan", value=False)

    required_contribution_no_sell, contribution_note = _estimate_contribution_needed_without_selling(
        ctx["df"],
        recommended_map,
    )

    if required_contribution_no_sell is None:
        st.info(
            "Estimated contribution needed to reach the recommended weights without selling: "
            "Not feasible, because at least one current holding has a zero recommended weight."
        )
        if contribution_note:
            st.caption(contribution_note)
    else:
        st.info(
            f"Estimated contribution needed to reach the recommended weights without selling: "
            f"{ctx['base_currency']} {required_contribution_no_sell:,.2f}"
        )

    (
        contribution_df,
        contribution_weight_map,
        buy_value,
        sell_value,
        residual_contribution,
        contribution_gap_closed,
        top_priority,
    ) = _build_contribution_plan(
        ctx=ctx,
        recommended_map=recommended_map,
        contribution_amount=float(contribution_amount),
        min_trade_value=float(min_trade_value),
        allow_sells=bool(allow_sells_contribution),
    )

    c7, c8, c9, c10 = st.columns(4)
    info_metric(c7, "Estimated Buy Value", f"{ctx['base_currency']} {buy_value:,.2f}", "Total buy value from the contribution plan.")
    info_metric(c8, "Estimated Sell Value", f"{ctx['base_currency']} {sell_value:,.2f}", "Total sell value from the contribution plan.")
    info_metric(c9, "Residual Contribution", f"{ctx['base_currency']} {residual_contribution:,.2f}", "Contribution amount not effectively used after applying the current contribution plan rules.")
    info_metric(c10, "Top Priority", top_priority, "Highest-priority ticker in the contribution plan.")

    c11, c12 = st.columns(2)
    info_metric(c11, "Gap Closed", f"{contribution_gap_closed:.2f}%", "Reduction in total absolute allocation gap after the contribution plan.")
    info_metric(c12, "Contribution Sell Mode", "On" if allow_sells_contribution else "Off", "When enabled, the contribution plan may recommend sells as well as buys.")

    if contribution_amount <= 0:
        st.info("Enter a positive contribution amount to generate a contribution plan.")
    else:
        st.dataframe(contribution_df, use_container_width=True, height=340)

        fig_contribution = _build_compare_figure(
            ctx["df"],
            recommended_map,
            proposed_weight_map=contribution_weight_map,
        )
        st.plotly_chart(fig_contribution, use_container_width=True, key="rebalance_contribution_chart_v2")

        contribution_execute_df = contribution_df[contribution_df["Decision"] == "Execute"].copy()
        if not contribution_execute_df.empty:
            contribution_orders_df = pd.DataFrame(
                {
                    "Ticker": contribution_execute_df["Ticker"],
                    "Side": np.where(contribution_execute_df["Action"] == "Buy", "BUY", "SELL"),
                    "Suggested Shares": contribution_execute_df["Trade Shares"].abs().round(4),
                    f"Trade Value ({ctx['base_currency']})": contribution_execute_df["Executed Trade Value"].abs().round(2),
                    f"Reference Price ({ctx['base_currency']})": contribution_execute_df["Reference Price"].round(2),
                }
            )
        else:
            contribution_orders_df = pd.DataFrame()

        _render_manual_orders("Manual Orders From Contribution Plan", contribution_orders_df)