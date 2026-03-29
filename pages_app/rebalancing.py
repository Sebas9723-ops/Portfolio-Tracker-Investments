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


def _render_control_buttons(ctx):
    c1, c2, c3 = st.columns(3)

    if c1.button("Refresh Market Data", use_container_width=True):
        st.rerun()

    if c2.button("Recalculate Portfolio", use_container_width=True):
        st.rerun()

    if c3.button("Sync Private Data", use_container_width=True):
        if ctx["mode"] == "Private" and ctx["authenticated"]:
            st.cache_data.clear()
            st.rerun()
        else:
            st.info("Private sync is only available in Private mode.")


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


def _build_alerts_table(ctx, recommended_map):
    df = ctx["df"].copy()
    if df.empty:
        return pd.DataFrame()

    tolerance_pct = 3.0
    concentration_pct = 35.0
    cash_alert_pct = 8.0

    rows = []

    for _, row in df.iterrows():
        ticker = str(row["Ticker"])
        name = str(row["Name"])
        current_weight = float(row["Weight %"])
        recommended_weight = float(recommended_map.get(ticker, 0.0)) * 100.0
        gap_pct = current_weight - recommended_weight

        if abs(gap_pct) > tolerance_pct:
            level = "Critical" if abs(gap_pct) >= 6.0 else "Warning"
            rows.append(
                {
                    "Level": level,
                    "Item": ticker,
                    "Message": f"{name} is {gap_pct:+.2f}% away from recommended weight.",
                }
            )

        if current_weight > concentration_pct:
            rows.append(
                {
                    "Level": "Warning",
                    "Item": ticker,
                    "Message": f"{name} concentration is {current_weight:.2f}%, above {concentration_pct:.2f}%.",
                }
            )

    total_portfolio_value = float(ctx["total_portfolio_value"])
    cash_total_value = float(ctx["cash_total_value"])
    cash_pct = (cash_total_value / total_portfolio_value * 100.0) if total_portfolio_value > 0 else 0.0

    if cash_pct > cash_alert_pct:
        rows.append(
            {
                "Level": "Info" if cash_pct < cash_alert_pct * 1.5 else "Warning",
                "Item": "Cash",
                "Message": f"Cash is {cash_pct:.2f}% of total portfolio value.",
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    order = {"Critical": 0, "Warning": 1, "Info": 2}
    out["__rank"] = out["Level"].map(order).fillna(9)
    out = out.sort_values(["__rank", "Item"]).drop(columns="__rank").reset_index(drop=True)
    return out


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


def _estimate_required_contribution_without_selling(df, target_map, base_currency):
    if df.empty:
        return None, pd.DataFrame(), "No holdings data available."

    total_value = float(df["Value"].sum())
    required_contribution = 0.0

    for _, row in df.iterrows():
        ticker = str(row["Ticker"])
        current_value = float(row["Value"])
        target_weight = float(target_map.get(ticker, 0.0))

        if current_value <= 1e-12:
            continue

        if target_weight <= 1e-12:
            return None, pd.DataFrame(), f"{ticker} has a positive current value and a zero recommended weight. A buy-only transition is not feasible."

        needed = current_value / target_weight - total_value
        required_contribution = max(required_contribution, needed)

    required_contribution = max(required_contribution, 0.0)
    total_after = total_value + required_contribution

    rows = []
    for _, row in df.iterrows():
        ticker = str(row["Ticker"])
        current_value = float(row["Value"])
        target_weight = float(target_map.get(ticker, 0.0))
        target_value_after = target_weight * total_after
        buy_value = max(target_value_after - current_value, 0.0)
        price = float(row["Price"])
        buy_shares = buy_value / price if price > 0 else 0.0

        rows.append(
            {
                "Ticker": ticker,
                "Name": str(row["Name"]),
                f"Required Buy Value ({base_currency})": round(buy_value, 2),
                "Required Buy Shares": round(buy_shares, 4),
                "Resulting Weight %": round(((current_value + buy_value) / total_after) * 100.0 if total_after > 0 else 0.0, 2),
                "Recommended Weight %": round(target_weight * 100.0, 2),
            }
        )

    out = pd.DataFrame(rows).sort_values(f"Required Buy Value ({base_currency})", ascending=False).reset_index(drop=True)
    return required_contribution, out, ""


def _build_contribution_plan(
    ctx,
    recommended_map: dict[str, float],
    contribution_amount: float,
    min_trade_value: float,
    allow_sells: bool,
):
    df = ctx["df"].copy()

    empty = {
        "plan_df": pd.DataFrame(),
        "suggested_weight_map": {},
        "executable_weight_map": {},
        "suggested_buy_value": 0.0,
        "suggested_sell_value": 0.0,
        "executable_buy_value": 0.0,
        "executable_sell_value": 0.0,
        "residual_contribution": 0.0,
        "suggested_gap_closed_pct": 0.0,
        "executable_gap_closed_pct": 0.0,
        "top_priority": "-",
        "suggested_orders_df": pd.DataFrame(),
        "executable_orders_df": pd.DataFrame(),
    }

    if contribution_amount <= 0 or df.empty:
        return empty

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
            suggested_trade_value = target_value_after - current_value
            price = float(current_price_map.get(ticker, 0.0))

            if abs(suggested_trade_value) < 1e-9:
                action = "Hold"
            elif suggested_trade_value > 0:
                action = "Buy"
            else:
                action = "Sell"

            executable = abs(suggested_trade_value) >= min_trade_value and action != "Hold"
            executable_trade_value = suggested_trade_value if executable else 0.0
            suggested_shares = abs(suggested_trade_value) / price if price > 0 else 0.0
            executable_shares = abs(executable_trade_value) / price if price > 0 else 0.0

            if action == "Hold":
                status = "No Action"
            elif executable:
                status = "Execute"
            else:
                status = "Below Minimum Trade"

            suggested_value_after = current_value + suggested_trade_value
            executable_value_after = current_value + executable_trade_value

            rows.append(
                {
                    "Ticker": ticker,
                    "Name": str(name_map.get(ticker, ticker)),
                    "Current Weight %": float(current_weight_map.get(ticker, 0.0)),
                    "Recommended Weight %": recommended_weight * 100.0,
                    "Current Value": current_value,
                    "Target Value After Contribution": target_value_after,
                    "Action": action,
                    "Suggested Trade Value": suggested_trade_value,
                    "Executable Trade Value": executable_trade_value,
                    "Reference Price": price,
                    "Suggested Shares": suggested_shares,
                    "Executable Shares": executable_shares,
                    "Status": status,
                    "Suggested Value After Plan": suggested_value_after,
                    "Executable Value After Plan": executable_value_after,
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
                suggested_trade_value = contribution_amount * float(row["Positive Gap"]) / positive_gap_total
            else:
                suggested_trade_value = contribution_amount * float(row["Recommended Weight %"]) / 100.0

            action = "Buy" if suggested_trade_value > 1e-9 else "Hold"
            executable = suggested_trade_value >= min_trade_value and action != "Hold"
            executable_trade_value = suggested_trade_value if executable else 0.0
            price = float(row["Reference Price"])
            suggested_shares = suggested_trade_value / price if price > 0 else 0.0
            executable_shares = executable_trade_value / price if price > 0 else 0.0

            if action == "Hold":
                status = "No Action"
            elif executable:
                status = "Execute"
            else:
                status = "Below Minimum Trade"

            rows.append(
                {
                    "Ticker": row["Ticker"],
                    "Name": row["Name"],
                    "Current Weight %": row["Current Weight %"],
                    "Recommended Weight %": row["Recommended Weight %"],
                    "Current Value": row["Current Value"],
                    "Target Value After Contribution": row["Target Value After Contribution"],
                    "Action": action,
                    "Suggested Trade Value": suggested_trade_value,
                    "Executable Trade Value": executable_trade_value,
                    "Reference Price": price,
                    "Suggested Shares": suggested_shares,
                    "Executable Shares": executable_shares,
                    "Status": status,
                    "Suggested Value After Plan": float(row["Current Value"]) + suggested_trade_value,
                    "Executable Value After Plan": float(row["Current Value"]) + executable_trade_value,
                }
            )

    plan_df = pd.DataFrame(rows)

    suggested_total = float(plan_df["Suggested Value After Plan"].sum())
    executable_total = float(plan_df["Executable Value After Plan"].sum())

    suggested_weight_map = {}
    executable_weight_map = {}

    if suggested_total > 0:
        for _, row in plan_df.iterrows():
            suggested_weight_map[str(row["Ticker"])] = float(row["Suggested Value After Plan"]) / suggested_total
    else:
        for ticker in df["Ticker"].tolist():
            suggested_weight_map[ticker] = 0.0

    if executable_total > 0:
        for _, row in plan_df.iterrows():
            executable_weight_map[str(row["Ticker"])] = float(row["Executable Value After Plan"]) / executable_total
    else:
        for ticker in df["Ticker"].tolist():
            executable_weight_map[ticker] = 0.0

    plan_df["Suggested Weight After Plan %"] = plan_df["Ticker"].map(
        lambda t: float(suggested_weight_map.get(t, 0.0)) * 100.0
    )
    plan_df["Executable Weight After Plan %"] = plan_df["Ticker"].map(
        lambda t: float(executable_weight_map.get(t, 0.0)) * 100.0
    )
    plan_df["Suggested Gap After Plan %"] = plan_df["Suggested Weight After Plan %"] - plan_df["Recommended Weight %"]
    plan_df["Executable Gap After Plan %"] = plan_df["Executable Weight After Plan %"] - plan_df["Recommended Weight %"]

    suggested_buy_value = float(plan_df.loc[plan_df["Suggested Trade Value"] > 0, "Suggested Trade Value"].sum())
    suggested_sell_value = float(abs(plan_df.loc[plan_df["Suggested Trade Value"] < 0, "Suggested Trade Value"].sum()))
    executable_buy_value = float(plan_df.loc[plan_df["Executable Trade Value"] > 0, "Executable Trade Value"].sum())
    executable_sell_value = float(abs(plan_df.loc[plan_df["Executable Trade Value"] < 0, "Executable Trade Value"].sum()))

    residual_contribution = float(contribution_amount - (executable_buy_value - executable_sell_value))

    current_abs_gap = float(
        np.abs(df["Weight %"] - df["Ticker"].map(lambda t: float(recommended_map.get(t, 0.0)) * 100.0)).sum()
    )
    suggested_abs_gap = float(np.abs(plan_df["Suggested Gap After Plan %"]).sum())
    executable_abs_gap = float(np.abs(plan_df["Executable Gap After Plan %"]).sum())

    suggested_gap_closed_pct = (
        (current_abs_gap - suggested_abs_gap) / current_abs_gap * 100.0
        if current_abs_gap > 0
        else 0.0
    )
    executable_gap_closed_pct = (
        (current_abs_gap - executable_abs_gap) / current_abs_gap * 100.0
        if current_abs_gap > 0
        else 0.0
    )

    top_priority = "-"
    informative_df = plan_df[plan_df["Action"] != "Hold"].copy()
    if not informative_df.empty:
        top_priority = str(
            informative_df.sort_values(
                "Suggested Trade Value",
                key=lambda s: s.abs(),
                ascending=False,
            ).iloc[0]["Ticker"]
        )

    plan_df = plan_df[
        [
            "Ticker",
            "Name",
            "Action",
            "Status",
            "Current Weight %",
            "Recommended Weight %",
            "Current Value",
            "Target Value After Contribution",
            "Suggested Trade Value",
            "Executable Trade Value",
            "Reference Price",
            "Suggested Shares",
            "Executable Shares",
            "Suggested Weight After Plan %",
            "Executable Weight After Plan %",
            "Suggested Gap After Plan %",
            "Executable Gap After Plan %",
        ]
    ].copy()

    for col in [
        "Current Weight %",
        "Recommended Weight %",
        "Current Value",
        "Target Value After Contribution",
        "Suggested Trade Value",
        "Executable Trade Value",
        "Reference Price",
        "Suggested Weight After Plan %",
        "Executable Weight After Plan %",
        "Suggested Gap After Plan %",
        "Executable Gap After Plan %",
    ]:
        plan_df[col] = pd.to_numeric(plan_df[col], errors="coerce").round(2)

    for col in ["Suggested Shares", "Executable Shares"]:
        plan_df[col] = pd.to_numeric(plan_df[col], errors="coerce").round(4)

    plan_df = plan_df.sort_values(
        "Suggested Trade Value",
        key=lambda s: s.abs(),
        ascending=False,
    ).reset_index(drop=True)

    suggested_orders_df = plan_df[plan_df["Action"] != "Hold"][
        [
            "Ticker",
            "Action",
            "Status",
            "Suggested Shares",
            "Suggested Trade Value",
            "Reference Price",
        ]
    ].copy()

    executable_orders_df = plan_df[plan_df["Status"] == "Execute"][
        [
            "Ticker",
            "Action",
            "Executable Shares",
            "Executable Trade Value",
            "Reference Price",
        ]
    ].copy()

    if not suggested_orders_df.empty:
        suggested_orders_df = suggested_orders_df.rename(
            columns={
                "Suggested Trade Value": f"Suggested Trade Value ({ctx['base_currency']})",
                "Reference Price": f"Reference Price ({ctx['base_currency']})",
            }
        )

    if not executable_orders_df.empty:
        executable_orders_df = executable_orders_df.rename(
            columns={
                "Executable Trade Value": f"Executable Trade Value ({ctx['base_currency']})",
                "Reference Price": f"Reference Price ({ctx['base_currency']})",
            }
        )

    return {
        "plan_df": plan_df,
        "suggested_weight_map": suggested_weight_map,
        "executable_weight_map": executable_weight_map,
        "suggested_buy_value": suggested_buy_value,
        "suggested_sell_value": suggested_sell_value,
        "executable_buy_value": executable_buy_value,
        "executable_sell_value": executable_sell_value,
        "residual_contribution": residual_contribution,
        "suggested_gap_closed_pct": suggested_gap_closed_pct,
        "executable_gap_closed_pct": executable_gap_closed_pct,
        "top_priority": top_priority,
        "suggested_orders_df": suggested_orders_df,
        "executable_orders_df": executable_orders_df,
    }


def _render_manual_orders(title: str, df_orders: pd.DataFrame, empty_message: str):
    info_section(title, "Manual order checklist to place trades in your broker.")

    if df_orders.empty:
        st.info(empty_message)
        return

    st.dataframe(df_orders, use_container_width=True, height=240)


def render_rebalancing_page(ctx):
    render_page_title("Rebalance Center")

    if ctx["df"].empty:
        st.info("No portfolio data available.")
        return

    _render_control_buttons(ctx)

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
    alerts_df = _build_alerts_table(ctx, recommended_map)

    m1, m2, m3, m4 = st.columns(4)
    info_metric(m1, "Current Return", f"{ctx['current_return']:.2%}", "Current portfolio expected return.")
    info_metric(m2, "Current Volatility", f"{ctx['current_vol']:.2%}", "Current portfolio expected volatility.")
    info_metric(m3, "Current Sharpe", f"{ctx['current_sharpe']:.2f}", "Current portfolio Sharpe ratio.")
    info_metric(m4, "Recommendation Model", model_name, "Target engine currently used.")

    m5, m6, m7, m8 = st.columns(4)
    info_metric(m5, "Recommended Return", f"{recommendation_stats['return']:.2%}", "Expected return of the selected recommendation.")
    info_metric(m6, "Recommended Volatility", f"{recommendation_stats['volatility']:.2%}", "Expected volatility of the selected recommendation.")
    info_metric(m7, "Recommended Sharpe", f"{recommendation_stats['sharpe']:.2f}", "Sharpe ratio of the selected recommendation.")
    info_metric(m8, "Active Alerts", str(len(alerts_df)), "Number of active rebalance alerts.")

    info_section(
        "Active Alerts",
        "Priority alerts for drift, concentration, and cash drag under the selected recommendation model.",
    )
    if alerts_df.empty:
        st.success("No active alerts for the selected recommendation model.")
    else:
        st.dataframe(alerts_df, use_container_width=True, height=240)

    info_section(
        "Current vs Policy vs Recommended",
        "Professional comparison between current allocation, policy target, and the selected recommendation.",
    )
    st.plotly_chart(
        _build_compare_figure(ctx["df"], recommended_map),
        use_container_width=True,
        key="rebalance_compare_chart_phase4b",
    )

    info_section(
        "Deviation Monitor",
        "Current weights, policy targets, recommended weights, tolerance bands, and estimated value required to move each position toward the selected recommendation.",
    )
    monitor_df = _build_monitor_table(
        df=ctx["df"],
        recommended_map=recommended_map,
        tolerance_pct=float(tolerance_pct),
        base_currency=ctx["base_currency"],
    )
    st.dataframe(monitor_df, use_container_width=True, height=360)

    required_contribution, required_df, msg = _estimate_required_contribution_without_selling(
        ctx["df"],
        recommended_map,
        ctx["base_currency"],
    )

    info_section(
        "Required Contribution To Reach Recommended Allocation Without Selling",
        "Estimated cash contribution required to reach the selected recommended weights by buying only, without selling any current holding.",
    )

    if required_contribution is None:
        st.warning(msg)
    else:
        rc1, rc2 = st.columns(2)
        info_metric(
            rc1,
            "Required Contribution",
            f"{ctx['base_currency']} {required_contribution:,.2f}",
            "Estimated total cash required to reach the selected recommended allocation without selling.",
        )
        info_metric(
            rc2,
            "Method",
            "Buy Only",
            "This estimate assumes no current position is sold.",
        )
        st.dataframe(required_df, use_container_width=True, height=280)

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
        "Institutional-style rebalance proposal filtered by tolerance bands, minimum trade size, sell permissions, and estimated transaction cost.",
    )

    p1, p2, p3, p4 = st.columns(4)
    info_metric(p1, "Trades To Execute", str(trade_count), "Number of trades that passed the proposal rules.")
    info_metric(p2, "Turnover", f"{turnover:.2f}%", "Trade value divided by invested holdings value.")
    info_metric(p3, "Estimated Cost", f"{ctx['base_currency']} {total_cost:,.2f}", "Estimated total transaction cost.")
    info_metric(p4, "Gap Closed", f"{gap_closed_pct:.2f}%", "Reduction in allocation gap if approved trades are executed.")

    p5, p6 = st.columns(2)
    info_metric(p5, "Net Cash Flow", f"{ctx['base_currency']} {net_cash_flow:,.2f}", "Positive means the proposal releases cash. Negative means it consumes cash.")
    info_metric(p6, "Sell Mode", "On" if allow_sells_proposal else "Off", "Sell permission status in the trade proposal.")

    st.dataframe(proposal_df, use_container_width=True, height=360)

    st.plotly_chart(
        _build_compare_figure(ctx["df"], recommended_map, proposed_weight_map=proposed_weight_map),
        use_container_width=True,
        key="rebalance_proposed_chart_phase4b",
    )

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

    _render_manual_orders(
        "Manual Orders From Trade Proposal",
        manual_orders_df,
        "No trades qualified for execution under the current rules.",
    )

    info_section(
        "Contribution Plan",
        "Enter a contribution amount and receive both suggested and executable buy or buy/sell recommendations using the selected recommendation model.",
    )

    cp1, cp2 = st.columns(2)
    contribution_amount = cp1.number_input(
        f"Contribution Amount ({ctx['base_currency']})",
        min_value=0.0,
        value=0.0,
        step=100.0,
    )
    allow_sells_contribution = cp2.checkbox("Allow Sell Trades In Contribution Plan", value=False)

    contribution_result = _build_contribution_plan(
        ctx=ctx,
        recommended_map=recommended_map,
        contribution_amount=float(contribution_amount),
        min_trade_value=float(min_trade_value),
        allow_sells=bool(allow_sells_contribution),
    )

    plan_df = contribution_result["plan_df"]
    suggested_weight_map = contribution_result["suggested_weight_map"]
    executable_weight_map = contribution_result["executable_weight_map"]
    suggested_buy_value = contribution_result["suggested_buy_value"]
    suggested_sell_value = contribution_result["suggested_sell_value"]
    executable_buy_value = contribution_result["executable_buy_value"]
    executable_sell_value = contribution_result["executable_sell_value"]
    residual_contribution = contribution_result["residual_contribution"]
    suggested_gap_closed_pct = contribution_result["suggested_gap_closed_pct"]
    executable_gap_closed_pct = contribution_result["executable_gap_closed_pct"]
    top_priority = contribution_result["top_priority"]
    suggested_orders_df = contribution_result["suggested_orders_df"]
    executable_orders_df = contribution_result["executable_orders_df"]

    c7, c8, c9 = st.columns(3)
    info_metric(c7, "Suggested Buy Value", f"{ctx['base_currency']} {suggested_buy_value:,.2f}", "Total suggested buy value before execution filters.")
    info_metric(c8, "Suggested Sell Value", f"{ctx['base_currency']} {suggested_sell_value:,.2f}", "Total suggested sell value before execution filters.")
    info_metric(c9, "Top Priority", top_priority, "Ticker with the largest suggested action, even if it is below the execution threshold.")

    c10, c11, c12 = st.columns(3)
    info_metric(c10, "Executable Buy Value", f"{ctx['base_currency']} {executable_buy_value:,.2f}", "Total executable buy value after applying filters.")
    info_metric(c11, "Executable Sell Value", f"{ctx['base_currency']} {executable_sell_value:,.2f}", "Total executable sell value after applying filters.")
    info_metric(c12, "Residual Contribution", f"{ctx['base_currency']} {residual_contribution:,.2f}", "Contribution amount not effectively used after execution filters.")

    c13, c14 = st.columns(2)
    info_metric(c13, "Suggested Gap Closed", f"{suggested_gap_closed_pct:.2f}%", "Improvement if all suggested trades were implemented.")
    info_metric(c14, "Executable Gap Closed", f"{executable_gap_closed_pct:.2f}%", "Improvement after applying execution filters.")

    if contribution_amount <= 0:
        st.info("Enter a positive contribution amount to generate a contribution plan.")
    else:
        st.dataframe(plan_df, use_container_width=True, height=360)

        st.plotly_chart(
            _build_compare_figure(ctx["df"], recommended_map, proposed_weight_map=suggested_weight_map),
            use_container_width=True,
            key="rebalance_contribution_suggested_chart_phase4b",
        )

        st.plotly_chart(
            _build_compare_figure(ctx["df"], recommended_map, proposed_weight_map=executable_weight_map),
            use_container_width=True,
            key="rebalance_contribution_executable_chart_phase4b",
        )

        _render_manual_orders(
            "Suggested Orders From Contribution Plan",
            suggested_orders_df,
            "There are no suggested contribution trades for the current amount.",
        )
        _render_manual_orders(
            "Executable Orders From Contribution Plan",
            executable_orders_df,
            "No contribution trades qualified for execution under the current rules.",
        )