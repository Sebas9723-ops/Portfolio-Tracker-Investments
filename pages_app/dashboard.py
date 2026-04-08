import datetime
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
from pages_app.portfolio_history import (
    build_allocation_history_figure,
    build_monthly_snapshot_summary,
    build_snapshot_report_table,
    build_snapshot_timeline_figure,
    filter_snapshots_for_context,
    load_portfolio_snapshots,
    save_portfolio_snapshot,
)


def _render_control_buttons(ctx):
    if ctx["mode"] == "Private" and ctx["authenticated"]:
        c1, c2, c3, c4 = st.columns(4)

        if c1.button("Refresh Market Data", use_container_width=True):
            st.rerun()

        if c2.button("Recalculate Portfolio", use_container_width=True):
            st.rerun()

        if c3.button("Sync Private Data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        if c4.button("Save Portfolio Snapshot", use_container_width=True):
            try:
                save_portfolio_snapshot(ctx, notes="Manual dashboard snapshot")
                st.cache_data.clear()
                st.session_state["dashboard_snapshot_banner"] = "Portfolio snapshot saved successfully."
                st.rerun()
            except Exception as e:
                st.error(f"Could not save portfolio snapshot: {e}")
    else:
        c1, c2 = st.columns(2)

        if c1.button("Refresh Market Data", use_container_width=True):
            st.rerun()

        if c2.button("Recalculate Portfolio", use_container_width=True):
            st.rerun()


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


def _estimate_required_contribution_without_selling(df, target_map):
    if df.empty:
        return None, "No holdings data."

    total_value = float(df["Value"].sum())
    required_contribution = 0.0

    for _, row in df.iterrows():
        ticker = str(row["Ticker"])
        current_value = float(row["Value"])
        target_weight = float(target_map.get(ticker, 0.0))

        if current_value <= 1e-12:
            continue

        if target_weight <= 1e-12:
            return None, f"{ticker} has positive value but zero recommended weight."

        needed = current_value / target_weight - total_value
        required_contribution = max(required_contribution, needed)

    return max(required_contribution, 0.0), ""


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


def _build_data_quality_table(ctx):
    rows = []
    df = ctx.get("df", pd.DataFrame()).copy()

    if df.empty:
        rows.append({"Level": "Critical", "Check": "Portfolio", "Message": "No portfolio holdings available."})
        return pd.DataFrame(rows)

    if pd.to_numeric(df["Price"], errors="coerce").fillna(0.0).le(0).any():
        bad = df[pd.to_numeric(df["Price"], errors="coerce").fillna(0.0).le(0)]["Ticker"].astype(str).tolist()
        rows.append({"Level": "Critical", "Check": "Pricing", "Message": f"Missing or zero market price for: {', '.join(bad)}."})

    if pd.to_numeric(df["Shares"], errors="coerce").fillna(0.0).lt(0).any():
        bad = df[pd.to_numeric(df["Shares"], errors="coerce").fillna(0.0).lt(0)]["Ticker"].astype(str).tolist()
        rows.append({"Level": "Critical", "Check": "Shares", "Message": f"Negative shares detected for: {', '.join(bad)}."})

    if df["Ticker"].astype(str).duplicated().any():
        dup = df.loc[df["Ticker"].astype(str).duplicated(), "Ticker"].astype(str).tolist()
        rows.append({"Level": "Warning", "Check": "Tickers", "Message": f"Duplicate ticker rows detected: {', '.join(dup)}."})

    cash_df = ctx.get("cash_display_df", pd.DataFrame()).copy()
    if not cash_df.empty and "Amount" in cash_df.columns:
        negative_cash = cash_df[pd.to_numeric(cash_df["Amount"], errors="coerce").fillna(0.0) < 0]
        if not negative_cash.empty:
            ccy = negative_cash["Currency"].astype(str).tolist() if "Currency" in negative_cash.columns else ["Unknown"]
            rows.append({"Level": "Warning", "Check": "Cash", "Message": f"Negative cash balance detected in: {', '.join(ccy)}."})

    # Frontier is computed on-demand on the Optimization page

    bench = ctx.get("benchmark_returns")
    if bench is None or bench.empty:
        rows.append({"Level": "Info", "Check": "Benchmark", "Message": "Benchmark return series is not available."})

    if not rows:
        rows.append({"Level": "OK", "Check": "Data Quality", "Message": "No obvious data quality issues detected."})

    out = pd.DataFrame(rows)
    order = {"Critical": 0, "Warning": 1, "Info": 2, "OK": 3}
    out["__rank"] = out["Level"].map(order).fillna(9)
    out = out.sort_values(["__rank", "Check"]).drop(columns="__rank").reset_index(drop=True)
    return out


def _build_decision_summary(ctx):
    df = ctx["df"].copy()
    if df.empty:
        return pd.DataFrame()

    target_map, source_label = _get_max_sharpe_target_map(ctx, df)
    actions_df, _ = _build_top_actions_table(ctx)
    total_portfolio_value = float(ctx["total_portfolio_value"])
    cash_total_value = float(ctx["cash_total_value"])
    cash_pct = (cash_total_value / total_portfolio_value * 100.0) if total_portfolio_value > 0 else 0.0
    required_contribution, contribution_note = _estimate_required_contribution_without_selling(df, target_map)

    rows = []

    rows.append(
        {
            "Priority": 1,
            "Decision": f"Use {source_label}",
            "Rationale": "Current recommendation source driving portfolio actions.",
        }
    )

    if not actions_df.empty:
        top_row = actions_df.iloc[0]
        rows.append(
            {
                "Priority": 2,
                "Decision": f"{top_row['Action']} {top_row['Ticker']}",
                "Rationale": f"Largest drift is {top_row['Gap %']:+.2f}% versus recommendation.",
            }
        )
    else:
        rows.append(
            {
                "Priority": 2,
                "Decision": "No immediate rebalance action",
                "Rationale": "No material drift detected versus current recommendation.",
            }
        )

    if required_contribution is None:
        rows.append(
            {
                "Priority": 3,
                "Decision": "Buy-only transition not feasible",
                "Rationale": contribution_note,
            }
        )
    else:
        rows.append(
            {
                "Priority": 3,
                "Decision": f"Buy-only contribution: {ctx['base_currency']} {required_contribution:,.2f}",
                "Rationale": "Estimated cash needed to reach recommended weights without selling.",
            }
        )

    rows.append(
        {
            "Priority": 4,
            "Decision": f"Cash ratio: {cash_pct:.2f}%",
            "Rationale": "Monitor whether cash drag is becoming meaningful.",
        }
    )

    rows.append(
        {
            "Priority": 5,
            "Decision": f"Current Sharpe: {ctx['sharpe']:.2f}",
            "Rationale": "Use together with recommended Sharpe in Rebalancing.",
        }
    )

    return pd.DataFrame(rows)


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


def _build_snapshot_metrics(snapshots_df):
    if snapshots_df is None or snapshots_df.empty:
        return {
            "count": 0,
            "latest": 0.0,
            "change_vs_prev": 0.0,
            "change_30d": 0.0,
        }

    work = snapshots_df.copy().sort_values("timestamp").reset_index(drop=True)
    latest_value = float(work.iloc[-1]["total_portfolio_value"])
    change_vs_prev = 0.0

    if len(work) >= 2:
        change_vs_prev = latest_value - float(work.iloc[-2]["total_portfolio_value"])

    change_30d = 0.0
    latest_ts = pd.to_datetime(work.iloc[-1]["timestamp"], errors="coerce")
    if pd.notna(latest_ts):
        window = work[pd.to_datetime(work["timestamp"], errors="coerce") >= latest_ts - pd.Timedelta(days=30)].copy()
        if len(window) >= 2:
            change_30d = latest_value - float(window.iloc[0]["total_portfolio_value"])

    return {
        "count": int(len(work)),
        "latest": latest_value,
        "change_vs_prev": change_vs_prev,
        "change_30d": change_30d,
    }


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

    @st.fragment(run_every=300)
    def _live():
        st.caption(f"Last refreshed: {datetime.datetime.now().strftime('%H:%M:%S')}")

        render_private_dashboard_logo(
            mode=ctx["mode"],
            authenticated=ctx["authenticated"],
        )

        render_status_bar(
            mode=ctx["mode"],
            base_currency=ctx["base_currency"],
            profile=ctx["profile"],
            tc_model="—",
            sheets_ok=ctx["positions_sheet_available"],
        )

        _render_control_buttons(ctx)

        snapshot_banner = st.session_state.pop("dashboard_snapshot_banner", None)
        if snapshot_banner:
            st.success(snapshot_banner)

        render_market_clocks()

        c1, c2, c3, c4 = st.columns(4)
        info_metric(c1, "Total Portfolio", f"{ctx['base_currency']} {ctx['total_portfolio_value']:,.2f}", "Holdings plus cash.")
        info_metric(c2, "Invested Assets", f"{ctx['base_currency']} {ctx['holdings_value']:,.2f}", "Market value of invested holdings.")
        info_metric(c3, "Cash", f"{ctx['base_currency']} {ctx['cash_total_value']:,.2f}", "Cash balances converted to base currency.")
        info_metric(c4, "Unrealized PnL", f"{ctx['base_currency']} {ctx['unrealized_pnl']:,.2f}", "Open profit and loss.")

        c5, c6, c7, c8, c9 = st.columns(5)
        info_metric(c5, "Return", f"{ctx['total_return']:.2%}", "Cumulative return over the available history.")
        info_metric(c6, "Volatility", f"{ctx['volatility']:.2%}", "Annualized portfolio volatility.")
        info_metric(c7, "Sharpe Ratio", f"{ctx['sharpe']:.2f}", "Portfolio Sharpe ratio.")
        invested_cap = float(ctx.get("invested_capital", 0.0))
        total_pnl = float(ctx.get("unrealized_pnl", 0.0)) + float(ctx.get("realized_pnl", 0.0))
        simple_return = total_pnl / invested_cap if invested_cap > 0 else None
        sr_str = f"{simple_return:.2%}" if simple_return is not None else "—"
        info_metric(c8, "Simple Return", sr_str, "Total gain vs cost basis (unrealized + realized). Not annualized.")
        ccy = ctx.get("base_currency", "")
        pnl_str = f"{ccy} {total_pnl:+,.2f}" if invested_cap > 0 else "—"
        info_metric(c9, "Total P&L", pnl_str, "Unrealized + realized gain/loss in base currency.")

        summary_df = _build_decision_summary(ctx)
        actions_df, source_label = _build_top_actions_table(ctx)
        alerts_df = _build_alerts_table(ctx)
        quality_df = _build_data_quality_table(ctx)

        info_section(
            "Decision Summary",
            "Clean executive summary of what matters most right now.",
        )
        st.dataframe(summary_df, use_container_width=True, height=240)

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

        with st.expander("Data Quality Checks", expanded=False):
            st.caption("Validation checks for prices, shares, benchmark, and cash balances.")
            st.dataframe(quality_df, use_container_width=True, height=240)

        if ctx["mode"] == "Private" and ctx["authenticated"]:
            with st.expander("Recent Audit Trail", expanded=False):
                st.caption("Most recent changes made through Private Manager, written automatically into the Transactions ledger.")
                audit_df = _build_recent_audit_trail(ctx, limit=8)
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
                key="dashboard_performance_pct_chart_phase5a",
            )

        if ctx["mode"] == "Private" and ctx["authenticated"]:
            try:
                all_snapshots = load_portfolio_snapshots()
                snapshots_df = filter_snapshots_for_context(
                    all_snapshots,
                    mode=ctx["mode"],
                    base_currency=ctx["base_currency"],
                )
            except Exception as e:
                snapshots_df = pd.DataFrame()
                st.warning(f"Snapshot history could not be loaded: {e}")

            snapshot_metrics = _build_snapshot_metrics(snapshots_df)

            info_section(
                "Snapshot History",
                "Historical memory of the portfolio. Use this to track portfolio evolution over time.",
            )

            s1, s2, s3, s4 = st.columns(4)
            info_metric(s1, "Snapshots Stored", str(snapshot_metrics["count"]), "Number of saved snapshots for this mode and base currency.")
            info_metric(s2, "Latest Snapshot", f"{ctx['base_currency']} {snapshot_metrics['latest']:,.2f}", "Most recent saved total portfolio value.")
            info_metric(s3, "Change vs Previous", f"{ctx['base_currency']} {snapshot_metrics['change_vs_prev']:,.2f}", "Absolute change versus the prior snapshot.")
            info_metric(s4, "30D Snapshot Change", f"{ctx['base_currency']} {snapshot_metrics['change_30d']:,.2f}", "Absolute change over the last 30 days using saved snapshots.")

            timeline_fig = build_snapshot_timeline_figure(snapshots_df, ctx["base_currency"])
            allocation_fig = build_allocation_history_figure(snapshots_df, top_n=5)
            report_df = build_snapshot_report_table(snapshots_df)
            monthly_df = build_monthly_snapshot_summary(snapshots_df)

            tab_charts, tab_report, tab_monthly = st.tabs(["Charts", "Full Report", "Monthly Summary"])

            with tab_charts:
                left3, right3 = st.columns(2)
                with left3:
                    st.caption("Portfolio Timeline — total value, holdings, and cash")
                    if timeline_fig is None:
                        st.info("No snapshots yet. Use Save Portfolio Snapshot to start building history.")
                    else:
                        st.plotly_chart(timeline_fig, use_container_width=True, key="snapshot_timeline_chart_phase5a")
                with right3:
                    st.caption("Allocation Timeline — weight history for largest positions")
                    if allocation_fig is None:
                        st.info("Allocation history will appear after snapshots are stored.")
                    else:
                        st.plotly_chart(allocation_fig, use_container_width=True, key="allocation_timeline_chart_phase5a")

            with tab_report:
                if report_df.empty:
                    st.info("No snapshot report available yet.")
                else:
                    st.dataframe(report_df, use_container_width=True, height=380)

            with tab_monthly:
                if monthly_df.empty:
                    st.info("No monthly summary available yet.")
                else:
                    st.dataframe(monthly_df, use_container_width=True, height=320)
    _live()
