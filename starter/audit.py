"""Audit-record finalize, failure records, and JSONL emission."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Union

from starter.state import Action, Intent, RequestState

# README-required fields plus extras already on RequestState.
REQUIRED_AUDIT_KEYS = frozenset(
    {
        "id",
        "raw_text",
        "intent",
        "fields",
        "citations",
        "tool_calls",
        "action",
        "confidence",
        "tokens",
        "cost_usd",
        "latency_ms",
        "flags",
        "route_to",
        "requires_approval",
        "answer",
    }
)


def finalize_audit(state: RequestState) -> RequestState:
    """Round accumulated ``cost_usd``; latency is set by the caller."""
    state.cost_usd = round(float(state.cost_usd), 8)
    return state


def validate_audit_record(record: Mapping[str, Any]) -> List[str]:
    """Return missing required keys (empty list if complete)."""
    return sorted(k for k in REQUIRED_AUDIT_KEYS if k not in record)


def emit_results_jsonl(
    path: Union[str, Path],
    records: Iterable[Dict[str, Any]],
) -> None:
    """Write one JSON audit object per line."""
    out = Path(path)
    with out.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def failure_audit_record(
    raw: Mapping[str, Any],
    error: BaseException | str,
    *,
    latency_ms: float = 0.0,
) -> Dict[str, Any]:
    """Machine-readable partial record when a request blows up mid-pipeline."""
    err_text = str(error)
    state = RequestState(
        id=str(raw.get("id", "UNKNOWN")),
        raw_text=str(raw.get("raw_text", "")),
        label_status=str(raw.get("label_status", "unlabeled")),
        intent=Intent.UNKNOWN,
        action=Action.ESCALATE,
        confidence=0.0,
        latency_ms=float(latency_ms),
        flags=["pipeline_error"],
        approval_prompt=f"pipeline_error: {err_text}"[:500],
    )
    finalize_audit(state)
    return state.to_audit_record()
