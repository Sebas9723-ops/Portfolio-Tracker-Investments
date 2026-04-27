"""
POST /api/agents/broker-reconcile
Broker Reconciliation Agent:
  1. Parses XTB xlsx (Cash Operations)
  2. Detects and skips duplicate transactions
  3. Imports new BUY/SELL transactions
  4. Recomputes net shares + weighted avg cost per ticker from ALL transactions
  5. Upserts positions table to match transaction history
  6. Uses Groq to validate data and flag anomalies
  7. Returns detailed reconciliation report
"""
from __future__ import annotations

import io
import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from app.auth.dependencies import get_user_id
from app.db.supabase_client import get_admin_client

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agents", tags=["agents"])


# ── Ticker helpers ────────────────────────────────────────────────────────────

def _xtb_to_app_ticker(xtb: str) -> str:
    xtb = xtb.strip()
    if xtb.endswith(".US"):
        return xtb[:-3]       # VOO.US → VOO
    if xtb.endswith(".UK"):
        return xtb[:-3] + ".L"  # EIMI.UK → EIMI.L
    return xtb                # QDVE.DE → QDVE.DE


def _ticker_exchange_info(ticker: str) -> dict:
    if ticker.endswith(".DE"):
        return {"currency": "EUR", "market": "XETRA"}
    if ticker.endswith(".L"):
        return {"currency": "GBP", "market": "LSE"}
    return {"currency": "USD", "market": "US"}


def _ticker_aliases(ticker: str) -> list[str]:
    """Return all formats a ticker might be stored under in positions."""
    aliases = [ticker]
    if ticker.endswith(".L"):
        aliases.append(ticker[:-2] + ".UK")   # EIMI.L → EIMI.UK
    elif ticker.endswith(".UK"):
        aliases.append(ticker[:-3] + ".L")    # EIMI.UK → EIMI.L
    elif "." not in ticker:
        aliases.append(ticker + ".US")         # VOO → VOO.US
    elif ticker.endswith(".US"):
        aliases.append(ticker[:-3])            # VOO.US → VOO
    return aliases


# ── XTB parser ────────────────────────────────────────────────────────────────

def _parse_xtb_comment(comment: str) -> tuple[float, float] | None:
    """Extract (quantity, price) from XTB comment field."""
    m = re.search(
        r'(?:OPEN|CLOSE)\s+(?:BUY|SELL)\s+([\d.]+)(?:/[\d.]+)?\s*@\s*([\d.]+)',
        comment or "",
    )
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def _parse_xtb_xlsx(content: bytes) -> list[dict]:
    """
    Parse XTB Cash Operations xlsx.
    Handles both fixed-column and dynamic-header layouts.
    Returns (trades_list, deposits_total).
    """
    import openpyxl
    from datetime import datetime

    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    ws = wb.active

    # ── Find header row: "Type" anywhere in first 30 rows ────────────────────
    header_row_idx = None
    col_map: dict[str, int] = {}

    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if not row:
            continue
        cells = [str(c).strip() if c is not None else "" for c in row]
        if "Type" in cells:
            header_row_idx = i
            col_map = {name: idx for idx, name in enumerate(cells) if name}
            break
        if i > 30:
            break

    if header_row_idx is None:
        raise ValueError(
            "Header row not found in first 30 rows. "
            "Expected a row containing 'Type'. "
            "Please export 'Cash Operations' from XTB (Mi Cuenta → Historial → Cash Operations → Exportar Excel)."
        )

    # ── Map required columns (fall back to positional defaults) ──────────────
    def col(name: str, default: int) -> int:
        return col_map.get(name, default)

    idx_type    = col("Type",    0)
    idx_symbol  = col("Symbol",  1)
    idx_time    = col("Time",    3)
    idx_amount  = col("Amount",  4)
    idx_comment = col("Comment", 6)

    trades: list[dict] = []
    deposits_total = 0.0

    for row in ws.iter_rows(min_row=header_row_idx + 1, values_only=True):
        if not row or row[idx_type] is None:
            continue

        tx_type    = str(row[idx_type]).strip()
        ticker_raw = str(row[idx_symbol] or "").strip() if idx_symbol < len(row) else ""
        time_val   = row[idx_time]   if idx_time   < len(row) else None
        amount     = row[idx_amount] if idx_amount < len(row) else None
        comment    = str(row[idx_comment] or "").strip() if idx_comment < len(row) else ""

        if tx_type == "Deposit":
            try:
                deposits_total += float(amount or 0)
            except Exception:
                pass
            continue

        if tx_type not in ("Stock purchase", "Stock sell"):
            continue
        if not ticker_raw:
            continue

        parsed = _parse_xtb_comment(comment)
        if parsed is None:
            log.warning("Could not parse XTB comment: %s", comment[:80])
            continue
        qty, price = parsed

        if isinstance(time_val, datetime):
            tx_date = time_val.date().isoformat()
        else:
            tx_date = str(time_val)[:10]

        trades.append({
            "ticker_xtb": ticker_raw,
            "ticker": _xtb_to_app_ticker(ticker_raw),
            "action": "BUY" if tx_type == "Stock purchase" else "SELL",
            "quantity": qty,
            "price_native": price,
            "date": tx_date,
            "comment_raw": comment,
        })

    return trades, deposits_total


# ── Duplicate detection ───────────────────────────────────────────────────────

def _is_duplicate(tx: dict, existing: list[dict]) -> bool:
    """
    Check if a transaction already exists in DB.
    Match on: ticker + date + action + quantity (rounded to 4dp).
    """
    qty_rounded = round(tx["quantity"], 4)
    for e in existing:
        if (
            e.get("ticker") == tx["ticker"]
            and (e.get("date") or "")[:10] == tx["date"]
            and e.get("action") == tx["action"]
            and abs(float(e.get("quantity", 0)) - qty_rounded) < 0.0001
        ):
            return True
    return False


# ── Position reconciliation ───────────────────────────────────────────────────

def _reconcile_positions(user_id: str, db) -> dict[str, dict]:
    """
    Recompute net shares and weighted avg cost per ticker from ALL transactions.
    Returns {ticker: {shares, avg_cost_native, currency, market}}
    """
    tx_res = (
        db.table("transactions")
        .select("*")
        .eq("user_id", user_id)
        .order("date")
        .execute()
    )
    all_txs = tx_res.data or []

    # Weighted average cost tracking
    # avg_cost = total_cost / total_shares (reset-on-sell not needed, we use running avg)
    net_shares: dict[str, float] = {}
    total_cost: dict[str, float] = {}   # cumulative buy cost for avg
    total_bought: dict[str, float] = {}  # cumulative shares bought

    for tx in all_txs:
        if tx.get("action") not in ("BUY", "SELL"):
            continue
        t = tx["ticker"]
        qty = float(tx.get("quantity", 0))
        price = float(tx.get("price_native", 0))

        if tx["action"] == "BUY":
            net_shares[t] = net_shares.get(t, 0) + qty
            total_cost[t] = total_cost.get(t, 0) + qty * price
            total_bought[t] = total_bought.get(t, 0) + qty
        elif tx["action"] == "SELL":
            net_shares[t] = max(0.0, net_shares.get(t, 0) - qty)

    result = {}
    for ticker, shares in net_shares.items():
        bought = total_bought.get(ticker, 0)
        avg_cost = total_cost.get(ticker, 0) / bought if bought > 0 else 0
        ex = _ticker_exchange_info(ticker)
        result[ticker] = {
            "shares": round(shares, 6),
            "avg_cost_native": round(avg_cost, 6),
            "currency": ex["currency"],
            "market": ex["market"],
        }

    return result


# ── Groq validation ───────────────────────────────────────────────────────────

def _groq_validate(
    imported: list[dict],
    skipped_dupes: int,
    reconciled: dict[str, dict],
    deposits_usd: float,
) -> str | None:
    """Use Groq to validate the reconciliation and flag anomalies."""
    try:
        from app.services.agent_pipeline import _call_groq

        ticker_lines = "\n".join(
            f"  • {t}: {v['shares']:.4f} shares | avg cost = {v['currency']} {v['avg_cost_native']:.4f}"
            for t, v in reconciled.items()
            if v["shares"] > 0
        )
        import_lines = "\n".join(
            f"  • {tx['date']} {tx['action']} {tx['quantity']:.4f} {tx['ticker']} @ {tx['price_native']:.4f}"
            for tx in imported[:20]
        )

        prompt = f"""Eres el Broker Reconciliation Agent de un hedge fund. Revisa este informe de reconciliación de transacciones y detecta anomalías.

TRANSACCIONES IMPORTADAS ({len(imported)} nuevas, {skipped_dupes} duplicadas omitidas):
{import_lines}

POSICIONES RECONCILIADAS (resultado final):
{ticker_lines}

DEPÓSITOS DETECTADOS EN EL PERÍODO: USD {deposits_usd:.2f}

INSTRUCCIÓN: Analiza los datos y responde en español en máximo 60 palabras. Identifica:
1. ¿Hay alguna anomalía? (precio fuera de rango, shares negativos, ticker inusual)
2. ¿La reconciliación parece correcta?
3. Alguna advertencia importante para el usuario.

Si todo está correcto, confirma brevemente. Sé directo."""

        return _call_groq(prompt, max_tokens=200)
    except Exception as exc:
        log.warning("Groq validation failed: %s", exc)
        return None


# ── Response model ────────────────────────────────────────────────────────────

class ReconcileResult(BaseModel):
    imported: int
    skipped_duplicates: int
    errors: list[str]
    positions_updated: int
    positions_created: int
    reconciled_tickers: list[str]
    deposits_usd: float
    agent_summary: str | None


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/broker-reconcile", response_model=ReconcileResult)
async def broker_reconcile(
    file: UploadFile = File(...),
    user_id: str = Depends(get_user_id),
):
    """
    Upload XTB Cash Operations xlsx.
    The agent parses it, deduplicates, imports transactions,
    reconciles positions (shares + avg cost), and validates with Groq.
    """
    if not file.filename or not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="File must be .xlsx (XTB Cash Operations export)")

    content = await file.read()

    # 1. Parse xlsx
    try:
        trades, deposits_usd = _parse_xtb_xlsx(content)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse xlsx: {exc}")

    if not trades:
        raise HTTPException(status_code=422, detail="No trades found in file.")

    db = get_admin_client()

    # 2. Load existing transactions for duplicate detection
    existing_res = (
        db.table("transactions")
        .select("ticker,date,action,quantity")
        .eq("user_id", user_id)
        .execute()
    )
    existing_txs = existing_res.data or []

    # 3. Import non-duplicate transactions
    imported_txs: list[dict] = []
    skipped_dupes = 0
    errors: list[str] = []

    for trade in trades:
        if _is_duplicate(trade, existing_txs):
            skipped_dupes += 1
            continue
        try:
            tx_row = {
                "user_id": user_id,
                "ticker": trade["ticker"],
                "action": trade["action"],
                "quantity": trade["quantity"],
                "price_native": trade["price_native"],
                "fee_native": 0.0,
                "currency": _ticker_exchange_info(trade["ticker"])["currency"],
                "date": trade["date"],
                "comment": f"XTB: {trade['comment_raw'][:80]}",
            }
            db.table("transactions").insert(tx_row).execute()
            imported_txs.append(trade)
            # Add to existing list so next iteration detects it as duplicate
            existing_txs.append({
                "ticker": trade["ticker"],
                "date": trade["date"],
                "action": trade["action"],
                "quantity": trade["quantity"],
            })
        except Exception as exc:
            errors.append(f"{trade['ticker']} {trade['date']}: {exc}")

    # 4. Reconcile positions from ALL transactions
    reconciled = _reconcile_positions(user_id, db)

    # 5. Load existing positions
    pos_res = db.table("positions").select("*").eq("user_id", user_id).execute()
    existing_positions = {p["ticker"]: p for p in (pos_res.data or [])}

    positions_updated = 0
    positions_created = 0

    # Zero out sold-off positions still showing shares in DB
    for ticker, computed in reconciled.items():
        if computed["shares"] > 0:
            continue
        aliases = _ticker_aliases(ticker)
        matched_key = next((a for a in aliases if a in existing_positions), None)
        if matched_key and float(existing_positions[matched_key].get("shares", 0)) > 0:
            db.table("positions").update({"shares": 0}).eq("user_id", user_id).eq("ticker", matched_key).execute()
            positions_updated += 1

    for ticker, computed in reconciled.items():
        if computed["shares"] <= 0:
            continue  # Don't touch zero-share positions (keep for history)

        # Find existing position using any known alias (e.g. EIMI.L ↔ EIMI.UK)
        aliases = _ticker_aliases(ticker)
        matched_key = next((a for a in aliases if a in existing_positions), None)

        if matched_key is not None:
            # Update shares + avg_cost only if they differ meaningfully
            existing = existing_positions[matched_key]
            needs_update = (
                abs(float(existing.get("shares", 0)) - computed["shares"]) > 0.0001
                or (computed["avg_cost_native"] > 0 and abs(float(existing.get("avg_cost_native") or 0) - computed["avg_cost_native"]) > 0.01)
            )
            if needs_update:
                update_data: dict = {"shares": computed["shares"]}
                if computed["avg_cost_native"] > 0:
                    update_data["avg_cost_native"] = computed["avg_cost_native"]
                # Update by the key the DB actually has
                db.table("positions").update(update_data).eq("user_id", user_id).eq("ticker", matched_key).execute()
                positions_updated += 1
        else:
            # Create new position
            db.table("positions").insert({
                "user_id": user_id,
                "ticker": ticker,
                "shares": computed["shares"],
                "avg_cost_native": computed["avg_cost_native"] or None,
                "currency": computed["currency"],
                "market": computed["market"],
            }).execute()
            positions_created += 1

    # 6. Groq validation
    agent_summary = _groq_validate(imported_txs, skipped_dupes, reconciled, deposits_usd)

    log.info(
        "Broker reconcile %s: %d imported, %d dupes, %d updated, %d created",
        user_id[:8], len(imported_txs), skipped_dupes, positions_updated, positions_created,
    )

    return ReconcileResult(
        imported=len(imported_txs),
        skipped_duplicates=skipped_dupes,
        errors=errors[:10],
        positions_updated=positions_updated,
        positions_created=positions_created,
        reconciled_tickers=[t for t, v in reconciled.items() if v["shares"] > 0],
        deposits_usd=deposits_usd,
        agent_summary=agent_summary,
    )
