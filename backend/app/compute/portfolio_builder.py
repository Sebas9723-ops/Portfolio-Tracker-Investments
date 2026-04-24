"""
Builds the enriched portfolio DataFrame from positions + live prices + FX rates.
Port of build_portfolio_df() from app_core.py.
"""
import pandas as pd
from datetime import datetime, timezone
from typing import Optional

from app.models.portfolio import PortfolioRow, PortfolioSummary
from app.models.market import QuoteResponse
from app.services.exchange_classifier import get_native_currency


def build_portfolio(
    positions: list[dict],
    quotes: dict[str, QuoteResponse],
    fx_rates: dict[str, float],
    base_currency: str = "USD",
    transactions: Optional[list[dict]] = None,
) -> PortfolioSummary:
    """
    positions: list of DB position dicts (ticker, name, shares, avg_cost_native, currency)
    quotes:    {ticker: QuoteResponse}
    fx_rates:  {currency: rate_to_base_currency}
    """
    rows: list[PortfolioRow] = []

    # Pre-compute avg costs from transactions if provided
    tx_avg_costs = _compute_tx_avg_costs(transactions or [], base_currency, fx_rates)

    for pos in positions:
        ticker = pos["ticker"]
        shares = float(pos.get("shares", 0))
        if shares == 0:
            continue

        # Exchange currency: always determined by where the ticker trades
        # (EUR for XETRA, GBP for LSE, USD for US). Used for price conversion.
        exchange_currency = get_native_currency(ticker)
        # Position currency: the currency in which avg_cost was entered by the user.
        # May differ from exchange_currency (e.g. user buys VWCE.DE on XTB in USD).
        pos_currency = pos.get("currency") or exchange_currency

        quote = quotes.get(ticker)
        price_native = quote.price if quote else 0.0
        # Always convert price using the exchange's native currency, not the DB field
        price_fx_rate = fx_rates.get(exchange_currency, 1.0)
        price_base = price_native * price_fx_rate

        value_native = shares * price_native
        value_base = shares * price_base

        # Avg cost: prefer transaction-computed, fall back to position record
        avg_cost_native: Optional[float] = (
            tx_avg_costs.get(ticker)
            or pos.get("avg_cost_native")
        )
        # Avg cost may be in pos_currency (e.g. USD if user entered cost in USD)
        avg_cost_fx_rate = fx_rates.get(pos_currency, 1.0)
        avg_cost_base = (avg_cost_native * avg_cost_fx_rate) if avg_cost_native else None
        invested_base = (shares * avg_cost_base) if avg_cost_base else None
        unrealized_pnl = (value_base - invested_base) if invested_base else None
        unrealized_pnl_pct = (unrealized_pnl / invested_base * 100) if invested_base else None

        rows.append(PortfolioRow(
            ticker=ticker,
            name=pos.get("name") or ticker,
            shares=shares,
            currency=exchange_currency,
            cost_currency=pos_currency,
            market=pos.get("market", "US"),
            price_native=price_native,
            price_base=price_base,
            fx_rate=price_fx_rate,
            avg_cost_native=avg_cost_native,
            avg_cost_base=avg_cost_base,
            value_native=value_native,
            value_base=value_base,
            invested_base=invested_base,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
            weight=0.0,  # filled below
            change_pct_1d=quote.change_pct if quote else None,
            data_source=quote.source if quote else "unavailable",
        ))

    total_value = sum(r.value_base for r in rows)
    for r in rows:
        r.weight = (r.value_base / total_value * 100) if total_value > 0 else 0.0

    total_invested = sum(r.invested_base for r in rows if r.invested_base) or None
    total_pnl = (total_value - total_invested) if total_invested else None
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested else None

    total_day_change: Optional[float] = None
    day_changes = [r.value_base * (r.change_pct_1d or 0) / 100 for r in rows if r.change_pct_1d]
    if day_changes:
        total_day_change = sum(day_changes)

    return PortfolioSummary(
        rows=rows,
        total_value_base=total_value,
        total_invested_base=total_invested,
        total_unrealized_pnl=total_pnl,
        total_unrealized_pnl_pct=total_pnl_pct,
        total_day_change_base=total_day_change,
        base_currency=base_currency,
        as_of=datetime.now(timezone.utc),
    )


def _compute_tx_avg_costs(
    transactions: list[dict],
    base_currency: str,
    fx_rates: dict[str, float],
) -> dict[str, float]:
    """FIFO average cost per ticker from transaction history (native currency)."""
    running: dict[str, tuple[float, float]] = {}  # ticker → (total_shares, total_cost_native)

    for tx in sorted(transactions, key=lambda t: t.get("date", "")):
        ticker = tx.get("ticker", "")
        action = tx.get("action", "")
        qty = float(tx.get("quantity", 0))
        price = float(tx.get("price_native", 0))
        fee = float(tx.get("fee_native", 0))

        shares, cost = running.get(ticker, (0.0, 0.0))

        if action == "BUY":
            total_cost = price * qty + fee
            running[ticker] = (shares + qty, cost + total_cost)
        elif action == "SELL":
            if shares > 0:
                avg = cost / shares
                remaining = max(0.0, shares - qty)
                running[ticker] = (remaining, avg * remaining if remaining > 0 else 0.0)

    return {ticker: (cost / shares) if shares > 0 else 0.0
            for ticker, (shares, cost) in running.items()}


def compute_realized_pnl(transactions: list[dict]) -> list[dict]:
    """FIFO realized P&L from SELL transactions (native currency of each ticker)."""
    running: dict[str, tuple[float, float]] = {}  # ticker → (shares, total_cost_native)
    realized: dict[str, dict] = {}

    for tx in sorted(transactions, key=lambda t: t.get("date", "")):
        ticker = tx.get("ticker", "")
        action = tx.get("action", "")
        qty = float(tx.get("quantity", 0))
        price = float(tx.get("price_native", 0))
        fee = float(tx.get("fee_native", 0))

        shares, cost = running.get(ticker, (0.0, 0.0))

        if action == "BUY":
            running[ticker] = (shares + qty, cost + price * qty + fee)
        elif action == "SELL":
            if shares > 0:
                avg = cost / shares
                sell_proceeds = price * qty - fee
                pnl = sell_proceeds - avg * qty
                if ticker not in realized:
                    realized[ticker] = {"ticker": ticker, "realized_pnl": 0.0, "trades": 0}
                realized[ticker]["realized_pnl"] += pnl
                realized[ticker]["trades"] += 1
                remaining = max(0.0, shares - qty)
                running[ticker] = (remaining, avg * remaining if remaining > 0 else 0.0)

    return list(realized.values())


def portfolio_to_df(summary: PortfolioSummary) -> pd.DataFrame:
    """Convert PortfolioSummary to a pandas DataFrame for compute modules."""
    return pd.DataFrame([r.model_dump() for r in summary.rows])
