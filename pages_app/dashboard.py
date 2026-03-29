import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core import (
    info_metric,
    info_section,
    render_market_clocks,
    render_page_title,
    render_private_dashboard_logo,
    render_status_bar,
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


def _build_top_actions_table(ctx):
    df = ctx["df"].copy()
    if df.empty:
        return pd.DataFrame(), "Policy Target"

    target_map, source_label = _get_max_sharpe_target_map(ctx, df)
    holdings_total = float(df["Value"].sum())

    df["Recommended Weight %"] = df["Ticker"].map(lambda t: float(target_map.get(t, 0.0)) * 100.0)
    df["Gap %"] = df["Weight %"] - df["Recommended Weight %"]

    if holdings_total > 0:
        df[f"Trade To Recommended ({ctx['base_currency']})"] = (
            (df["Recommended Weight %"] - df["Weight %"]) / 100.0 * holdings_total
        )
    else:
        df[f"Trade To Recommended ({ctx['base_currency']})"] = 0.0

    df["Action"] = np.where(
        df["Gap %"] > 0,
        "Trim / Sell",
        np.where(df["Gap %"] < 0, "Buy / Add", "Hold"),
    )

    out = df[
        [
            "Ticker",
            "Name",
            "Action",
            "Weight %",
            "Recommended Weight %",
            "Gap %",
            f"Trade To Recommended ({ctx['base_currency']})",
        ]
    ].copy()

    out = out[out["Action"] != "Hold"].copy()
    out = out.sort_values("Gap %", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)
    return out.head(5), source_label


def _build_alerts_table(ctx):
    df = ctx["df"].copy()
    if df.empty:
        return pd.DataFrame()

    target_map, _ = _get_max_sharpe_target_map(ctx, df)

    tolerance_pct = 3.0
    concentration_pct = 35.0
    cash_alert_pct = 8.0

    rows = []

    for _, row in df.iterrows():
        ticker = str(row["Ticker"])
        name = str(row["Name"])
        weight_pct = float(row["Weight %"])
        recommended_pct = float(target_map.get(ticker, 0.0)) * 100.0
        gap_pct = weight_pct - recommended_pct

        if abs(gap_pct) > tolerance_pct:
            level = "Critical" if abs(gap_pct) >= 6.0 else "Warning"
            rows.append(
                {
                    "Level": level,
                    "Item": ticker,
                    "Message": f"{name} is {gap_pct:+.2f}% away from recommended weight.",
                }
            )

        if weight_pct > concentration_pct:
            rows.append(
                {
                    "Level": "Warning",
                    "Item": ticker,
                    "Message": f"{name} concentration is {weight_pct:.2f}%, above {concentration_pct:.2f}%.",
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

    if float(ctx["max_drawdown"]) < -0.15:
        rows.append(
            {
                "Level": "Info",
                "Item": "Drawdown",
                "Message": f"Maximum drawdown is {ctx['max_drawdown']:.2%}.",
            }
        )

    if float(ctx["volatility"]) > 0.20:
        rows.append(
            {
                "Level": "Info",
                "Item": "Volatility",
                "Message": f"Annualized volatility is {ctx['volatility']:.2%}.",
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    order = {"Critical": 0, "Warning": 1, "Info": 2}
    out["__rank"] = out["Level"].map(order).fillna(9)
    out = out.sort_values(["__rank", "Item"]).drop(columns="__rank").reset_index(drop=True)
    return out


def _build_recent_audit_trail(ctx, limit=8):
    tx_df = ctx.get("transactions_df", pd.DataFrame()).copy()
    if tx_df.empty:
        return pd.DataFrame()

    work = tx_df.copy()
    work["notes"] = work["notes"].fillna("").astype(str)
    work = work[work["notes"].str.contains("Private Manager share adjustment", case=False, na=False)].copy()

    if work.empty:
        return pd.DataFrame()

    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work["shares"] = pd.to_numeric(work["shares"], errors="coerce").fillna(0.0)
    work["price"] = pd.to_numeric(work["price"], errors="coerce").fillna(0.0)
    work["fees"] = pd.to_numeric(work["fees"], errors="coerce").fillna(0.0)
    work["gross_value"] = work["shares"] * work["price"]

    display = work.rename(
        columns={
            "date": "Date",
            "ticker": "Ticker",
            "type": "Type",
            "shares": "Shares",
            "price": "Price",
            "fees": "Fees",
            "notes": "Notes",
            "gross_value": "Gross Value",
        }
    ).copy()

    display["Date"] = pd.to_datetime(display["Date"], errors="coerce").dt.date
    display = display.sort_values("Date", ascending=False).reset_index(drop=True)

    return display[["Date", "Ticker", "Type", "Shares", "Price", "Gross Value", "Fees", "Notes"]].head(limit)


def _build_performance_vs_benchmark_pct_chart(ctx):
    portfolio_returns = ctx.get("portfolio_returns")
    benchmark_returns = ctx.get("benchmark_returns")

    if portfolio_returns is None or portfolio_returns.empty:
        return None

    fig = go.Figure()

    portfolio_cum = (1 + portfolio_returns).cumprod() - 1
    portfolio_last = float(portfolio_cum.iloc[-1]) if not portfolio_cum.empty else 0.0
    portfolio_name = f"Portfolio ({portfolio_last:.2%})"

    fig.add_scatter(
        x=portfolio_cum.index,
        y=portfolio_cum,
        mode="lines",
        name=portfolio_name,
        hovertemplate="%{x|%Y-%m-%d}<br>Portfolio: %{y:.2%}<extra></extra>",
    )

    if benchmark_returns is not None and not benchmark_returns.empty:
        aligned = pd.concat(
            [portfolio_returns.rename("Portfolio"), benchmark_returns.rename("VOO")],
            axis=1,
        ).dropna()

        if not aligned.empty:
            voo_cum = (1 + aligned["VOO"]).cumprod() - 1
            voo_last = float(voo_cum.iloc[-1]) if not voo_cum.empty else 0.0
            voo_name = f"VOO ({voo_last:.2%})"

            fig.add_scatter(
                x=voo_cum.index,
                y=voo_cum,
                mode="lines",
                name=voo_name,
                hovertemplate="%{x|%Y-%m-%d}<br>VOO: %{y:.2%}<extra></extra>",
            )

    fig.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=420,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Date",
        yaxis_title="Return",
        yaxis=dict(tickformat=".0%"),
        legend=dict(orientation="h", y=1.08, x=0.0),
    )
    return fig


def render_dashboard(ctx):
    render_page_title("Dashboard")

    render_private_dashboard_logo(
        mode=ctx["mode"],
        authenticated=ctx["authenticated"],
    )

    render_status_bar(
        mode=ctx["mode"],
        base_currency=ctx["base_currency"],
        profile=ctx["profile"],
        tc_model=ctx["tc_model"],
        sheets_ok=ctx["positions_sheet_available"],
    )

    _render_control_buttons(ctx)
    render_market_clocks()

    c1, c2, c3, c4 = st.columns(4)
    info_metric(c1, "Total Portfolio", f"{ctx['base_currency']} {ctx['total_portfolio_value']:,.2f}", "Holdings plus cash.")
    info_metric(c2, "Invested Assets", f"{ctx['base_currency']} {ctx['holdings_value']:,.2f}", "Market value of invested holdings.")
    info_metric(c3, "Cash", f"{ctx['base_currency']} {ctx['cash_total_value']:,.2f}", "Cash balances converted to base currency.")
    info_metric(c4, "Unrealized PnL", f"{ctx['base_currency']} {ctx['unrealized_pnl']:,.2f}", "Open profit and loss.")

    c5, c6, c7, c8 = st.columns(4)
    info_metric(c5, "Return", f"{ctx['total_return']:.2%}", "Cumulative return over the available history.")
    info_metric(c6, "Volatility", f"{ctx['volatility']:.2%}", "Annualized portfolio volatility.")
    info_metric(c7, "Sharpe Ratio", f"{ctx['sharpe']:.2f}", "Portfolio Sharpe ratio.")
    info_metric(c8, "Realized PnL", f"{ctx['base_currency']} {ctx['realized_pnl']:,.2f}", "Closed profit and loss.")

    actions_df, source_label = _build_top_actions_table(ctx)
    alerts_df = _build_alerts_table(ctx)
    audit_df = _build_recent_audit_trail(ctx)

    left, right = st.columns(2)

    with left:
        info_section(
            "Top Actions",
            f"Largest drifts versus current recommendation source: {source_label}.",
        )
        if actions_df.empty:
            st.success("No material drifts detected versus the current recommendation.")
        else:
            st.dataframe(actions_df, use_container_width=True, height=260)

    with right:
        info_section(
            "Active Alerts",
            "Priority alerts for drift, concentration, cash drag, and risk conditions.",
        )
        if alerts_df.empty:
            st.success("No active alerts.")
        else:
            st.dataframe(alerts_df, use_container_width=True, height=260)

    info_section(
        "Recent Audit Trail",
        "Most recent changes made through Private Manager and written automatically into the Transactions ledger.",
    )
    if audit_df.empty:
        st.info("No Private Manager audit entries found.")
    else:
        st.dataframe(audit_df, use_container_width=True, height=260)

    perf_fig = _build_performance_vs_benchmark_pct_chart(ctx)
    if perf_fig is not None:
        info_section(
            "Performance vs Benchmark",
            "Portfolio cumulative return versus VOO, displayed in percentage terms.",
        )
        st.plotly_chart(
            perf_fig,
            use_container_width=True,
            key="dashboard_performance_pct_chart_phase4b",
        )