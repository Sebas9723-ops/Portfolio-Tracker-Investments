"""Insert positions directly into Supabase from private_positions sheet."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.db.supabase_client import get_admin_client

USER_ID = os.environ.get("MIGRATE_USER_ID", "")

POSITIONS = [
    {"ticker": "8RMY.DE",  "name": "iShares MSCI EM Multifactor ETF", "shares": 4.8024, "avg_cost_native": 10.496,  "currency": "EUR", "market": "XETRA"},
    {"ticker": "EIMI.UK",  "name": "iShares Core MSCI EM IMI",         "shares": 2.7461, "avg_cost_native": 49.248,  "currency": "GBP", "market": "LSE"},
    {"ticker": "IGLN.L",   "name": "iShares Physical Gold",            "shares": 1.8927, "avg_cost_native": 88.0041, "currency": "USD", "market": "LSE"},
    {"ticker": "QQQM",     "name": "Nasdaq-100 Growth ETF",            "shares": 0.2396, "avg_cost_native": 250.05,  "currency": "USD", "market": "US"},
    {"ticker": "VOO",      "name": "S&P 500",                          "shares": 0.5731, "avg_cost_native": 590.58,  "currency": "USD", "market": "US"},
    {"ticker": "VWCE.DE",  "name": "Vanguard FTSE All-World",          "shares": 0.8533, "avg_cost_native": 142.46,  "currency": "EUR", "market": "XETRA"},
]

if not USER_ID:
    print("ERROR: Set MIGRATE_USER_ID")
    sys.exit(1)

db = get_admin_client()
for pos in POSITIONS:
    pos["user_id"] = USER_ID
    db.table("positions").upsert(pos, on_conflict="user_id,ticker").execute()
    print(f"✓ {pos['ticker']}")

print("\n✓ All positions inserted!")
