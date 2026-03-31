from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import pytz
import streamlit as st

from app_core import build_portfolio_df, info_metric, info_section, render_page_title


def _market_status(ticker: str) -> str:
    now_utc = datetime.now(pytz.utc)
    wd = now_utc.weekday()  # 0=Mon, 6=Sun
    t = ticker.upper()

    if t.endswith(".L"):
        tz, oh, om, ch, cm = pytz.timezone("Europe/London"), 8, 0, 16, 30
    elif t.endswith(".DE") or t.endswith(".AS"):
        tz, oh, om, ch, cm = pytz.timezone("Europe/Berlin"), 9, 0, 17, 30
    elif "." in t:
        tz, oh, om, ch, cm = pytz.timezone("Europe/Paris"), 9, 0, 17, 30
    else:
        tz, oh, om, ch, cm = pytz.timezone("America/New_York"), 9, 30, 16, 0

    if wd >= 5:
        return "Closed"
    now_local = now_utc.astimezone(tz)
    opens = now_local.replace(hour=oh, minute=om, second=0, microsecond=0)
    closes = now_local.replace(hour=ch, minute=cm, second=0, microsecond=0)
    return "Open" if opens <= now_local <= closes else "Closed"


def _build_intraday_table(df: pd.DataFrame, hist: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in df.iterrows():
        ticker = str(row["Ticker"])
        current = float(row["Native Price"])
        prev = current
        sparkline = []

        if not hist.empty and ticker in hist.columns:
            series = pd.to_numeric(hist[ticker], errors="coerce").dropna()
            if len(series) >= 2:
                prev = float(series.iloc[-2])
                sparkline = [round(v, 4) for v in series.iloc[-10:].tolist()]
            elif len(series) == 1:
                sparkline = [round(float(series.iloc[-1]), 4)]

        day_pct = (current / prev - 1) * 100 if prev > 0 else 0.0
        day_abs = current - prev

        rows.append({
            "Ticker": ticker,
            "Name": str(row["Name"]),
            "Ccy": str(row["Native Currency"]),
            "Price": round(current, 4),
            "Prev Close": round(prev, 4),
            "Day Δ": round(day_abs, 4),
            "Day Δ%": round(day_pct, 2),
            "Trend (10d)": sparkline,
            "Market": _market_status(ticker),
        })

    return pd.DataFrame(rows)


def _build_monthly_table(df: pd.DataFrame, hist: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in df.iterrows():
        ticker = str(row["Ticker"])
        current = float(row["Native Price"])
        month_ago = current

        if not hist.empty and ticker in hist.columns:
            series = pd.to_numeric(hist[ticker], errors="coerce").dropna()
            if not series.empty:
                cutoff = series.index[-1] - pd.DateOffset(days=30)
                past = series[series.index <= cutoff]
                if not past.empty:
                    month_ago = float(past.iloc[-1])

        month_pct = (current / month_ago - 1) * 100 if month_ago > 0 else 0.0
        month_abs = current - month_ago

        rows.append({
            "Ticker": ticker,
            "Name": str(row["Name"]),
            "Ccy": str(row["Native Currency"]),
            "Price": round(current, 4),
            "1M Ago": round(month_ago, 4),
            "Month Δ": round(month_abs, 4),
            "Month Δ%": round(month_pct, 2),
        })

    return pd.DataFrame(rows)


def _build_weights_vs_targets_chart(ctx):
    df = ctx["df"].copy()
    policy_map = ctx.get("policy_target_map", {})

    max_sharpe_map = {}
    if ctx.get("max_sharpe_row") is not None and ctx.get("usable"):
        usable = list(ctx["usable"])
        arr = ctx["max_sharpe_row"]["Weights"]
        max_sharpe_map = {t: 0.0 for t in df["Ticker"]}
        if len(arr) == len(usable):
            for ticker, weight in zip(usable, arr):
                max_sharpe_map[ticker] = float(weight)
    else:
        max_sharpe_map = dict(policy_map)

    fig = go.Figure()
    fig.add_bar(
        x=df["Ticker"],
        y=df["Weight %"],
        name="Current Weight %",
    )
    fig.add_bar(
        x=df["Ticker"],
        y=[float(max_sharpe_map.get(t, 0.0)) * 100.0 for t in df["Ticker"]],
        name="Max Sharpe %",
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


def _build_performance_vs_benchmark_chart(ctx):
    portfolio_returns = ctx.get("portfolio_returns")
    benchmark_returns = ctx.get("resolved_benchmark_returns")

    if portfolio_returns is None or portfolio_returns.empty:
        return None

    fig = go.Figure()
    portfolio_cum = (1 + portfolio_returns).cumprod() - 1
    fig.add_scatter(
        x=portfolio_cum.index,
        y=portfolio_cum,
        mode="lines",
        name=f"Portfolio ({portfolio_cum.iloc[-1]:.2%})",
        hovertemplate="%{x|%Y-%m-%d}<br>Portfolio: %{y:.2%}<extra></extra>",
    )

    if benchmark_returns is not None and not benchmark_returns.empty:
        aligned = (
            portfolio_returns.rename("Portfolio")
            .to_frame()
            .join(benchmark_returns.rename("VOO"), how="inner")
            .dropna()
        )

        if not aligned.empty:
            voo_cum = (1 + aligned["VOO"]).cumprod() - 1
            fig.add_scatter(
                x=voo_cum.index,
                y=voo_cum,
                mode="lines",
                name=f"VOO ({voo_cum.iloc[-1]:.2%})",
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


def _render_data_source_badges(ctx):
    info = ctx.get("data_source_info", {})
    if not info:
        return
    parts = []
    for ticker, label in info.items():
        is_live = label.startswith("Live")
        bg = "#0d3d0d" if is_live else "#0d2340"
        fg = "#4dff4d" if is_live else "#4db8ff"
        parts.append(
            f'<span style="background:{bg};color:{fg};border:1px solid {fg};'
            f'padding:2px 9px;border-radius:10px;font-size:11px;'
            f'font-family:\'IBM Plex Mono\',monospace;margin-right:4px;white-space:nowrap;">'
            f"{ticker}&nbsp;·&nbsp;{label}</span>"
        )
    st.markdown("&nbsp;".join(parts), unsafe_allow_html=True)


def render_portfolio_page(ctx):
    render_page_title("Portfolio")

    @st.fragment(run_every=60)
    def _live_prices_section():
        tickers = list(ctx["updated_portfolio"].keys())

        if ctx["app_scope"] == "private":
            from data_providers import get_prices_private
            fresh_prices = get_prices_private(tickers)
        else:
            from utils import get_prices
            fresh_prices = get_prices(tickers)

        df_fresh, _, pnl = build_portfolio_df(
            updated_portfolio=ctx["updated_portfolio"],
            live_prices_native=fresh_prices,
            asset_hist_native=pd.DataFrame(),
            fx_prices=ctx["fx_prices"],
            fx_hist=ctx["fx_hist"],
            base_currency=ctx["base_currency"],
            tx_stats_map=ctx.get("tx_stats_map", {}),
        )

        df_fresh["Price Source"] = df_fresh["Ticker"].map(
            lambda t: ctx.get("data_source_info", {}).get(t, "")
        )
        df_fresh["Market Status"] = df_fresh["Ticker"].map(_market_status)

        total_portfolio = pnl["holdings_value"] + ctx["cash_total_value"]

        c1, c2, c3 = st.columns(3)
        info_metric(c1, "Total Portfolio", f"{ctx['base_currency']} {total_portfolio:,.2f}", "Holdings plus cash.")
        info_metric(c2, "Invested Capital", f"{ctx['base_currency']} {pnl['invested_capital']:,.2f}", "Estimated invested capital.")
        info_metric(c3, "Unrealized PnL", f"{ctx['base_currency']} {pnl['unrealized_pnl']:,.2f}", "Open profit and loss.")

        display_cols = [c for c in [
            "Ticker", "Name", "Market Status", "Price Source", "Source", "Market", "Native Currency",
            "Shares", "Avg Cost", "Price", "Invested Capital", "Value",
            "Unrealized PnL", "Unrealized PnL %",
            "Weight %", "Target %", "Deviation %",
        ] if c in df_fresh.columns]

        info_section("Portfolio Snapshot", "Current holdings, values, and performance metrics.")
        _render_data_source_badges(ctx)
        st.dataframe(df_fresh[display_cols], use_container_width=True, height=360, freeze_columns=1)
        st.caption(f"Prices as of {datetime.now().strftime('%H:%M:%S')}")

    _live_prices_section()

    hist = ctx.get("asset_hist_native", pd.DataFrame())

    info_section(
        "Intraday Variation",
        "Day change vs previous close in native currency, recent 10-day trend, and market status.",
    )
    intraday_df = _build_intraday_table(ctx["df"], hist)
    st.dataframe(
        intraday_df,
        use_container_width=True,
        height=250,
        column_config={
            "Trend (10d)": st.column_config.LineChartColumn(
                "Trend (10d)", width="medium", y_min=None, y_max=None
            ),
            "Day Δ%": st.column_config.NumberColumn("Day Δ%", format="%.2f%%"),
            "Market": st.column_config.TextColumn("Market", width="small"),
        },
    )

    info_section(
        "Monthly Variation",
        "Price change vs approximately 30 calendar days ago in native currency.",
    )
    monthly_df = _build_monthly_table(ctx["df"], hist)
    st.dataframe(
        monthly_df,
        use_container_width=True,
        height=250,
        column_config={
            "Month Δ%": st.column_config.NumberColumn("Month Δ%", format="%.2f%%"),
        },
    )

    left, right = st.columns(2)

    with left:
        info_section("Allocation", "Current portfolio allocation by market value.")
        st.plotly_chart(ctx["fig_pie"], use_container_width=True, key="portfolio_allocation_chart_fixed_v2")

    with right:
        info_section(
            "Weights vs Targets",
            "Current weight, policy target, and max Sharpe allocation shown side by side.",
        )
        st.plotly_chart(
            _build_weights_vs_targets_chart(ctx),
            use_container_width=True,
            key="portfolio_weights_targets_chart_fixed_v2",
        )

    perf_fig = _build_performance_vs_benchmark_chart(ctx)
    if perf_fig is not None:
        info_section(
            "Performance vs Benchmark",
            "Portfolio cumulative return versus VOO in percentage terms. Legend includes latest cumulative values.",
        )
        st.plotly_chart(
            perf_fig,
            use_container_width=True,
            key="portfolio_performance_vs_benchmark_fixed_v2",
        )

    info_section("Cash Balances", "Cash balances by currency converted to the base currency.")
    st.dataframe(ctx["cash_display_df"], use_container_width=True, height=240)
