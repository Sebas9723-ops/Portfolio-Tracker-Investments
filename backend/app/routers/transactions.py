from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from app.auth.dependencies import get_user_id
from app.db.supabase_client import get_admin_client
from app.models.transactions import TransactionCreate, Transaction, CashBalanceUpdate

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


@router.get("", response_model=list[Transaction])
def list_transactions(user_id: str = Depends(get_user_id)):
    db = get_admin_client()
    res = db.table("transactions").select("*").eq("user_id", user_id)\
        .order("date", desc=True).execute()
    return res.data or []


@router.post("", status_code=201, response_model=Transaction)
def create_transaction(body: TransactionCreate, user_id: str = Depends(get_user_id)):
    db = get_admin_client()
    data = body.model_dump()
    data["user_id"] = user_id
    data["date"] = str(data["date"])
    data["action"] = data["action"].value if hasattr(data["action"], "value") else data["action"]
    res = db.table("transactions").insert(data).execute()
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to create transaction")
    return res.data[0]


@router.delete("/{tx_id}", status_code=204)
def delete_transaction(tx_id: str, user_id: str = Depends(get_user_id)):
    db = get_admin_client()
    res = db.table("transactions").select("id").eq("id", tx_id).eq("user_id", user_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Transaction not found")
    db.table("transactions").delete().eq("id", tx_id).execute()


# ── Cash Balances ─────────────────────────────────────────────────────────────

@router.get("/cash")
def get_cash(user_id: str = Depends(get_user_id)):
    db = get_admin_client()
    res = db.table("cash_balances").select("*").eq("user_id", user_id).execute()
    return res.data or []


@router.put("/cash")
def upsert_cash(body: CashBalanceUpdate, user_id: str = Depends(get_user_id)):
    db = get_admin_client()
    data = body.model_dump()
    data["user_id"] = user_id
    res = db.table("cash_balances").upsert(
        data, on_conflict="user_id,currency,account_name"
    ).execute()
    return res.data[0] if res.data else {}


@router.delete("/cash", status_code=204)
def delete_cash(
    currency: str = Query(...),
    account_name: Optional[str] = Query(default=None),
    user_id: str = Depends(get_user_id),
):
    db = get_admin_client()
    q = db.table("cash_balances").delete().eq("user_id", user_id).eq("currency", currency)
    if account_name:
        q = q.eq("account_name", account_name)
    else:
        q = q.is_("account_name", "null")
    q.execute()


# ── Dividends ─────────────────────────────────────────────────────────────────

@router.get("/dividends")
def list_dividends(user_id: str = Depends(get_user_id)):
    db = get_admin_client()
    res = db.table("dividends").select("*").eq("user_id", user_id)\
        .order("date", desc=True).execute()
    return res.data or []
