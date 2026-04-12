import re

import pandas as pd
import streamlit as st

from app_core import append_transaction_to_sheets, info_section, render_page_title
from utils_aggrid import show_aggrid

# ── Column auto-detection ────────────────────────────────────────────────────
_COLUMN_CANDIDATES: dict[str, list[str]] = {
    "date":   ["open time", "close time", "transaction date", "date", "time", "fecha", "datetime", "data"],
    "ticker": ["symbol", "instrument", "ticker", "asset", "símbolo", "walor"],
    "type":   ["buy/sell", "type", "side", "operation", "transaction type", "tipo", "operacja"],
    "shares": ["volume", "quantity", "amount", "lots", "shares", "volumen", "ilość"],
    "price":  ["open price", "price", "execution price", "precio", "kurs otwarcia"],
    "fees":   ["commission", "fee", "fees", "commissions", "comission", "comisión", "prowizja"],
    "notes":  ["comment", "notes", "description", "comentario", "komentarz"],
}


def _detect_column(df_cols: list[str], candidates: list[str]) -> str | None:
    lower_map = {c.lower().strip(): c for c in df_cols}
    for cand in candidates:
        if cand in lower_map:
            return lower_map[cand]
    return None


def _clean_xtb_ticker(raw: str) -> str:
    """VOO.US_9 → VOO  |  VWCE.DE_9 → VWCE.DE  |  IGLN.L_9 → IGLN.L"""
    s = re.sub(r"_\d+$", "", str(raw).strip().upper())   # strip _9, _4 …
    if s.endswith(".US"):
        s = s[:-3]                                         # yfinance uses bare US symbol
    return s


def _parse_xtb_df(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    errors: list[str] = []
    mapping: dict[str, str] = {}

    for field, candidates in _COLUMN_CANDIDATES.items():
        col = _detect_column(list(raw.columns), candidates)
        if col:
            mapping[field] = col

    required = ["date", "ticker", "type", "shares", "price"]
    missing = [f for f in required if f not in mapping]
    if missing:
        errors.append(
            f"Could not detect columns for: **{', '.join(missing)}**. "
            f"Found columns: `{', '.join(raw.columns.tolist())}`"
        )
        return pd.DataFrame(), errors

    rows: list[dict] = []
    for idx, row in raw.iterrows():
        try:
            raw_type = str(row[mapping["type"]]).strip().upper()
            if any(k in raw_type for k in ("BUY", "COMPRA", "KUPNO", "PURCHASE")):
                tx_type = "BUY"
            elif any(k in raw_type for k in ("SELL", "VENTA", "SPRZEDAŻ", "SALE")):
                tx_type = "SELL"
            else:
                continue  # dividends, fees, other cash ops — skip

            raw_date = pd.to_datetime(str(row[mapping["date"]]), errors="coerce", dayfirst=True)
            if pd.isna(raw_date):
                continue

            ticker = _clean_xtb_ticker(str(row[mapping["ticker"]]))
            if not ticker:
                continue

            shares = abs(float(str(row[mapping["shares"]]).replace(",", ".")))
            price  = abs(float(str(row[mapping["price"]]).replace(",", ".")))

            fees = 0.0
            if mapping.get("fees"):
                try:
                    fees = abs(float(str(row[mapping["fees"]]).replace(",", ".")))
                except Exception:
                    fees = 0.0

            notes = "XTB import"
            if mapping.get("notes"):
                raw_note = str(row.get(mapping["notes"], "")).strip()
                if raw_note and raw_note.lower() != "nan":
                    notes = raw_note

            rows.append({
                "date":   raw_date.strftime("%Y-%m-%d"),
                "ticker": ticker,
                "type":   tx_type,
                "shares": shares,
                "price":  price,
                "fees":   fees,
                "notes":  notes,
            })
        except Exception as e:
            errors.append(f"Row {idx}: {e}")

    return pd.DataFrame(rows), errors


def render_xtb_import_page(ctx):
    render_page_title("XTB Import")

    if ctx.get("app_scope") != "private":
        st.info("XTB Import is only available in private mode.")
        return

    st.markdown(
        "Upload a transaction history export from XTB. "
        "The file is parsed locally — nothing is sent anywhere until you click **Import**."
    )

    uploaded = st.file_uploader("Upload XTB export", type=["csv", "xlsx"])

    if uploaded is None:
        info_section("How to export from XTB", "")
        st.markdown("""
1. Open XTB → **History** tab
2. Set your desired date range
3. Click **Export → CSV** (or XLSX)
4. Upload the file above

**Auto-detected columns:**

| XTB column | Mapped to |
|---|---|
| Symbol / Instrument | Ticker |
| Buy/Sell / Type / Operation | Transaction type |
| Volume / Quantity | Shares |
| Open price / Price | Price |
| Commission / Fee | Fees |
| Open time / Date | Date |
| Comment / Notes | Notes |

> **Ticker cleanup:** `VOO.US_9 → VOO` · `VWCE.DE_9 → VWCE.DE` · `IGLN.L_9 → IGLN.L`
        """)
        return

    # ── Load file ─────────────────────────────────────────────────────────────
    try:
        if uploaded.name.endswith(".xlsx"):
            raw_df = pd.read_excel(uploaded)
        else:
            raw_df = pd.read_csv(uploaded, sep=None, engine="python")
    except Exception as e:
        st.error(f"Could not read file: {e}")
        return

    st.caption(f"Loaded {len(raw_df)} rows · Columns detected: `{', '.join(raw_df.columns.tolist())}`")

    # ── Parse ─────────────────────────────────────────────────────────────────
    parsed_df, errors = _parse_xtb_df(raw_df)

    if errors:
        with st.expander(f"⚠️ {len(errors)} parse warning(s)", expanded=len(parsed_df) == 0):
            for err in errors[:10]:
                st.warning(err)

    if parsed_df.empty:
        st.error("No valid BUY/SELL transactions found. Check the warnings above.")
        return

    # ── Preview ───────────────────────────────────────────────────────────────
    info_section("Preview", f"{len(parsed_df)} transactions parsed — review before importing.")

    n_buy  = int((parsed_df["type"] == "BUY").sum())
    n_sell = int((parsed_df["type"] == "SELL").sum())
    tickers = ", ".join(sorted(parsed_df["ticker"].unique()))

    c1, c2, c3 = st.columns(3)
    c1.metric("Buy transactions", n_buy)
    c2.metric("Sell transactions", n_sell)
    c3.metric("Tickers", parsed_df["ticker"].nunique())
    st.caption(f"Tickers: {tickers}")

    show_aggrid(parsed_df, height=350, key="aggrid_xtb_parsed")

    # ── Import ────────────────────────────────────────────────────────────────
    st.divider()
    st.warning(
        "⚠️ Duplicates are **not** automatically detected. "
        "If you already imported this file, importing again will create duplicate entries."
    )

    if st.button("✅ Import All to Sheets", type="primary", key="xtb_import_btn"):
        imported = 0
        failed   = 0
        bar = st.progress(0, text="Importing…")
        for i, (_, tx) in enumerate(parsed_df.iterrows()):
            try:
                append_transaction_to_sheets(tx.to_dict())
                imported += 1
            except Exception as e:
                failed += 1
                st.warning(f"Row {i} failed: {e}")
            bar.progress((i + 1) / len(parsed_df), text=f"Importing {i + 1}/{len(parsed_df)}…")

        st.cache_data.clear()
        if failed == 0:
            st.success(f"✅ {imported} transactions imported successfully.")
        else:
            st.warning(f"Imported {imported}, failed {failed}.")
