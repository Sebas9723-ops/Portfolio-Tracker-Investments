import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from portfolio import portfolio
from utils import get_prices, get_historical_data

st.title("Sebastian's Portfolio Dashboard")

# =========================
# CURRENT PRICES
# =========================
tickers = list(portfolio.keys())
prices = get_prices(tickers)

# =========================
# BUILD PORTFOLIO
# =========================
data = []
total_value = 0

for ticker in portfolio:
    shares = portfolio[ticker]["shares"]
    price = prices.get(ticker, None)

    if price is not None:
        value = shares * price
        total_value += value
    else:
        value = 0

    data.append({
        "Ticker": ticker,
        "Name": portfolio[ticker]["name"],
        "Shares": shares,
        "Price": round(price, 2) if price is not None else None,
        "Value": round(value, 2)
    })

df = pd.DataFrame(data)

# =========================
# WEIGHTS
# =========================
if total_value > 0:
    df["Weight"] = df["Value"] / total_value
else:
    df["Weight"] = 0

# =========================
# HISTORICAL DATA
# =========================
historical = get_historical_data(tickers)

if historical is None or historical.empty:
    st.error("No historical data available")
    st.stop()

historical = historical.dropna(axis=1, how="all")
historical = historical.ffill().dropna()

# =========================
# RETURNS
# =========================
returns = historical.pct_change().dropna()

# Align tickers
available_tickers = returns.columns
df = df[df["Ticker"].isin(available_tickers)]

weights = df["Weight"].values

if len(weights) != len(returns.columns):
    st.error("Mismatch between weights and returns")
    st.stop()

portfolio_returns = returns.dot(weights)
portfolio_cum = (1 + portfolio_returns).cumprod()

# =========================
# BENCHMARK
# =========================
sp500_data = get_historical_data(["VOO"])

if sp500_data is None or sp500_data.empty:
    st.error("No benchmark data available")
    st.stop()

sp500 = sp500_data["VOO"].dropna()
sp500_returns = sp500.pct_change().dropna()
sp500_cum = (1 + sp500_returns).cumprod()

# =========================
# ALIGN DATA
# =========================
aligned = pd.concat([portfolio_returns, sp500_returns], axis=1).dropna()
aligned.columns = ["Portfolio", "Market"]

portfolio_returns = aligned["Portfolio"]
sp500_returns = aligned["Market"]

portfolio_cum = (1 + portfolio_returns).cumprod()
sp500_cum = (1 + sp500_returns).cumprod()

# =========================
# METRICS
# =========================
total_return = portfolio_cum.iloc[-1] - 1
volatility = portfolio_returns.std() * (252 ** 0.5)

if portfolio_returns.std() != 0:
    sharpe_ratio = portfolio_returns.mean() / portfolio_returns.std() * (252 ** 0.5)
else:
    sharpe_ratio = 0

rolling_max = portfolio_cum.cummax()
drawdown = portfolio_cum / rolling_max - 1
max_drawdown = drawdown.min()

var_95 = portfolio_returns.quantile(0.05)
expected_return = portfolio_returns.mean() * 252

# =========================
# ALPHA & BETA
# =========================
cov_matrix = aligned.cov()
beta = cov_matrix.loc["Portfolio", "Market"] / cov_matrix.loc["Market", "Market"]

portfolio_mean = aligned["Portfolio"].mean() * 252
market_mean = aligned["Market"].mean() * 252
alpha = portfolio_mean - beta * market_mean

# =========================
# ROLLING METRICS (NEW)
# =========================
rolling_beta = (
    aligned["Portfolio"].rolling(60).cov(aligned["Market"]) /
    aligned["Market"].rolling(60).var()
)

rolling_alpha = (
    aligned["Portfolio"].rolling(60).mean() * 252 -
    rolling_beta * (aligned["Market"].rolling(60).mean() * 252)
)

rolling_vol = portfolio_returns.rolling(30).std() * (252 ** 0.5)

# =========================
# CORRELATION
# =========================
correlation = aligned["Portfolio"].corr(aligned["Market"])

# =========================
# UI
# =========================
st.subheader("Portfolio")
st.dataframe(df)

st.metric("Total Value", f"${total_value:,.2f}")

# =========================
# PERFORMANCE METRICS
# =========================
st.subheader("Performance Metrics")

col1, col2, col3, col4 = st.columns(4)

col1.metric("Return", f"{total_return*100:.2f}%")
col2.metric("Volatility", f"{volatility*100:.2f}%")
col3.metric("Sharpe Ratio", f"{sharpe_ratio:.2f}")
col4.metric("Max Drawdown", f"{max_drawdown*100:.2f}%")

col5, col6 = st.columns(2)

col5.metric("VaR (95%)", f"{var_95*100:.2f}%")
col6.metric("Expected Return", f"{expected_return*100:.2f}%")

col7, col8 = st.columns(2)

col7.metric("Beta", f"{beta:.2f}")
col8.metric("Alpha", f"{alpha*100:.2f}%")

st.metric("Correlation vs Market", f"{correlation:.2f}")

# =========================
# CHARTS
# =========================
st.subheader("Portfolio Allocation")
st.plotly_chart(px.pie(df, names="Name", values="Value", hole=0.4))

st.subheader("Value by Asset")
st.plotly_chart(px.bar(df, x="Ticker", y="Value", color="Name"))

# =========================
# PERFORMANCE
# =========================
st.subheader("Performance vs S&P 500")

fig = go.Figure()
fig.add_trace(go.Scatter(x=portfolio_cum.index, y=portfolio_cum, name="Portfolio"))
fig.add_trace(go.Scatter(x=sp500_cum.index, y=sp500_cum, name="S&P 500"))

st.plotly_chart(fig)

# =========================
# DRAWDOWN (NEW)
# =========================
st.subheader("Drawdown")

fig_dd = go.Figure()
fig_dd.add_trace(go.Scatter(x=drawdown.index, y=drawdown, name="Drawdown"))

st.plotly_chart(fig_dd)

# =========================
# ROLLING VOLATILITY
# =========================
st.subheader("Rolling Volatility (30D)")

fig_vol = go.Figure()
fig_vol.add_trace(go.Scatter(x=rolling_vol.index, y=rolling_vol, name="Volatility"))

st.plotly_chart(fig_vol)

# =========================
# ROLLING BETA (NEW)
# =========================
st.subheader("Rolling Beta (60D)")

fig_beta = go.Figure()
fig_beta.add_trace(go.Scatter(x=rolling_beta.index, y=rolling_beta, name="Beta"))

st.plotly_chart(fig_beta)

# =========================
# ROLLING ALPHA (NEW)
# =========================
st.subheader("Rolling Alpha (60D)")

fig_alpha = go.Figure()
fig_alpha.add_trace(go.Scatter(x=rolling_alpha.index, y=rolling_alpha, name="Alpha"))

st.plotly_chart(fig_alpha)