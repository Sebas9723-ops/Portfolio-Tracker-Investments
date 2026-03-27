import streamlit as st
import pandas as pd
import plotly.express as px

from portfolio import public_portfolio
from utils import get_prices, get_historical_data

st.title("Portfolio Dashboard")

# =========================
# PRIVATE LOAD
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
except:
    private_available = False

# =========================
# MODE
# =========================
mode = st.sidebar.selectbox("View Mode", ["Public", "Private"])

authenticated = False

if mode == "Private":
    if private_available:
        password = st.sidebar.text_input("Password", type="password")

        if password == st.secrets["auth"]["password"]:
            authenticated = True
            st.success("Access granted")
        elif password:
            st.error("Incorrect password")
    else:
        st.error("Configure secrets")

# =========================
# SELECT PORTFOLIO
# =========================
if mode == "Private" and authenticated:
    portfolio_data = real_portfolio
else:
    portfolio_data = public_portfolio

# =========================
# 🔥 RESET TOTAL POR MODO
# =========================
if "mode_memory" not in st.session_state:
    st.session_state.mode_memory = mode

if st.session_state.mode_memory != mode:
    # reset completo
    st.session_state.clear()
    st.session_state.mode_memory = mode
    st.rerun()

# =========================
# 🔥 INIT STATE CORRECTO
# =========================
if "shares" not in st.session_state:
    st.session_state.shares = {
        t: portfolio_data[t]["shares"] for t in portfolio_data
    }

# =========================
# INPUTS (SIN BUGS)
# =========================
st.sidebar.header("Portfolio Inputs")

for ticker in portfolio_data:
    st.session_state.shares[ticker] = st.sidebar.number_input(
        f"{ticker} shares",
        min_value=0.0,
        step=0.1,
        value=float(st.session_state.shares.get(ticker, portfolio_data[ticker]["shares"])),
        key=f"{mode}_{ticker}"
    )

# =========================
# DATA
# =========================
tickers = list(st.session_state.shares.keys())

prices = get_prices(tickers)
historical = get_historical_data(tickers)

historical = historical.ffill().dropna()

data = []
total_value = 0

for t in tickers:
    shares = float(st.session_state.shares[t])

    price = prices.get(t)

    if price is None or not isinstance(price, (int, float)):
        try:
            price = float(historical[t].iloc[-1])
        except:
            price = 0.0

    value = shares * price
    total_value += value

    data.append({
        "Ticker": t,
        "Name": portfolio_data[t]["name"],
        "Shares": shares,
        "Price": round(price, 2),
        "Value": round(value, 2)
    })

df = pd.DataFrame(data)

# =========================
# CALCULOS CORRECTOS
# =========================
if total_value > 0:
    df["Weight"] = df["Value"] / total_value
else:
    df["Weight"] = 0

df["Weight %"] = (df["Weight"] * 100).round(2)

target_weight = 1 / len(df)

df["Target %"] = round(target_weight * 100, 2)
df["Deviation %"] = ((df["Weight"] - target_weight) * 100).round(2)

# =========================
# DISPLAY
# =========================
st.subheader("Portfolio")
st.dataframe(df)

st.metric("Total Value", f"${total_value:,.2f}")

# =========================
# CHART
# =========================
st.subheader("Allocation")

values = df["Value"] if (mode == "Private" and authenticated) else df["Weight"]

st.plotly_chart(px.pie(df, names="Name", values=values, hole=0.4))