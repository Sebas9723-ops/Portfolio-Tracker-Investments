import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core import info_metric, info_section, render_page_title


def _normalize_weight_map(weight_map, tickers):
    clean = {t: max(float(weight_map.get(t, 0.0)), 0.0) for t in tickers}
    total = float(sum(clean.values()))
    if total <= 0:
        equal = 1.0 / len(tickers) if tickers else 0.0
        return {t: equal for t in tickers}
    return {t: v / total for t, v in clean.items()}


def _max_sharpe_weight_map(ctx, df):
    tickers = df["Ticker"].tolist()

    if ctx.get("max_sharpe_row") is None or not ctx.get("usable"):
        raw = df.set_index("Ticker")["Target Weight"].to_dict()
        return _normalize_weight_map(raw, tickers), "Policy Target"

    usable = list(ctx["usable"])
    arr = np.array(ctx["max_sharpe_row"]["Weights"], dtype=float)
    raw = {ticker: 0.0 for ticker in tickers}

    if len(arr) == len(usable):
        for ticker, weight in zip(usable, arr):
            raw[ticker] = float(weight)

    return _normalize_weight_map(raw, tickers), "Max Sharpe Frontier"


def _build_compare_figure(df, target_map):
    fig = go.Figure()
    fig.add_bar(x=df["Ticker"], y=df["Weight %"], name="Current Weight %")
    fig.add_bar(
        x=df["Ticker"],
        y=[float(target_map.get(t, 0.0)) * 100.0 for t in df["Ticker"]],
        name="Max Sharpe Weight %",
    )
    fig.update_layout(
        barmode="group",
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=380,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Ticker",
        yaxis_title="Weight %",
        legend=dict(orientation="h", y=1.08, x=0.0),
    )
    return fig


def _build_monitor_table(df, target_map, base_currency):
    work = df.copy()
    holdings_total = float(work["Value"].sum()) if not work.empty else 0.0

    work["Max Sharpe Weight %"] = work["Ticker"].map(lambda t: float(target_map.get(t, 0.0)) * 100.0)
    work["Gap %"] = work["Weight %"] - work["Max Sharpe Weight %"]

    if holdings_total > 0:
        work[f"Trade To Max Sharpe ({base_currency})"] = (
            (work["Max Sharpe Weight %"] - work["Weight %"]) / 100.0 * holdings_total
        )
    else:
        work[f"Trade To Max Sharpe ({base_currency})"] = 0.0

    work["Action"] = np.where(
        work["Gap %"] > 0,
        "Reduce",
        np.where(work["Gap %"] < 0, "Add", "Hold"),
    )

    out = work[
        [
            "Ticker",
            "Name",
            "Weight %",
            "Target %",
            "Max Sharpe Weight %",
            "Gap %",
            f"Trade To Max Sharpe ({base_currency})",
            "Action",
        ]
    ].copy()

    for col in [
        "Weight %",
        "Target %",
        "Max Sharpe Weight %",
        "Gap %",
        f"Trade To Max Sharpe ({base_currency})",
    ]:
        out[col] = pd.to_numeric(out[col], errors="coerce").round(2)

    out = out.sort_values("Gap %", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)
    return out


def _estimate_required_contribution_no_sell(df, target_map, base_currency):
    if df.empty:
        return None, pd.DataFrame(), "No holdings data available."

    total_value = float(df["Value"].sum())
    rows = []
    required_contribution = 0.0

    for _, row in df.iterrows():
        ticker = str(row["Ticker"])
        current_value = float(row["Value"])
        target_weight = float(target_map.get(ticker, 0.0))

        if current_value <= 1e-12:
            continue

        if target_weight <= 1e-12:
            return None, pd.DataFrame(), f"{ticker} has a positive current value and a zero max Sharpe weight. A no-sell transition is not feasible."

        contribution_i = current_value / target_weight - total_value
        required_contribution = max(required_contribution, contribution_i)

    required_contribution = max(required_contribution, 0.0)

    for _, row in df.iterrows():
        ticker = str(row["Ticker"])
        current_value = float(row["Value"])
        target_weight = float(target_map.get(ticker, 0.0))
        target_value_after = target_weight * (total_value + required_contribution)
        buy_value = max(target_value_after - current_value, 0.0)
        price = float(row["Price"])
        buy_shares = buy_value / price if price > 0 else 0.0

        rows.append(
            {
                "Ticker": ticker,
                "Name": str(row["Name"]),
                f"Buy Value ({base_currency})": round(buy_value, 2),
                "Buy Shares": round(buy_shares, 4),
                "Resulting Weight %": round((current_value + buy_value) / (total_value + required_contribution) * 100.0 if (total_value + required_contribution) > 0 else 0.0, 2),
                "Max Sharpe Weight %": round(target_weight * 100.0, 2),
            }
        )

    out = pd.DataFrame(rows).sort_values(f"Buy Value ({base_currency})", ascending=False).reset_index(drop=True)
    return required_contribution, out, ""


def _build_custom_contribution_plan(df, target_map, contribution_amount, allow_sells, base_currency):
    if df.empty or contribution_amount <= 0:
        return pd.DataFrame(), {}

    total_value = float(df["Value"].sum())
    total_after = total_value + float(contribution_amount)

    current_values = df.set_index("Ticker")["Value"].to_dict()
    current_prices = df.set_index("Ticker")["Price"].to_dict()
    current_names = df.set_index("Ticker")["Name"].to_dict()

    rows = []

    if allow_sells:
        for ticker in df["Ticker"].tolist():
            current_value = float(current_values.get(ticker, 0.0))
            target_weight = float(target_map.get(ticker, 0.0))
            target_value = target_weight * total_after
            trade_value = target_value - current_value
            action = "BUY" if trade_value > 0 else ("SELL" if trade_value < 0 else "HOLD")
            price = float(current_prices.get(ticker, 0.0))
            shares = abs(trade_value) / price if price > 0 else 0.0

            rows.append(
                {
                    "Ticker": ticker,
                    "Name": str(current_names.get(ticker, ticker)),
                    "Action": action,
                    f"Trade Value ({base_currency})": round(abs(trade_value), 2),
                    "Trade Shares": round(shares, 4),
                    "Reference Price": round(price, 2),
                    "Proposed Value": current_value + trade_value,
                }
            )
    else:
        positive_gaps = {}
        gap_sum = 0.0

        for ticker in df["Ticker"].tolist():
            current_value = float(current_values.get(ticker, 0.0))
            target_weight = float(target_map.get(ticker, 0.0))
            target_value = target_weight * total_after
            positive_gap = max(target_value - current_value, 0.0)
            positive_gaps[ticker] = positive_gap
            gap_sum += positive_gap

        for ticker in df["Ticker"].tolist():
            current_value = float(current_values.get(ticker, 0.0))
            price = float(current_prices.get(ticker, 0.0))

            if gap_sum > 0:
                trade_value = contribution_amount * positive_gaps[ticker] / gap_sum
            else:
                trade_value = contribution_amount * float(target_map.get(ticker, 0.0))

            action = "BUY" if trade_value > 0 else "HOLD"
            shares = trade_value / price if price > 0 else 0.0

            rows.append(
                {
                    "Ticker": ticker,
                    "Name": str(current_names.get(ticker, ticker)),
                    "Action": action,
                    f"Trade Value ({base_currency})": round(trade_value, 2),
                    "Trade Shares": round(shares, 4),
                    "Reference Price": round(price, 2),
                    "Proposed Value": current_value + trade_value,
                }
            )

    plan_df = pd.DataFrame(rows)

    total_proposed = float(plan_df["Proposed Value"].sum())
    proposed_map = {}
    if total_proposed > 0:
        for _, row in plan_df.iterrows():
            proposed_map[str(row["Ticker"])] = float(row["Proposed Value"]) / total_proposed
    else:
        for ticker in df["Ticker"].tolist():
            proposed_map[ticker] = 0.0

    plan_df["Proposed Weight %"] = plan_df["Ticker"].map(lambda t: float(proposed_map.get(t, 0.0)) * 100.0)
    plan_df["Max Sharpe Weight %"] = plan_df["Ticker"].map(lambda t: float(target_map.get(t, 0.0)) * 100.0)
    plan_df["Gap After Plan %"] = plan_df["Proposed Weight %"] - plan_df["Max Sharpe Weight %"]

    keep_cols = [
        "Ticker",
        "Name",
        "Action",
        f"Trade Value ({base_currency})",
        "Trade Shares",
        "Reference Price",
        "Proposed Weight %",
        "Max Sharpe Weight %",
        "Gap After Plan %",
    ]
    plan_df = plan_df[keep_cols].copy()
    plan_df = plan_df.sort_values(f"Trade Value ({base_currency})", ascending=False).reset_index(drop=True)

    return plan_df, proposed_map


def render_rebalancing_page(ctx):
    render_page_title("Rebalance Center")

    if ctx["df"].empty:
        st.info("No portfolio data available.")
        return

    target_map, source_label = _max_sharpe_weight_map(ctx, ctx["df"])

    c1, c2, c3, c4 = st.columns(4)
    info_metric(c1, "Current Return", f"{ctx['current_return']:.2%}", "Expected annualized return of the current portfolio.")
    info_metric(c2, "Current Volatility", f"{ctx['current_vol']:.2%}", "Expected annualized volatility of the current portfolio.")
    info_metric(c3, "Current Sharpe", f"{ctx['current_sharpe']:.2f}", "Current Sharpe ratio.")
    info_metric(c4, "Target Source", source_label, "Weight source used in this rebalance page.")

    info_section(
        "Current vs Max Sharpe",
        "Current allocation compared against the maximum Sharpe allocation from the efficient frontier.",
    )
    fig_compare = _build_compare_figure(ctx["df"], target_map)
    st.plotly_chart(fig_compare, use_container_width=True, key="rebalancing_compare_ms_chart")

    info_section(
        "Deviation Monitor",
        "Current weights, current policy target, max Sharpe target, and estimated value to move each position toward max Sharpe.",
    )
    monitor_df = _build_monitor_table(ctx["df"], target_map, ctx["base_currency"])
    st.dataframe(monitor_df, use_container_width=True, height=340)

    required_contribution, required_df, msg = _estimate_required_contribution_no_sell(
        ctx["df"],
        target_map,
        ctx["base_currency"],
    )

    info_section(
        "Required Contribution To Reach Max Sharpe Without Selling",
        "Estimated cash contribution required to reach the max Sharpe weights by buying positions only, without selling any current holding.",
    )

    if required_contribution is None:
        st.warning(msg)
    else:
        k1, k2 = st.columns(2)
        info_metric(
            k1,
            "Required Contribution",
            f"{ctx['base_currency']} {required_contribution:,.2f}",
            "Estimated total cash required to reach the max Sharpe allocation without selling.",
        )
        info_metric(
            k2,
            "Method",
            "Buy Only",
            "This estimate assumes no existing position is sold.",
        )

        st.dataframe(required_df, use_container_width=True, height=280)

    info_section(
        "Custom Contribution Plan",
        "Enter any contribution amount and see how much to buy in each position. Enable sell mode if you want the plan to include sells as well.",
    )

    cp1, cp2 = st.columns(2)
    contribution_amount = cp1.number_input(
        f"Contribution Amount ({ctx['base_currency']})",
        min_value=0.0,
        value=0.0,
        step=100.0,
    )
    allow_sells = cp2.checkbox("Allow Sell Trades", value=False)

    if contribution_amount > 0:
        plan_df, proposed_map = _build_custom_contribution_plan(
            ctx["df"],
            target_map,
            contribution_amount,
            allow_sells,
            ctx["base_currency"],
        )

        buy_total = 0.0
        sell_total = 0.0
        trade_col = f"Trade Value ({ctx['base_currency']})"

        if not plan_df.empty:
            buy_total = float(plan_df.loc[plan_df["Action"] == "BUY", trade_col].sum())
            sell_total = float(plan_df.loc[plan_df["Action"] == "SELL", trade_col].sum())

        s1, s2, s3 = st.columns(3)
        info_metric(s1, "Planned Buys", f"{ctx['base_currency']} {buy_total:,.2f}", "Total buy value in the custom contribution plan.")
        info_metric(s2, "Planned Sells", f"{ctx['base_currency']} {sell_total:,.2f}", "Total sell value in the custom contribution plan.")
        info_metric(s3, "Contribution Mode", "Buy + Sell" if allow_sells else "Buy Only", "Planning mode for the custom contribution plan.")

        st.dataframe(plan_df, use_container_width=True, height=320)

        fig_plan = _build_compare_figure(
            ctx["df"],
            target_map,
        )
        fig_plan.add_bar(
            x=ctx["df"]["Ticker"],
            y=[float(proposed_map.get(t, 0.0)) * 100.0 for t in ctx["df"]["Ticker"]],
            name="Proposed Weight %",
        )
        fig_plan.update_layout(barmode="group")
        st.plotly_chart(fig_plan, use_container_width=True, key="rebalancing_custom_contribution_chart")
    else:
        st.info("Enter a positive contribution amount to generate a custom contribution plan.")