import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_echarts import st_echarts

from app_core import DEFAULT_RISK_FREE_RATE, info_metric, info_section, render_page_title
from utils_aggrid import show_aggrid


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
    """Horizontal divergence chart — right = underweight (buy, green), left = overweight (amber)."""
    tickers, drifts, colors, tooltips = [], [], [], []

    for _, row in df.iterrows():
        t = str(row["Ticker"])
        current = float(row["Weight %"])
        target = float(max_sharpe_map.get(t, 0.0)) * 100.0
        drift = target - current  # positive = underweight → buy

        tickers.append(t)
        drifts.append(drift)
        colors.append("#00ff88" if drift > 0 else "#f5a623")

        tooltips.append(
            f"<b>{t}</b><br>"
            f"Current weight: {current:.2f}%<br>"
            f"Target weight: {target:.2f}%<br>"
            f"Drift: {drift:+.2f}%<br>"
            f"Action: {'Buy ↑' if drift > 0 else 'Reduce ↓'}"
        )

    fig = go.Figure(go.Bar(
        x=drifts,
        y=tickers,
        orientation="h",
        marker_color=colors,
        text=[f"{d:+.1f}%" for d in drifts],
        textposition="outside",
        hovertext=tooltips,
        hoverinfo="text",
    ))

    fig.add_vline(x=0, line_color="#333", line_width=1.5)

    fig.update_layout(
        paper_bgcolor="#0a0a0a",
        plot_bgcolor="#0a0a0a",
        font=dict(color="#e6e6e6", family="IBM Plex Mono"),
        height=max(300, len(tickers) * 52),
        margin=dict(t=50, b=20, l=10, r=70),
        xaxis=dict(
            title="Drift vs Target (%)",
            gridcolor="rgba(255,255,255,0.06)",
            zeroline=False,
        ),
        yaxis=dict(autorange="reversed"),
        annotations=[
            dict(x=0.18, y=1.09, xref="paper", yref="paper", showarrow=False,
                 text="◀ OVERWEIGHT", font=dict(color="#f5a623", size=11, family="IBM Plex Mono")),
            dict(x=0.82, y=1.09, xref="paper", yref="paper", showarrow=False,
                 text="UNDERWEIGHT ▶", font=dict(color="#00ff88", size=11, family="IBM Plex Mono")),
        ],
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


def _build_contribution_plan(df, target_map, contribution_base, base_currency):
    """
    Allocate a cash contribution across tickers to close underweight gaps
    toward max Sharpe targets. Scales proportionally if total gap > contribution.
    """
    if df.empty or contribution_base <= 0:
        return pd.DataFrame()

    total_current = float(df["Value"].sum())
    total_after = total_current + contribution_base

    gaps = {}
    for _, row in df.iterrows():
        ticker = str(row["Ticker"])
        current_value = float(row["Value"])
        target_weight = float(target_map.get(ticker, 0.0))
        target_value = target_weight * total_after
        gap = target_value - current_value
        gaps[ticker] = max(gap, 0.0)

    total_gap = sum(gaps.values())

    rows = []
    for _, row in df.iterrows():
        ticker = str(row["Ticker"])
        name = str(row["Name"])
        current_value = float(row["Value"])
        current_shares = float(row["Shares"])
        price = float(row["Price"])
        target_weight = float(target_map.get(ticker, 0.0))
        gap = gaps[ticker]

        if total_gap > 0:
            if total_gap <= contribution_base:
                buy_value = gap
            else:
                buy_value = gap / total_gap * contribution_base
        else:
            buy_value = 0.0

        buy_shares = buy_value / price if price > 0 else 0.0
        new_value = current_value + buy_value
        new_weight = new_value / total_after * 100.0 if total_after > 0 else 0.0
        current_weight = current_value / total_current * 100.0 if total_current > 0 else 0.0

        rows.append({
            "Ticker": ticker,
            "Name": name,
            "Current Weight %": round(current_weight, 2),
            "Target Weight %": round(target_weight * 100.0, 2),
            f"Buy ({base_currency})": round(buy_value, 2),
            "Buy Shares": round(buy_shares, 4),
            "Resulting Weight %": round(new_weight, 2),
        })

    out = pd.DataFrame(rows).sort_values(f"Buy ({base_currency})", ascending=False).reset_index(drop=True)
    return out


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

    # Compute portfolio stats from returns (not from ctx keys removed during refactor)
    portfolio_returns = ctx.get("portfolio_returns", pd.Series(dtype=float))
    if not portfolio_returns.empty:
        current_return = float(portfolio_returns.mean() * 252)
        current_vol = float(portfolio_returns.std() * np.sqrt(252))
        rfr = ctx.get("risk_free_rate", DEFAULT_RISK_FREE_RATE)
        current_sharpe = (current_return - rfr) / current_vol if current_vol > 0 else 0.0
    else:
        current_return = ctx.get("total_return", 0.0)
        current_vol = ctx.get("volatility", 0.0)
        current_sharpe = ctx.get("sharpe", 0.0)

    c1, c2, c3, c4 = st.columns(4)
    info_metric(c1, "Current Return", f"{current_return:.2%}", "Annualized portfolio return based on historical daily returns.")
    info_metric(c2, "VOO Return", "—" if voo_return is None else f"{voo_return:.2%}", "Annualized VOO return over the same historical window.")
    info_metric(c3, "Current Volatility", f"{current_vol:.2%}", "Annualized portfolio volatility.")
    info_metric(c4, "Current Sharpe", f"{current_sharpe:.2f}", "Current Sharpe ratio.")

    info_section(
        "Current vs Max Sharpe",
        f"Current allocation compared against recommendation source: {source_label}.",
    )
    _rebal_df = ctx["df"].copy()
    _tickers = []
    _divergences = []
    _colors = []
    for _, _row in _rebal_df.iterrows():
        _t = str(_row["Ticker"])
        _current = float(_row["Weight %"])
        _target = float(max_sharpe_map.get(_t, 0.0)) * 100.0
        _drift = _target - _current
        _tickers.append(_t)
        _divergences.append(round(_drift, 4))
        _colors.append("#00ff88" if _drift > 0 else "#f5a623")

    rebal_option = {
        "backgroundColor": "#0a0a0a",
        "tooltip": {
            "trigger": "axis",
            "axisPointer": {"type": "shadow"},
            "backgroundColor": "#1a1a2e",
            "borderColor": "#2a313c",
            "textStyle": {"color": "#e6e6e6", "fontFamily": "IBM Plex Mono"},
            "formatter": "function(params) { var p = params[0]; var sign = p.value >= 0 ? 'UNDERWEIGHT — Buy' : 'OVERWEIGHT'; return p.name + '<br/>' + p.marker + ' Drift: <b>' + p.value.toFixed(2) + '%</b><br/>' + sign; }"
        },
        "grid": {"left": "15%", "right": "8%", "top": "6%", "bottom": "8%", "containLabel": False},
        "xAxis": {
            "type": "value",
            "axisLabel": {"color": "#666", "fontFamily": "IBM Plex Mono", "fontSize": 10,
                          "formatter": "function(v){ return v.toFixed(1)+'%'; }"},
            "splitLine": {"lineStyle": {"color": "#1a1a2e"}},
            "axisLine": {"lineStyle": {"color": "#2a313c"}}
        },
        "yAxis": {
            "type": "category", "data": _tickers,
            "axisLabel": {"color": "#bbb", "fontFamily": "IBM Plex Mono", "fontSize": 11},
            "axisLine": {"lineStyle": {"color": "#2a313c"}}
        },
        "series": [{
            "type": "bar",
            "data": [{"value": d, "itemStyle": {"color": c}} for d, c in zip(_divergences, _colors)],
            "barMaxWidth": 30,
            "label": {
                "show": True,
                "position": "right",
                "formatter": "function(p){ return p.value.toFixed(2)+'%'; }",
                "color": "#888", "fontSize": 10, "fontFamily": "IBM Plex Mono"
            }
        }],
        "graphic": [
            {"type": "text", "left": "16%", "top": "2%",
             "style": {"text": "◀ OVERWEIGHT", "fill": "#f5a623", "fontSize": 10, "fontFamily": "IBM Plex Mono"}},
            {"type": "text", "right": "2%", "top": "2%",
             "style": {"text": "UNDERWEIGHT ▶", "fill": "#00ff88", "fontSize": 10, "fontFamily": "IBM Plex Mono"}}
        ]
    }
    st_echarts(options=rebal_option, height="400px", key="rebalancing_compare_echarts")

    info_section(
        "Deviation Monitor",
        "Current weight, policy target, max Sharpe target, and estimated value required to move each position toward max Sharpe.",
    )
    show_aggrid(
        _build_monitor_table(ctx["df"], policy_map, max_sharpe_map, ctx["base_currency"]),
        height=340,
        key="aggrid_rebalancing_monitor",
    )

    # ── Contribution Engine ────────────────────────────────────────────────────
    info_section(
        "Contribution Planner",
        "Enter how much you want to invest and the engine will tell you how to allocate it "
        "across your portfolio to move closer to the Max Sharpe target weights.",
    )

    from app_core import SUPPORTED_BASE_CCY
    col_amt, col_ccy, col_btn = st.columns([3, 1, 1])
    with col_amt:
        contribution_amount = st.number_input(
            "Contribution Amount",
            min_value=0.0,
            value=float(ctx.get("monthly_contribution", 1000.0)) or 1000.0,
            step=100.0,
            format="%.2f",
            label_visibility="collapsed",
        )
    with col_ccy:
        contribution_ccy = st.selectbox(
            "Currency",
            SUPPORTED_BASE_CCY,
            index=SUPPORTED_BASE_CCY.index(ctx["base_currency"]) if ctx["base_currency"] in SUPPORTED_BASE_CCY else 0,
            label_visibility="collapsed",
        )
    with col_btn:
        run_contribution = st.button("Calculate", use_container_width=True)

    if run_contribution or contribution_amount > 0:
        fx_prices = ctx.get("fx_prices", {})
        fx_hist = ctx.get("fx_hist", pd.DataFrame())
        base_currency = ctx["base_currency"]

        if contribution_ccy == base_currency:
            contribution_base = contribution_amount
        else:
            from app_core import get_fx_rate_current
            pair = f"{contribution_ccy}{base_currency}=X"
            rate = get_fx_rate_current(contribution_ccy, base_currency, fx_prices, fx_hist)
            if rate and rate > 0:
                contribution_base = contribution_amount * rate
            else:
                st.warning(f"Could not convert {contribution_ccy} → {base_currency}. Treating as {base_currency}.")
                contribution_base = contribution_amount

        if contribution_base > 0:
            plan_df = _build_contribution_plan(
                ctx["df"], max_sharpe_map, contribution_base, base_currency
            )

            if not plan_df.empty:
                total_allocated = plan_df[f"Buy ({base_currency})"].sum()
                unallocated = max(contribution_base - total_allocated, 0.0)

                m1, m2, m3 = st.columns(3)
                info_metric(
                    m1,
                    f"Contribution ({contribution_ccy})",
                    f"{contribution_ccy} {contribution_amount:,.2f}",
                    "Amount entered by the user.",
                )
                info_metric(
                    m2,
                    f"Allocated ({base_currency})",
                    f"{base_currency} {total_allocated:,.2f}",
                    "Total amount allocated across tickers.",
                )
                info_metric(
                    m3,
                    f"Unallocated ({base_currency})",
                    f"{base_currency} {unallocated:,.2f}",
                    "Remaining cash after allocation (all targets already met or rounding).",
                )

                show_aggrid(plan_df, height=280, key="aggrid_rebalancing_plan")

                fig_contrib = go.Figure()
                fig_contrib.add_bar(
                    x=plan_df["Ticker"],
                    y=plan_df["Current Weight %"],
                    name="Current Weight %",
                )
                fig_contrib.add_bar(
                    x=plan_df["Ticker"],
                    y=plan_df["Resulting Weight %"],
                    name="Resulting Weight %",
                )
                fig_contrib.add_bar(
                    x=plan_df["Ticker"],
                    y=plan_df["Target Weight %"],
                    name="Max Sharpe Target %",
                )
                fig_contrib.update_layout(
                    barmode="group",
                    paper_bgcolor="#0b0f14",
                    plot_bgcolor="#0b0f14",
                    font=dict(color="#e6e6e6"),
                    height=350,
                    margin=dict(t=20, b=20, l=20, r=20),
                    xaxis_title="Ticker",
                    yaxis_title="Weight %",
                    legend=dict(orientation="h", y=1.08, x=0.0),
                )
                st.plotly_chart(fig_contrib, use_container_width=True, key="contribution_chart")

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

        monthly_contrib = float(ctx.get("monthly_contribution", 0.0))
        if monthly_contrib > 0:
            months_needed = required_contribution / monthly_contrib
            k3, k4 = st.columns(2)
            info_metric(
                k3,
                "Months at Your Contribution",
                f"{months_needed:.1f} months",
                f"At {ctx['base_currency']} {monthly_contrib:,.0f}/month (your saved monthly contribution).",
            )
            info_metric(
                k4,
                "Your Monthly Contribution",
                f"{ctx['base_currency']} {monthly_contrib:,.0f}",
                "Set in Investment Horizon → Save as Defaults.",
            )
        elif required_contribution > 0:
            st.caption("💡 Set a monthly contribution in **Investment Horizon → Financial Independence** and save as defaults to see how many months until you reach Max Sharpe.")

        show_aggrid(required_df, height=300, key="aggrid_rebalancing_required")

    info_section(
        "Live Validation Warning",
        "Final validation layer for prices, benchmark, frontier availability, and target consistency.",
    )
    show_aggrid(
        _build_live_validation_table(ctx, policy_map, max_sharpe_map),
        height=220,
        key="aggrid_rebalancing_validation",
    )