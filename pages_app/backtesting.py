import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core import DEFAULT_RISK_FREE_RATE, info_metric, info_section, render_page_title


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_ohlcv(ticker: str, period: str) -> pd.DataFrame:
    import yfinance as yf
    return yf.Ticker(ticker).history(period=period, auto_adjust=True)


# ── Signal generators ─────────────────────────────────────────────────────────

def _signal_sma_crossover(close: pd.Series, fast: int, slow: int) -> pd.Series:
    """1 when fast SMA > slow SMA, 0 otherwise."""
    return (close.rolling(fast).mean() > close.rolling(slow).mean()).astype(float)


def _signal_rsi_mean_reversion(
    close: pd.Series, period: int, oversold: float, overbought: float
) -> pd.Series:
    """Long when RSI dips below oversold, exit when it rises above overbought."""
    delta = close.diff()
    avg_gain = delta.clip(lower=0).rolling(period).mean()
    avg_loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)

    signal = pd.Series(0.0, index=close.index)
    in_trade = False
    for i in range(len(rsi)):
        r = rsi.iloc[i]
        if pd.isna(r):
            continue
        if not in_trade and r < oversold:
            in_trade = True
        elif in_trade and r > overbought:
            in_trade = False
        signal.iloc[i] = 1.0 if in_trade else 0.0
    return signal


def _signal_momentum(close: pd.Series, lookback: int) -> pd.Series:
    """1 if past `lookback` return is positive."""
    return (close.pct_change(lookback) > 0).astype(float)


def _signal_bb_breakout(close: pd.Series, window: int, num_std: float) -> pd.Series:
    """Enter when price breaks above upper BB, exit when it falls below lower BB."""
    mid = close.rolling(window).mean()
    std = close.rolling(window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std

    signal = pd.Series(0.0, index=close.index)
    in_trade = False
    for i in range(len(close)):
        c = close.iloc[i]
        u = upper.iloc[i]
        ll = lower.iloc[i]
        if pd.isna(u) or pd.isna(ll):
            continue
        if not in_trade and c > u:
            in_trade = True
        elif in_trade and c < ll:
            in_trade = False
        signal.iloc[i] = 1.0 if in_trade else 0.0
    return signal


# ── Simulation ────────────────────────────────────────────────────────────────

def _run_simulation(
    close: pd.Series,
    signal: pd.Series,
    starting_capital: float = 10_000.0,
):
    position = signal.shift(1).fillna(0.0)
    daily_ret = close.pct_change().fillna(0.0)
    strat_ret = position * daily_ret

    equity = (1 + strat_ret).cumprod() * starting_capital
    bah = (close / close.iloc[0]) * starting_capital

    # Build trade log from signal transitions
    pos_diff = position.diff().fillna(position.iloc[0])
    entries = close.index[pos_diff > 0.5]
    exits = close.index[pos_diff < -0.5]

    trades = []
    for entry_date in entries:
        later_exits = exits[exits > entry_date]
        exit_date = later_exits[0] if len(later_exits) > 0 else close.index[-1]
        p_in = float(close.loc[entry_date])
        p_out = float(close.loc[exit_date])
        ret_pct = (p_out / p_in - 1) * 100 if p_in > 0 else 0.0
        try:
            days_held = (exit_date - entry_date).days
        except Exception:
            days_held = 0
        trades.append({
            "Entry Date": entry_date.date() if hasattr(entry_date, "date") else entry_date,
            "Exit Date": exit_date.date() if hasattr(exit_date, "date") else exit_date,
            "Price In": round(p_in, 4),
            "Price Out": round(p_out, 4),
            "Return %": round(ret_pct, 2),
            "Days Held": days_held,
            "Win": ret_pct > 0,
        })

    trade_log = pd.DataFrame(trades)

    # Stats for strategy
    years = len(equity) / 252
    total_ret = (equity.iloc[-1] / starting_capital - 1) * 100
    ann_ret = ((equity.iloc[-1] / starting_capital) ** (1 / max(years, 0.01)) - 1) * 100

    active_ret = strat_ret[strat_ret != 0]
    sharpe = 0.0
    if len(active_ret) > 1 and active_ret.std() > 0:
        sharpe = (active_ret.mean() * 252 - DEFAULT_RISK_FREE_RATE) / (active_ret.std() * np.sqrt(252))

    rolling_max = equity.cummax()
    max_dd = float(((equity - rolling_max) / rolling_max).min()) * 100

    n_trades = len(trade_log)
    win_rate = (trade_log["Win"].sum() / n_trades * 100) if n_trades > 0 else 0.0

    stats = {
        "Total Return %": round(total_ret, 2),
        "Ann. Return %": round(ann_ret, 2),
        "Sharpe Ratio": round(sharpe, 3),
        "Max Drawdown %": round(max_dd, 2),
        "Win Rate %": round(win_rate, 1),
        "# Trades": n_trades,
    }

    # Stats for buy & hold
    bah_total = (bah.iloc[-1] / starting_capital - 1) * 100
    bah_ann = ((bah.iloc[-1] / starting_capital) ** (1 / max(years, 0.01)) - 1) * 100
    bah_dd = float(((bah - bah.cummax()) / bah.cummax()).min()) * 100
    bah_stats = {
        "Total Return %": round(bah_total, 2),
        "Ann. Return %": round(bah_ann, 2),
        "Sharpe Ratio": "—",
        "Max Drawdown %": round(bah_dd, 2),
        "Win Rate %": "—",
        "# Trades": 1,
    }

    return equity, bah, trade_log, stats, bah_stats


# ── Charts ────────────────────────────────────────────────────────────────────

def _build_equity_chart(equity: pd.Series, bah: pd.Series) -> go.Figure:
    fig = go.Figure()
    fig.add_scatter(
        x=equity.index, y=equity,
        mode="lines", name="Strategy",
        line=dict(color="#f3a712", width=2),
        hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.2f}<extra>Strategy</extra>",
    )
    fig.add_scatter(
        x=bah.index, y=bah,
        mode="lines", name="Buy & Hold",
        line=dict(color="#00c8ff", width=1.5, dash="dot"),
        hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.2f}<extra>Buy & Hold</extra>",
    )
    fig.update_layout(
        paper_bgcolor="#0b0f14", plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"), height=400,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Date", yaxis_title="Value ($)",
        yaxis=dict(tickprefix="$", tickformat=",.0f"),
        legend=dict(orientation="h", y=1.08, x=0.0),
    )
    return fig


# ── Page renderer ─────────────────────────────────────────────────────────────

def render_backtesting_page(ctx):
    render_page_title("Backtesting")

    portfolio_tickers = list(ctx.get("updated_portfolio", {}).keys())

    col_strat, col_ticker_src, col_period = st.columns([2, 2, 1])
    with col_strat:
        strategy = st.selectbox(
            "Strategy",
            ["SMA Crossover", "RSI Mean Reversion", "Momentum", "Bollinger Band Breakout"],
            key="bt_strategy",
        )
    with col_ticker_src:
        ticker_source = st.radio(
            "Ticker source", ["Portfolio", "Custom"],
            horizontal=True, key="bt_ticker_source",
        )
        if ticker_source == "Portfolio" and portfolio_tickers:
            ticker = st.selectbox("Ticker", portfolio_tickers, key="bt_ticker_portfolio")
        else:
            ticker = st.text_input(
                "Custom ticker", placeholder="e.g. NVDA", key="bt_ticker_custom",
            ).upper().strip()
    with col_period:
        period = st.selectbox("Period", ["1y", "3y", "5y", "10y"], index=2, key="bt_period")

    # Strategy-specific parameters
    st.markdown("#### Strategy Parameters")
    params: dict = {}
    if strategy == "SMA Crossover":
        c1, c2 = st.columns(2)
        params["fast"] = c1.number_input(
            "Fast SMA window", min_value=5, max_value=100, value=20, step=5, key="bt_sma_fast",
        )
        params["slow"] = c2.number_input(
            "Slow SMA window", min_value=20, max_value=300, value=50, step=10, key="bt_sma_slow",
        )
    elif strategy == "RSI Mean Reversion":
        c1, c2, c3 = st.columns(3)
        params["period"] = c1.number_input("RSI period", 5, 30, 14, key="bt_rsi_period")
        params["oversold"] = c2.number_input("Oversold level", 10, 45, 30, key="bt_rsi_os")
        params["overbought"] = c3.number_input("Overbought level", 55, 90, 70, key="bt_rsi_ob")
    elif strategy == "Momentum":
        params["lookback"] = st.number_input(
            "Lookback days", min_value=5, max_value=252, value=63, step=5, key="bt_mom_lb",
        )
    elif strategy == "Bollinger Band Breakout":
        c1, c2 = st.columns(2)
        params["window"] = c1.number_input("Window", 10, 50, 20, key="bt_bb_win")
        params["num_std"] = c2.number_input(
            "Std Dev multiplier", 1.0, 3.0, 2.0, step=0.1, key="bt_bb_std",
        )

    if not st.button("Run Backtest", type="primary", key="bt_run"):
        st.info("Configure strategy parameters above and press **Run Backtest**.")
        return

    if not ticker:
        st.warning("Enter a ticker symbol.")
        return

    with st.spinner(f"Loading {ticker} ({period.upper()})..."):
        df = _fetch_ohlcv(ticker, period)

    if df is None or df.empty:
        st.error(f"No data found for **{ticker}**.")
        return

    close = df["Close"].dropna()
    if len(close) < 60:
        st.warning("Not enough data — need at least 60 trading days.")
        return

    with st.spinner("Running simulation..."):
        if strategy == "SMA Crossover":
            sig = _signal_sma_crossover(close, int(params["fast"]), int(params["slow"]))
        elif strategy == "RSI Mean Reversion":
            sig = _signal_rsi_mean_reversion(
                close, int(params["period"]), float(params["oversold"]), float(params["overbought"])
            )
        elif strategy == "Momentum":
            sig = _signal_momentum(close, int(params["lookback"]))
        else:
            sig = _signal_bb_breakout(close, int(params["window"]), float(params["num_std"]))

        equity, bah, trade_log, stats, bah_stats = _run_simulation(close, sig)

    st.markdown(f"### {ticker} · {strategy} · {period.upper()}")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    info_metric(c1, "Total Return", f"{stats['Total Return %']:+.1f}%", f"B&H: {bah_stats['Total Return %']:+.1f}%")
    info_metric(c2, "Ann. Return", f"{stats['Ann. Return %']:+.1f}%", f"B&H: {bah_stats['Ann. Return %']:+.1f}%")
    info_metric(c3, "Sharpe", f"{stats['Sharpe Ratio']:.3f}", "Strategy Sharpe ratio")
    info_metric(c4, "Max Drawdown", f"{stats['Max Drawdown %']:.1f}%", f"B&H: {bah_stats['Max Drawdown %']:.1f}%")
    info_metric(c5, "Win Rate", f"{stats['Win Rate %']:.0f}%", f"{stats['# Trades']} trades")
    info_metric(c6, "# Trades", str(stats["# Trades"]), "Round-trip trades")

    info_section("Equity Curve", "Strategy vs Buy & Hold — starting capital $10,000.")
    st.plotly_chart(_build_equity_chart(equity, bah), use_container_width=True, key="bt_equity_chart")

    if not trade_log.empty:
        info_section("Trade Log", "All round-trip entries and exits.")
        st.dataframe(
            trade_log.drop(columns=["Win"]),
            use_container_width=True,
            height=320,
            column_config={
                "Return %": st.column_config.NumberColumn("Return %", format="%.2f%%"),
            },
        )
    else:
        st.info("No trades were generated. Try adjusting parameters or selecting a longer period.")
