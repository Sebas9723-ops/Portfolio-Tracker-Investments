import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from portfolio import portfolio
from utils import get_prices, get_historical_data

st.title("Sebastian's Portfolio Dashboard")

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
        "Price": round(price, 2) if price is not None else None,
        "Value": round(value, 2)
    })

df = pd.DataFrame(data)

if total_value > 0:
    df["Weight"] = df["Value"] / total_value
else:
    df["Weight"] = 0

df["Weight %"] = (df["Weight"] * 100).round(2)

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
# ALPHA & BETA
# =========================
if not sp500_returns.empty:
    aligned = pd.concat([portfolio_returns, sp500_returns], axis=1).dropna()
    aligned.columns = ["Portfolio", "Market"]

    cov_matrix = aligned.cov()
    beta = cov_matrix.loc["Portfolio", "Market"] / cov_matrix.loc["Market", "Market"]

    portfolio_mean = aligned["Portfolio"].mean() * 252
    market_mean = aligned["Market"].mean() * 252

    alpha = portfolio_mean - beta * market_mean
else:
    beta = alpha = 0

# =========================
# DISPLAY
# =========================
st.subheader("Portfolio")
st.dataframe(df)

st.metric("Total Value", f"${total_value:,.2f}")

# Charts
st.subheader("Portfolio Allocation")
fig_pie = px.pie(df, names="Name", values="Value", hole=0.4)
st.plotly_chart(fig_pie)

st.subheader("Value by Asset")
fig_bar = px.bar(df, x="Ticker", y="Value", color="Name")
st.plotly_chart(fig_bar)

# Performance chart
st.subheader("Performance vs Benchmark")

fig = go.Figure()
fig.add_trace(go.Scatter(x=portfolio_cum.index, y=portfolio_cum, name="Portfolio"))

if not sp500_cum.empty:
    fig.add_trace(go.Scatter(x=sp500_cum.index, y=sp500_cum, name="S&P 500"))

st.plotly_chart(fig)

# Metrics
st.subheader("Performance Metrics")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Return", f"{mean_return:.2%}")
col2.metric("Volatility", f"{volatility:.2%}")
col3.metric("Sharpe", f"{sharpe:.2f}")
col4.metric("Max Drawdown", f"{max_dd:.2%}")

col5, col6, col7 = st.columns(3)
col5.metric("VaR (95%)", f"{var_95:.2%}")
col6.metric("Beta", f"{beta:.2f}")
col7.metric("Alpha", f"{alpha:.2%}")