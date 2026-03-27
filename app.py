import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from portfolio import public_portfolio
from utils import get_prices, get_historical_data

st.title("Portfolio Dashboard")

# =========================
# LOAD PRIVATE FROM SECRETS
# =========================
private_available = False
real_portfolio = {}

try:
    p = st.secrets["private_portfolio"]

    real_portfolio = {
        "SCHD": {"name": "Dividend ETF", "shares": float(p["SCHD"])},
        "VOO": {"name": "S&P 500", "shares": float(p["VOO"])},
        "VWCE.DE": {"name": "All World", "shares": float(p["VWCE_DE"])},
        "IGLN.L": {"name": "Gold", "shares": float(p["IGLN_L"])},
        "BND": {"name": "Bonds", "shares": float(p["BND"])},
    }

    private_available = True

except Exception as e:
    private_available = False

# =========================
# MODE
# =========================
mode = st.sidebar.selectbox("View Mode", ["Public", "Private"])

# =========================
# PASSWORD
# =========================
authenticated = False

if mode == "Private":
    if not private_available:
        st.error("Private portfolio not available. Configure secrets.")
    else:
        password = st.sidebar.text_input("Password", type="password")

        if password:
            if password == st.secrets["auth"]["password"]:
                authenticated = True
                st.success("Access granted")
            else:
                st.error("Incorrect password")

# =========================
# SELECT PORTFOLIO
# =========================
if mode == "Private" and authenticated:
    portfolio_data = real_portfolio
    st.info("Private portfolio loaded")
else:
    portfolio_data = public_portfolio
    st.info("Public portfolio view")

# =========================
# SESSION STATE
# =========================
if "portfolio_state" not in st.session_state:
    st.session_state.portfolio_state = {
        t: portfolio_data[t]["shares"] for t in portfolio_data
    }

if "mode_state" not in st.session_state:
    st.session_state.mode_state = mode

if st.session_state.mode_state != mode:
    st.session_state.portfolio_state = {
        t: portfolio_data[t]["shares"] for t in portfolio_data
    }
    st.session_state.mode_state = mode

# =========================
# RESET
# =========================
if st.sidebar.button("Reset Portfolio"):
    st.session_state.portfolio_state = {
        t: portfolio_data[t]["shares"] for t in portfolio_data
    }
    st.rerun()

# =========================
# INPUTS
# =========================
st.sidebar.header("Portfolio Inputs")

updated = {}

for ticker in portfolio_data:
    shares = st.sidebar.number_input(
        f"{ticker} shares",
        min_value=0.0,
        step=0.1,
        value=float(st.session_state.portfolio_state[ticker]),
        key=ticker
    )

    st.session_state.portfolio_state[ticker] = shares

    updated[ticker] = {
        "name": portfolio_data[ticker]["name"],
        "shares": shares
    }

# =========================
# DATA
# =========================
tickers = list(updated.keys())

prices = get_prices(tickers)
historical = get_historical_data(tickers)

if historical is None or historical.empty:
    st.error("Error loading data")
    st.stop()

historical = historical.ffill().dropna()

# =========================
# BUILD DATAFRAME
# =========================
data = []
total_value = 0

for t in updated:
    shares = updated[t]["shares"]
    price = prices.get(t)

    # 🔥 FIX PRECIOS EN 0
    if price is None or price == 0:
        try:
            price = historical[t].dropna().iloc[-1]
        except:
            price = 0

    value = shares * price
    total_value += value

    data.append({
        "Ticker": t,
        "Name": updated[t]["name"],
        "Shares": shares,
        "Value": round(value, 2)
    })

df = pd.DataFrame(data)

df["Weight"] = df["Value"] / total_value if total_value > 0 else 0
df["Weight %"] = (df["Weight"] * 100).round(2)

# =========================
# TARGET
# =========================
target = {t: 1/len(df) for t in df["Ticker"]}

df["Target %"] = df["Ticker"].map(lambda x: target[x]*100)
df["Deviation %"] = (df["Weight"] - df["Ticker"].map(target)) * 100

# =========================
# DISPLAY
# =========================
st.subheader("Portfolio")
st.dataframe(df)

# 🔥 SIEMPRE MOSTRAR
st.metric("Total Value", f"${total_value:,.2f}")

# =========================
# CHART
# =========================
st.subheader("Allocation")

values = df["Value"] if mode == "Private" and authenticated else df["Weight"]

st.plotly_chart(px.pie(df, names="Name", values=values, hole=0.4))