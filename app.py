import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import json
import os

from portfolio import public_portfolio
from utils import get_prices, get_historical_data

# =========================
# LOAD PRIVATE FROM SECRETS
# =========================
try:
    private_portfolio_secrets = st.secrets["private_portfolio"]

    real_portfolio = {
        "SCHD": {"name": "Dividend ETF", "shares": private_portfolio_secrets["SCHD"]},
        "VOO": {"name": "S&P 500", "shares": private_portfolio_secrets["VOO"]},
        "VWCE.DE": {"name": "All World", "shares": private_portfolio_secrets["VWCE_DE"]},
        "IGLN.L": {"name": "Gold", "shares": private_portfolio_secrets["IGLN_L"]},
        "BND": {"name": "Bonds", "shares": private_portfolio_secrets["BND"]},
    }

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
# MODE
# =========================
mode = st.sidebar.selectbox("View Mode", ["Public", "Private"])

# =========================
# PASSWORD
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
# SESSION STATE
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

if st.session_state.current_mode != mode:
    if mode == "Private" and authenticated:
        st.session_state.portfolio_state = load_private_state(portfolio_data)
    else:
        st.session_state.portfolio_state = {
            ticker: portfolio_data[ticker]["shares"] for ticker in portfolio_data
        }

    st.session_state.current_mode = mode

# =========================
# RESET
# =========================
if st.sidebar.button("Reset to Original Portfolio"):
    st.session_state.portfolio_state = {
        ticker: portfolio_data[ticker]["shares"] for ticker in portfolio_data
    }

    if mode == "Private" and authenticated:
        save_private_state(st.session_state.portfolio_state)

    st.rerun()

# =========================
# INPUTS
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

# Save only in private
if mode == "Private" and authenticated:
    save_private_state(st.session_state.portfolio_state)

# =========================
# DATA
# =========================
tickers = list(updated_portfolio.keys())

prices = get_prices(tickers)
historical = get_historical_data(tickers)

if historical is None or historical.empty:
    st.error("Error loading data")
    st.stop()

historical = historical.ffill().dropna()
returns = historical.pct_change().dropna()

# =========================
# BUILD DF
# =========================
data = []
total_value = 0

for ticker in updated_portfolio:
    shares = updated_portfolio[ticker]["shares"]
    price = prices.get(ticker, None)

    value = shares * price if price else 0
    total_value += value

    data.append({
        "Ticker": ticker,
        "Name": updated_portfolio[ticker]["name"],
        "Shares": shares,
        "Value": round(value, 2)
    })

df = pd.DataFrame(data)

df["Weight"] = df["Value"] / total_value if total_value > 0 else 0
df["Weight %"] = (df["Weight"] * 100).round(2)

# =========================
# TARGET
# =========================
target_weights = {t: 1 / len(df) for t in df["Ticker"]}

df["Target Weight"] = df["Ticker"].map(target_weights)
df["Target %"] = (df["Target Weight"] * 100).round(2)

df["Deviation"] = df["Weight"] - df["Target Weight"]
df["Deviation %"] = (df["Deviation"] * 100).round(2)

# =========================
# DISPLAY
# =========================
st.subheader("Portfolio")
st.dataframe(df)

st.metric("Total Value", f"${total_value:,.2f}" if mode == "Private" else "Hidden")

# =========================
# PIE
# =========================
st.subheader("Portfolio Allocation")

values = df["Value"] if mode == "Private" else df["Weight"]

st.plotly_chart(px.pie(df, names="Name", values=values, hole=0.4))