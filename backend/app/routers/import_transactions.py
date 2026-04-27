"""
POST /api/import/ibkr-csv  — IBKR Flex Query CSV
POST /api/import/xtb-xlsx  — XTB Cash Operations Excel report
"""
from __future__ import annotations

import csv
import io
import logging
import re
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
        errors=errors[:10],
        tickers=sorted(tickers),
    )


# ── XTB xlsx import ────────────────────────────────────────────────────────────

def _xtb_ticker(xtb: str) -> str:
    """Convert XTB ticker format to app/yfinance format."""
    xtb = xtb.strip()
    if xtb.endswith(".US"):
        return xtb[:-3]          # VOO.US → VOO
    if xtb.endswith(".UK"):
        return xtb[:-3] + ".L"  # EIMI.UK → EIMI.L
    return xtb                   # QDVE.DE, ZPRV.DE → unchanged


def _parse_xtb_comment(comment: str) -> tuple[float, float] | None:
    """
    Extract (quantity, price) from XTB comment field.
    Handles:
      "OPEN BUY 0.5671 @ 590.58"
      "OPEN BUY 3/3.3674 @ 30.06"   ← partial fill: quantity = 3
      "CLOSE BUY 0.0897/1.6866 @ 93.6600"
    """
    m = re.search(
        r'(?:OPEN|CLOSE)\s+(?:BUY|SELL)\s+([\d.]+)(?:/[\d.]+)?\s*@\s*([\d.]+)',
        comment or "",
    )
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


class XTBImportResult(BaseModel):
    imported: int
    skipped: int
    errors: list[str]
    tickers: list[str]
    deposits_usd: float


@router.post("/xtb-xlsx", response_model=XTBImportResult)
async def import_xtb_xlsx(
    file: UploadFile = File(...),
    user_id: str = Depends(get_user_id),
):
    """
    Upload an XTB 'Cash Operations' Excel report (.xlsx) to import trades
    as BUY/SELL transactions. Deposits are counted for reference only.
    """
    if not file.filename or not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="File must be a .xlsx XTB Cash Operations export")

    content_bytes = await file.read()

    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content_bytes), data_only=True)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not read xlsx: {exc}")

    # XTB exports to 'Cash Operations' sheet
    ws = wb.active

    db = get_admin_client()
    imported = 0
    skipped = 0
    errors: list[str] = []
    tickers: set[str] = set()
    deposits_usd = 0.0

    # Find the header row
    header_row = None
    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if row and row[0] == "Type":
            header_row = i
            break

    if header_row is None:
        raise HTTPException(status_code=422, detail="Could not find header row. Expected 'Type' column.")

    # Parse data rows
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        if not row or row[0] is None:
            continue
        tx_type_raw = str(row[0]).strip()
        ticker_raw = str(row[1] or "").strip()
        time_val = row[3]
        amount = row[4]
        comment = str(row[6] or "").strip()

        # Track deposits for capital reference
        if tx_type_raw == "Deposit":
            try:
                deposits_usd += float(amount or 0)
            except Exception:
                pass
            skipped += 1
            continue

        # Skip non-trade rows
        if tx_type_raw not in ("Stock purchase", "Stock sell"):
            skipped += 1
            continue

        if not ticker_raw:
            skipped += 1
            continue

        # Parse comment for qty/price
        parsed = _parse_xtb_comment(comment)
        if parsed is None:
            errors.append(f"Could not parse comment: {comment[:60]}")
            skipped += 1
            continue
        qty, price = parsed

        # Parse date
        if isinstance(time_val, datetime):
            tx_date = time_val.date().isoformat()
        else:
            try:
                tx_date = str(time_val)[:10]
            except Exception:
                skipped += 1
                continue

        # Convert ticker
        app_ticker = _xtb_ticker(ticker_raw)
        action = "BUY" if tx_type_raw == "Stock purchase" else "SELL"

        # Currency: XTB reports amounts in account currency (USD for this account)
        # Determine native currency from ticker exchange
        if ticker_raw.endswith(".DE"):
            native_ccy = "EUR"
        elif ticker_raw.endswith(".UK"):
            native_ccy = "GBP"
        else:
            native_ccy = "USD"

        try:
            tx_row = {
                "user_id": user_id,
                "ticker": app_ticker,
                "action": action,
                "quantity": qty,
                "price_native": price,
                "currency": native_ccy,
                "fee_native": 0.0,
                "date": tx_date,
                "comment": f"XTB: {comment[:80]}",
            }
            db.table("transactions").insert(tx_row).execute()
            tickers.add(app_ticker)
            imported += 1
        except Exception as exc:
            errors.append(f"{app_ticker} {tx_date}: {exc}")
            skipped += 1

    log.info(
        "XTB import for %s: %d imported, %d skipped, deposits=%.2f",
        user_id[:8], imported, skipped, deposits_usd,
    )

    return XTBImportResult(
        imported=imported,
        skipped=skipped,
        errors=errors[:10],
        tickers=sorted(tickers),
        deposits_usd=deposits_usd,
    )
