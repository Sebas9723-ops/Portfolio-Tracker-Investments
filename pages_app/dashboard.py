import datetime
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_echarts import st_echarts

from utils_aggrid import show_aggrid

from app_core import (
    build_portfolio_df,
    fetch_day_change_for_tickers,
    info_metric,
    info_section,
    render_page_title,
    render_private_dashboard_logo,
    render_status_bar,
)

_MARKET_WATCH = ("VOO", "QQQM", "QQQ")
_DROP_THRESHOLD = -0.05


@st.cache_data(ttl=300, show_spinner=False)
def _cached_day_changes(tickers: tuple) -> dict:
    return fetch_day_change_for_tickers(tickers)


def _render_drop_alerts(ctx):
    """Show a warning banner if S&P 500, NASDAQ, or any portfolio position dropped >5%."""
    df = ctx.get("df", pd.DataFrame())
    asset_returns = ctx.get("asset_returns")
    portfolio_tickers = set(df["Ticker"].tolist()) if not df.empty else set()

    # Check portfolio tickers via existing asset_returns (already loaded)
    drops = []
    if asset_returns is not None and not asset_returns.empty:
        for t in portfolio_tickers:
            if t in asset_returns.columns:
                col = asset_returns[t].dropna()
                if len(col) >= 1:
                    ret = float(col.iloc[-1])
                    if ret <= _DROP_THRESHOLD:
                        drops.append({"ticker": t, "change": ret, "in_portfolio": True})

    # Check market indices (VOO/QQQM/QQQ) even if not in portfolio
    extra = tuple(t for t in _MARKET_WATCH if t not in portfolio_tickers)
    if extra:
        market_changes = _cached_day_changes(extra)
        for t, ret in market_changes.items():
            if ret <= _DROP_THRESHOLD:
                drops.append({"ticker": t, "change": ret, "in_portfolio": False})

    for d in drops:
        label = "S&P 500" if d["ticker"] == "VOO" else ("NASDAQ" if d["ticker"] in ("QQQM", "QQQ") else d["ticker"])
        is_market_index = d["ticker"] in _MARKET_WATCH
        suggestion = " — Consider doubling your contribution this month on S&P 500 and NASDAQ." if is_market_index else ""
        st.warning(
            f"**{label}** dropped {d['change']:.2%} today.{suggestion}",
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

    # Portfolio — solid bright line with gradient fill
    fig.add_scatter(
        x=portfolio_cum.index,
        y=portfolio_cum,
        mode="lines",
        name=portfolio_name,
        line=dict(color="#00ff88", width=2),
        fill="tozeroy",
        fillcolor="rgba(0,255,136,0.12)",
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

            # VOO — dashed grey line
            fig.add_scatter(
                x=voo_cum.index,
                y=voo_cum,
                mode="lines",
                name=voo_name,
                line=dict(color="#888888", width=1.5, dash="dash"),
                hovertemplate="%{x|%Y-%m-%d}<br>VOO: %{y:.2%}<extra></extra>",
            )

    fig.update_layout(
        paper_bgcolor="#0a0a0a",
        plot_bgcolor="#0a0a0a",
        font=dict(color="#e6e6e6", family="IBM Plex Mono"),
        height=420,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis=dict(
            title="Date",
            gridcolor="rgba(255,255,255,0.06)",
            showspikes=True,
            spikemode="across",
            spikesnap="cursor",
            spikecolor="#444",
            spikethickness=1,
        ),
        yaxis=dict(
            title="Return",
            tickformat=".0%",
            gridcolor="rgba(255,255,255,0.06)",
        ),
        hovermode="x unified",
        legend=dict(orientation="h", y=1.08, x=0.0),
    )
    return fig


def render_dashboard(ctx):
    render_page_title("Dashboard")

    @st.fragment(run_every=60)
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

        # Re-fetch live prices so metrics stay in sync with Portfolio page
        tickers = list(ctx["updated_portfolio"].keys())
        if ctx["app_scope"] == "private":
            from data_providers import get_prices_private
            fresh_prices = get_prices_private(tickers)
        else:
            from utils import get_prices
            fresh_prices = get_prices(tickers)

        _, _, pnl = build_portfolio_df(
            updated_portfolio=ctx["updated_portfolio"],
            live_prices_native=fresh_prices,
            asset_hist_native=pd.DataFrame(),
            fx_prices=ctx["fx_prices"],
            fx_hist=ctx["fx_hist"],
            base_currency=ctx["base_currency"],
            tx_stats_map=ctx.get("tx_stats_map", {}),
            fx_fallback=ctx.get("fx_rate_cache"),
        )

        holdings_value = pnl["holdings_value"]
        cash_value = float(ctx["cash_total_value"])
        total_portfolio = holdings_value + cash_value
        unrealized_pnl = pnl["unrealized_pnl"]
        invested_cap = pnl["invested_capital"]
        total_pnl = unrealized_pnl + pnl.get("realized_pnl", 0.0)

        ccy = ctx.get("base_currency", "")
        c1, c2, c3, c4 = st.columns(4)
        info_metric(c1, "Total Portfolio", f"{ccy} {total_portfolio:,.2f}", "Holdings plus cash.",
                    accent_color="#f5a623")
        info_metric(c2, "Invested Assets", f"{ccy} {holdings_value:,.2f}", "Market value of invested holdings.",
                    accent_color="#f5a623")
        info_metric(c3, "Cash", f"{ccy} {cash_value:,.2f}", "Cash balances converted to base currency.",
                    accent_color="#f5a623")
        info_metric(c4, "Unrealized PnL", f"{ccy} {unrealized_pnl:,.2f}", "Open profit and loss.",
                    accent_color="#00ff88" if unrealized_pnl >= 0 else "#ff4444")

        simple_return = total_pnl / invested_cap if invested_cap > 0 else None
        sr_str = f"{simple_return:.2%}" if simple_return is not None else "—"
        pnl_str = f"{ccy} {total_pnl:+,.2f}" if invested_cap > 0 else "—"
        c5, c6, c7, c8, c9 = st.columns(5)
        _ret_pos = ctx['total_return'] >= 0
        info_metric(c5, "Return", f"{ctx['total_return']:.2%}", "Cumulative return over the available history.",
                    accent_color="#00ff88" if _ret_pos else "#ff4444")
        info_metric(c6, "Volatility", f"{ctx['volatility']:.2%}", "Annualized portfolio volatility.",
                    accent_color="#ff4444" if ctx['volatility'] > 0.20 else "#00ff88")
        _sharpe = float(ctx['sharpe'])
        info_metric(c7, "Sharpe Ratio", f"{_sharpe:.2f}", "Portfolio Sharpe ratio.",
                    accent_color="#00ff88" if _sharpe >= 1.0 else "#ff4444",
                    sharpe_value=_sharpe, sharpe_target=3.0)
        info_metric(c8, "Simple Return", sr_str, "Total gain vs cost basis (unrealized + realized). Not annualized.",
                    accent_color="#00ff88" if simple_return and simple_return >= 0 else "#ff4444")
        info_metric(c9, "Total P&L", pnl_str, "Unrealized + realized gain/loss in base currency.",
                    accent_color="#00ff88" if total_pnl >= 0 else "#ff4444")

        _render_drop_alerts(ctx)

        summary_df = _build_decision_summary(ctx)
        actions_df, source_label = _build_top_actions_table(ctx)
        alerts_df = _build_alerts_table(ctx)
        # Critical alerts live in Custom Alerts — show only Warning and Info here
        if not alerts_df.empty and "Level" in alerts_df.columns:
            alerts_df = alerts_df[alerts_df["Level"] != "Critical"].reset_index(drop=True)
        quality_df = _build_data_quality_table(ctx)

        info_section(
            "Decision Summary",
            "Clean executive summary of what matters most right now.",
        )
        show_aggrid(summary_df, height=240, key="aggrid_dashboard_summary")

        left, right = st.columns(2)

        with left:
            info_section(
                "Top Actions",
                f"Largest drifts versus current recommendation source: {source_label}.",
            )
            if actions_df.empty:
                st.success("No material drifts detected versus the current recommendation.")
            else:
                show_aggrid(actions_df, height=260, key="aggrid_dashboard_actions")

        with right:
            info_section(
                "Active Alerts",
                "Priority alerts for drift, concentration, cash drag, and risk conditions.",
            )
            if alerts_df.empty:
                st.success("No active alerts.")
            else:
                show_aggrid(alerts_df, height=260, key="aggrid_dashboard_alerts")

        with st.expander("Data Quality Checks", expanded=False):
            st.caption("Validation checks for prices, shares, benchmark, and cash balances.")
            show_aggrid(quality_df, height=240, key="aggrid_dashboard_quality")

        if ctx["mode"] == "Private" and ctx["authenticated"]:
            with st.expander("Recent Audit Trail", expanded=False):
                st.caption("Most recent changes made through Private Manager, written automatically into the Transactions ledger.")
                audit_df = _build_recent_audit_trail(ctx, limit=8)
                if audit_df.empty:
                    st.info("No Private Manager audit entries found.")
                else:
                    show_aggrid(audit_df, height=260, key="aggrid_dashboard_audit")

        portfolio_returns = ctx.get("portfolio_returns")
        benchmark_returns = ctx.get("benchmark_returns")
        if portfolio_returns is not None and not portfolio_returns.empty:
            info_section(
                "Performance vs Benchmark",
                "Portfolio cumulative return versus VOO, displayed in percentage terms.",
            )
            portfolio_ret = (1 + portfolio_returns).cumprod() - 1
            bench_ret = None
            if benchmark_returns is not None and not benchmark_returns.empty:
                aligned = pd.concat(
                    [portfolio_returns.rename("Portfolio"), benchmark_returns.rename("VOO")],
                    axis=1,
                ).dropna()
                if not aligned.empty:
                    bench_ret = (1 + aligned["VOO"]).cumprod() - 1
                    portfolio_ret = (1 + aligned["Portfolio"]).cumprod() - 1

            dates = [str(d)[:10] for d in portfolio_ret.index.tolist()]
            port_vals = [round(float(v) * 100, 2) for v in portfolio_ret.tolist()]
            bench_vals = [round(float(v) * 100, 2) for v in bench_ret.tolist()] if bench_ret is not None else []

            perf_option = {
                "backgroundColor": "#0a0a0a",
                "tooltip": {
                    "trigger": "axis",
                    "axisPointer": {"type": "cross", "crossStyle": {"color": "#555"}},
                    "backgroundColor": "#1a1a2e",
                    "borderColor": "#2a313c",
                    "textStyle": {"color": "#e6e6e6", "fontFamily": "IBM Plex Mono"},
                    "valueFormatter": "{value}%"
                },
                "legend": {
                    "data": ["Portfolio", "VOO Benchmark"],
                    "textStyle": {"color": "#888", "fontFamily": "IBM Plex Mono"},
                    "top": 4
                },
                "grid": {"left": "3%", "right": "3%", "bottom": "8%", "top": "12%", "containLabel": True},
                "dataZoom": [
                    {"type": "inside", "start": 0, "end": 100},
                    {"type": "slider", "start": 0, "end": 100, "height": 18, "bottom": 0,
                     "borderColor": "#2a313c", "fillerColor": "rgba(245,166,35,0.1)",
                     "handleStyle": {"color": "#f5a623"}}
                ],
                "xAxis": {
                    "type": "category", "data": dates, "boundaryGap": False,
                    "axisLine": {"lineStyle": {"color": "#2a313c"}},
                    "axisLabel": {"color": "#666", "fontFamily": "IBM Plex Mono", "fontSize": 10},
                    "splitLine": {"show": False}
                },
                "yAxis": {
                    "type": "value",
                    "axisLabel": {"color": "#666", "fontFamily": "IBM Plex Mono", "fontSize": 10,
                                  "formatter": "{value}%"},
                    "splitLine": {"lineStyle": {"color": "#1a1a2e"}},
                    "axisLine": {"show": False}
                },
                "series": [
                    {
                        "name": "Portfolio",
                        "type": "line", "data": port_vals, "smooth": True,
                        "symbol": "none", "lineStyle": {"color": "#f5a623", "width": 2},
                        "itemStyle": {"color": "#f5a623"},
                        "areaStyle": {
                            "color": {
                                "type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1,
                                "colorStops": [
                                    {"offset": 0, "color": "rgba(245,166,35,0.25)"},
                                    {"offset": 1, "color": "rgba(245,166,35,0.01)"}
                                ]
                            }
                        }
                    },
                    {
                        "name": "VOO Benchmark",
                        "type": "line", "data": bench_vals, "smooth": True,
                        "symbol": "none",
                        "lineStyle": {"color": "#4a9eff", "width": 1.5, "type": "dashed"},
                        "itemStyle": {"color": "#4a9eff"}
                    }
                ]
            }
            st_echarts(options=perf_option, height="340px", key="dashboard_perf_echarts")

        if ctx["mode"] == "Private" and ctx["authenticated"]:
            try:
                all_snapshots = load_portfolio_snapshots()
                snapshots_df = filter_snapshots_for_context(
                    all_snapshots,
                    mode=ctx["mode"],
                    base_currency=ctx["base_currency"],
                )
                # Auto-save one snapshot per day if none exists for today
                import datetime as _dt_snap
                today_str = str(_dt_snap.date.today())
                has_today = (
                    not snapshots_df.empty
                    and "snapshot_date" in snapshots_df.columns
                    and snapshots_df["snapshot_date"].astype(str).str[:10].eq(today_str).any()
                )
                if not has_today:
                    try:
                        save_portfolio_snapshot(ctx, notes="auto-daily")
                        # Reload after auto-save
                        all_snapshots = load_portfolio_snapshots()
                        snapshots_df = filter_snapshots_for_context(
                            all_snapshots,
                            mode=ctx["mode"],
                            base_currency=ctx["base_currency"],
                        )
                    except Exception:
                        pass
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
                    show_aggrid(report_df, height=380, key="aggrid_dashboard_report")

            with tab_monthly:
                if monthly_df.empty:
                    st.info("No monthly summary available yet.")
                else:
                    show_aggrid(monthly_df, height=320, key="aggrid_dashboard_monthly")
    _live()
