"""
XTB xStation API client.

Uses WebSocket over port 443 (wss://) via the `websockets` library which is
already a Streamlit dependency — no extra requirements needed.

Async coroutines are executed in a dedicated background thread to avoid
conflicts with Streamlit's own event loop.

Requires in .streamlit/secrets.toml:
    [xtb]
    account_id = "52413110"
    password   = "your_xtb_password"
    mode       = "real"   # or "demo"
"""
from __future__ import annotations

import asyncio
import json
import queue
import threading
from typing import Any

import pandas as pd
import streamlit as st

# ── WebSocket endpoints (port 443, not blocked by GCP/Streamlit Cloud) ────────
_WS_URLS: dict[str, list[str]] = {
    "real": [
        "wss://ws.xtb.com/real",
        "wss://x-api.xtb.com/real",
    ],
    "demo": [
        "wss://ws.xtb.com/demo",
        "wss://x-api.xtb.com/demo",
    ],
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


# ── Async helpers ─────────────────────────────────────────────────────────────

def _run_async(coro, timeout: int = 20) -> Any:
    """
    Run an async coroutine in a dedicated background thread with its own
    event loop — avoids conflicts with Streamlit's event loop.
    """
    result_q: queue.Queue = queue.Queue()

    def _target():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result_q.put(("ok", loop.run_until_complete(coro)))
        except Exception as exc:
            result_q.put(("err", exc))
        finally:
            loop.close()

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        raise TimeoutError("XTB connection timed out after 20 s")

    status, value = result_q.get_nowait()
    if status == "err":
        raise value
    return value


async def _ws_session(
    mode: str,
    account_id: str,
    password: str,
    commands: list[tuple[str, dict | None]],
) -> list[dict]:
    """
    Opens one WebSocket connection, logs in, runs all commands, disconnects.
    Tries each URL in _WS_URLS[mode] and moves on if one fails.
    Returns list of response dicts (one per command).
    """
    import websockets

    urls = _WS_URLS.get(mode, _WS_URLS["real"])
    last_exc: Exception = RuntimeError("No XTB endpoint reachable")

    for url in urls:
        try:
            # Try with and without extra headers to handle version differences
            connect_kwargs: dict[str, Any] = {"open_timeout": 15, "close_timeout": 5}
            try:
                # websockets >= 10 uses extra_headers or additional_headers
                async with websockets.connect(url, extra_headers={
                    "Origin": "https://www.xtb.com",
                }, **connect_kwargs) as ws:
                    return await _execute_commands(ws, account_id, password, commands)
            except TypeError:
                async with websockets.connect(url, **connect_kwargs) as ws:
                    return await _execute_commands(ws, account_id, password, commands)

        except Exception as exc:
            last_exc = exc
            continue

    raise last_exc


async def _execute_commands(ws, account_id: str, password: str,
                             commands: list[tuple[str, dict | None]]) -> list[dict]:
    """Login then execute each command on an already-open WebSocket."""
    # Login
    await ws.send(json.dumps({
        "command": "login",
        "arguments": {
            "userId":   account_id,
            "password": password,
            "appId":    "PortafolioManagementSA",
            "appName":  "PortafolioManagementSA",
        },
    }))
    login_resp = json.loads(await ws.recv())
    if not login_resp.get("status"):
        err = login_resp.get("errorDescr", "Login failed")
        raise RuntimeError(f"XTB login error: {err}")

    results: list[dict] = []
    for cmd, args in commands:
        payload: dict[str, Any] = {"command": cmd}
        if args:
            payload["arguments"] = args
        await ws.send(json.dumps(payload))
        results.append(json.loads(await ws.recv()))

    return results


# ── Convenience function ──────────────────────────────────────────────────────

def xtb_call(mode: str, account_id: str, password: str,
             commands: list[tuple[str, dict | None]]) -> list[dict]:
    """Synchronous wrapper around _ws_session for use in Streamlit."""
    return _run_async(_ws_session(mode, account_id, password, commands))


# ── Streamlit cached helpers ──────────────────────────────────────────────────

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
        results = xtb_call(mode, account_id, password, [
            ("getTrades", {"openedOnly": True}),
        ])
        resp = results[0]
        return resp.get("returnData", []) if resp.get("status") else [], ""
    except Exception as e:
        return [], str(e)


@st.cache_data(ttl=300, show_spinner=False)
def load_xtb_account() -> tuple[dict, str]:
    """Account balance/equity from XTB. Cached 5 min."""
    account_id, password, mode = _get_xtb_cfg()
    if not account_id or not password:
        return {}, "XTB no configurado."
    try:
        results = xtb_call(mode, account_id, password, [
            ("getMarginLevel", None),
        ])
        resp = results[0]
        return resp.get("returnData", {}) if resp.get("status") else {}, ""
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
        results = xtb_call(mode, account_id, password, [
            ("getTradesHistory", {"end": 0, "start": start_ms}),
        ])
        resp = results[0]
        return resp.get("returnData", []) if resp.get("status") else [], ""
    except Exception as e:
        return [], str(e)


def place_xtb_order(symbol: str, action: str, volume: float,
                    comment: str = "PortafolioManagementSA") -> dict:
    """Place a single market order. Returns {"order": id} or {"error": msg}."""
    account_id, password, mode = _get_xtb_cfg()
    cmd = 0 if action.upper() == "BUY" else 1
    try:
        results = xtb_call(mode, account_id, password, [
            ("tradeTransaction", {
                "tradeTransInfo": {
                    "cmd": cmd, "symbol": symbol,
                    "volume": round(float(volume), 4),
                    "price": 0.0, "type": 0, "order": 0,
                    "comment": comment, "expiration": 0,
                }
            }),
        ])
        resp = results[0]
        if resp.get("status"):
            return {"order": resp.get("returnData", {}).get("order", 0)}
        return {"error": resp.get("errorDescr", "Unknown error")}
    except Exception as e:
        return {"error": str(e)}


def get_xtb_order_status(order_id: int) -> dict:
    account_id, password, mode = _get_xtb_cfg()
    try:
        results = xtb_call(mode, account_id, password, [
            ("tradeTransactionStatus", {"order": order_id}),
        ])
        resp = results[0]
        return resp.get("returnData", {}) if resp.get("status") else {}
    except Exception:
        return {}


# ── Data conversion helpers ───────────────────────────────────────────────────

def trades_to_shares(trades: list[dict]) -> dict[str, float]:
    result: dict[str, float] = {}
    for t in trades:
        sym = str(t.get("symbol", ""))
        ticker = resolve_ticker(sym)
        if ticker:
            result[ticker] = result.get(ticker, 0.0) + float(t.get("volume", 0.0))
    return result


def history_to_transactions(history: list[dict]) -> pd.DataFrame:
    from datetime import datetime, timezone

    rows = []
    for t in history:
        sym = str(t.get("symbol", ""))
        ticker = resolve_ticker(sym)
        if not ticker:
            continue
        volume = float(t.get("volume", 0.0))
        if int(t.get("cmd", -1)) != 0:
            continue

        open_ts = t.get("open_time", 0)
        open_price = float(t.get("open_price", 0.0))
        if open_ts and open_price > 0:
            rows.append({
                "date": datetime.fromtimestamp(open_ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d"),
                "ticker": ticker, "type": "BUY",
                "shares": round(volume, 6), "price": round(open_price, 4),
                "notes": f"XTB #{t.get('position', '')}",
            })

        close_price = float(t.get("close_price", 0.0))
        close_ts = t.get("close_time", 0)
        if close_ts and close_price > 0:
            rows.append({
                "date": datetime.fromtimestamp(close_ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d"),
                "ticker": ticker, "type": "SELL",
                "shares": round(volume, 6), "price": round(close_price, 4),
                "notes": f"XTB #{t.get('position', '')}",
            })

    if not rows:
        return pd.DataFrame(columns=["date", "ticker", "type", "shares", "price", "notes"])

    df = pd.DataFrame(rows).drop_duplicates()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


def build_positions_comparison(xtb_shares: dict[str, float], app_df: pd.DataFrame) -> pd.DataFrame:
    tickers = sorted(set(xtb_shares) | set(app_df["Ticker"].tolist() if not app_df.empty else []))
    app_map = app_df.set_index("Ticker")["Shares"].to_dict() if not app_df.empty else {}
    rows = []
    for t in tickers:
        xtb = round(xtb_shares.get(t, 0.0), 4)
        app = round(float(app_map.get(t, 0.0)), 4)
        delta = round(xtb - app, 4)
        rows.append({
            "Ticker": t, "XTB Shares": xtb, "App Shares": app,
            "Δ Shares": delta, "Sincronizado": "✅" if abs(delta) < 0.001 else "❌",
        })
    return pd.DataFrame(rows)
