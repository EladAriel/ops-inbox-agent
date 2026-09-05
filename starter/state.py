"""Shared enums and audit state for the triage pipeline."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Intent(str, Enum):
    ACCESS_REQUEST = "access_request"
    DATA_PULL = "data_pull"
    POLICY_QUESTION = "policy_question"
    BUG_REPORT = "bug_report"
    PURCHASE_APPROVAL = "purchase_approval"
    OUT_OF_SCOPE = "out_of_scope"
    UNKNOWN = "unknown"


class Action(str, Enum):
    AUTO_RESOLVE = "auto_resolve"
    ROUTE = "route"
    ESCALATE = "escalate"
    REJECT = "reject"
    UNDECIDED = "undecided"


@dataclass
class ToolCall:
    """Record of a single tool invocation for the audit trail."""

    tool: str
    args: Dict[str, Any]
    result: Dict[str, Any] = field(default_factory=dict)
    approved_by: Optional[str] = None


@dataclass
class RequestState:
    """State object threaded through every pipeline stage (the audit record)."""

    id: str
    raw_text: str
    label_status: str = "unlabeled"

    intent: Intent = Intent.UNKNOWN
    fields: Dict[str, Any] = field(default_factory=dict)
    action: Action = Action.UNDECIDED
    route_to: Optional[str] = None

    answer: Optional[str] = None
    citations: List[str] = field(default_factory=list)

    tool_calls: List[ToolCall] = field(default_factory=list)
    requires_approval: bool = False
    approval_prompt: Optional[str] = None

    confidence: float = 0.0
    flags: List[str] = field(default_factory=list)

    tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0

    def to_audit_record(self) -> Dict[str, Any]:
        d = asdict(self)
        d["intent"] = self.intent.value
        d["action"] = self.action.value
        d["tool_calls"] = [asdict(tc) for tc in self.tool_calls]
        return d
