import html
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import gspread

from google.oauth2.service_account import Credentials

from portfolio import public_portfolio
from utils import get_prices, get_historical_data


st.set_page_config(page_title="Portfolio Dashboard", layout="wide")

DEFAULT_RISK_FREE_RATE = 0.02
N_SIMULATIONS = 8000
SUPPORTED_BASE_CCY = ["USD", "EUR", "GBP", "COP", "CHF"]


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


def render_status_bar(mode: str, base_currency: str, profile: str, tc_model: str, sheets_ok: bool):
    sheets_text = "SHEETS OK" if sheets_ok else "SHEETS OFF"
    sheets_color = "#22c55e" if sheets_ok else "#ef4444"

    st.markdown(
        f"""
        <div style="
            display:flex;
            gap:18px;
            flex-wrap:wrap;
            align-items:center;
            margin:0.2rem 0 0.9rem 0;
            padding:0.45rem 0.65rem;
            border:1px solid #2b3340;
            border-left:4px solid #f3a712;
            background:#111821;
            border-radius:6px;
            font-size:0.82rem;
            text-transform:uppercase;
            letter-spacing:0.5px;
            color:#cbd5df;
        ">
            <span><b>Mode:</b> {mode}</span>
            <span><b>Base CCY:</b> {base_currency}</span>
            <span><b>Profile:</b> {profile}</span>
            <span><b>TC Model:</b> {tc_model}</span>
            <span><b>Private Sync:</b> <span style="color:{sheets_color}; font-weight:800;">{sheets_text}</span></span>
        </div>
        """,
        unsafe_allow_html=True,
    )


# =========================
# PRIVATE PORTFOLIO
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


def get_manage_password():
    auth_section = dict(st.secrets["auth"])
    return auth_section.get("manage_password", auth_section["password"])


def merge_private_portfolios(base_private: dict, custom_private: dict):
    merged = dict(base_private)
    merged.update(custom_private)
    return merged


# =========================
# GOOGLE SHEETS PRIVATE POSITIONS
# =========================
def connect_private_positions_worksheet():
    try:
        gcp_cfg = dict(st.secrets["gcp_service_account"])
    except Exception as e:
        raise RuntimeError("Missing [gcp_service_account] in Streamlit secrets.") from e

    try:
        sheets_cfg = dict(st.secrets["sheets"])
    except Exception as e:
        raise RuntimeError("Missing [sheets] in Streamlit secrets.") from e

    required_gcp_keys = [
        "type",
        "project_id",
        "private_key",
        "client_email",
        "token_uri",
    ]
    missing_gcp = [k for k in required_gcp_keys if k not in gcp_cfg or not str(gcp_cfg[k]).strip()]
    if missing_gcp:
        raise RuntimeError(f"Missing keys in [gcp_service_account]: {', '.join(missing_gcp)}")

    worksheet_name = str(sheets_cfg.get("private_positions_worksheet", "private_positions")).strip()
    sheet_id = str(sheets_cfg.get("private_positions_sheet_id", "")).strip()
    sheet_url = str(sheets_cfg.get("private_positions_sheet_url", "")).strip()

    if not sheet_id and not sheet_url:
        raise RuntimeError("Missing 'private_positions_sheet_id' or 'private_positions_sheet_url' in [sheets].")

    private_key = str(gcp_cfg["private_key"])
    if "\\n" in private_key:
        gcp_cfg["private_key"] = private_key.replace("\\n", "\n")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    try:
        creds = Credentials.from_service_account_info(gcp_cfg, scopes=scopes)
    except Exception as e:
        raise RuntimeError(f"Invalid Google service account credentials: {e}") from e

    try:
        client = gspread.authorize(creds)
    except Exception as e:
        raise RuntimeError(f"Google authorization failed: {e}") from e

    try:
        if sheet_id:
            spreadsheet = client.open_by_key(sheet_id)
        else:
            spreadsheet = client.open_by_url(sheet_url)
    except Exception as e:
        raise RuntimeError(
            f"Could not open Google Sheet. Verify sheet access, APIs enabled, and sheet id/url. Original error: {e}"
        ) from e

    try:
        ws = spreadsheet.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        try:
            ws = spreadsheet.add_worksheet(title=worksheet_name, rows=500, cols=3)
        except Exception as e:
            raise RuntimeError(f"Could not create worksheet '{worksheet_name}': {e}") from e

    expected_header = ["Ticker", "Name", "Shares"]

    try:
        current_header = ws.row_values(1)
    except Exception:
        current_header = []

    if current_header != expected_header:
        try:
            ws.clear()
            ws.update(range_name="A1:C1", values=[expected_header])
        except Exception as e:
            raise RuntimeError(f"Could not initialize worksheet header: {e}") from e

    return ws


def load_private_positions_from_sheets():
    ws = connect_private_positions_worksheet()
    records = ws.get_all_records()

    positions = {}
    for row in records:
        ticker = str(row.get("Ticker", "")).strip().upper()
        name = str(row.get("Name", "")).strip()
        shares = row.get("Shares", 0)

        if ticker and name:
            try:
                positions[ticker] = {
                    "name": name,
                    "shares": float(shares),
                }
            except Exception:
                continue

    return positions


def save_private_positions_to_sheets(positions: dict):
    ws = connect_private_positions_worksheet()

    rows = [["Ticker", "Name", "Shares"]]
    for ticker in sorted(positions.keys()):
        meta = positions[ticker]
        rows.append([ticker, meta["name"], float(meta["shares"])])

    ws.clear()
    ws.update(range_name="A1", values=rows)


def build_private_portfolio_for_save(portfolio_data: dict, prefix: str):
    saved = {}

    for ticker, meta in portfolio_data.items():
        widget_key = f"{prefix}_shares_{ticker}"
        saved[ticker] = {
            "name": meta["name"],
            "shares": float(st.session_state.get(widget_key, meta["shares"])),
        }

    return saved


def update_selected_private_position(updated_portfolio: dict, prefix: str, selected_ticker: str, new_shares: float):
    payload = {}

    for ticker, meta in updated_portfolio.items():
        payload[ticker] = {
            "name": meta["name"],
            "shares": float(st.session_state.get(f"{prefix}_shares_{ticker}", meta["shares"])),
        }

    if selected_ticker not in payload:
        raise ValueError(f"{selected_ticker} not found in private portfolio.")

    payload[selected_ticker]["shares"] = float(new_shares)
    st.session_state[f"{prefix}_shares_{selected_ticker}"] = float(new_shares)

    save_private_positions_to_sheets(payload)


# =========================
# GENERAL HELPERS
# =========================
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


# =========================
# FX HELPERS
# =========================
def asset_currency(ticker: str) -> str:
    if ticker.endswith(".DE") or ticker.endswith(".AS"):
        return "EUR"
    if ticker.endswith(".L"):
        return "GBP"
    return "USD"


def asset_market_group(ticker: str) -> str:
    if ticker.endswith(".L"):
        return "UK"
    if "." in ticker:
        return "Europe"
    return "US"


def build_fx_data(tickers: list, base_currency: str, period: str = "2y"):
    needed_ccy = set(asset_currency(t) for t in tickers)
    needed_ccy.add(base_currency)
    needed_ccy.add("USD")

    fx_tickers = set()
    for a in needed_ccy:
        for b in needed_ccy:
            if a != b:
                fx_tickers.add(f"{a}{b}=X")

    fx_tickers = sorted(fx_tickers)
    fx_prices = get_prices(fx_tickers) if fx_tickers else {}
    fx_hist = get_historical_data(fx_tickers, period=period) if fx_tickers else pd.DataFrame()

    return fx_prices, fx_hist, fx_tickers


def _get_direct_or_inverse_current(from_ccy: str, to_ccy: str, fx_prices: dict, fx_hist: pd.DataFrame):
    if from_ccy == to_ccy:
        return 1.0

    direct = f"{from_ccy}{to_ccy}=X"
    inverse = f"{to_ccy}{from_ccy}=X"

    direct_val = fx_prices.get(direct)
    if isinstance(direct_val, (int, float)) and pd.notna(direct_val) and direct_val > 0:
        return float(direct_val)

    inverse_val = fx_prices.get(inverse)
    if isinstance(inverse_val, (int, float)) and pd.notna(inverse_val) and inverse_val > 0:
        return 1.0 / float(inverse_val)

    try:
        if direct in fx_hist.columns:
            direct_hist = pd.to_numeric(fx_hist[direct], errors="coerce").dropna()
            if not direct_hist.empty and direct_hist.iloc[-1] > 0:
                return float(direct_hist.iloc[-1])
    except Exception:
        pass

    try:
        if inverse in fx_hist.columns:
            inverse_hist = pd.to_numeric(fx_hist[inverse], errors="coerce").dropna()
            if not inverse_hist.empty and inverse_hist.iloc[-1] > 0:
                return 1.0 / float(inverse_hist.iloc[-1])
    except Exception:
        pass

    return None


def get_fx_rate_current(from_ccy: str, to_ccy: str, fx_prices: dict, fx_hist: pd.DataFrame):
    if from_ccy == to_ccy:
        return 1.0

    direct = _get_direct_or_inverse_current(from_ccy, to_ccy, fx_prices, fx_hist)
    if direct is not None:
        return direct

    if from_ccy != "USD" and to_ccy != "USD":
        leg1 = _get_direct_or_inverse_current(from_ccy, "USD", fx_prices, fx_hist)
        leg2 = _get_direct_or_inverse_current("USD", to_ccy, fx_prices, fx_hist)
        if leg1 is not None and leg2 is not None:
            return leg1 * leg2

    return np.nan


def get_fx_series(from_ccy: str, to_ccy: str, fx_hist: pd.DataFrame):
    if from_ccy == to_ccy:
        return None

    direct = f"{from_ccy}{to_ccy}=X"
    inverse = f"{to_ccy}{from_ccy}=X"

    try:
        if direct in fx_hist.columns:
            s = pd.to_numeric(fx_hist[direct], errors="coerce").dropna()
            if not s.empty:
                return s
    except Exception:
        pass

    try:
        if inverse in fx_hist.columns:
            s = pd.to_numeric(fx_hist[inverse], errors="coerce").dropna()
            if not s.empty:
                return 1.0 / s.replace(0, np.nan)
    except Exception:
        pass

    if from_ccy != "USD" and to_ccy != "USD":
        s1 = get_fx_series(from_ccy, "USD", fx_hist)
        s2 = get_fx_series("USD", to_ccy, fx_hist)

        if s1 is not None and s2 is not None:
            aligned = pd.concat([s1.rename("leg1"), s2.rename("leg2")], axis=1).dropna()
            if not aligned.empty:
                return aligned["leg1"] * aligned["leg2"]

    return None


def convert_historical_to_base(asset_hist_native: pd.DataFrame, tickers: list, base_currency: str, fx_hist: pd.DataFrame):
    converted = {}
    missing_fx = []

    for ticker in tickers:
        if ticker not in asset_hist_native.columns:
            continue

        native_series = pd.to_numeric(asset_hist_native[ticker], errors="coerce").dropna()
        from_ccy = asset_currency(ticker)

        if from_ccy == base_currency:
            converted[ticker] = native_series.rename(ticker)
            continue

        fx_series = get_fx_series(from_ccy, base_currency, fx_hist)
        if fx_series is None:
            missing_fx.append(f"{from_ccy}->{base_currency}")
            continue

        aligned = pd.concat([native_series.rename("asset"), fx_series.rename("fx")], axis=1).dropna()
        if not aligned.empty:
            converted[ticker] = (aligned["asset"] * aligned["fx"]).rename(ticker)

    if not converted:
        return pd.DataFrame(), sorted(set(missing_fx))

    out = pd.concat(converted.values(), axis=1)
    out.columns = list(converted.keys())
    out = out.sort_index().ffill().dropna(how="all")

    return out, sorted(set(missing_fx))


def get_safe_native_price(ticker: str, live_prices: dict, asset_hist_native: pd.DataFrame):
    live_price = live_prices.get(ticker)

    if isinstance(live_price, (int, float)) and pd.notna(live_price) and live_price > 0:
        return float(live_price)

    try:
        if ticker in asset_hist_native.columns:
            last_hist = pd.to_numeric(asset_hist_native[ticker], errors="coerce").dropna().iloc[-1]
            return float(last_hist)
    except Exception:
        pass

    return 0.0


# =========================
# PORTFOLIO DATAFRAME
# =========================
def build_portfolio_df(
    updated_portfolio: dict,
    live_prices_native: dict,
    asset_hist_native: pd.DataFrame,
    fx_prices: dict,
    fx_hist: pd.DataFrame,
    base_currency: str,
):
    rows = []
    total_value = 0.0
    base_total_value = 0.0

    for ticker, meta in updated_portfolio.items():
        native_currency = asset_currency(ticker)
        native_price = get_safe_native_price(ticker, live_prices_native, asset_hist_native)
        fx_rate = get_fx_rate_current(native_currency, base_currency, fx_prices, fx_hist)

        if pd.isna(fx_rate):
            fx_rate = 0.0

        price = native_price * fx_rate

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
                "Market": asset_market_group(ticker),
                "Native Currency": native_currency,
                "Shares": round(shares, 4),
                "Native Price": round(native_price, 2),
                "FX Rate": round(fx_rate, 6),
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


def build_portfolio_returns(df: pd.DataFrame, historical_base: pd.DataFrame):
    usable = [ticker for ticker in df["Ticker"] if ticker in historical_base.columns]

    if not usable:
        return pd.Series(dtype=float), pd.DataFrame()

    hist = historical_base[usable].copy().dropna(how="all")
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


def build_benchmark_returns(base_currency: str, fx_hist: pd.DataFrame):
    bench_native = get_historical_data(["VOO"], period="2y")
    if bench_native.empty or "VOO" not in bench_native.columns:
        return pd.Series(dtype=float)

    voo_series = pd.to_numeric(bench_native["VOO"], errors="coerce").dropna()

    if base_currency == "USD":
        return voo_series.pct_change().dropna()

    fx_series = get_fx_series("USD", base_currency, fx_hist)
    if fx_series is None:
        return pd.Series(dtype=float)

    aligned = pd.concat([voo_series.rename("VOO"), fx_series.rename("FX")], axis=1).dropna()
    if aligned.empty:
        return pd.Series(dtype=float)

    bench_base = aligned["VOO"] * aligned["FX"]
    return bench_base.pct_change().dropna()


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


# =========================
# TRANSACTION COST ENGINE
# =========================
def estimate_transaction_cost(
    ticker: str,
    trade_value: float,
    base_currency: str,
    native_currency: str,
    model: str,
    params: dict,
):
    if trade_value <= 0:
        return {
            "Commission": 0.0,
            "Slippage": 0.0,
            "FX Cost": 0.0,
            "Total Cost": 0.0,
        }

    market = asset_market_group(ticker)

    if model == "Simple Bps":
        commission = 0.0
        slippage = trade_value * params["simple_bps"] / 10000
        fx_cost = trade_value * params["fx_bps"] / 10000 if native_currency != base_currency else 0.0

    elif model == "Manual Override":
        commission = params["manual_fixed_fee"]
        slippage = trade_value * params["manual_bps"] / 10000
        fx_cost = trade_value * params["fx_bps"] / 10000 if native_currency != base_currency else 0.0

    else:
        if market == "US":
            commission_bps = params["us_commission_bps"]
            min_fee = params["us_min_fee"]
        elif market == "UK":
            commission_bps = params["uk_commission_bps"]
            min_fee = params["uk_min_fee"]
        else:
            commission_bps = params["eu_commission_bps"]
            min_fee = params["eu_min_fee"]

        commission = max(trade_value * commission_bps / 10000, min_fee)
        slippage = trade_value * params["slippage_bps"] / 10000
        fx_cost = trade_value * params["fx_bps"] / 10000 if native_currency != base_currency else 0.0

    total_cost = commission + slippage + fx_cost

    return {
        "Commission": commission,
        "Slippage": slippage,
        "FX Cost": fx_cost,
        "Total Cost": total_cost,
    }


def build_rebalancing_table(
    df_current: pd.DataFrame,
    target_weight_map: dict,
    base_currency: str,
    tc_model: str,
    tc_params: dict,
):
    total_value = float(df_current["Value"].sum())
    rows = []

    for _, row in df_current.iterrows():
        ticker = row["Ticker"]
        price = float(row["Price"])
        current_shares = float(row["Shares"])
        current_value = float(row["Value"])
        current_weight = float(row["Weight"])
        native_currency = row["Native Currency"]
        market = row["Market"]

        target_weight = float(target_weight_map.get(ticker, 0.0))
        target_value = total_value * target_weight
        target_shares = target_value / price if price > 0 else 0.0

        shares_delta = target_shares - current_shares
        value_delta = target_value - current_value
        trade_value = abs(value_delta)

        if abs(value_delta) < 1:
            action = "Hold"
        elif value_delta > 0:
            action = "Buy"
        else:
            action = "Sell"

        costs = estimate_transaction_cost(
            ticker=ticker,
            trade_value=trade_value,
            base_currency=base_currency,
            native_currency=native_currency,
            model=tc_model,
            params=tc_params,
        )

        if action == "Buy":
            net_cash_flow = -(trade_value + costs["Total Cost"])
        elif action == "Sell":
            net_cash_flow = trade_value - costs["Total Cost"]
        else:
            net_cash_flow = 0.0

        rows.append({
            "Ticker": ticker,
            "Market": market,
            "Native Currency": native_currency,
            "Current Shares": round(current_shares, 4),
            "Target Shares": round(target_shares, 4),
            "Shares Delta": round(shares_delta, 4),
            "Current Value": round(current_value, 2),
            "Target Value": round(target_value, 2),
            "Value Delta": round(value_delta, 2),
            "Current Weight %": round(current_weight * 100, 2),
            "Target Weight %": round(target_weight * 100, 2),
            "Estimated Cost": round(costs["Total Cost"], 2),
            "Net Cash Flow": round(net_cash_flow, 2),
            "Action": action,
        })

    out = pd.DataFrame(rows)
    out["Abs Value Delta"] = out["Value Delta"].abs()
    out = out.sort_values("Abs Value Delta", ascending=False).drop(columns=["Abs Value Delta"]).reset_index(drop=True)
    return out


# =========================
# STRESS TEST / ROLLING
# =========================
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
# PRIVATE PORTFOLIO / AUTH
# =========================
private_available = True
positions_sheet_available = True
positions_sheet_error = ""
private_portfolio = {}
private_sheet_positions = {}

try:
    base_private_portfolio = load_private_portfolio()
except Exception as e:
    private_available = False
    base_private_portfolio = {}
    positions_sheet_error = f"Private base portfolio error: {e}"

if private_available:
    try:
        private_sheet_positions = load_private_positions_from_sheets()
    except Exception as e:
        positions_sheet_available = False
        positions_sheet_error = str(e)
        private_sheet_positions = {}

    private_portfolio = merge_private_portfolios(
        base_private_portfolio,
        private_sheet_positions,
    )

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
# ACTIVE PORTFOLIO / SIDEBAR
# =========================
portfolio_data = get_active_portfolio(mode, authenticated, private_portfolio)
prefix = get_mode_prefix(mode)

base_currency = st.sidebar.selectbox(
    "Base Currency",
    SUPPORTED_BASE_CCY,
    index=0,
    help="Reference currency used to convert all positions, weights, returns, and rebalancing calculations.",
)

init_mode_state(portfolio_data, prefix)

if st.sidebar.button("Reset Portfolio", help="Restore the original share quantities defined for the active mode."):
    reset_mode_state(portfolio_data, prefix)
    st.rerun()

st.sidebar.header("Portfolio Inputs")
updated_portfolio = build_current_portfolio(portfolio_data, prefix, mode)

if mode == "Private" and authenticated:
    st.sidebar.header(
        "Private Position Manager",
        help="Select one of your existing private tickers and update its current shares."
    )

    if not positions_sheet_available:
        st.sidebar.error("Google Sheets connection is not available.")
        if positions_sheet_error:
            st.sidebar.caption(positions_sheet_error)

        if st.sidebar.button("Retry Google Sheets", key="retry_google_sheets_manager"):
            st.rerun()
    else:
        manager_password_input = st.sidebar.text_input(
            "Manager Password",
            type="password",
            key="manager_password_input_update",
            help="Required to update a private position in Google Sheets.",
        )

        manager_unlocked = manager_password_input == get_manage_password()

        if manager_password_input and not manager_unlocked:
            st.sidebar.error("Incorrect manager password.")

        if manager_unlocked:
            selectable_tickers = list(updated_portfolio.keys())

            selected_ticker = st.sidebar.selectbox(
                "Select Ticker",
                selectable_tickers,
                key="selected_private_ticker_to_update",
                help="Choose which existing private ticker you want to update.",
            )

            current_selected_shares = float(
                st.session_state.get(
                    f"{prefix}_shares_{selected_ticker}",
                    updated_portfolio[selected_ticker]["shares"]
                )
            )

            selected_name = updated_portfolio[selected_ticker]["name"]

            st.sidebar.caption(f"Selected name: {selected_name}")
            st.sidebar.caption(f"Current shares: {current_selected_shares:.4f}")

            new_selected_shares = st.sidebar.number_input(
                "New Current Shares",
                min_value=0.0,
                step=0.0001,
                format="%.4f",
                value=current_selected_shares,
                key=f"new_current_shares_{selected_ticker}",
                help="Write the new current shares for the selected ticker.",
            )

            if st.sidebar.button(
                "Update Selected Position",
                key="update_selected_position_button",
                help="Save only the selected ticker with the new current shares."
            ):
                try:
                    update_selected_private_position(
                        updated_portfolio=updated_portfolio,
                        prefix=prefix,
                        selected_ticker=selected_ticker,
                        new_shares=new_selected_shares,
                    )
                    st.sidebar.success(f"{selected_ticker} updated successfully.")
                    st.rerun()
                except Exception as e:
                    st.sidebar.error(str(e))

if mode == "Private" and authenticated and positions_sheet_available:
    if st.sidebar.button(
        "Save Private Shares",
        help="Save all current private share quantities to Google Sheets so they persist across sessions."
    ):
        try:
            sheet_payload = build_private_portfolio_for_save(updated_portfolio, prefix)
            save_private_positions_to_sheets(sheet_payload)
            st.sidebar.success("Private shares saved to Google Sheets.")
            st.rerun()
        except Exception as e:
            st.sidebar.error(str(e))

st.sidebar.header("Optimization Settings")

profile = st.sidebar.selectbox("Investor Profile", ["Aggressive", "Balanced", "Conservative"])
defaults = get_default_constraints(profile)

with st.sidebar.expander("Custom Constraints", expanded=False):
    max_single_asset = st.number_input("Max single-asset weight", 0.05, 1.00, float(defaults["max_single_asset"]), 0.01, format="%.2f")
    min_bonds = st.number_input("Minimum bonds allocation", 0.00, 1.00, float(defaults["min_bonds"]), 0.01, format="%.2f")
    min_gold = st.number_input("Minimum gold allocation", 0.00, 1.00, float(defaults["min_gold"]), 0.01, format="%.2f")
    risk_free_rate = st.number_input("Risk-free rate", 0.00, 0.20, float(DEFAULT_RISK_FREE_RATE), 0.005, format="%.3f")

constraints = {
    "max_single_asset": max_single_asset,
    "min_bonds": min_bonds,
    "min_gold": min_gold,
}

st.sidebar.header("Transaction Cost Model")

tc_model = st.sidebar.selectbox(
    "Model",
    ["Broker Profile", "Simple Bps", "Manual Override"],
    help="Automated cost estimation model used in the rebalancing engine.",
)

with st.sidebar.expander("Transaction Cost Parameters", expanded=False):
    if tc_model == "Broker Profile":
        us_commission_bps = st.number_input("US commission (bps)", 0.0, 100.0, 3.0, 0.5)
        us_min_fee = st.number_input(f"US minimum fee ({base_currency})", 0.0, 50.0, 1.0, 0.5)
        eu_commission_bps = st.number_input("Europe commission (bps)", 0.0, 100.0, 5.0, 0.5)
        eu_min_fee = st.number_input(f"Europe minimum fee ({base_currency})", 0.0, 50.0, 1.5, 0.5)
        uk_commission_bps = st.number_input("UK commission (bps)", 0.0, 100.0, 5.0, 0.5)
        uk_min_fee = st.number_input(f"UK minimum fee ({base_currency})", 0.0, 50.0, 1.5, 0.5)
        slippage_bps = st.number_input("Slippage (bps)", 0.0, 100.0, 5.0, 0.5)
        fx_bps = st.number_input("FX conversion cost (bps)", 0.0, 100.0, 10.0, 0.5)

        tc_params = {
            "us_commission_bps": us_commission_bps,
            "us_min_fee": us_min_fee,
            "eu_commission_bps": eu_commission_bps,
            "eu_min_fee": eu_min_fee,
            "uk_commission_bps": uk_commission_bps,
            "uk_min_fee": uk_min_fee,
            "slippage_bps": slippage_bps,
            "fx_bps": fx_bps,
        }

    elif tc_model == "Simple Bps":
        simple_bps = st.number_input("All-in trading cost (bps)", 0.0, 100.0, 10.0, 0.5)
        fx_bps = st.number_input("FX conversion cost (bps)", 0.0, 100.0, 10.0, 0.5)

        tc_params = {
            "simple_bps": simple_bps,
            "fx_bps": fx_bps,
        }

    else:
        manual_bps = st.number_input("Variable cost (bps)", 0.0, 100.0, 8.0, 0.5)
        manual_fixed_fee = st.number_input(f"Fixed fee per trade ({base_currency})", 0.0, 100.0, 1.0, 0.5)
        fx_bps = st.number_input("FX conversion cost (bps)", 0.0, 100.0, 10.0, 0.5)

        tc_params = {
            "manual_bps": manual_bps,
            "manual_fixed_fee": manual_fixed_fee,
            "fx_bps": fx_bps,
        }

st.sidebar.header("Stress Testing")
equity_shock = st.sidebar.number_input("Equities Shock", -1.00, 1.00, -0.10, 0.01, format="%.2f")
bonds_shock = st.sidebar.number_input("Bonds Shock", -1.00, 1.00, -0.03, 0.01, format="%.2f")
gold_shock = st.sidebar.number_input("Gold Shock", -1.00, 1.00, 0.05, 0.01, format="%.2f")
rolling_window = st.sidebar.slider("Rolling Window (days)", 21, 252, 63, 21)

stress_shocks = {
    "Equities": equity_shock,
    "Bonds": bonds_shock,
    "Gold": gold_shock,
}


# =========================
# MARKET DATA + FX
# =========================
tickers = list(updated_portfolio.keys())
live_prices_native = get_prices(tickers)
asset_hist_native = get_historical_data(tickers, period="2y")

if asset_hist_native.empty:
    st.error("Could not load historical data.")
    st.stop()

fx_prices, fx_hist, fx_tickers = build_fx_data(tickers, base_currency, period="2y")
historical_base, missing_fx = convert_historical_to_base(asset_hist_native, tickers, base_currency, fx_hist)

if historical_base.empty:
    st.error("Could not build base-currency historical series.")
    st.stop()

missing_hist = [ticker for ticker in tickers if ticker not in historical_base.columns]
if missing_hist:
    st.warning(f"No converted historical data for: {', '.join(missing_hist)}")

if missing_fx:
    st.warning(f"Missing FX history for: {', '.join(missing_fx)}")


# =========================
# PORTFOLIO TABLE
# =========================
df, total_value = build_portfolio_df(
    updated_portfolio=updated_portfolio,
    live_prices_native=live_prices_native,
    asset_hist_native=asset_hist_native,
    fx_prices=fx_prices,
    fx_hist=fx_hist,
    base_currency=base_currency,
)

render_status_bar(
    mode=mode,
    base_currency=base_currency,
    profile=profile,
    tc_model=tc_model,
    sheets_ok=(positions_sheet_available if mode == "Private" else True),
)

info_section("Portfolio", f"Snapshot of current positions in {base_currency}, including FX conversion, current weights, target weights, and deviations.")

display_df = df[[
    "Ticker",
    "Name",
    "Market",
    "Native Currency",
    "Shares",
    "Native Price",
    "FX Rate",
    "Price",
    "Value",
    "Weight %",
    "Target %",
    "Deviation %",
]].copy()

st.dataframe(display_df, use_container_width=True)
info_metric(st, f"Total Value ({base_currency})", f"{base_currency} {total_value:,.2f}", f"Current market value of the portfolio converted into {base_currency}.")


# =========================
# ALLOCATION
# =========================
info_section("Portfolio Allocation", f"Portfolio composition by market value in {base_currency}.")

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
portfolio_returns, asset_returns = build_portfolio_returns(df, historical_base)
benchmark_returns = build_benchmark_returns(base_currency, fx_hist)

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

info_section("Performance Metrics", f"Return and risk indicators in base currency ({base_currency}) derived from historical daily returns.")

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


# =========================
# PERFORMANCE VS BENCHMARK
# =========================
if not portfolio_cum.empty:
    info_section("Performance vs Benchmark", "Cumulative growth of the portfolio compared with the benchmark (VOO), both expressed in the selected base currency.")

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
# REBALANCING ENGINE + COSTS
# =========================
info_section(
    "Rebalancing Engine",
    "Trade list showing the required buy and sell adjustments to move from the current allocation to a selected target allocation, including estimated transaction costs."
)

target_options = ["Base Target"]
if max_sharpe_row is not None:
    target_options.append("Max Sharpe")
if min_vol_row is not None:
    target_options.append("Minimum Volatility")

rebal_target = st.selectbox(
    "Rebalancing Target",
    target_options,
    help="Choose the target allocation used to generate the trade list."
)

if rebal_target == "Base Target":
    target_weight_map = df.set_index("Ticker")["Target Weight"].to_dict()
elif rebal_target == "Max Sharpe" and max_sharpe_row is not None:
    target_weight_map = dict(zip(usable, max_sharpe_row["Weights"]))
else:
    target_weight_map = dict(zip(usable, min_vol_row["Weights"]))

rebal_df = build_rebalancing_table(
    df_current=df,
    target_weight_map=target_weight_map,
    base_currency=base_currency,
    tc_model=tc_model,
    tc_params=tc_params,
)

buy_value = rebal_df.loc[rebal_df["Action"] == "Buy", "Value Delta"].sum()
sell_value = -rebal_df.loc[rebal_df["Action"] == "Sell", "Value Delta"].sum()
total_estimated_cost = rebal_df["Estimated Cost"].sum()
net_cash_after_costs = rebal_df["Net Cash Flow"].sum()

r1, r2, r3, r4 = st.columns(4)
info_metric(r1, "Total Buy Value", f"{base_currency} {buy_value:,.2f}", "Total gross capital required for buy trades.")
info_metric(r2, "Total Sell Value", f"{base_currency} {sell_value:,.2f}", "Total gross capital released by sell trades.")
info_metric(r3, "Estimated Transaction Costs", f"{base_currency} {total_estimated_cost:,.2f}", "Estimated total trading costs under the selected transaction cost model.")
info_metric(r4, "Net Cash Impact After Costs", f"{base_currency} {net_cash_after_costs:,.2f}", "Positive means net cash released. Negative means additional cash required.")

st.dataframe(rebal_df, use_container_width=True)


# =========================
# STRESS TESTING
# =========================
info_section(
    "Scenario / Stress Testing",
    "Applies category-level shocks to estimate how the portfolio would behave under adverse or favorable market scenarios."
)

stress_df, current_total_value, stressed_total_value = build_stress_test_table(df, stress_shocks)
stress_pnl = stressed_total_value - current_total_value
stress_return = (stressed_total_value / current_total_value - 1) if current_total_value > 0 else 0.0

s1, s2, s3 = st.columns(3)
info_metric(s1, "Current Portfolio Value", f"{base_currency} {current_total_value:,.2f}", "Current portfolio value before the stress scenario.")
info_metric(s2, "Stressed Portfolio Value", f"{base_currency} {stressed_total_value:,.2f}", "Portfolio value after applying the stress scenario.")
info_metric(s3, "Scenario P/L", f"{base_currency} {stress_pnl:,.2f} ({stress_return:.2%})", "Profit or loss implied by the selected shocks.")

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
# ROLLING METRICS
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
        if "Sharpe" in available_metric or "Beta" in available_metric:
            latest_display = f"{last_value:.2f}"
        else:
            latest_display = f"{last_value:.2%}"

        info_metric(
            st,
            f"Latest {available_metric}",
            latest_display,
            f"Most recent value of {available_metric.lower()} using a {rolling_window}-day rolling window."
        )