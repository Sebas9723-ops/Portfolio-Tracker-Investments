import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from portfolio import public_portfolio
from utils import get_prices, get_historical_data


st.set_page_config(page_title="Portfolio Dashboard", layout="wide")
st.title("Portfolio Dashboard")


def load_private_portfolio():
    p = st.secrets["private_portfolio"]
    return {
        "SCHD": {"name": "Dividend ETF", "shares": float(p["SCHD"])},
        "VOO": {"name": "S&P 500", "shares": float(p["VOO"])},
        "VWCE.DE": {"name": "All World", "shares": float(p["VWCE_DE"])},
        "IGLN.L": {"name": "Gold", "shares": float(p["IGLN_L"])},
        "BND": {"name": "Bonds", "shares": float(p["BND"])},
    }


def get_active_portfolio(mode: str, authenticated: bool, private_portfolio: dict):
    if mode == "Private" and authenticated:
        return private_portfolio
    return public_portfolio


def get_mode_prefix(mode: str):
    return "private" if mode == "Private" else "public"


def init_mode_state(portfolio_data: dict, prefix: str):
    for ticker, meta in portfolio_data.items():
        key = f"{prefix}_shares_{ticker}"
        if key not in st.session_state:
            st.session_state[key] = float(meta["shares"])


def reset_mode_state(portfolio_data: dict, prefix: str):
    for ticker, meta in portfolio_data.items():
        st.session_state[f"{prefix}_shares_{ticker}"] = float(meta["shares"])


def build_current_portfolio(portfolio_data: dict, prefix: str, mode: str):
    updated = {}

    step_value = 1.0 if mode == "Public" else 0.0001

    for ticker, meta in portfolio_data.items():
        widget_key = f"{prefix}_shares_{ticker}"

        st.sidebar.number_input(
            f"{ticker} shares",
            min_value=0.0,
            step=step_value,
            format="%.4f",
            key=widget_key,
        )

        updated[ticker] = {
            "name": meta["name"],
            "shares": float(st.session_state[widget_key]),
            "base_shares": float(meta["shares"]),
        }

    return updated


def get_safe_price(ticker: str, live_prices: dict, historical: pd.DataFrame):
    live_price = live_prices.get(ticker)

    if isinstance(live_price, (int, float)) and pd.notna(live_price) and live_price > 0:
        return float(live_price)

    try:
        if ticker in historical.columns:
            last_hist = pd.to_numeric(historical[ticker], errors="coerce").dropna().iloc[-1]
            return float(last_hist)
    except Exception:
        pass

    return 0.0


def build_portfolio_df(updated_portfolio: dict, live_prices: dict, historical: pd.DataFrame):
    rows = []
    total_value = 0.0
    base_total_value = 0.0

    for ticker, meta in updated_portfolio.items():
        price = get_safe_price(ticker, live_prices, historical)

        shares = float(meta["shares"])
        base_shares = float(meta["base_shares"])

        value = shares * price
        base_value = base_shares * price

        total_value += value
        base_total_value += base_value

        rows.append(
            {
                "Ticker": ticker,
                "Name": meta["name"],
                "Shares": round(shares, 4),
                "Price": round(price, 2),
                "Value": round(value, 2),
                "Base Shares": round(base_shares, 4),
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
    usable = [ticker for ticker in df["Ticker"] if ticker in historical.columns]

    if not usable:
        return pd.Series(dtype=float), pd.DataFrame()

    hist = historical[usable].copy().dropna(how="all")
    returns = hist.pct_change().dropna()

    if returns.empty:
        return pd.Series(dtype=float), returns

    weight_map = df.set_index("Ticker")["Weight"]
    weights = weight_map.loc[usable]

    if weights.sum() <= 0:
        return pd.Series(dtype=float), returns

    weights = weights / weights.sum()

    portfolio_returns = returns.mul(weights, axis=1).sum(axis=1)

    return portfolio_returns, returns


def build_benchmark_returns():
    bench = get_historical_data(["VOO"], period="2y")
    if bench.empty or "VOO" not in bench.columns:
        return pd.Series(dtype=float)

    return bench["VOO"].pct_change().dropna()


def simulate_efficient_frontier(asset_returns: pd.DataFrame, n_portfolios: int = 4000):
    if asset_returns.empty or asset_returns.shape[1] < 2:
        return pd.DataFrame()

    mean_returns = asset_returns.mean() * 252
    cov_matrix = asset_returns.cov() * 252

    n_assets = len(mean_returns)
    rng = np.random.default_rng(42)

    weights = rng.random((n_portfolios, n_assets))
    weights = weights / weights.sum(axis=1, keepdims=True)

    port_returns = weights @ mean_returns.values
    port_vols = np.sqrt(np.einsum("ij,jk,ik->i", weights, cov_matrix.values, weights))
    sharpe = np.where(port_vols > 0, port_returns / port_vols, 0)

    frontier = pd.DataFrame({
        "Return": port_returns,
        "Volatility": port_vols,
        "Sharpe": sharpe,
    })

    frontier["Weights"] = list(weights)

    return frontier


# -------------------------
# Private portfolio
# -------------------------
private_available = True
private_portfolio = {}

try:
    private_portfolio = load_private_portfolio()
except Exception:
    private_available = False

# -------------------------
# Mode / auth
# -------------------------
mode = st.sidebar.selectbox("View Mode", ["Public", "Private"])
authenticated = False

if mode == "Private":
    if not private_available:
        st.error("Private portfolio not available. Check Streamlit secrets.")
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

# -------------------------
# Active portfolio
# -------------------------
portfolio_data = get_active_portfolio(mode, authenticated, private_portfolio)
prefix = get_mode_prefix(mode)

# -------------------------
# Widget state
# -------------------------
init_mode_state(portfolio_data, prefix)

if st.sidebar.button("Reset Portfolio"):
    reset_mode_state(portfolio_data, prefix)
    st.rerun()

st.sidebar.header("Portfolio Inputs")
updated_portfolio = build_current_portfolio(portfolio_data, prefix, mode)

# -------------------------
# Market data
# -------------------------
tickers = list(updated_portfolio.keys())
live_prices = get_prices(tickers)
historical = get_historical_data(tickers, period="2y")

if historical.empty:
    st.error("Could not load historical data.")
    st.stop()

missing_hist = [ticker for ticker in tickers if ticker not in historical.columns]
if missing_hist:
    st.warning(f"No historical data for: {', '.join(missing_hist)}")

# -------------------------
# Portfolio table
# -------------------------
df, total_value = build_portfolio_df(updated_portfolio, live_prices, historical)

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

# -------------------------
# Allocation charts
# -------------------------
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

# -------------------------
# Performance metrics
# -------------------------
portfolio_returns, asset_returns = build_portfolio_returns(df, historical)
benchmark_returns = build_benchmark_returns()

total_return = 0.0
volatility = 0.0
sharpe = 0.0
max_drawdown = 0.0
alpha = 0.0
beta = 0.0
tracking_error = 0.0
information_ratio = 0.0

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

if not portfolio_cum.empty:
    st.subheader("Performance vs Benchmark")

    fig_perf = go.Figure()
    fig_perf.add_scatter(x=portfolio_cum.index, y=portfolio_cum, name="Portfolio")

    portfolio_last_x = portfolio_cum.index[-1]
    portfolio_last_y = portfolio_cum.iloc[-1]
    fig_perf.add_annotation(
        x=portfolio_last_x,
        y=portfolio_last_y,
        text=f"Portfolio: {portfolio_last_y - 1:.2%}",
        showarrow=True,
        arrowhead=2,
        ax=20,
        ay=-20,
    )

    portfolio_benchmark_return = None
    excess_vs_benchmark = None

    if not benchmark_cum.empty:
        fig_perf.add_scatter(x=benchmark_cum.index, y=benchmark_cum, name="VOO")

        benchmark_last_x = benchmark_cum.index[-1]
        benchmark_last_y = benchmark_cum.iloc[-1]

        fig_perf.add_annotation(
            x=benchmark_last_x,
            y=benchmark_last_y,
            text=f"VOO: {benchmark_last_y - 1:.2%}",
            showarrow=True,
            arrowhead=2,
            ax=20,
            ay=20,
        )

        portfolio_benchmark_return = float(benchmark_last_y - 1)
        excess_vs_benchmark = float((portfolio_last_y - 1) - portfolio_benchmark_return)

    st.plotly_chart(fig_perf, use_container_width=True)

    p1, p2, p3 = st.columns(3)
    p1.metric("Portfolio Cumulative Return", f"{portfolio_last_y - 1:.2%}")

    if portfolio_benchmark_return is not None:
        p2.metric("Benchmark Cumulative Return", f"{portfolio_benchmark_return:.2%}")
        p3.metric("Excess Return vs Benchmark", f"{excess_vs_benchmark:.2%}")
    else:
        p2.metric("Benchmark Cumulative Return", "N/A")
        p3.metric("Excess Return vs Benchmark", "N/A")

# -------------------------
# Efficient frontier
# -------------------------
st.subheader("Efficient Frontier")

frontier = simulate_efficient_frontier(asset_returns)

if frontier.empty:
    st.info("Efficient frontier requires historical data for at least 2 assets.")
else:
    mean_returns = asset_returns.mean() * 252
    cov_matrix = asset_returns.cov() * 252
    usable = asset_returns.columns.tolist()

    current_weights = (
        df.set_index("Ticker").loc[usable, "Weight"] /
        max(df.set_index("Ticker").loc[usable, "Weight"].sum(), 1e-12)
    ).values

    current_return = float(current_weights @ mean_returns.values)
    current_vol = float(np.sqrt(current_weights @ cov_matrix.values @ current_weights.T))
    current_sharpe = float(current_return / current_vol) if current_vol > 0 else 0.0

    max_sharpe_row = frontier.loc[frontier["Sharpe"].idxmax()]
    min_vol_row = frontier.loc[frontier["Volatility"].idxmin()]

    fig_frontier = go.Figure()

    fig_frontier.add_trace(
        go.Scatter(
            x=frontier["Volatility"],
            y=frontier["Return"],
            mode="markers",
            marker=dict(
                size=5,
                color=frontier["Sharpe"],
                colorscale="Viridis",
                showscale=True,
                colorbar=dict(title="Sharpe"),
            ),
            name="Simulated Portfolios",
            hovertemplate="Volatility: %{x:.2%}<br>Return: %{y:.2%}<br>Sharpe: %{marker.color:.2f}<extra></extra>",
        )
    )

    fig_frontier.add_trace(
        go.Scatter(
            x=[current_vol],
            y=[current_return],
            mode="markers+text",
            text=["Current"],
            textposition="top center",
            marker=dict(size=12, symbol="x"),
            name="Current Portfolio",
        )
    )

    fig_frontier.add_trace(
        go.Scatter(
            x=[max_sharpe_row["Volatility"]],
            y=[max_sharpe_row["Return"]],
            mode="markers+text",
            text=["Max Sharpe"],
            textposition="top center",
            marker=dict(size=12, symbol="diamond"),
            name="Max Sharpe",
        )
    )

    fig_frontier.add_trace(
        go.Scatter(
            x=[min_vol_row["Volatility"]],
            y=[min_vol_row["Return"]],
            mode="markers+text",
            text=["Min Vol"],
            textposition="bottom center",
            marker=dict(size=12, symbol="circle"),
            name="Min Volatility",
        )
    )

    fig_frontier.update_layout(
        xaxis_title="Volatility",
        yaxis_title="Expected Return",
    )

    st.plotly_chart(fig_frontier, use_container_width=True)

    f1, f2, f3 = st.columns(3)
    f1.metric("Current Portfolio Return / Vol", f"{current_return:.2%} / {current_vol:.2%}")
    f2.metric("Max Sharpe Return / Vol", f"{max_sharpe_row['Return']:.2%} / {max_sharpe_row['Volatility']:.2%}")
    f3.metric("Min Vol Return / Vol", f"{min_vol_row['Return']:.2%} / {min_vol_row['Volatility']:.2%}")

    f4, f5, f6 = st.columns(3)
    f4.metric("Current Portfolio Sharpe", f"{current_sharpe:.2f}")
    f5.metric("Max Sharpe Ratio", f"{max_sharpe_row['Sharpe']:.2f}")
    f6.metric("Min Vol Sharpe", f"{min_vol_row['Sharpe']:.2f}")