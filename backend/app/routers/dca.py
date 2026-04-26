"""
DCA (Dollar-Cost Averaging) Schedule endpoints.
GET  /api/dca/schedule        — get user's DCA schedule
POST /api/dca/schedule        — create/update DCA schedule
DELETE /api/dca/schedule      — delete DCA schedule
POST /api/dca/run-now         — manually trigger DCA run

The scheduler job runs on the configured day_of_month at 09:00 America/Bogota.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.dependencies import get_user_id
from app.db.supabase_client import get_admin_client

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/dca", tags=["dca"])


class DCAScheduleCreate(BaseModel):
    amount: float = Field(gt=0)
    day_of_month: int = Field(ge=1, le=28)
    tc_model: str = "broker"
    profile: str = "base"
    time_horizon: str = "long"
    active: bool = True


@router.get("/schedule")
def get_dca_schedule(user_id: str = Depends(get_user_id)) -> dict[str, Any]:
    db = get_admin_client()
    res = db.table("dca_schedule").select("*").eq("user_id", user_id).maybe_single().execute()
    return res.data or {}


@router.post("/schedule")
def upsert_dca_schedule(
    body: DCAScheduleCreate,
    user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    db = get_admin_client()
    row = {
        "user_id": user_id,
        "amount": body.amount,
        "day_of_month": body.day_of_month,
        "tc_model": body.tc_model,
        "profile": body.profile,
        "time_horizon": body.time_horizon,
        "active": body.active,
    }
    res = db.table("dca_schedule").upsert(row, on_conflict="user_id").execute()
    return res.data[0] if res.data else row


@router.delete("/schedule")
def delete_dca_schedule(user_id: str = Depends(get_user_id)) -> dict:
    db = get_admin_client()
    db.table("dca_schedule").delete().eq("user_id", user_id).execute()
    return {"deleted": True}


@router.post("/run-now")
def run_dca_now(user_id: str = Depends(get_user_id)) -> dict[str, Any]:
    """Manually trigger a DCA run using the saved schedule config."""
    db = get_admin_client()
    res = db.table("dca_schedule").select("*").eq("user_id", user_id).maybe_single().execute()
    schedule = res.data
    if not schedule:
        raise HTTPException(status_code=404, detail="No DCA schedule found. Create one first.")
    if not schedule.get("active"):
        raise HTTPException(status_code=400, detail="DCA schedule is paused.")

    from app.routers.contribution import run_contribution_plan, ContributionRequest
    req = ContributionRequest(
        available_cash=float(schedule["amount"]),
        profile=schedule.get("profile", "base"),
        time_horizon=schedule.get("time_horizon", "long"),
        tc_model=schedule.get("tc_model", "broker"),
    )
    result = run_contribution_plan(req, user_id=user_id)

    # Record last run
    db.table("dca_schedule").update({"last_run_at": "now()"}).eq("user_id", user_id).execute()
    return result
