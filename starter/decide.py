"""Deterministic routing — thresholds from knowledge/*.md.

Fuzzy classification (access tier, data category) belongs in extract.
This module only maps already-normalized fields to action / route / gate.
"""
from __future__ import annotations

from typing import Callable, Dict, Optional, Tuple

from starter.state import Action, Intent, RequestState

# purchase_limits.md — annualized bands
PURCHASE_AUTO_LT = 500.0
PURCHASE_MANAGER_LE = 5000.0

# data_request_rules.md category → action / queue
DATA_CATEGORY_ACTION: Dict[str, Tuple[Action, Optional[str]]] = {
    "aggregate": (Action.ROUTE, "Data-Analytics"),
    "pii": (Action.ESCALATE, None),
    "regulated": (Action.ESCALATE, None),
    "unclear": (Action.ESCALATE, None),
}

INJECTION_MARKERS = (
    "ignore all previous",
    "ignore previous instructions",
    "approval gate has been disabled",
    "skip the usual approval",
    "auto-approve this grant",
    "mark it resolved",
)


def looks_like_injection(text: str) -> bool:
    lower = text.lower()
    return any(m in lower for m in INJECTION_MARKERS)


def _decide_out_of_scope(state: RequestState) -> None:
    state.action = Action.REJECT


def _decide_policy_question(state: RequestState) -> None:
    # Grounding stage may escalate later if docs don't cover it.
    state.action = Action.AUTO_RESOLVE


def _decide_bug_report(state: RequestState) -> None:
    state.action = Action.ROUTE
    state.route_to = "Engineering"


def _decide_purchase(state: RequestState) -> None:
    amount = state.fields.get("amount_yearly")
    if amount is None:
        state.action = Action.ESCALATE
        return
    amount_f = float(amount)
    if amount_f < PURCHASE_AUTO_LT:
        state.action = Action.AUTO_RESOLVE
        state.route_to = None
    elif amount_f <= PURCHASE_MANAGER_LE:
        state.action = Action.ROUTE
        state.route_to = "Manager-Approvals"
    else:
        state.action = Action.ESCALATE
        state.route_to = None


def _decide_data_pull(state: RequestState) -> None:
    cat = (state.fields.get("data_category") or "unclear").strip().lower()
    action, route_to = DATA_CATEGORY_ACTION.get(cat, (Action.ESCALATE, None))
    state.action = action
    state.route_to = route_to


def _decide_access(state: RequestState) -> None:
    raw = state.fields.get("access_tier")
    if raw is None:
        state.action = Action.ESCALATE
        return
    try:
        tier = int(raw)
    except (TypeError, ValueError):
        state.action = Action.ESCALATE
        return
    if tier >= 2:
        state.action = Action.ESCALATE
        state.requires_approval = True
        resource = state.fields.get("resource") or "requested resource"
        state.approval_prompt = (
            f"Approve Tier {tier} grant_access for {resource}? "
            "Policy requires human approval; do not auto-grant."
        )
        return
    state.action = Action.AUTO_RESOLVE


def _decide_unknown(state: RequestState) -> None:
    state.action = Action.ESCALATE


INTENT_HANDLERS: Dict[Intent, Callable[[RequestState], None]] = {
    Intent.OUT_OF_SCOPE: _decide_out_of_scope,
    Intent.POLICY_QUESTION: _decide_policy_question,
    Intent.BUG_REPORT: _decide_bug_report,
    Intent.PURCHASE_APPROVAL: _decide_purchase,
    Intent.DATA_PULL: _decide_data_pull,
    Intent.ACCESS_REQUEST: _decide_access,
}


def finalize_decide(state: RequestState) -> RequestState:
    """Block auto_resolve when prompt injection was flagged."""
    if "prompt_injection" in state.flags and state.action == Action.AUTO_RESOLVE:
        state.action = Action.ESCALATE
        state.requires_approval = True
        state.approval_prompt = (
            state.approval_prompt
            or "Adversarial language detected; confirm before resolving."
        )
    return state
