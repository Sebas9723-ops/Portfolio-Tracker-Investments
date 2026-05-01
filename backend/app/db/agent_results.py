"""DB helpers for agent_results table."""
from __future__ import annotations
from typing import Any
from datetime import datetime, timezone


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


def load_latest_target_research(
    user_id: str,
    profile: str,
    max_age_hours: float = 12.0,
) -> dict[str, Any] | None:
    """
    Load the most recent target_research result for a user+profile combo.
    Returns None if no result exists or if it is older than max_age_hours.
    The returned dict is the `result` payload (optimal_weights, mu_vector, etc.).
    """
    row = load_latest_agent_result(user_id, f"target_research_{profile}")
    if not row:
        return None
    run_at = row.get("run_at")
    if run_at:
        try:
            ts = datetime.fromisoformat(run_at.replace("Z", "+00:00"))
            age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
            if age_h > max_age_hours:
                return None
        except Exception:
            pass
    return row.get("result")


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
