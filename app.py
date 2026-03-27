import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import json
import os

from portfolio import public_portfolio

# Try to load private portfolio
try:
    from private_portfolio import real_portfolio
    private_available = True
except:
    private_available = False

# =========================
# FILE FOR PRIVATE STATE
# =========================
STATE_FILE = "private_state.json"

def load_private_state(default_portfolio):
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {ticker: default_portfolio[ticker]["shares"] for ticker in default_portfolio}

def save_private_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

st.title("Portfolio Dashboard")

# =========================
# MODE SELECTOR
# =========================
mode = st.sidebar.selectbox("View Mode", ["Public", "Private"])

# =========================
# PASSWORD PROTECTION
# =========================
authenticated = False

if mode == "Private":
    if private_available:
        password = st.sidebar.text_input("Enter password", type="password")

        if password == st.secrets["auth"]["password"]:
            authenticated = True
        else:
            st.warning("Incorrect password")
    else:
        st.error("Private portfolio not available")

# =========================
# SELECT PORTFOLIO
# =========================
if mode == "Private" and authenticated:
    portfolio_data = real_portfolio
    st.info("Private portfolio loaded.")
else:
    portfolio_data = public_portfolio
    if mode == "Private":
        st.stop()
    st.info("Public portfolio view.")

# =========================
# SESSION STATE INIT / SYNC
# =========================
if "current_mode" not in st.session_state:
    st.session_state.current_mode = mode

if "portfolio_state" not in st.session_state:
    if mode == "Private" and authenticated:
        st.session_state.portfolio_state = load_private_state(portfolio_data)
    else:
        st.session_state.portfolio_state = {
            ticker: portfolio_data[ticker]["shares"] for ticker in portfolio_data
        }

# Reset when switching mode
if st.session_state.current_mode != mode:
    if mode == "Private" and authenticated:
        st.session_state.portfolio_state = load_private_state(portfolio_data)
    else:
        st.session_state.portfolio_state = {
            ticker: portfolio_data[ticker]["shares"] for ticker in portfolio_data
        }

    st.session_state.current_mode = mode

# =========================
# RESET BUTTON
# =========================
if st.sidebar.button("Reset to Original Portfolio"):
    st.session_state.portfolio_state = {
        ticker: portfolio_data[ticker]["shares"] for ticker in portfolio_data
    }

    if mode == "Private" and authenticated:
        save_private_state(st.session_state.portfolio_state)

    st.rerun()

# =========================
# SIDEBAR INPUTS
# =========================
st.sidebar.header("Portfolio Inputs")

updated_portfolio = {}

for ticker in portfolio_data:
    shares = st.sidebar.number_input(
        f"{ticker} shares",
        min_value=0.0,
        step=0.1,
        key=ticker,
        value=float(st.session_state.portfolio_state[ticker])
    )

    st.session_state.portfolio_state[ticker] = shares

    updated_portfolio[ticker] = {
        "name": portfolio_data[ticker]["name"],
        "shares": shares
    }

# Save ONLY in private mode
if mode == "Private" and authenticated:
    save_private_state(st.session_state.portfolio_state)

# =========================
# DATA
# =========================
from utils import get_prices, get_historical_data

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
# RETURNS
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
# DISPLAY
# =========================
st.subheader("Portfolio")

if mode == "Public":
    st.dataframe(df[[
        "Ticker", "Name", "Weight %", "Target %", "Deviation %"
    ]])
else:
    st.dataframe(df)

st.metric("Total Value", f"${total_value:,.2f}" if mode == "Private" else "Hidden")

# =========================
# CHARTS
# =========================
st.subheader("Portfolio Allocation")

values = df["Value"] if mode == "Private" else df["Weight"]

st.plotly_chart(px.pie(df, names="Name", values=values, hole=0.4))

st.subheader("Target vs Actual Allocation")

fig_target = go.Figure()
fig_target.add_trace(go.Bar(x=df["Ticker"], y=df["Weight"], name="Actual"))
fig_target.add_trace(go.Bar(x=df["Ticker"], y=df["Target Weight"], name="Target"))

fig_target.update_layout(barmode="group")

st.plotly_chart(fig_target)