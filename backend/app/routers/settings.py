from fastapi import APIRouter, Depends
from app.auth.dependencies import get_user_id
from app.db.supabase_client import get_admin_client
from app.models.user import UserSettings

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=UserSettings)
def get_settings(user_id: str = Depends(get_user_id)):
    db = get_admin_client()
    res = db.table("user_settings").select("*").eq("user_id", user_id).maybe_single().execute()
    if not res.data:
        return UserSettings()
    data = res.data
    return UserSettings(**{k: v for k, v in data.items() if k in UserSettings.model_fields})


@router.put("", response_model=UserSettings)
def update_settings(body: UserSettings, user_id: str = Depends(get_user_id)):
    db = get_admin_client()
    data = body.model_dump()
    data["user_id"] = user_id
    db.table("user_settings").upsert(data, on_conflict="user_id").execute()
    return body


# ── Watchlist ─────────────────────────────────────────────────────────────────
from app.models.user import WatchlistItemCreate, AlertCreate

wl_router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@wl_router.get("")
def list_watchlist(user_id: str = Depends(get_user_id)):
    db = get_admin_client()
    res = db.table("watchlist").select("*").eq("user_id", user_id).execute()
    return res.data or []


@wl_router.post("", status_code=201)
def add_to_watchlist(body: WatchlistItemCreate, user_id: str = Depends(get_user_id)):
    db = get_admin_client()
    data = body.model_dump()
    data["user_id"] = user_id
    res = db.table("watchlist").upsert(data, on_conflict="user_id,ticker").execute()
    return res.data[0] if res.data else {}


@wl_router.delete("/{ticker}", status_code=204)
def remove_from_watchlist(ticker: str, user_id: str = Depends(get_user_id)):
    db = get_admin_client()
    db.table("watchlist").delete().eq("user_id", user_id).eq("ticker", ticker).execute()


# ── Alerts ────────────────────────────────────────────────────────────────────
alerts_router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@alerts_router.get("")
def list_alerts(user_id: str = Depends(get_user_id)):
    db = get_admin_client()
    res = db.table("alerts").select("*").eq("user_id", user_id).execute()
    return res.data or []


@alerts_router.post("", status_code=201)
def create_alert(body: AlertCreate, user_id: str = Depends(get_user_id)):
    db = get_admin_client()
    data = body.model_dump()
    data["user_id"] = user_id
    res = db.table("alerts").insert(data).execute()
    return res.data[0]


@alerts_router.delete("/{alert_id}", status_code=204)
def delete_alert(alert_id: str, user_id: str = Depends(get_user_id)):
    db = get_admin_client()
    db.table("alerts").delete().eq("id", alert_id).eq("user_id", user_id).execute()
