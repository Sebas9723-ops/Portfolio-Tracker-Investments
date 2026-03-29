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


def _get_max_sharpe_target_map(ctx, df):
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


def _build_compare_chart(df, target_map):
    fig = go.Figure()
    fig.add_bar(
        x=df["Ticker"],
        y=df["Weight %"],
        name="Current Weight %",
    )
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
            return None, pd.DataFrame(), f"{ticker} has a positive current value and a zero max Sharpe weight. A buy-only transition is not feasible."

        needed = current_value / target_weight - total_value
        required_contribution = max(required_contribution, needed)

    required_contribution = max(required_contribution, 0.0)

    rows = []
    total_after = total_value + required_contribution

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
                "Max Sharpe Weight %": round(target_weight * 100.0, 2),
            }
        )

    out = pd.DataFrame(rows).sort_values(f"Required Buy Value ({base_currency})", ascending=False).reset_index(drop=True)
    return required_contribution, out, ""


def render_rebalancing_page(ctx):
    render_page_title("Rebalance Center")

    if ctx["df"].empty:
        st.info("No portfolio data available.")
        return

    target_map, source_label = _get_max_sharpe_target_map(ctx, ctx["df"])

    c1, c2, c3, c4 = st.columns(4)
    info_metric(c1, "Current Return", f"{ctx['current_return']:.2%}", "Expected annualized return of the current portfolio.")
    info_metric(c2, "Current Volatility", f"{ctx['current_vol']:.2%}", "Expected annualized volatility of the current portfolio.")
    info_metric(c3, "Current Sharpe", f"{ctx['current_sharpe']:.2f}", "Current Sharpe ratio.")
    info_metric(c4, "Target Source", source_label, "Weight source used in this rebalance page.")

    info_section(
        "Current vs Max Sharpe",
        "Current allocation compared against the maximum Sharpe allocation from the efficient frontier.",
    )
    st.plotly_chart(
        _build_compare_chart(ctx["df"], target_map),
        use_container_width=True,
        key="rebalancing_compare_ms_chart_v2",
    )

    info_section(
        "Deviation Monitor",
        "Current weights, current policy target, max Sharpe target, and estimated value to move each position toward max Sharpe.",
    )
    st.dataframe(
        _build_monitor_table(ctx["df"], target_map, ctx["base_currency"]),
        use_container_width=True,
        height=340,
    )

    required_contribution, required_df, msg = _estimate_required_contribution_without_selling(
        ctx["df"],
        target_map,
        ctx["base_currency"],
    )

    info_section(
        "Required Contribution To Reach Max Sharpe Without Selling",
        "Estimated cash contribution required to reach the max Sharpe weights by buying only, without selling any current holding.",
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
            "This estimate assumes no current position is sold.",
        )

        st.dataframe(required_df, use_container_width=True, height=300)