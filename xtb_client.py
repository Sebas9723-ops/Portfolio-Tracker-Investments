"""
XTB xStation API client.

Uses raw SSL sockets (xAPI protocol) — NOT WebSocket.
Official protocol: JSON messages terminated with \\n\\n over SSL TCP.

Official connector reference: https://github.com/X-trade-Brokers/xAPIConnector

Requires in .streamlit/secrets.toml:
    [xtb]
    account_id = "52413110"
    password   = "your_xtb_password"
    mode       = "real"   # or "demo"
"""
from __future__ import annotations

import json
import socket
import ssl
from typing import Any

import pandas as pd
import streamlit as st

# ── Endpoints (SSL TCP, not WebSocket) ────────────────────────────────────────
_HOSTS = {
    "real": ("xapia.x-trade.com", 5124),
    "demo": ("xapia.x-trade.com", 5124),
}

# ── Symbol mapping ─────────────────────────────────────────────────────────────
_TICKER_TO_XTB: dict[str, list[str]] = {
    "SCHD":    ["SCHD.US_9",  "SCHD.US"],
    "VOO":     ["VOO.US_9",   "VOO.US"],
    "VWCE.DE": ["VWCE.DE_9",  "VWCE.DE"],
    "IGLN.L":  ["IGLN.UK_9",  "IGLN.UK", "IGLN.L"],
    "BND":     ["BND.US_9",   "BND.US"],
    "QQQM":    ["QQQM.US_9",  "QQQM.US"],
    "VDE":     ["VDE.US_9",   "VDE.US"],
}

_XTB_TO_TICKER: dict[str, str] = {}
for _t, _variants in _TICKER_TO_XTB.items():
    for _v in _variants:
        if _v not in _XTB_TO_TICKER:
            _XTB_TO_TICKER[_v] = _t

_TICKER_PRIMARY_XTB: dict[str, str] = {t: v[0] for t, v in _TICKER_TO_XTB.items()}


def resolve_ticker(xtb_symbol: str) -> str | None:
    return _XTB_TO_TICKER.get(xtb_symbol)


def preferred_xtb_symbol(ticker: str) -> str:
    return _TICKER_PRIMARY_XTB.get(ticker, ticker)


# ── SSL socket client ─────────────────────────────────────────────────────────

class XTBClient:
    """Synchronous XTB xStation API client using SSL TCP sockets."""

    def __init__(self, account_id: str, password: str, mode: str = "real"):
        self._account_id = str(account_id)
        self._password = password
        host, port = _HOSTS.get(mode.lower(), _HOSTS["real"])
        self._host = host
        self._port = port
        self._conn: ssl.SSLSocket | None = None
        self._file = None
        self.stream_session_id: str = ""

    # ── Connection ─────────────────────────────────────────────────────────

    def connect(self, timeout: int = 15):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw.settimeout(timeout)
        self._conn = ctx.wrap_socket(raw)
        self._conn.connect((self._host, self._port))
        self._file = self._conn.makefile("r", encoding="utf-8")

    def disconnect(self):
        try:
            if self._file:
                self._file.close()
            if self._conn:
                self._conn.close()
        except Exception:
            pass
        self._conn = None
        self._file = None

    # ── Low-level send / receive ───────────────────────────────────────────

    def _send(self, command: str, arguments: dict | None = None) -> dict:
        payload: dict[str, Any] = {"command": command}
        if arguments:
            payload["arguments"] = arguments
        msg = json.dumps(payload) + "\n\n"
        self._conn.sendall(msg.encode("utf-8"))
        return self._recv()

    def _recv(self) -> dict:
        buf = ""
        while True:
            chunk = self._file.read(4096)
            if not chunk:
                break
            buf += chunk
            if buf.endswith("\n\n"):
                break
        return json.loads(buf.strip())

    # ── Auth ───────────────────────────────────────────────────────────────

    def login(self) -> bool:
        resp = self._send("login", {
            "userId":  self._account_id,
            "password": self._password,
            "appId":   "PortafolioManagementSA",
            "appName": "PortafolioManagementSA",
        })
        if resp.get("status"):
            self.stream_session_id = resp.get("streamSessionId", "")
            return True
        err = resp.get("errorDescr", "Login failed")
        raise RuntimeError(f"XTB login error: {err}")

    # ── Account ────────────────────────────────────────────────────────────

    def get_account_info(self) -> dict:
        resp = self._send("getMarginLevel")
        return resp.get("returnData", {}) if resp.get("status") else {}

    # ── Positions ──────────────────────────────────────────────────────────

    def get_open_trades(self) -> list[dict]:
        resp = self._send("getTrades", {"openedOnly": True})
        return resp.get("returnData", []) if resp.get("status") else []

    def get_trades_history(self, start_ms: int = 0) -> list[dict]:
        resp = self._send("getTradesHistory", {"end": 0, "start": start_ms})
        return resp.get("returnData", []) if resp.get("status") else []

    # ── Prices ─────────────────────────────────────────────────────────────

    def get_tick_prices(self, symbols: list[str]) -> dict[str, dict]:
        resp = self._send("getTickPrices", {
            "level": 0,
            "symbols": symbols,
            "timestamp": 0,
        })
        if not resp.get("status"):
            return {}
        return {q["symbol"]: q for q in resp.get("returnData", {}).get("quotations", [])}

    # ── Order execution ────────────────────────────────────────────────────

    def place_order(self, symbol: str, action: str, volume: float,
                    comment: str = "PortafolioManagementSA") -> dict:
        cmd = 0 if action.upper() == "BUY" else 1
        resp = self._send("tradeTransaction", {
            "tradeTransInfo": {
                "cmd":        cmd,
                "symbol":     symbol,
                "volume":     round(float(volume), 4),
                "price":      0.0,
                "type":       0,
                "order":      0,
                "comment":    comment,
                "expiration": 0,
            }
        })
        if resp.get("status"):
            return {"order": resp.get("returnData", {}).get("order", 0)}
        return {"error": resp.get("errorDescr", "Unknown error")}

    def get_order_status(self, order_id: int) -> dict:
        resp = self._send("tradeTransactionStatus", {"order": order_id})
        return resp.get("returnData", {}) if resp.get("status") else {}

    # ── Context manager ────────────────────────────────────────────────────

    def __enter__(self):
        self.connect()
        self.login()
        return self

    def __exit__(self, *args):
        self.disconnect()


# ── Streamlit helpers ─────────────────────────────────────────────────────────

def _get_xtb_cfg() -> tuple[str, str, str]:
    cfg = st.secrets.get("xtb", {})
    return (
        str(cfg.get("account_id", "")),
        str(cfg.get("password", "")),
        str(cfg.get("mode", "real")),
    )


def xtb_configured() -> bool:
    account_id, password, _ = _get_xtb_cfg()
    return bool(account_id and password)


@st.cache_data(ttl=60, show_spinner=False)
def load_xtb_positions() -> tuple[list[dict], str]:
    """Open positions from XTB. Cached 60 s."""
    account_id, password, mode = _get_xtb_cfg()
    if not account_id or not password:
        return [], "XTB no configurado."
    try:
        with XTBClient(account_id, password, mode) as client:
            trades = client.get_open_trades()
        return trades, ""
    except Exception as e:
        return [], str(e)


@st.cache_data(ttl=300, show_spinner=False)
def load_xtb_account() -> tuple[dict, str]:
    """Account balance/equity from XTB. Cached 5 min."""
    account_id, password, mode = _get_xtb_cfg()
    if not account_id or not password:
        return {}, "XTB no configurado."
    try:
        with XTBClient(account_id, password, mode) as client:
            info = client.get_account_info()
        return info, ""
    except Exception as e:
        return {}, str(e)


@st.cache_data(ttl=3600, show_spinner=False)
def load_xtb_history(start_year: int = 2023) -> tuple[list[dict], str]:
    """Closed trade history from XTB. Cached 1 h."""
    import calendar
    account_id, password, mode = _get_xtb_cfg()
    if not account_id or not password:
        return [], "XTB no configurado."
    try:
        start_ms = int(calendar.timegm((start_year, 1, 1, 0, 0, 0)) * 1000)
        with XTBClient(account_id, password, mode) as client:
            history = client.get_trades_history(start_ms)
        return history, ""
    except Exception as e:
        return [], str(e)


# ── Data conversion helpers ───────────────────────────────────────────────────

def trades_to_shares(trades: list[dict]) -> dict[str, float]:
    """Convert open XTB trades to {app_ticker: total_shares}."""
    result: dict[str, float] = {}
    for t in trades:
        sym = str(t.get("symbol", ""))
        ticker = resolve_ticker(sym)
        if ticker:
            result[ticker] = result.get(ticker, 0.0) + float(t.get("volume", 0.0))
    return result


def history_to_transactions(history: list[dict]) -> pd.DataFrame:
    """Convert XTB closed trade history to transactions DataFrame."""
    from datetime import datetime, timezone

    rows = []
    for t in history:
        sym = str(t.get("symbol", ""))
        ticker = resolve_ticker(sym)
        if not ticker:
            continue

        volume = float(t.get("volume", 0.0))
        cmd = int(t.get("cmd", -1))

        if cmd == 0:  # Long position
            open_ts = t.get("open_time", 0)
            open_price = float(t.get("open_price", 0.0))
            if open_ts and open_price > 0:
                date_str = datetime.fromtimestamp(open_ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                rows.append({
                    "date": date_str, "ticker": ticker, "type": "BUY",
                    "shares": round(volume, 6), "price": round(open_price, 4),
                    "notes": f"XTB #{t.get('position', '')}",
                })
            close_price = float(t.get("close_price", 0.0))
            close_ts = t.get("close_time", 0)
            if close_ts and close_price > 0:
                date_str = datetime.fromtimestamp(close_ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                rows.append({
                    "date": date_str, "ticker": ticker, "type": "SELL",
                    "shares": round(volume, 6), "price": round(close_price, 4),
                    "notes": f"XTB #{t.get('position', '')}",
                })

    if not rows:
        return pd.DataFrame(columns=["date", "ticker", "type", "shares", "price", "notes"])

    df = pd.DataFrame(rows).drop_duplicates()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


def build_positions_comparison(xtb_shares: dict[str, float], app_df: pd.DataFrame) -> pd.DataFrame:
    """XTB shares vs app-tracked shares comparison."""
    tickers = sorted(set(xtb_shares) | set(app_df["Ticker"].tolist() if not app_df.empty else []))
    app_map = app_df.set_index("Ticker")["Shares"].to_dict() if not app_df.empty else {}
    rows = []
    for t in tickers:
        xtb = round(xtb_shares.get(t, 0.0), 4)
        app = round(float(app_map.get(t, 0.0)), 4)
        delta = round(xtb - app, 4)
        rows.append({
            "Ticker": t,
            "XTB Shares": xtb,
            "App Shares": app,
            "Δ Shares": delta,
            "Sincronizado": "✅" if abs(delta) < 0.001 else "❌",
        })
    return pd.DataFrame(rows)
