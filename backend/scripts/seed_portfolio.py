"""
One-time script: seed Sebastian's portfolio positions + capital snapshots.
Run from the backend/ directory:
    python scripts/seed_portfolio.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client
from datetime import date

SUPABASE_URL = "https://rydkitnqijdangpfbfms.supabase.co"
SERVICE_KEY  = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJ5ZGtpdG5xaWpkYW5ncGZiZm1zIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NTEwMTcwOSwiZXhwIjoyMDkwNjc3NzA5fQ.NQf6_NTfUB3fITTaSDoLfjYOBBJgnE5Sc-FFPF4WwhM"

db = create_client(SUPABASE_URL, SERVICE_KEY)

# ── Find user ──────────────────────────────────────────────────────────────────
users = db.auth.admin.list_users()
user = next((u for u in users if u.email == "sebastianaguilar9723@gmail.com"), None)
if not user:
    print("User not found"); sys.exit(1)
uid = user.id
print(f"User: {uid}")

# ── Positions: ticker, shares, avg_cost_native, currency ──────────────────────
# avg_cost_native = price per share in the native currency at time of purchase
# Derived from Buy In column in dashboard + P&L math
positions = [
    # ticker       shares    avg_cost_native  currency  market  name
    ("VOO",        0.5731,   590.58,          "USD",    "US",   "S&P 500"),
    ("QQQM",       0.7582,   258.93,          "USD",    "US",   "Nasdaq-100 Growth ETF"),
    ("VWCE.DE",    0.8533,   142.46,          "EUR",    "XETRA","Vanguard FTSE All-World"),
    ("EIMI.UK",    2.8450,   49.31,           "USD",    "LSE",  "iShares Core MSCI EM IMI"),
    ("8RMY.DE",    6.1783,   10.47,           "EUR",    "XETRA","iShares MSCI EM Multifactor ETF"),
    ("QDVE.DE",    0.7556,   31.87,           "EUR",    "XETRA","S&P 500 IT sector"),
    ("IGLN.L",     0.2061,   91.73,           "USD",    "LSE",  "iShares Physical Gold"),
    ("ZPRV.DE",    0.0189,   63.68,           "EUR",    "XETRA","MSCI USA Small Cap"),
]

# ── Upsert positions ───────────────────────────────────────────────────────────
print("\nUpserting positions...")
for ticker, shares, avg_cost, currency, market, name in positions:
    data = {
        "user_id": uid,
        "ticker": ticker,
        "shares": shares,
        "avg_cost_native": avg_cost,
        "currency": currency,
        "market": market,
        "name": name,
    }
    res = db.table("positions").upsert(data, on_conflict="user_id,ticker").execute()
    print(f"  {ticker}: {shares} shares @ {currency} {avg_cost} ✓")

# ── Capital snapshot (today = all positions invested) ─────────────────────────
# Total invested in USD (using approximate current FX: EUR/USD=1.13, GBP/USD=1.33)
FX = {"USD": 1.0, "EUR": 1.13, "GBP": 1.33}

def invested_usd(pos_list):
    total = 0.0
    for ticker, shares, avg_cost, currency, *_ in pos_list:
        total += shares * avg_cost * FX.get(currency, 1.0)
    return round(total, 2)

today = str(date.today())
total_invested = invested_usd(positions)
print(f"\nTotal invested (USD): ${total_invested}")

# Upsert today's capital snapshot
existing = (db.table("portfolio_snapshots")
    .select("id").eq("user_id", uid).eq("snapshot_date", today)
    .maybe_single().execute())

if existing.data:
    db.table("portfolio_snapshots").update({"invested_base": total_invested, "base_currency": "USD"}).eq("id", existing.data["id"]).execute()
    print(f"Updated snapshot for {today}: ${total_invested}")
else:
    db.table("portfolio_snapshots").insert({
        "user_id": uid,
        "snapshot_date": today,
        "base_currency": "USD",
        "invested_base": total_invested,
    }).execute()
    print(f"Created snapshot for {today}: ${total_invested}")

print("\nDone! ✓")
