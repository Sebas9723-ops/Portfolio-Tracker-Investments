import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core import info_metric, info_section, render_page_title


def _annualized_voo_return(ctx):
    benchmark_returns = ctx.get("resolved_benchmark_returns")
    if benchmark_returns is not None and not benchmark_returns.empty:
        return float(benchmark_returns.mean() * 252)
    return None


def _get_max_sharpe_target_map(ctx, df):
    tickers = df["Ticker"].tolist()
    policy_map = ctx.get("policy_target_map", {})

    if ctx.get("max_sharpe_row") is None or not ctx.get("usable"):
        return dict(policy_map), "Policy Target"

    usable = list(ctx["usable"])
    arr = np.array(ctx["max_sharpe_row"]["Weights"], dtype=float)

    raw = {ticker: 0.0 for ticker in tickers}
    if len(arr) == len(usable):
        for ticker, weight in zip(usable, arr):
            raw[ticker] = float(weight)

    total = sum(raw.values())
    if total > 0:
        raw = {k: v / total for k, v in raw.items()}
        return raw, "Max Sharpe Frontier"

    return dict(policy_map), "Policy Target"


def _build_compare_chart(df, policy_map, max_sharpe_map):
    fig = go.Figure()
    fig.add_bar(
        x=df["Ticker"],
        y=df["Weight %"],
        name="Current Weight %",
    )
    fig.add_bar(
        x=df["Ticker"],
        y=[float(max_sharpe_map.get(t, 0.0)) * 100.0 for t in df["Ticker"]],
        name="Max Sharpe Weight %",
    )

    fig.update_layout(
        barmode="group",
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=390,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Ticker",
        yaxis_title="Weight %",
        legend=dict(orientation="h", y=1.08, x=0.0),
    )
    return fig


def _build_monitor_table(df, policy_map, max_sharpe_map, base_currency):
    work = df.copy()
    holdings_total = float(work["Value"].sum()) if not work.empty else 0.0

    work["Policy Target %"] = work["Ticker"].map(lambda t: float(policy_map.get(t, 0.0)) * 100.0)
    work["Max Sharpe Weight %"] = work["Ticker"].map(lambda t: float(max_sharpe_map.get(t, 0.0)) * 100.0)
    work["Gap vs Max Sharpe %"] = work["Weight %"] - work["Max Sharpe Weight %"]

    if holdings_total > 0:
        work[f"Trade To Max Sharpe ({base_currency})"] = (
            (work["Max Sharpe Weight %"] - work["Weight %"]) / 100.0 * holdings_total
        )
    else:
        work[f"Trade To Max Sharpe ({base_currency})"] = 0.0

    work["Action"] = np.where(
        work["Gap vs Max Sharpe %"] > 0,
        "Reduce",
        np.where(work["Gap vs Max Sharpe %"] < 0, "Add", "Hold"),
    )

    out = work[
        [
            "Ticker",
            "Name",
            "Weight %",
            "Policy Target %",
            "Max Sharpe Weight %",
            "Gap vs Max Sharpe %",
            f"Trade To Max Sharpe ({base_currency})",
            "Action",
        ]
    ].copy()

    for col in [
        "Weight %",
        "Policy Target %",
        "Max Sharpe Weight %",
        "Gap vs Max Sharpe %",
        f"Trade To Max Sharpe ({base_currency})",
    ]:
        out[col] = pd.to_numeric(out[col], errors="coerce").round(2)

    out = out.sort_values("Gap vs Max Sharpe %", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)
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
            return None, pd.DataFrame(), (
                f"{ticker} has a positive current value and a zero max Sharpe weight. "
                "A buy-only transition is not feasible."
            )

        needed = current_value / target_weight - total_value
        required_contribution = max(required_contribution, needed)

    required_contribution = max(required_contribution, 0.0)
    total_after = total_value + required_contribution

    rows = []
    for _, row in df.iterrows():
        ticker = str(row["Ticker"])
        name = str(row["Name"])
        current_value = float(row["Value"])
        current_shares = float(row["Shares"])
        price = float(row["Price"])
        target_weight = float(target_map.get(ticker, 0.0))

        target_value_after = target_weight * total_after
        buy_value = max(target_value_after - current_value, 0.0)
        buy_shares = buy_value / price if price > 0 else 0.0
        resulting_weight = ((current_value + buy_value) / total_after * 100.0) if total_after > 0 else 0.0

        rows.append(
            {
                "Ticker": ticker,
                "Name": name,
                "Current Shares": round(current_shares, 4),
                "Current Value": round(current_value, 2),
                f"Required Buy Value ({base_currency})": round(buy_value, 2),
                "Required Buy Shares": round(buy_shares, 4),
                "Resulting Weight %": round(resulting_weight, 2),
                "Max Sharpe Weight %": round(target_weight * 100.0, 2),
            }
        )

    out = pd.DataFrame(rows).sort_values(
        f"Required Buy Value ({base_currency})",
        ascending=False,
    ).reset_index(drop=True)

    return required_contribution, out, ""


def _build_live_validation_table(ctx, policy_map, max_sharpe_map):
    rows = []

    df = ctx.get("df", pd.DataFrame()).copy()
    if df.empty:
        return pd.DataFrame([{"Level": "Critical", "Check": "Portfolio", "Message": "No portfolio data available."}])

    if pd.to_numeric(df["Price"], errors="coerce").fillna(0.0).le(0).any():
        missing = df[pd.to_numeric(df["Price"], errors="coerce").fillna(0.0).le(0)]["Ticker"].astype(str).tolist()
        rows.append(
            {
                "Level": "Critical",
                "Check": "Prices",
                "Message": f"Missing or zero prices detected for: {', '.join(missing)}.",
            }
        )

    total_policy = sum(float(v) for v in policy_map.values())
    total_ms = sum(float(v) for v in max_sharpe_map.values())

    if abs(total_policy - 1.0) > 0.01:
        rows.append(
            {
                "Level": "Warning",
                "Check": "Policy Weights",
                "Message": f"Policy target weights sum to {total_policy:.4f}, not 1.0000.",
            }
        )

    if abs(total_ms - 1.0) > 0.01:
        rows.append(
            {
                "Level": "Warning",
                "Check": "Max Sharpe Weights",
                "Message": f"Max Sharpe weights sum to {total_ms:.4f}, not 1.0000.",
            }
        )

    if ctx.get("max_sharpe_row") is None:
        rows.append(
            {
                "Level": "Info",
                "Check": "Efficient Frontier",
                "Message": "Efficient frontier is not available. Rebalancing uses policy target as fallback.",
            }
        )

    bench = ctx.get("resolved_benchmark_returns")
    if bench is None or bench.empty:
        rows.append(
            {
                "Level": "Info",
                "Check": "Benchmark",
                "Message": "VOO benchmark series is unavailable or empty.",
            }
        )

    if not rows:
        rows.append(
            {
                "Level": "OK",
                "Check": "Validation",
                "Message": "No live validation issues detected.",
            }
        )

    out = pd.DataFrame(rows)
    order = {"Critical": 0, "Warning": 1, "Info": 2, "OK": 3}
    out["__rank"] = out["Level"].map(order).fillna(9)
    out = out.sort_values(["__rank", "Check"]).drop(columns="__rank").reset_index(drop=True)
    return out


def render_rebalancing_page(ctx):
    render_page_title("Rebalance Center")

    if ctx["df"].empty:
        st.info("No portfolio data available.")
        return

    policy_map = ctx.get("policy_target_map", {})
    max_sharpe_map, source_label = _get_max_sharpe_target_map(ctx, ctx["df"])
    voo_return = _annualized_voo_return(ctx)

    c1, c2, c3, c4 = st.columns(4)
    info_metric(c1, "Current Return", f"{ctx['current_return']:.2%}", "Expected annualized return of the current portfolio.")
    info_metric(c2, "VOO Return", "—" if voo_return is None else f"{voo_return:.2%}", "Annualized VOO return over the same historical window.")
    info_metric(c3, "Current Volatility", f"{ctx['current_vol']:.2%}", "Expected annualized volatility of the current portfolio.")
    info_metric(c4, "Current Sharpe", f"{ctx['current_sharpe']:.2f}", "Current Sharpe ratio.")

    info_section(
        "Current vs Policy vs Max Sharpe",
        f"Current allocation compared against policy targets and recommendation source: {source_label}.",
    )
    st.plotly_chart(
        _build_compare_chart(ctx["df"], policy_map, max_sharpe_map),
        use_container_width=True,
        key="rebalancing_compare_chart_fixed_v2",
    )

    info_section(
        "Deviation Monitor",
        "Current weight, policy target, max Sharpe target, and estimated value required to move each position toward max Sharpe.",
    )
    st.dataframe(
        _build_monitor_table(ctx["df"], policy_map, max_sharpe_map, ctx["base_currency"]),
        use_container_width=True,
        height=340,
    )

    required_contribution, required_df, msg = _estimate_required_contribution_without_selling(
        ctx["df"],
        max_sharpe_map,
        ctx["base_currency"],
    )

    info_section(
        "Required Contribution To Reach Max Sharpe Without Selling",
        "Estimated cash contribution required to reach max Sharpe weights through purchases only, without selling current positions.",
    )

    if required_contribution is None:
        st.warning(msg)
    else:
        k1, k2 = st.columns(2)
        info_metric(
            k1,
            "Required Contribution",
            f"{ctx['base_currency']} {required_contribution:,.2f}",
            "Estimated total cash needed to reach max Sharpe allocation without selling.",
        )
        info_metric(
            k2,
            "Method",
            "Buy Only",
            "This estimate assumes no current position is sold.",
        )

        st.dataframe(required_df, use_container_width=True, height=300)

    info_section(
        "Live Validation Warning",
        "Final validation layer for prices, benchmark, frontier availability, and target consistency.",
    )
    st.dataframe(
        _build_live_validation_table(ctx, policy_map, max_sharpe_map),
        use_container_width=True,
        height=220,
    )