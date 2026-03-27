import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from portfolio import public_portfolio
from utils import get_prices, get_historical_data


st.title("Portfolio Dashboard")


# =========================
# PRIVATE PORTFOLIO FROM SECRETS
# =========================
def load_private_portfolio():
    p = st.secrets["private_portfolio"]

    return {
        "SCHD": {"name": "Dividend ETF", "shares": float(p["SCHD"])},
        "VOO": {"name": "S&P 500", "shares": float(p["VOO"])},
        "VWCE.DE": {"name": "All World", "shares": float(p["VWCE_DE"])},
        "IGLN.L": {"name": "Gold", "shares": float(p["IGLN_L"])},
        "BND": {"name": "Bonds", "shares": float(p["BND"])},
    }


private_available = True
real_portfolio = {}

try:
    real_portfolio = load_private_portfolio()
except Exception:
    private_available = False


# =========================
# HELPERS
# =========================
def current_portfolio(mode: str, authenticated: bool):
    if mode == "Private" and authenticated:
        return real_portfolio
    return public_portfolio


def widget_prefix(mode: str):
    return "private" if mode == "Private" else "public"


def init_widget_state(portfolio_data: dict, prefix: str):
    for ticker, meta in portfolio_data.items():
        key = f"{prefix}_shares_{ticker}"
        if key not in st.session_state:
            st.session_state[key] = float(meta["shares"])


def reset_widget_state(portfolio_data: dict, prefix: str):
    for ticker, meta in portfolio_data.items():
        st.session_state[f"{prefix}_shares_{ticker}"] = float(meta["shares"])


def get_updated_shares(portfolio_data: dict, prefix: str):
    updated = {}

    for ticker, meta in portfolio_data.items():
        key = f"{prefix}_shares_{ticker}"

        shares = st.sidebar.number_input(
            f"{ticker} shares",
            min_value=0.0,
            step=0.0001,
            key=key,
        )

        updated[ticker] = {
            "name": meta["name"],
            "shares": float(shares),
            "base_shares": float(meta["shares"]),
        }

    return updated


def safe_price(ticker: str, live_prices: dict, historical: pd.DataFrame):
    price = live_prices.get(ticker)

    if isinstance(price, (int, float)) and pd.notna(price) and price > 0:
        return float(price)

    try:
        if ticker in historical.columns:
            last_price = pd.to_numeric(historical[ticker], errors="coerce").dropna().iloc[-1]
            return float(last_price)
    except Exception:
        pass

    return 0.0


def build_portfolio_df(updated: dict, live_prices: dict, historical: pd.DataFrame):
    rows = []
    total_value = 0.0
    base_total_value = 0.0

    for ticker, meta in updated.items():
        shares = float(meta["shares"])
        base_shares = float(meta["base_shares"])
        price = safe_price(ticker, live_prices, historical)

        value = shares * price
        base_value = base_shares * price

        total_value += value
        base_total_value += base_value

        rows.append(
            {
                "Ticker": ticker,
                "Name": meta["name"],
                "Shares": shares,
                "Price": round(price, 2),
                "Value": round(value, 2),
                "Base Shares": base_shares,
                "Base Value": round(base_value, 2),
            }
        )

    df = pd.DataFrame(rows)

    if total_value > 0:
        df["Weight"] = df["Value"] / total_value
    else:
        df["Weight"] = 0.0

    if base_total_value > 0:
        df["Target Weight"] = df["Base Value"] / base_total_value
    else:
        df["Target Weight"] = 0.0

    df["Weight %"] = (df["Weight"] * 100).round(2)
    df["Target %"] = (df["Target Weight"] * 100).round(2)
    df["Deviation %"] = ((df["Weight"] - df["Target Weight"]) * 100).round(2)

    return df, total_value


def build_portfolio_returns(df: pd.DataFrame, historical: pd.DataFrame):
    perf_cols = [t for t in df["Ticker"] if t in historical.columns]
    if not perf_cols:
        return pd.Series(dtype=float)

    perf_df = df.set_index("Ticker").loc[perf_cols].copy()

    if perf_df["Weight"].sum() <= 0:
        return pd.Series(dtype=float)

    perf_weights = perf_df["Weight"] / perf_df["Weight"].sum()

    asset_returns = historical[perf_cols].pct_change().dropna()
    if asset_returns.empty:
        return pd.Series(dtype=float)

    portfolio_returns = asset_returns.mul(perf_weights, axis=1).sum(axis=1)
    return portfolio_returns


# =========================
# MODE + AUTH
# =========================
mode = st.sidebar.selectbox("View Mode", ["Public", "Private"])

authenticated = False

if mode == "Private":
    if not private_available:
        st.error("Private portfolio not available. Configure Streamlit secrets.")
        st.stop()

    password = st.sidebar.text_input("Password", type="password")

    if not password:
        st.info("Enter your password to access the private portfolio.")
        st.stop()

    if password != st.secrets["auth"]["password"]:
        st.error("Incorrect password.")
        st.stop()

    authenticated = True
    st.success("Access granted")
    st.info("Private portfolio loaded")
else:
    st.info("Public portfolio view")


# =========================
# ACTIVE PORTFOLIO
# =========================
portfolio_data = current_portfolio(mode, authenticated)
prefix = widget_prefix(mode)


# =========================
# WIDGET STATE
# =========================
init_widget_state(portfolio_data, prefix)

if st.sidebar.button("Reset Portfolio"):
    reset_widget_state(portfolio_data, prefix)
    st.rerun()


# =========================
# INPUTS
# =========================
st.sidebar.header("Portfolio Inputs")
updated = get_updated_shares(portfolio_data, prefix)


# =========================
# DATA
# =========================
tickers = list(updated.keys())

live_prices = get_prices(tickers)
historical = get_historical_data(tickers)

if historical is None or historical.empty:
    st.error("Could not load historical data.")
    st.stop()

historical = historical.ffill().dropna(how="all")

df, total_value = build_portfolio_df(updated, live_prices, historical)


# =========================
# PERFORMANCE
# =========================
portfolio_returns = build_portfolio_returns(df, historical)

benchmark_hist = get_historical_data(["VOO"])
benchmark_returns = pd.Series(dtype=float)

if benchmark_hist is not None and not benchmark_hist.empty and "VOO" in benchmark_hist.columns:
    benchmark_returns = benchmark_hist["VOO"].pct_change().dropna()

total_return = volatility = sharpe = max_drawdown = 0.0
alpha = beta = tracking_error = information_ratio = 0.0
portfolio_cum = pd.Series(dtype=float)
benchmark_cum = pd.Series(dtype=float)

if not portfolio_returns.empty:
    portfolio_cum = (1 + portfolio_returns).cumprod()
    total_return = float(portfolio_cum.iloc[-1] - 1)
    volatility = float(portfolio_returns.std() * np.sqrt(252))

    if volatility > 0:
        sharpe = float((portfolio_returns.mean() * 252) / volatility)

    rolling_max = portfolio_cum.cummax()
    drawdown = portfolio_cum / rolling_max - 1
    max_drawdown = float(drawdown.min())

if not portfolio_returns.empty and not benchmark_returns.empty:
    aligned = pd.concat(
        [portfolio_returns.rename("Portfolio"), benchmark_returns.rename("Benchmark")],
        axis=1
    ).dropna()

    if not aligned.empty:
        benchmark_cum = (1 + aligned["Benchmark"]).cumprod()

        bench_var = aligned["Benchmark"].var()
        if bench_var > 0:
            beta = float(aligned.cov().loc["Portfolio", "Benchmark"] / bench_var)

        p_mean = float(aligned["Portfolio"].mean() * 252)
        b_mean = float(aligned["Benchmark"].mean() * 252)
        alpha = float(p_mean - beta * b_mean)

        excess = aligned["Portfolio"] - aligned["Benchmark"]
        tracking_error = float(excess.std() * np.sqrt(252))

        if tracking_error > 0:
            information_ratio = float((excess.mean() * 252) / tracking_error)


# =========================
# DISPLAY
# =========================
st.subheader("Portfolio")

display_df = df[[
    "Ticker",
    "Name",
    "Shares",
    "Price",
    "Value",
    "Weight %",
    "Target %",
    "Deviation %",
]].copy()

st.dataframe(display_df, use_container_width=True)

st.metric("Total Value", f"${total_value:,.2f}")


# =========================
# ALLOCATION CHARTS
# =========================
st.subheader("Portfolio Allocation")

pie_values = df["Value"] if total_value > 0 else df["Weight"]
fig_pie = px.pie(df, names="Name", values=pie_values, hole=0.4)
st.plotly_chart(fig_pie, use_container_width=True)

st.subheader("Target vs Actual Allocation")

fig_bar = go.Figure()
fig_bar.add_bar(x=df["Ticker"], y=df["Weight %"], name="Actual %")
fig_bar.add_bar(x=df["Ticker"], y=df["Target %"], name="Target %")
fig_bar.update_layout(barmode="group")

st.plotly_chart(fig_bar, use_container_width=True)


# =========================
# PERFORMANCE METRICS
# =========================
st.subheader("Performance Metrics")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Return", f"{total_return:.2%}")
c2.metric("Volatility", f"{volatility:.2%}")
c3.metric("Sharpe", f"{sharpe:.2f}")
c4.metric("Max Drawdown", f"{max_drawdown:.2%}")

c5, c6, c7, c8 = st.columns(4)
c5.metric("Alpha", f"{alpha:.2%}")
c6.metric("Beta", f"{beta:.2f}")
c7.metric("Tracking Error", f"{tracking_error:.2%}")
c8.metric("Information Ratio", f"{information_ratio:.2f}")


# =========================
# PERFORMANCE CHART
# =========================
if not portfolio_cum.empty:
    st.subheader("Performance vs Benchmark")

    fig_perf = go.Figure()
    fig_perf.add_scatter(x=portfolio_cum.index, y=portfolio_cum, name="Portfolio")

    if not benchmark_cum.empty:
        fig_perf.add_scatter(x=benchmark_cum.index, y=benchmark_cum, name="VOO")

    st.plotly_chart(fig_perf, use_container_width=True)