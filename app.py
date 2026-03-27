import html
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from portfolio import public_portfolio
from utils import get_prices, get_historical_data


st.set_page_config(page_title="Portfolio Dashboard", layout="wide")

RISK_FREE_RATE = 0.02
N_SIMULATIONS = 8000


# =========================
# BLOOMBERG-STYLE THEME
# =========================
def apply_bloomberg_style():
    st.markdown(
        """
        <style>
        html, body, [class*="css"]  {
            font-family: "IBM Plex Mono", "SFMono-Regular", Menlo, Monaco, Consolas, "Liberation Mono", monospace !important;
        }

        .stApp {
            background-color: #0b0f14;
            color: #e6e6e6;
        }

        [data-testid="stSidebar"] {
            background: #0f141b;
            border-right: 1px solid #2a313c;
        }

        [data-testid="stHeader"] {
            background: #0b0f14;
        }

        h1, h2, h3, h4 {
            color: #f3a712 !important;
            letter-spacing: 0.5px;
        }

        .bb-title {
            font-size: 2.2rem;
            font-weight: 800;
            color: #f3a712;
            letter-spacing: 1px;
            padding: 0.2rem 0 0.8rem 0;
            border-bottom: 2px solid #f3a712;
            margin-bottom: 1rem;
            text-transform: uppercase;
        }

        .bb-section {
            background: linear-gradient(180deg, #111821 0%, #0d131a 100%);
            border: 1px solid #2b3340;
            border-left: 4px solid #f3a712;
            border-radius: 6px;
            padding: 0.85rem 1rem 0.9rem 1rem;
            margin: 0.65rem 0 1rem 0;
            box-shadow: 0 0 0 1px rgba(243,167,18,0.05) inset;
        }

        .bb-section-title {
            font-size: 1rem;
            font-weight: 800;
            color: #f3a712;
            text-transform: uppercase;
            margin-bottom: 0.4rem;
            letter-spacing: 0.5px;
        }

        .bb-info {
            color: #7fb3ff;
            cursor: help;
            font-weight: 700;
            margin-left: 0.2rem;
        }

        [data-testid="stMetric"] {
            background: #121922;
            border: 1px solid #2e3744;
            border-top: 2px solid #f3a712;
            border-radius: 6px;
            padding: 0.7rem 0.8rem 0.5rem 0.8rem;
        }

        [data-testid="stMetricLabel"] {
            color: #9fb0c3 !important;
            text-transform: uppercase;
            font-size: 0.75rem !important;
            letter-spacing: 0.6px;
        }

        [data-testid="stMetricValue"] {
            color: #f8f8f8 !important;
            font-size: 1.45rem !important;
            font-weight: 800 !important;
        }

        .stButton > button {
            background: #151d27;
            color: #f3a712;
            border: 1px solid #f3a712;
            border-radius: 4px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.4px;
        }

        .stButton > button:hover {
            background: #f3a712;
            color: #0b0f14;
            border-color: #f3a712;
        }

        .stSelectbox label, .stNumberInput label, .stTextInput label, .stMarkdown, .stCaption {
            color: #cbd5df !important;
        }

        .stTextInput > div > div > input,
        .stNumberInput input,
        .stSelectbox div[data-baseweb="select"] > div {
            background-color: #0f141b !important;
            color: #f2f2f2 !important;
            border: 1px solid #394250 !important;
            border-radius: 4px !important;
        }

        .stExpander {
            border: 1px solid #2d3642 !important;
            border-radius: 6px !important;
            background: #0f141b !important;
        }

        div[data-testid="stDataFrame"] {
            border: 1px solid #2d3642;
            border-radius: 6px;
            overflow: hidden;
        }

        div[data-testid="stDataFrame"] * {
            color: #e5e7eb !important;
        }

        div[data-testid="stDataFrame"] [role="columnheader"] {
            background-color: #18212c !important;
            color: #f3a712 !important;
            font-weight: 800 !important;
            text-transform: uppercase;
        }

        div[data-testid="stDataFrame"] [role="gridcell"] {
            background-color: #0f141b !important;
        }

        .stAlert {
            border-radius: 6px !important;
            border: 1px solid #2b3340 !important;
        }

        .stTabs [data-baseweb="tab-list"] {
            gap: 6px;
        }

        .stTabs [data-baseweb="tab"] {
            background: #111821;
            border: 1px solid #2b3340;
            border-radius: 4px 4px 0 0;
            color: #d1d5db;
            font-weight: 700;
        }

        .stTabs [aria-selected="true"] {
            color: #f3a712 !important;
            border-color: #f3a712 !important;
        }

        .bb-topline {
            color: #7fb3ff;
            font-size: 0.82rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 0.4rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


apply_bloomberg_style()
st.markdown('<div class="bb-title">Portfolio Dashboard</div>', unsafe_allow_html=True)


# =========================
# UI HELPERS
# =========================
def info_html(text: str, help_text: str, size: str = "1rem", weight: str = "700"):
    safe_help = html.escape(help_text, quote=True)
    safe_text = html.escape(text)
    return (
        f"<span style='font-size:{size}; font-weight:{weight}; color:#f3a712; text-transform:uppercase; letter-spacing:0.5px;'>"
        f"{safe_text}</span>"
        f"<span class='bb-info' title='{safe_help}'>ⓘ</span>"
    )


def info_section(title: str, help_text: str):
    st.markdown(
        f"""
        <div class="bb-section">
            <div class="bb-section-title">{info_html(title, help_text)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def info_metric(container, label: str, value: str, help_text: str):
    container.markdown(
        info_html(label, help_text, size="0.84rem", weight="800"),
        unsafe_allow_html=True,
    )
    container.metric(" ", value)


# =========================
# DATA LOADERS
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
            help=(
                "Number of shares currently held for this asset. "
                "Public mode changes with step 1. Private mode changes with step 0.0001."
            ),
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


# =========================
# OPTIMIZATION HELPERS
# =========================
def get_default_constraints(profile: str):
    if profile == "Aggressive":
        return {"max_single_asset": 0.70, "min_bonds": 0.00, "min_gold": 0.00}
    if profile == "Balanced":
        return {"max_single_asset": 0.45, "min_bonds": 0.10, "min_gold": 0.05}
    return {"max_single_asset": 0.35, "min_bonds": 0.20, "min_gold": 0.10}


def classify_assets(asset_names):
    bonds = {"BND", "AGG", "IEF", "TLT", "VGIT", "BNDX"}
    gold = {"IGLN.L", "GLD", "IAU", "SGLN.L"}

    bond_idx = [i for i, t in enumerate(asset_names) if t in bonds]
    gold_idx = [i for i, t in enumerate(asset_names) if t in gold]

    return bond_idx, gold_idx


def bucket_for_ticker(ticker: str):
    bonds = {"BND", "AGG", "IEF", "TLT", "VGIT", "BNDX"}
    gold = {"IGLN.L", "GLD", "IAU", "SGLN.L"}
    if ticker in bonds:
        return "Bonds"
    if ticker in gold:
        return "Gold"
    return "Equities"


def simulate_constrained_efficient_frontier(
    asset_returns: pd.DataFrame,
    asset_names: list,
    constraints: dict,
    risk_free_rate: float = 0.02,
    n_portfolios: int = 8000,
):
    if asset_returns.empty or asset_returns.shape[1] < 2:
        return pd.DataFrame()

    mean_returns = asset_returns.mean() * 252
    cov_matrix = asset_returns.cov() * 252

    n_assets = len(mean_returns)
    max_single_asset = float(constraints["max_single_asset"])
    min_bonds = float(constraints["min_bonds"])
    min_gold = float(constraints["min_gold"])

    if min_bonds + min_gold > 1:
        return pd.DataFrame()

    bond_idx, gold_idx = classify_assets(asset_names)

    rng = np.random.default_rng(42)
    raw = rng.random((n_portfolios * 6, n_assets))
    weights = raw / raw.sum(axis=1, keepdims=True)

    mask = weights.max(axis=1) <= max_single_asset

    if bond_idx:
        mask &= weights[:, bond_idx].sum(axis=1) >= min_bonds
    elif min_bonds > 0:
        mask &= False

    if gold_idx:
        mask &= weights[:, gold_idx].sum(axis=1) >= min_gold
    elif min_gold > 0:
        mask &= False

    feasible = weights[mask]

    if feasible.shape[0] == 0:
        return pd.DataFrame()

    feasible = feasible[:n_portfolios]

    port_returns = feasible @ mean_returns.values
    port_vols = np.sqrt(np.einsum("ij,jk,ik->i", feasible, cov_matrix.values, feasible))
    sharpe = np.where(port_vols > 0, (port_returns - risk_free_rate) / port_vols, 0)

    frontier = pd.DataFrame({
        "Return": port_returns,
        "Volatility": port_vols,
        "Sharpe": sharpe,
    })
    frontier["Weights"] = list(feasible)

    return frontier


def weights_table(weight_array, asset_names):
    out = pd.DataFrame({
        "Ticker": asset_names,
        "Weight %": np.round(np.array(weight_array) * 100, 2),
    })
    return out.sort_values("Weight %", ascending=False).reset_index(drop=True)


def build_recommended_shares_table(weight_array, asset_names, df_current):
    price_map = df_current.set_index("Ticker")["Price"].to_dict()
    current_shares_map = df_current.set_index("Ticker")["Shares"].to_dict()
    current_weight_map = df_current.set_index("Ticker")["Weight %"].to_dict()
    current_value_map = df_current.set_index("Ticker")["Value"].to_dict()

    total_value = float(df_current["Value"].sum())
    rows = []

    for ticker, weight in zip(asset_names, weight_array):
        price = float(price_map.get(ticker, 0.0))
        current_shares = float(current_shares_map.get(ticker, 0.0))
        current_weight = float(current_weight_map.get(ticker, 0.0))
        current_value = float(current_value_map.get(ticker, 0.0))

        target_value = total_value * float(weight)
        target_shares = target_value / price if price > 0 else 0.0
        delta_shares = target_shares - current_shares

        rows.append({
            "Ticker": ticker,
            "Current Shares": round(current_shares, 4),
            "Recommended Shares": round(target_shares, 4),
            "Shares Delta": round(delta_shares, 4),
            "Current Value": round(current_value, 2),
            "Target Value": round(target_value, 2),
            "Current Weight %": round(current_weight, 2),
            "Target Weight %": round(float(weight) * 100, 2),
        })

    rec = pd.DataFrame(rows)
    rec["Abs Delta"] = rec["Shares Delta"].abs()
    rec = rec.sort_values("Abs Delta", ascending=False).drop(columns=["Abs Delta"]).reset_index(drop=True)
    return rec


def build_rebalancing_table(df_current: pd.DataFrame, target_weight_map: dict):
    total_value = float(df_current["Value"].sum())
    rows = []

    for _, row in df_current.iterrows():
        ticker = row["Ticker"]
        price = float(row["Price"])
        current_shares = float(row["Shares"])
        current_value = float(row["Value"])
        current_weight = float(row["Weight"])

        target_weight = float(target_weight_map.get(ticker, 0.0))
        target_value = total_value * target_weight
        target_shares = target_value / price if price > 0 else 0.0

        shares_delta = target_shares - current_shares
        value_delta = target_value - current_value

        if abs(value_delta) < 1:
            action = "Hold"
        elif value_delta > 0:
            action = "Buy"
        else:
            action = "Sell"

        rows.append({
            "Ticker": ticker,
            "Current Shares": round(current_shares, 4),
            "Target Shares": round(target_shares, 4),
            "Shares Delta": round(shares_delta, 4),
            "Current Value": round(current_value, 2),
            "Target Value": round(target_value, 2),
            "Value Delta": round(value_delta, 2),
            "Current Weight %": round(current_weight * 100, 2),
            "Target Weight %": round(target_weight * 100, 2),
            "Action": action,
        })

    out = pd.DataFrame(rows)
    out["Abs Value Delta"] = out["Value Delta"].abs()
    out = out.sort_values("Abs Value Delta", ascending=False).drop(columns=["Abs Value Delta"]).reset_index(drop=True)
    return out


def build_stress_test_table(df_current: pd.DataFrame, shocks: dict):
    rows = []
    current_total = float(df_current["Value"].sum())
    stressed_total = 0.0

    for _, row in df_current.iterrows():
        ticker = row["Ticker"]
        bucket = bucket_for_ticker(ticker)
        shock = float(shocks.get(bucket, 0.0))

        current_price = float(row["Price"])
        current_value = float(row["Value"])
        shares = float(row["Shares"])

        stressed_price = current_price * (1 + shock)
        stressed_value = shares * stressed_price
        stressed_total += stressed_value

        rows.append({
            "Ticker": ticker,
            "Bucket": bucket,
            "Shock %": round(shock * 100, 2),
            "Current Price": round(current_price, 2),
            "Stressed Price": round(stressed_price, 2),
            "Current Value": round(current_value, 2),
            "Stressed Value": round(stressed_value, 2),
            "P/L": round(stressed_value - current_value, 2),
        })

    out = pd.DataFrame(rows)
    if stressed_total > 0:
        out["Stressed Weight %"] = (out["Stressed Value"] / stressed_total * 100).round(2)
    else:
        out["Stressed Weight %"] = 0.0

    return out, current_total, stressed_total


def compute_rolling_metrics(portfolio_returns: pd.Series, benchmark_returns: pd.Series, risk_free_rate: float, window: int):
    if portfolio_returns.empty:
        return pd.DataFrame()

    df_roll = pd.DataFrame(index=portfolio_returns.index)
    rolling_vol = portfolio_returns.rolling(window).std() * np.sqrt(252)
    rolling_return = portfolio_returns.rolling(window).mean() * 252
    rolling_sharpe = (rolling_return - risk_free_rate) / rolling_vol.replace(0, np.nan)

    cum = (1 + portfolio_returns).cumprod()
    rolling_peak = cum.rolling(window).max()
    rolling_drawdown = cum / rolling_peak - 1

    df_roll["Rolling Volatility"] = rolling_vol
    df_roll["Rolling Sharpe"] = rolling_sharpe
    df_roll["Rolling Drawdown"] = rolling_drawdown

    if not benchmark_returns.empty:
        aligned = pd.concat(
            [portfolio_returns.rename("Portfolio"), benchmark_returns.rename("Benchmark")],
            axis=1
        ).dropna()

        if not aligned.empty:
            rolling_cov = aligned["Portfolio"].rolling(window).cov(aligned["Benchmark"])
            rolling_var = aligned["Benchmark"].rolling(window).var()
            rolling_beta = rolling_cov / rolling_var.replace(0, np.nan)

            df_roll = df_roll.join(rolling_beta.rename("Rolling Beta"), how="left")

    return df_roll.dropna(how="all")


# =========================
# PRIVATE PORTFOLIO
# =========================
private_available = True
private_portfolio = {}

try:
    private_portfolio = load_private_portfolio()
except Exception:
    private_available = False


# =========================
# MODE / AUTH
# =========================
mode = st.sidebar.selectbox("View Mode", ["Public", "Private"])
authenticated = False

if mode == "Private":
    if not private_available:
        st.error("Private portfolio not available. Check Streamlit secrets.")
        st.stop()

    password = st.sidebar.text_input("Password", type="password")

    if not password:
        st.stop()

    if password != st.secrets["auth"]["password"]:
        st.error("Incorrect password.")
        st.stop()

    authenticated = True


# =========================
# ACTIVE PORTFOLIO
# =========================
portfolio_data = get_active_portfolio(mode, authenticated, private_portfolio)
prefix = get_mode_prefix(mode)


# =========================
# WIDGET STATE
# =========================
init_mode_state(portfolio_data, prefix)

if st.sidebar.button("Reset Portfolio", help="Restore the original share quantities defined for the active mode."):
    reset_mode_state(portfolio_data, prefix)
    st.rerun()

st.sidebar.header("Portfolio Inputs", help="Adjust share quantities for the active portfolio.")
updated_portfolio = build_current_portfolio(portfolio_data, prefix, mode)

st.sidebar.header("Optimization Settings", help="Controls used for the constrained efficient frontier simulation.")

profile = st.sidebar.selectbox(
    "Investor Profile",
    ["Aggressive", "Balanced", "Conservative"],
    help="Select a default constraint set based on the investor risk profile.",
)

defaults = get_default_constraints(profile)

with st.sidebar.expander("Custom Constraints", expanded=False):
    max_single_asset = st.number_input(
        "Max single-asset weight",
        min_value=0.05,
        max_value=1.00,
        value=float(defaults["max_single_asset"]),
        step=0.01,
        format="%.2f",
        help="Maximum allowed portfolio weight for any single asset.",
    )
    min_bonds = st.number_input(
        "Minimum bonds allocation",
        min_value=0.00,
        max_value=1.00,
        value=float(defaults["min_bonds"]),
        step=0.01,
        format="%.2f",
        help="Minimum required total weight allocated to bond assets.",
    )
    min_gold = st.number_input(
        "Minimum gold allocation",
        min_value=0.00,
        max_value=1.00,
        value=float(defaults["min_gold"]),
        step=0.01,
        format="%.2f",
        help="Minimum required total weight allocated to gold assets.",
    )
    custom_rf = st.number_input(
        "Risk-free rate",
        min_value=0.00,
        max_value=0.20,
        value=float(RISK_FREE_RATE),
        step=0.005,
        format="%.3f",
        help="Annual risk-free rate used in Sharpe ratio and Capital Market Line calculations.",
    )

constraints = {
    "max_single_asset": max_single_asset,
    "min_bonds": min_bonds,
    "min_gold": min_gold,
}
risk_free_rate = custom_rf

st.sidebar.header("Stress Testing", help="Apply category shocks to estimate stressed portfolio value.")
equity_shock = st.sidebar.number_input(
    "Equities Shock",
    min_value=-1.00,
    max_value=1.00,
    value=-0.10,
    step=0.01,
    format="%.2f",
    help="Shock applied to assets classified as equities.",
)
bonds_shock = st.sidebar.number_input(
    "Bonds Shock",
    min_value=-1.00,
    max_value=1.00,
    value=-0.03,
    step=0.01,
    format="%.2f",
    help="Shock applied to assets classified as bonds.",
)
gold_shock = st.sidebar.number_input(
    "Gold Shock",
    min_value=-1.00,
    max_value=1.00,
    value=0.05,
    step=0.01,
    format="%.2f",
    help="Shock applied to assets classified as gold.",
)
rolling_window = st.sidebar.slider(
    "Rolling Window (days)",
    min_value=21,
    max_value=252,
    value=63,
    step=21,
    help="Window used to compute rolling volatility, Sharpe, beta, and drawdown.",
)

stress_shocks = {
    "Equities": equity_shock,
    "Bonds": bonds_shock,
    "Gold": gold_shock,
}


# =========================
# MARKET DATA
# =========================
tickers = list(updated_portfolio.keys())
live_prices = get_prices(tickers)
historical = get_historical_data(tickers, period="2y")

if historical.empty:
    st.error("Could not load historical data.")
    st.stop()

missing_hist = [ticker for ticker in tickers if ticker not in historical.columns]
if missing_hist:
    st.warning(f"No historical data for: {', '.join(missing_hist)}")


# =========================
# PORTFOLIO TABLE
# =========================
df, total_value = build_portfolio_df(updated_portfolio, live_prices, historical)

st.markdown('<div class="bb-topline">PX_LAST · WGT · RISK · OPTIMIZATION</div>', unsafe_allow_html=True)

info_section("Portfolio", "Snapshot of current positions, prices, market values, current weights, target weights, and deviations.")
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
info_metric(st, "Total Value", f"${total_value:,.2f}", "Current market value of the portfolio using the latest available prices.")


# =========================
# ALLOCATION CHARTS
# =========================
info_section("Portfolio Allocation", "Portfolio composition by market value. In practice this is the current capital allocation across assets.")

pie_values = df["Value"] if total_value > 0 else df["Weight"]
fig_pie = px.pie(df, names="Name", values=pie_values, hole=0.4)
fig_pie.update_layout(
    paper_bgcolor="#0b0f14",
    plot_bgcolor="#0b0f14",
    font=dict(color="#e6e6e6"),
)
st.plotly_chart(fig_pie, use_container_width=True)

info_section("Target vs Actual Allocation", "Compares current weights with the original base weights for the active mode.")

fig_bar = go.Figure()
fig_bar.add_bar(x=df["Ticker"], y=df["Weight %"], name="Actual %")
fig_bar.add_bar(x=df["Ticker"], y=df["Target %"], name="Target %")
fig_bar.update_layout(
    barmode="group",
    paper_bgcolor="#0b0f14",
    plot_bgcolor="#0b0f14",
    font=dict(color="#e6e6e6"),
)
st.plotly_chart(fig_bar, use_container_width=True)


# =========================
# PERFORMANCE
# =========================
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
        sharpe = float((portfolio_returns.mean() * 252 - risk_free_rate) / volatility)

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

info_section("Performance Metrics", "Return and risk indicators derived from historical daily returns.")

c1, c2, c3, c4 = st.columns(4)
info_metric(c1, "Return", f"{total_return:.2%}", "Cumulative portfolio return over the historical sample.")
info_metric(c2, "Volatility", f"{volatility:.2%}", "Annualized standard deviation of portfolio returns.")
info_metric(c3, "Sharpe Ratio", f"{sharpe:.2f}", "Risk-adjusted return using the selected risk-free rate.")
info_metric(c4, "Max Drawdown", f"{max_drawdown:.2%}", "Largest peak-to-trough decline over the sample.")

c5, c6, c7, c8 = st.columns(4)
info_metric(c5, "Alpha", f"{alpha:.2%}", "Return unexplained by benchmark beta exposure.")
info_metric(c6, "Beta", f"{beta:.2f}", "Sensitivity of portfolio returns to benchmark returns.")
info_metric(c7, "Tracking Error", f"{tracking_error:.2%}", "Annualized volatility of active returns versus the benchmark.")
info_metric(c8, "Information Ratio", f"{information_ratio:.2f}", "Active return divided by tracking error.")

if not portfolio_cum.empty:
    info_section("Performance vs Benchmark", "Cumulative growth of the portfolio compared with the benchmark (VOO).")

    fig_perf = go.Figure()
    fig_perf.add_scatter(x=portfolio_cum.index, y=portfolio_cum, name="Portfolio")

    portfolio_last_x = portfolio_cum.index[-1]
    portfolio_last_y = portfolio_cum.iloc[-1]
    portfolio_cum_return = float(portfolio_last_y - 1)

    fig_perf.add_annotation(
        x=portfolio_last_x,
        y=portfolio_last_y,
        text=f"Portfolio: {portfolio_cum_return:.2%}",
        showarrow=True,
        arrowhead=2,
        ax=20,
        ay=-20,
    )

    benchmark_cum_return = None
    excess_vs_benchmark = None

    if not benchmark_cum.empty:
        fig_perf.add_scatter(x=benchmark_cum.index, y=benchmark_cum, name="VOO")

        benchmark_last_x = benchmark_cum.index[-1]
        benchmark_last_y = benchmark_cum.iloc[-1]
        benchmark_cum_return = float(benchmark_last_y - 1)
        excess_vs_benchmark = float(portfolio_cum_return - benchmark_cum_return)

        fig_perf.add_annotation(
            x=benchmark_last_x,
            y=benchmark_last_y,
            text=f"VOO: {benchmark_cum_return:.2%}",
            showarrow=True,
            arrowhead=2,
            ax=20,
            ay=20,
        )

    fig_perf.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
    )
    st.plotly_chart(fig_perf, use_container_width=True)

    p1, p2, p3 = st.columns(3)
    info_metric(p1, "Portfolio Cumulative Return", f"{portfolio_cum_return:.2%}", "End-to-end cumulative return of the portfolio.")
    if benchmark_cum_return is not None:
        info_metric(p2, "Benchmark Cumulative Return", f"{benchmark_cum_return:.2%}", "End-to-end cumulative return of the benchmark.")
        info_metric(p3, "Excess Return vs Benchmark", f"{excess_vs_benchmark:.2%}", "Portfolio cumulative return minus benchmark cumulative return.")
    else:
        info_metric(p2, "Benchmark Cumulative Return", "N/A", "Benchmark data is not available.")
        info_metric(p3, "Excess Return vs Benchmark", "N/A", "Benchmark data is not available.")


# =========================
# EFFICIENT FRONTIER
# =========================
info_section("Efficient Frontier", "Simulated portfolios showing the trade-off between expected return and volatility under the selected constraints.")

frontier = simulate_constrained_efficient_frontier(
    asset_returns=asset_returns,
    asset_names=asset_returns.columns.tolist() if not asset_returns.empty else [],
    constraints=constraints,
    risk_free_rate=risk_free_rate,
    n_portfolios=N_SIMULATIONS,
)

max_sharpe_row = None
min_vol_row = None
usable = []

if frontier.empty:
    st.info("No feasible frontier was found. Try relaxing the constraints or checking historical data availability.")
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
    current_sharpe = float((current_return - risk_free_rate) / current_vol) if current_vol > 0 else 0.0

    max_sharpe_row = frontier.loc[frontier["Sharpe"].idxmax()]
    min_vol_row = frontier.loc[frontier["Volatility"].idxmin()]

    max_x = max(
        frontier["Volatility"].max(),
        current_vol,
        float(max_sharpe_row["Volatility"]),
        float(min_vol_row["Volatility"]),
    ) * 1.1

    cml_x = np.linspace(0, max_x, 100)
    cml_y = risk_free_rate + float(max_sharpe_row["Sharpe"]) * cml_x

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
            hovertemplate="Volatility: %{x:.2%}<br>Expected Return: %{y:.2%}<br>Sharpe: %{marker.color:.2f}<extra></extra>",
        )
    )

    fig_frontier.add_trace(
        go.Scatter(
            x=cml_x,
            y=cml_y,
            mode="lines",
            name="Capital Market Line",
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
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
    )

    st.plotly_chart(fig_frontier, use_container_width=True)

    f1, f2, f3 = st.columns(3)
    info_metric(f1, "Current Expected Return / Volatility", f"{current_return:.2%} / {current_vol:.2%}", "Expected annual return and annualized volatility of the current portfolio.")
    info_metric(f2, "Max Sharpe Return / Volatility", f"{max_sharpe_row['Return']:.2%} / {max_sharpe_row['Volatility']:.2%}", "Expected annual return and volatility of the highest-Sharpe simulated portfolio.")
    info_metric(f3, "Min Vol Return / Volatility", f"{min_vol_row['Return']:.2%} / {min_vol_row['Volatility']:.2%}", "Expected annual return and volatility of the minimum-volatility portfolio.")

    f4, f5, f6 = st.columns(3)
    info_metric(f4, "Current Sharpe Ratio", f"{current_sharpe:.2f}", "Risk-adjusted return of the current portfolio using the selected risk-free rate.")
    info_metric(f5, "Max Sharpe Ratio", f"{max_sharpe_row['Sharpe']:.2f}", "Highest Sharpe ratio among the feasible simulated portfolios.")
    info_metric(f6, "Min Vol Sharpe Ratio", f"{min_vol_row['Sharpe']:.2f}", "Sharpe ratio of the minimum-volatility feasible portfolio.")

    action_col1, action_col2, _ = st.columns([1, 1, 2])

    with action_col1:
        if st.button("Estimate Max Sharpe Shares", help="Estimate how many shares each ETF should have to match the maximum-Sharpe portfolio, without modifying your current holdings."):
            st.session_state[f"show_max_sharpe_targets_{prefix}"] = True

    with action_col2:
        if st.button("Estimate Min Vol Shares", help="Estimate how many shares each ETF should have to match the minimum-volatility portfolio, without modifying your current holdings."):
            st.session_state[f"show_min_vol_targets_{prefix}"] = True

    if st.session_state.get(f"show_max_sharpe_targets_{prefix}", False):
        info_section("Recommended Shares for Max Sharpe", "Estimated share quantities required to reach the maximum-Sharpe allocation, based on current total portfolio value and current prices.")
        rec_df_max = build_recommended_shares_table(max_sharpe_row["Weights"], usable, df)
        st.dataframe(rec_df_max, use_container_width=True)

    if st.session_state.get(f"show_min_vol_targets_{prefix}", False):
        info_section("Recommended Shares for Minimum Volatility", "Estimated share quantities required to reach the minimum-volatility allocation, based on current total portfolio value and current prices.")
        rec_df_min = build_recommended_shares_table(min_vol_row["Weights"], usable, df)
        st.dataframe(rec_df_min, use_container_width=True)

    info_section("Optimization Weights", "Weight breakdown for the optimal simulated portfolios.")

    opt1, opt2 = st.columns(2)

    with opt1:
        st.write("Max Sharpe Portfolio")
        st.dataframe(weights_table(max_sharpe_row["Weights"], usable), use_container_width=True)

    with opt2:
        st.write("Minimum Volatility Portfolio")
        st.dataframe(weights_table(min_vol_row["Weights"], usable), use_container_width=True)


# =========================
# PHASE 1 - REBALANCING ENGINE
# =========================
info_section(
    "Rebalancing Engine",
    "Trade list showing the required buy and sell adjustments to move from the current allocation to a selected target allocation."
)

target_options = ["Base Target"]
if max_sharpe_row is not None:
    target_options.append("Max Sharpe")
if min_vol_row is not None:
    target_options.append("Minimum Volatility")

rebal_target = st.selectbox(
    "Rebalancing Target",
    target_options,
    help="Choose the target allocation used to generate the rebalancing trade list."
)

if rebal_target == "Base Target":
    target_weight_map = df.set_index("Ticker")["Target Weight"].to_dict()
elif rebal_target == "Max Sharpe" and max_sharpe_row is not None:
    target_weight_map = dict(zip(usable, max_sharpe_row["Weights"]))
else:
    target_weight_map = dict(zip(usable, min_vol_row["Weights"]))

rebal_df = build_rebalancing_table(df, target_weight_map)

buy_value = rebal_df.loc[rebal_df["Action"] == "Buy", "Value Delta"].sum()
sell_value = -rebal_df.loc[rebal_df["Action"] == "Sell", "Value Delta"].sum()
net_cash = sell_value - buy_value

r1, r2, r3 = st.columns(3)
info_metric(r1, "Total Buy Value", f"${buy_value:,.2f}", "Total capital required for buy trades.")
info_metric(r2, "Total Sell Value", f"${sell_value:,.2f}", "Total capital released from sell trades.")
info_metric(r3, "Net Cash Impact", f"${net_cash:,.2f}", "Positive means net cash released. Negative means extra cash required.")

st.dataframe(rebal_df, use_container_width=True)


# =========================
# PHASE 1 - STRESS TESTING
# =========================
info_section(
    "Scenario / Stress Testing",
    "Applies category-level shocks to estimate how the portfolio would behave under adverse or favorable market scenarios."
)

stress_df, current_total_value, stressed_total_value = build_stress_test_table(df, stress_shocks)
stress_pnl = stressed_total_value - current_total_value
stress_return = (stressed_total_value / current_total_value - 1) if current_total_value > 0 else 0.0

s1, s2, s3 = st.columns(3)
info_metric(s1, "Current Portfolio Value", f"${current_total_value:,.2f}", "Current market value before stress shocks.")
info_metric(s2, "Stressed Portfolio Value", f"${stressed_total_value:,.2f}", "Portfolio value after applying the stress scenario.")
info_metric(s3, "Scenario P/L", f"${stress_pnl:,.2f} ({stress_return:.2%})", "Profit or loss implied by the scenario.")

fig_stress = go.Figure()
fig_stress.add_bar(x=stress_df["Ticker"], y=stress_df["Current Value"], name="Current Value")
fig_stress.add_bar(x=stress_df["Ticker"], y=stress_df["Stressed Value"], name="Stressed Value")
fig_stress.update_layout(
    barmode="group",
    paper_bgcolor="#0b0f14",
    plot_bgcolor="#0b0f14",
    font=dict(color="#e6e6e6"),
)
st.plotly_chart(fig_stress, use_container_width=True)

st.dataframe(stress_df, use_container_width=True)


# =========================
# PHASE 1 - ROLLING METRICS
# =========================
info_section(
    "Rolling Metrics",
    "Time-varying view of portfolio risk and risk-adjusted performance using a rolling historical window."
)

rolling_df = compute_rolling_metrics(portfolio_returns, benchmark_returns, risk_free_rate, rolling_window)

if rolling_df.empty:
    st.info("Rolling metrics are not available for the current data window.")
else:
    rolling_metric = st.selectbox(
        "Rolling Metric",
        ["Rolling Volatility", "Rolling Sharpe", "Rolling Beta", "Rolling Drawdown"],
        help="Select the rolling indicator to display."
    )

    available_metric = rolling_metric
    if available_metric not in rolling_df.columns:
        available_metric = rolling_df.columns[0]

    fig_roll = go.Figure()
    fig_roll.add_scatter(
        x=rolling_df.index,
        y=rolling_df[available_metric],
        name=available_metric,
    )
    fig_roll.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        xaxis_title="Date",
        yaxis_title=available_metric,
    )
    st.plotly_chart(fig_roll, use_container_width=True)

    last_val = rolling_df[available_metric].dropna()
    if not last_val.empty:
        last_value = last_val.iloc[-1]
        info_metric(
            st,
            f"Latest {available_metric}",
            f"{last_value:.2%}" if "Sharpe" not in available_metric and "Beta" not in available_metric else f"{last_value:.2f}",
            f"Most recent value of {available_metric.lower()} using a {rolling_window}-day rolling window."
        )