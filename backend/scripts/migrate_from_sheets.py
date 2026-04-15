"""
Migration script: Google Sheets → Supabase

Usage:
  1. Copy your existing .streamlit/secrets.toml credentials
  2. Set SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY in environment
  3. Set USER_ID to your Supabase Auth user UUID
  4. Run: python scripts/migrate_from_sheets.py

This script reads from Google Sheets (using the same credentials as the Streamlit app)
and inserts into Supabase tables.
"""
import os
import sys
import json
from datetime import date

# Add parent to path so we can import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ── Configuration ──────────────────────────────────────────────────────────────
USER_ID = os.environ.get("MIGRATE_USER_ID", "")  # Set your Supabase user UUID here
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "")  # From your secrets.toml

if not all([USER_ID, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY]):
    print("ERROR: Set MIGRATE_USER_ID, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY env vars")
    sys.exit(1)


def get_supabase():
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def get_sheets_client():
    """Build Google Sheets client from service account JSON."""
    import gspread
    from google.oauth2.service_account import Credentials

    # Load from environment or from secrets.toml
    sa_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
    if sa_json:
        creds_dict = json.loads(sa_json)
    else:
        # Try to read from .streamlit/secrets.toml
        import toml
        secrets_path = os.path.join(os.path.dirname(__file__), "../../.streamlit/secrets.toml")
        if os.path.exists(secrets_path):
            secrets = toml.load(secrets_path)
            creds_dict = secrets.get("gcp", {})
        else:
            raise RuntimeError("No GCP credentials found")

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)


def migrate_positions(sheets, supabase, spreadsheet_id: str, user_id: str):
    """Migrate positions sheet to Supabase positions table."""
    print("Migrating positions…")
    try:
        ws = sheets.open_by_key(spreadsheet_id).worksheet("Positions")
        records = ws.get_all_records()
        for row in records:
            ticker = str(row.get("ticker", "")).strip()
            if not ticker:
                continue
            data = {
                "user_id": user_id,
                "ticker": ticker,
                "name": str(row.get("name", ticker)),
                "shares": float(row.get("shares", 0) or 0),
                "avg_cost_native": float(row.get("avg_cost_native", 0) or 0) or None,
                "currency": str(row.get("currency", "USD")),
                "market": str(row.get("market", "US")),
            }
            supabase.table("positions").upsert(data, on_conflict="user_id,ticker").execute()
            print(f"  ✓ {ticker}")
    except Exception as e:
        print(f"  ⚠ positions migration error: {e}")


def migrate_transactions(sheets, supabase, spreadsheet_id: str, user_id: str):
    """Migrate transactions sheet."""
    print("Migrating transactions…")
    try:
        ws = sheets.open_by_key(spreadsheet_id).worksheet("Transactions")
        records = ws.get_all_records()
        for row in records:
            ticker = str(row.get("ticker", "")).strip()
            if not ticker:
                continue
            action = str(row.get("action", "BUY")).upper()
            if action not in ["BUY", "SELL", "DIVIDEND", "SPLIT", "FEE"]:
                action = "BUY"
            data = {
                "user_id": user_id,
                "ticker": ticker,
                "date": str(row.get("date", date.today())),
                "action": action,
                "quantity": float(row.get("quantity", 0) or 0),
                "price_native": float(row.get("price_native", 0) or 0),
                "fee_native": float(row.get("fee_native", 0) or 0),
                "currency": str(row.get("currency", "USD")),
                "comment": str(row.get("comment", "")) or None,
            }
            supabase.table("transactions").insert(data).execute()
            print(f"  ✓ {action} {ticker}")
    except Exception as e:
        print(f"  ⚠ transactions migration error: {e}")


def migrate_cash_balances(sheets, supabase, spreadsheet_id: str, user_id: str):
    """Migrate cash balances sheet."""
    print("Migrating cash balances…")
    try:
        ws = sheets.open_by_key(spreadsheet_id).worksheet("Cash Balances")
        records = ws.get_all_records()
        for row in records:
            currency = str(row.get("currency", "")).strip()
            if not currency:
                continue
            data = {
                "user_id": user_id,
                "currency": currency,
                "amount": float(row.get("amount", 0) or 0),
                "account_name": str(row.get("account_name", "")) or None,
            }
            supabase.table("cash_balances").upsert(
                data, on_conflict="user_id,currency,account_name"
            ).execute()
            print(f"  ✓ {currency}")
    except Exception as e:
        print(f"  ⚠ cash migration error: {e}")


def migrate_dividends(sheets, supabase, spreadsheet_id: str, user_id: str):
    """Migrate dividends sheet."""
    print("Migrating dividends…")
    try:
        ws = sheets.open_by_key(spreadsheet_id).worksheet("Dividends")
        records = ws.get_all_records()
        for row in records:
            ticker = str(row.get("ticker", "")).strip()
            if not ticker:
                continue
            data = {
                "user_id": user_id,
                "ticker": ticker,
                "date": str(row.get("date", date.today())),
                "amount_native": float(row.get("amount_native", 0) or 0),
                "currency": str(row.get("currency", "USD")),
            }
            supabase.table("dividends").insert(data).execute()
            print(f"  ✓ {ticker}")
    except Exception as e:
        print(f"  ⚠ dividends migration error: {e}")


def migrate_settings(supabase, user_id: str):
    """Insert default user settings."""
    print("Inserting default settings…")
    defaults = {
        "user_id": user_id,
        "base_currency": "USD",
        "rebalancing_threshold": 0.05,
        "max_single_asset": 0.30,
        "min_bonds": 0.10,
        "min_gold": 0.05,
        "preferred_benchmark": "VOO",
        "risk_free_rate": 0.045,
        "rolling_window": 63,
        "tc_model": "broker",
    }
    supabase.table("user_settings").upsert(defaults, on_conflict="user_id").execute()
    print("  ✓ settings")


if __name__ == "__main__":
    supabase = get_supabase()

    # Settings (no Sheets needed)
    migrate_settings(supabase, USER_ID)

    if SPREADSHEET_ID:
        try:
            sheets = get_sheets_client()
            migrate_positions(sheets, supabase, SPREADSHEET_ID, USER_ID)
            migrate_transactions(sheets, supabase, SPREADSHEET_ID, USER_ID)
            migrate_cash_balances(sheets, supabase, SPREADSHEET_ID, USER_ID)
            migrate_dividends(sheets, supabase, SPREADSHEET_ID, USER_ID)
        except Exception as e:
            print(f"Google Sheets connection failed: {e}")
            print("Skipping Sheets migration. Add positions manually via the app.")
    else:
        print("SPREADSHEET_ID not set — skipping Sheets migration.")
        print("Add your positions manually via the Portfolio page.")

    print("\n✓ Migration complete!")
    print(f"  User ID: {USER_ID}")
    print("  Login at http://localhost:3000/login with your Supabase email/password")
