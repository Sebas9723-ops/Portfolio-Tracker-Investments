import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from portfolio import portfolio
from utils import get_prices, get_historical_data

st.title("Portfolio Dashboard")

st.info("This dashboard allows dynamic portfolio simulation. Changes are not saved.")

# =========================
# SESSION STATE INIT
# =========================
if "portfolio_state" not in st.session_state:
    st.session_state.portfolio_state = {
        ticker: portfolio[ticker]["shares"] for ticker in portfolio
    }

# =========================
# RESET BUTTON
# =========================
if st.sidebar.button("Reset to Original Portfolio"):
    st.session_state.portfolio_state = {
        ticker: portfolio[ticker]["shares"] for ticker in portfolio
    }
    st.rerun()

# =========================
# SIDEBAR INPUTS
# =========================
st.sidebar.header("Portfolio Inputs")

updated_portfolio = {}

for ticker in portfolio:
    shares = st.sidebar.number_input(
        f"{ticker} shares",
        min_value=0.0,
        step=1.0,
        key=ticker,
        value=float(st.session_state.portfolio_state[ticker])
    )

    st.session_state.portfolio_state[ticker] = shares

    updated_portfolio[ticker] = {
        "name": portfolio[ticker]["name"],
        "shares": shares
    }

# =========================
# DATA
# =========================
tickers = list(updated_portfolio.keys())

prices = get_prices(tickers)
historical = get_historical_data(tickers)

if historical is None or historical.empty:
    st.error("Error loading historical data")
    st.stop()

historical = historical.ffill().dropna()
returns = historical.pct_change().dropna()

# =========================
# BUILD DATAFRAME
# =========================
data = []
total_value = 0

for ticker in updated_portfolio:
    shares = updated_portfolio[ticker]["shares"]
    price = prices.get(ticker, None)

    if price is not None:
        value = shares * price
        total_value += value
    else:
        value = 0

    data.append({
        "Ticker": ticker,
        "Name": updated_portfolio[ticker]["name"],
        "Shares": shares,
        "Value": round(value, 2)
    })

df = pd.DataFrame(data)

if total_value > 0:
    df["Weight"] = df["Value"] / total_value
else:
    df["Weight"] = 0

df["Weight %"] = (df["Weight"] * 100).round(2)

# =========================
# TARGET ALLOCATION
# =========================
target_weights = {
    ticker: 1 / len(df) for ticker in df["Ticker"]
}

df["Target Weight"] = df["Ticker"].map(target_weights)
df["Target %"] = (df["Target Weight"] * 100).round(2)

df["Deviation"] = df["Weight"] - df["Target Weight"]
df["Deviation %"] = (df["Deviation"] * 100).round(2)

# =========================
# PORTFOLIO RETURNS
# =========================
weights = df["Weight"].values

portfolio_returns = returns.dot(weights)
portfolio_cum = (1 + portfolio_returns).cumprod()

# =========================
# BENCHMARK
# =========================
sp500_data = get_historical_data(["VOO"])

if sp500_data is not None and "VOO" in sp500_data:
    sp500 = sp500_data["VOO"]
    sp500_returns = sp500.pct_change().dropna()
    sp500_cum = (1 + sp500_returns).cumprod()
else:
    sp500_returns = pd.Series(dtype=float)
    sp500_cum = pd.Series(dtype=float)

# =========================
# METRICS
# =========================
if not portfolio_returns.empty:
    mean_return = portfolio_returns.mean() * 252
    volatility = portfolio_returns.std() * np.sqrt(252)
    sharpe = mean_return / volatility if volatility != 0 else 0

    cumulative = portfolio_cum
    peak = cumulative.cummax()
    drawdown = (cumulative - peak) / peak
    max_dd = drawdown.min()

    var_95 = np.percentile(portfolio_returns, 5)
else:
    mean_return = volatility = sharpe = max_dd = var_95 = 0

# =========================
# RELATIVE METRICS
# =========================
if not sp500_returns.empty:
    aligned = pd.concat([portfolio_returns, sp500_returns], axis=1).dropna()
    aligned.columns = ["Portfolio", "Market"]

    portfolio_returns = aligned["Portfolio"]
    sp500_returns = aligned["Market"]

    portfolio_cum = (1 + portfolio_returns).cumprod()
    sp500_cum = (1 + sp500_returns).cumprod()

    cov_matrix = aligned.cov()
    beta = cov_matrix.loc["Portfolio", "Market"] / cov_matrix.loc["Market", "Market"]

    portfolio_mean = aligned["Portfolio"].mean() * 252
    market_mean = aligned["Market"].mean() * 252

    alpha = portfolio_mean - beta * market_mean

    excess_returns = portfolio_returns - sp500_returns
    tracking_error = excess_returns.std() * np.sqrt(252)

    if tracking_error != 0:
        information_ratio = excess_returns.mean() * 252 / tracking_error
    else:
        information_ratio = 0
else:
    beta = alpha = tracking_error = information_ratio = 0

# =========================
# DISPLAY
# =========================
st.subheader("Portfolio")
st.dataframe(df[[
    "Ticker", "Name", "Shares", "Value",
    "Weight %", "Target %", "Deviation %"
]])

st.metric("Total Value", f"${total_value:,.2f}")

# =========================
# CHARTS
# =========================
st.subheader("Portfolio Allocation")
st.plotly_chart(px.pie(df, names="Name", values="Value", hole=0.4))

st.subheader("Target vs Actual Allocation")

fig_target = go.Figure()

fig_target.add_trace(go.Bar(
    x=df["Ticker"],
    y=df["Weight"],
    name="Actual"
))

fig_target.add_trace(go.Bar(
    x=df["Ticker"],
    y=df["Target Weight"],
    name="Target"
))

fig_target.update_layout(barmode="group")

st.plotly_chart(fig_target)

st.subheader("Performance vs Benchmark")

fig = go.Figure()

fig.add_trace(go.Scatter(
    x=portfolio_cum.index,
    y=portfolio_cum,
    name="Portfolio"
))

if not sp500_cum.empty:
    fig.add_trace(go.Scatter(
        x=sp500_cum.index,
        y=sp500_cum,
        name="S&P 500"
    ))

st.plotly_chart(fig)

# =========================
# METRICS DISPLAY
# =========================
st.subheader("Performance Metrics")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Return", f"{mean_return:.2%}")
col2.metric("Volatility", f"{volatility:.2%}")
col3.metric("Sharpe", f"{sharpe:.2f}")
col4.metric("Max Drawdown", f"{max_dd:.2%}")

col5, col6, col7, col8, col9 = st.columns(5)
col5.metric("VaR (95%)", f"{var_95:.2%}")
col6.metric("Beta", f"{beta:.2f}")
col7.metric("Alpha", f"{alpha:.2%}")
col8.metric("Tracking Error", f"{tracking_error:.2%}")
col9.metric("Information Ratio", f"{information_ratio:.2f}")