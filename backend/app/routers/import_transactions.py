"""
POST /api/import/ibkr-csv
Parses an IBKR (Interactive Brokers) Flex Query CSV export and imports
trades as portfolio transactions.

Expected CSV columns (subset of IBKR Flex Query Trade format):
  Symbol, DateTime, Quantity, TradePrice, CurrencyPrimary, IBCommission, Buy/Sell, Description
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from app.auth.dependencies import get_user_id
from app.db.supabase_client import get_admin_client

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/import", tags=["import"])


class ImportResult(BaseModel):
    imported: int
    skipped: int
    errors: list[str]
    tickers: list[str]


def _parse_ibkr_flex_csv(content: str) -> list[dict[str, Any]]:
    """
    Parse IBKR Flex Query CSV/text.
    Handles both comma and semicolon delimiters.
    Returns list of raw row dicts.
    """
    # Detect delimiter
    delim = "," if content.count(",") > content.count(";") else ";"
    reader = csv.DictReader(io.StringIO(content), delimiter=delim)
    rows = []
    for row in reader:
        # Skip header/summary rows that IBKR sometimes injects
        if not row:
            continue
        symbol = (row.get("Symbol") or row.get("symbol") or "").strip()
        if not symbol or symbol in ("Symbol", "Total"):
            continue
        rows.append({k.strip(): v.strip() for k, v in row.items()})
    return rows


def _map_ibkr_row(row: dict) -> dict | None:
    """
    Map an IBKR Flex row to our transaction schema.
    Returns None if row should be skipped.
    """
    # Normalize column names (IBKR uses different names in different exports)
    def _get(*keys: str) -> str:
        for k in keys:
            v = row.get(k, "")
            if v:
                return v.strip()
        return ""

    symbol = _get("Symbol", "symbol", "Ticker")
    if not symbol:
        return None

    qty_str = _get("Quantity", "quantity", "Qty")
    price_str = _get("TradePrice", "tradePrice", "Price", "price")
    currency = _get("CurrencyPrimary", "Currency", "currency") or "USD"
    commission_str = _get("IBCommission", "Commission", "commission") or "0"
    side = _get("Buy/Sell", "Side", "side", "Action")
    date_str = _get("DateTime", "TradeDate", "date", "Date")

    try:
        qty = abs(float(qty_str.replace(",", "")))
    except ValueError:
        return None

    try:
        price = abs(float(price_str.replace(",", "")))
    except ValueError:
        return None

    try:
        commission = abs(float(commission_str.replace(",", "")))
    except ValueError:
        commission = 0.0

    # Determine transaction type
    side_upper = side.upper()
    if "SELL" in side_upper or "SHORT" in side_upper or qty_str.startswith("-"):
        tx_type = "sell"
    else:
        tx_type = "buy"

    # Parse date
    tx_date = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y", "%Y%m%d"):
        try:
            tx_date = datetime.strptime(date_str[:len(fmt.replace("%Y","0000").replace("%m","00").replace("%d","00").replace("%H","00").replace("%M","00").replace("%S","00"))], fmt).date().isoformat()
            break
        except (ValueError, IndexError):
            continue
    if tx_date is None:
        # Try first 10 chars
        try:
            tx_date = date_str[:10]
        except Exception:
            return None

    return {
        "ticker": symbol.upper(),
        "type": tx_type,
        "shares": qty,
        "price": price,
        "currency": currency.upper() if currency else "USD",
        "fee": commission,
        "date": tx_date,
        "note": "Imported from IBKR",
    }


@router.post("/ibkr-csv", response_model=ImportResult)
async def import_ibkr_csv(
    file: UploadFile = File(...),
    user_id: str = Depends(get_user_id),
):
    """
    Upload an IBKR Flex Query CSV export to import trades as transactions.
    Accepts .csv or .txt files.
    """
    if not file.filename or not (file.filename.endswith(".csv") or file.filename.endswith(".txt")):
        raise HTTPException(status_code=400, detail="File must be a .csv or .txt IBKR Flex export")

    content_bytes = await file.read()
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = content_bytes.decode("latin-1")

    raw_rows = _parse_ibkr_flex_csv(content)
    if not raw_rows:
        raise HTTPException(status_code=422, detail="No valid trades found in file. Check IBKR Flex Query format.")

    db = get_admin_client()
    imported = 0
    skipped = 0
    errors: list[str] = []
    tickers: set[str] = set()

    for i, row in enumerate(raw_rows):
        try:
            mapped = _map_ibkr_row(row)
            if mapped is None:
                skipped += 1
                continue

            tx_row = {
                "user_id": user_id,
                "ticker": mapped["ticker"],
                "type": mapped["type"],
                "shares": mapped["shares"],
                "price": mapped["price"],
                "currency": mapped["currency"],
                "fee": mapped["fee"],
                "date": mapped["date"],
                "note": mapped["note"],
            }
            db.table("transactions").insert(tx_row).execute()
            tickers.add(mapped["ticker"])
            imported += 1
        except Exception as exc:
            errors.append(f"Row {i+1}: {exc}")
            skipped += 1

    log.info("IBKR import for %s: %d imported, %d skipped, %d errors", user_id[:8], imported, skipped, len(errors))

    return ImportResult(
        imported=imported,
        skipped=skipped,
        errors=errors[:10],  # cap at 10 errors to avoid huge responses
        tickers=sorted(tickers),
    )
