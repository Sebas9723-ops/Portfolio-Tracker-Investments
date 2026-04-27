"""DB helpers for agent_results table."""
from __future__ import annotations
from typing import Any


def save_agent_result(
    user_id: str,
    agent_type: str,
    result: dict[str, Any],
    triggered_by: str = "scheduler",
) -> None:
    from app.db.supabase_client import get_admin_client
    db = get_admin_client()
    db.table("agent_results").insert({
        "user_id": user_id,
        "agent_type": agent_type,
        "result": result,
        "triggered_by": triggered_by,
    }).execute()


def load_latest_agent_result(user_id: str, agent_type: str) -> dict[str, Any] | None:
    from app.db.supabase_client import get_admin_client
    db = get_admin_client()
    res = (
        db.table("agent_results")
        .select("*")
        .eq("user_id", user_id)
        .eq("agent_type", agent_type)
        .order("run_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None
