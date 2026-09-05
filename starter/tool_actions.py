"""Helpers for stub tool calls — ticket payloads, grant retry, audit append."""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from tools import grant_access

from starter.state import Action, RequestState, ToolCall

_GRANT_RETRY_BACKOFF_S = 0.05


def append_tool_call(
    state: RequestState,
    tool: str,
    args: Dict[str, Any],
    result: Dict[str, Any],
    *,
    approved_by: Optional[str] = None,
) -> ToolCall:
    """Append one tool invocation to the audit trail; return the ToolCall."""
    tc = ToolCall(
        tool=tool,
        args=args,
        result=result,
        approved_by=approved_by,
    )
    state.tool_calls.append(tc)
    return tc


def safe_ticket_payload(state: RequestState) -> Dict[str, Any]:
    """Ticket payload without raw_text or raw PII — user_id / structured fields only."""
    fields = state.fields or {}
    summary = (
        fields.get("summary")
        or fields.get("data_description")
        or fields.get("item")
        or fields.get("resource")
    )
    return {
        "request_id": state.id,
        "intent": state.intent.value,
        "user_id": fields.get("user_id"),
        "resource": fields.get("resource"),
        "summary": summary,
        "amount_yearly": fields.get("amount_yearly"),
        "data_category": fields.get("data_category"),
        "access_tier": fields.get("access_tier"),
    }


def try_grant_access(
    state: RequestState,
    *,
    user: str,
    resource: str,
    tier: int,
    approved_by: Optional[str],
) -> bool:
    """Call grant_access once, retry once on failure, escalate if still failing.

    Returns True if a successful grant was recorded.
    """
    args = {"user": user, "resource": resource, "tier": tier}
    for attempt in range(2):
        result = grant_access(user, resource, tier)
        append_tool_call(
            state, "grant_access", args, result, approved_by=approved_by
        )
        if result.get("ok"):
            return True
        if attempt == 0:
            time.sleep(_GRANT_RETRY_BACKOFF_S)
    state.action = Action.ESCALATE
    if "grant_access_failed" not in state.flags:
        state.flags.append("grant_access_failed")
    return False
