"""Triage & Resolve — pipeline SKELETON.

This is a SCAFFOLD, not a solution. It imports cleanly and runs end-to-end,
producing placeholder audit records, so you have a working starting point
instead of a blank page. YOUR JOB is to implement the stages marked ``TODO``.

Design intent (you may change the structure — justify it in your write-up):

    load requests
        -> classify intent            (LLM where language understanding is needed)
        -> extract fields             (who / resource / tier / amount / ...)
        -> decide action              (auto_resolve | route | escalate | reject)
        -> ground policy answers      (cite knowledge/*.md; don't guess -> escalate)
        -> call tools w/ approval gate (mutating calls above threshold MUST gate)
        -> emit an audit record        (machine-readable, one per request)

LLM stages so far: ``classify_intent`` and ``extract_fields`` (OpenAI structured
outputs). Deterministic routing vs. LLM judgment for later stages is still yours.

Run:  python3 -m starter.pipeline            (from the candidate-package/ dir)
  or: python3 starter/pipeline.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Literal, Optional

from openai import OpenAI
from pydantic import BaseModel, Field

# Make the sibling `tools` package importable whether run as a module or a script.
_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG_ROOT = os.path.dirname(_HERE)  # candidate-package/
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

from tools import create_ticket, grant_access, lookup_user  # noqa: E402

from starter.config import get_openai_client, settings  # noqa: E402
from starter.decide import (  # noqa: E402
    INTENT_HANDLERS,
    _decide_unknown,
    finalize_decide,
    looks_like_injection,
)
from starter.knowledge_index import KnowledgeIndex  # noqa: E402
from starter.prompts import (  # noqa: E402
    CLASSIFY_SYSTEM_PROMPT,
    EXTRACT_SYSTEM_PROMPT,
    GROUND_SYSTEM_PROMPT,
)
from starter.state import Action, Intent, RequestState, ToolCall  # noqa: E402

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
REQUESTS_PATH = os.path.join(_PKG_ROOT, "requests.jsonl")
KNOWLEDGE_DIR = os.path.join(_PKG_ROOT, "knowledge")
DEFAULT_RESULTS_PATH = os.path.join(_PKG_ROOT, "results.jsonl")


# --------------------------------------------------------------------------- #
# LLM structured-output schemas
# --------------------------------------------------------------------------- #
class IntentClassification(BaseModel):
    """Structured LLM output: Literal labels only — Intent includes UNKNOWN (app sentinel, not a model choice)."""

    intent: Literal[
        "access_request",
        "data_pull",
        "policy_question",
        "bug_report",
        "purchase_approval",
        "out_of_scope",
    ]
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractedFields(BaseModel):
    """Flat field bag for all intents; unused keys stay null."""

    user_id: Optional[str] = None
    resource: Optional[str] = None
    tier: Optional[str] = None
    access_tier: Optional[int] = None
    item: Optional[str] = None
    amount_yearly: Optional[float] = None
    data_description: Optional[str] = None
    purpose: Optional[str] = None
    data_category: Optional[Literal["aggregate", "pii", "regulated", "unclear"]] = None
    summary: Optional[str] = None
    topic: Optional[str] = None


class GroundedPolicyAnswer(BaseModel):
    """Structured LLM output for policy grounding."""

    covered: bool
    answer: str
    citations: List[str] = Field(default_factory=list)


# Keys kept on the audit record per intent (others forced to null).
_FIELDS_BY_INTENT: Dict[Intent, frozenset[str]] = {
    Intent.ACCESS_REQUEST: frozenset({"user_id", "resource", "tier", "access_tier"}),
    Intent.PURCHASE_APPROVAL: frozenset({"user_id", "item", "amount_yearly"}),
    Intent.DATA_PULL: frozenset(
        {"user_id", "data_description", "purpose", "data_category"}
    ),
    Intent.BUG_REPORT: frozenset({"summary", "resource"}),
    Intent.POLICY_QUESTION: frozenset({"topic"}),
    Intent.OUT_OF_SCOPE: frozenset(),
}

# --------------------------------------------------------------------------- #
# Knowledge loading (provided helper — feel free to replace with real retrieval)
# --------------------------------------------------------------------------- #
def load_knowledge() -> Dict[str, str]:
    """Load knowledge/*.md into {filename: text}. Trivial for a 4-doc corpus."""
    docs: Dict[str, str] = {}
    if os.path.isdir(KNOWLEDGE_DIR):
        for name in sorted(os.listdir(KNOWLEDGE_DIR)):
            if name.endswith(".md"):
                with open(os.path.join(KNOWLEDGE_DIR, name), "r", encoding="utf-8") as fh:
                    docs[name] = fh.read()
    return docs


# --------------------------------------------------------------------------- #
# Pipeline stages — IMPLEMENT THESE
# --------------------------------------------------------------------------- #
def classify_intent(
    state: RequestState,
    client: Optional[OpenAI] = None,
    model: Optional[str] = None,
) -> RequestState:
    """Classify ``state.raw_text`` into an ``Intent`` via OpenAI structured outputs.

    Treats request text as untrusted data. Sets ``state.intent`` and
    ``state.confidence``. On refusal / missing parse, leaves UNKNOWN and flags.
    """
    openai_client = client if client is not None else get_openai_client()
    model_name = model or settings.OPENAI_MODEL

    completion = openai_client.chat.completions.parse(
        model=model_name,
        messages=[
            {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Classify the following Ops inbox message.\n\n"
                    f"<message>\n{state.raw_text}\n</message>"
                ),
            },
        ],
        response_format=IntentClassification,
    )

    usage = getattr(completion, "usage", None)
    if usage is not None and getattr(usage, "total_tokens", None) is not None:
        state.tokens += int(usage.total_tokens)

    message = completion.choices[0].message
    parsed = getattr(message, "parsed", None)
    if parsed is None:
        state.intent = Intent.UNKNOWN
        state.confidence = 0.0
        state.flags.append("classify_refusal_or_empty")
        return state

    state.intent = Intent(parsed.intent)
    state.confidence = float(parsed.confidence)
    return state


def extract_fields(
    state: RequestState,
    client: Optional[OpenAI] = None,
    model: Optional[str] = None,
) -> RequestState:
    """Extract structured fields for ``state.intent`` via OpenAI structured outputs.

    Treats request text as untrusted data. Writes ``state.fields``. When
    ``user_id`` is present, calls ``lookup_user`` and records the tool call.
    """
    if state.intent == Intent.UNKNOWN:
        return state

    openai_client = client if client is not None else get_openai_client()
    model_name = model or settings.OPENAI_MODEL

    completion = openai_client.chat.completions.parse(
        model=model_name,
        messages=[
            {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Intent: {state.intent.value}\n\n"
                    "Extract fields from the following Ops inbox message.\n\n"
                    f"<message>\n{state.raw_text}\n</message>"
                ),
            },
        ],
        response_format=ExtractedFields,
    )

    usage = getattr(completion, "usage", None)
    if usage is not None and getattr(usage, "total_tokens", None) is not None:
        state.tokens += int(usage.total_tokens)

    message = completion.choices[0].message
    parsed = getattr(message, "parsed", None)
    if parsed is None:
        state.fields = {}
        state.flags.append("extract_refusal_or_empty")
        return state

    state.fields = parsed.model_dump()
    allowed = _FIELDS_BY_INTENT.get(state.intent, frozenset())
    state.fields = {k: (v if k in allowed else None) for k, v in state.fields.items()}
    user_id = state.fields.get("user_id")
    if user_id:
        result = lookup_user(user_id)
        state.tool_calls.append(
            ToolCall(tool="lookup_user", args={"user_id": user_id}, result=result)
        )
    return state


def decide_action(state: RequestState) -> RequestState:
    """Decide ``auto_resolve`` | ``route`` | ``escalate`` | ``reject``.

    Apply the policy docs (tiers, purchase bands, data categories). Prefer
    deterministic rules where the policy is deterministic. Set
    ``state.requires_approval`` for any mutating action above the risk threshold.
    """
    if looks_like_injection(state.raw_text):
        if "prompt_injection" not in state.flags:
            state.flags.append("prompt_injection")

    handler = INTENT_HANDLERS.get(state.intent, _decide_unknown)
    handler(state)
    return finalize_decide(state)


def ground_policy_answer(
    state: RequestState,
    *,
    index: Optional[KnowledgeIndex] = None,
    client: Optional[OpenAI] = None,
    model: Optional[str] = None,
    embed_model: Optional[str] = None,
) -> RequestState:
    """For policy questions, answer from retrieved knowledge chunks with citations.

    If docs do not cover the question: escalate and do not invent policy.
    """
    if state.intent != Intent.POLICY_QUESTION:
        return state

    openai_client = client if client is not None else get_openai_client()
    chat_model = model or settings.OPENAI_MODEL
    emb_model = embed_model or settings.EMBEDDING_MODEL

    if index is None:
        index = KnowledgeIndex.load_or_build(
            load_knowledge(), openai_client, emb_model
        )

    # Prefer raw_text for retrieval — short topic paraphrases can starve embeddings
    # (e.g. "customer data sharing policy" missing "email / phone / external vendor").
    topic = str(state.fields.get("topic") or "").strip()
    raw = (state.raw_text or "").strip()
    query = raw or topic
    hits = index.retrieve(query, openai_client, emb_model, top_k=4)
    if not hits:
        state.action = Action.ESCALATE
        state.answer = "Docs do not cover this question; escalating."
        state.citations = []
        state.flags.append("ground_no_hits")
        return state

    allowed_citations = {c.citation for c in hits}
    context = "\n\n".join(f"[{c.citation}]\n{c.heading}\n{c.text}" for c in hits)

    completion = openai_client.chat.completions.parse(
        model=chat_model,
        messages=[
            {"role": "system", "content": GROUND_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Knowledge selected chunks:\n"
                    f"{context or '(none)'}\n\n"
                    "Answer the policy question using only those selected chunks.\n\n"
                    f"<message>\n{state.raw_text}\n</message>"
                ),
            },
        ],
        response_format=GroundedPolicyAnswer,
    )

    usage = getattr(completion, "usage", None)
    if usage is not None and getattr(usage, "total_tokens", None) is not None:
        state.tokens += int(usage.total_tokens)

    message = completion.choices[0].message
    parsed = getattr(message, "parsed", None)
    if parsed is None:
        state.action = Action.ESCALATE
        state.answer = "Could not ground a policy answer; escalating."
        state.citations = []
        state.flags.append("ground_refusal_or_empty")
        return state

    citations = [c for c in parsed.citations if c in allowed_citations]
    if not parsed.covered or not citations:
        state.action = Action.ESCALATE
        state.answer = parsed.answer or "Docs do not cover this question; escalating."
        state.citations = []
        return state

    state.answer = parsed.answer
    state.citations = citations
    return state


def human_approval_gate(
    state: RequestState,
    approver: str = "MOCK_APPROVER",
    *,
    decisions: Optional[Dict[str, bool]] = None,
) -> bool:
    """Explicit stop for mutating actions above the risk threshold.

    Batch/eval: pass ``decisions`` keyed by request id, or set env
    ``TRIAGE_MOCK_APPROVE`` to ``all`` / comma-separated ids. Default deny.
    """
    _ = approver  # caller records approved_by on ToolCall
    if decisions is not None:
        return bool(decisions.get(state.id, False))

    mode = (os.environ.get("TRIAGE_MOCK_APPROVE") or "deny").strip().lower()
    if mode in ("1", "true", "all", "yes"):
        return True
    if mode in ("0", "false", "deny", "no", ""):
        return False
    allowed = {x.strip() for x in mode.split(",") if x.strip()}
    return state.id in allowed


_GRANT_RETRY_BACKOFF_S = 0.05


def _safe_ticket_payload(state: RequestState) -> Dict[str, Any]:
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


def _try_grant_access(
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
        state.tool_calls.append(
            ToolCall(
                tool="grant_access",
                args=args,
                result=result,
                approved_by=approved_by,
            )
        )
        if result.get("ok"):
            return True
        if attempt == 0:
            time.sleep(_GRANT_RETRY_BACKOFF_S)
    state.action = Action.ESCALATE
    if "grant_access_failed" not in state.flags:
        state.flags.append("grant_access_failed")
    return False


def execute_tools(
    state: RequestState,
    *,
    decisions: Optional[Dict[str, bool]] = None,
    approver: str = "MOCK_APPROVER",
) -> RequestState:
    """Perform the decided action via stub tools (gate before grant_access).

    - ``route`` -> ``create_ticket`` (no raw PII in payload).
    - Tier-1 ``auto_resolve`` access -> ``grant_access`` without gate.
    - ``requires_approval`` -> ``human_approval_gate`` then grant only if True.
    - Flaky ``grant_access``: one short backoff retry, then escalate; every try logged.
    """
    if state.action == Action.ROUTE and state.route_to:
        payload = _safe_ticket_payload(state)
        result = create_ticket(state.route_to, payload)
        state.tool_calls.append(
            ToolCall(
                tool="create_ticket",
                args={"team": state.route_to, "payload": payload},
                result=result,
            )
        )
        return state

    access_grant = state.intent == Intent.ACCESS_REQUEST and (
        state.action == Action.AUTO_RESOLVE or state.requires_approval
    )
    if not access_grant:
        return state

    # Gate first whenever ticket 03 seeded requires_approval — even if fields incomplete.
    approved_by: Optional[str] = None
    if state.requires_approval:
        if not human_approval_gate(state, approver=approver, decisions=decisions):
            state.tool_calls.append(
                ToolCall(
                    tool="grant_access",
                    args={
                        "user": state.fields.get("user_id"),
                        "resource": state.fields.get("resource"),
                        "tier": state.fields.get("access_tier"),
                    },
                    result={
                        "ok": False,
                        "tool": "grant_access",
                        "data": {"denied_by": approver},
                        "error": "approval_denied",
                    },
                    approved_by=None,
                )
            )
            if "approval_denied" not in state.flags:
                state.flags.append("approval_denied")
            return state
        approved_by = approver

    user = state.fields.get("user_id")
    resource = state.fields.get("resource")
    raw_tier = state.fields.get("access_tier")
    if not user or not resource or raw_tier is None:
        state.action = Action.ESCALATE
        if "grant_missing_fields" not in state.flags:
            state.flags.append("grant_missing_fields")
        return state
    try:
        tier = int(raw_tier)
    except (TypeError, ValueError):
        state.action = Action.ESCALATE
        if "grant_missing_fields" not in state.flags:
            state.flags.append("grant_missing_fields")
        return state

    _try_grant_access(
        state, user=user, resource=resource, tier=tier, approved_by=approved_by
    )
    return state


_SSN_RE = re.compile(r"\b(\d{3})-(\d{2})-(\d{4})\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# 555-0142 or 617-555-0199 or 555.0142
_PHONE_RE = re.compile(
    r"\b(?:\d{3}[-.\s]?)?\d{3}[-.\s]?\d{4}\b"
)
_ADDRESS_RE = re.compile(
    r"\b\d+\s+[A-Za-z0-9.'\-]+(?:\s+[A-Za-z0-9.'\-]+)*\s+"
    r"(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Ln|Lane|Dr|Drive|Ct|Court)\b",
    re.IGNORECASE,
)


def _mask_pii_text(text: str) -> tuple[str, bool]:
    """Return (masked_text, found_pii)."""
    if not text:
        return text, False
    found = False

    def _ssn(m: re.Match[str]) -> str:
        nonlocal found
        found = True
        return f"***-**-{m.group(3)}"

    def _mark(repl: str):
        def _fn(_m: re.Match[str]) -> str:
            nonlocal found
            found = True
            return repl

        return _fn

    out = _SSN_RE.sub(_ssn, text)
    out = _EMAIL_RE.sub(_mark("[REDACTED_EMAIL]"), out)
    out = _ADDRESS_RE.sub(_mark("[REDACTED_ADDRESS]"), out)
    out = _PHONE_RE.sub(_mark("[REDACTED_PHONE]"), out)
    return out, found


def redact_pii(state: RequestState) -> RequestState:
    """Mask SSN / email / phone / address in audit fields per knowledge/pii_handling.md."""
    found_any = False

    state.raw_text, hit = _mask_pii_text(state.raw_text)
    found_any = found_any or hit

    if state.answer:
        state.answer, hit = _mask_pii_text(state.answer)
        found_any = found_any or hit

    for key, val in list(state.fields.items()):
        if isinstance(val, str):
            masked, hit = _mask_pii_text(val)
            state.fields[key] = masked
            found_any = found_any or hit

    if found_any and "contains_pii" not in state.flags:
        state.flags.append("contains_pii")
    return state


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def process_request(
    raw: Dict[str, Any],
    knowledge: Dict[str, str],
    *,
    index: Optional[KnowledgeIndex] = None,
    client: Optional[OpenAI] = None,
) -> RequestState:
    """Run one request through all stages and return the completed state.

    NOTE: the ordering below is a suggestion. Part of the exercise is deciding
    the right control flow (e.g. classify -> flag injection -> maybe short-circuit).
    """
    t0 = time.perf_counter()
    state = RequestState(
        id=raw.get("id", "UNKNOWN"),
        raw_text=raw.get("raw_text", ""),
        label_status=raw.get("label_status", "unlabeled"),
    )

    state = classify_intent(state, client=client)
    state = extract_fields(state, client=client)
    state = decide_action(state)
    state = ground_policy_answer(state, index=index, client=client)
    state = redact_pii(state)
    state = execute_tools(state)

    state.latency_ms = (time.perf_counter() - t0) * 1000.0
    return state


def load_requests(path: str = REQUESTS_PATH) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def main(argv: Optional[List[str]] = None) -> int:
    requests = load_requests()
    knowledge = load_knowledge()
    client = get_openai_client()
    index = KnowledgeIndex.load_or_build(
        knowledge, client, settings.EMBEDDING_MODEL
    )
    results: List[Dict[str, Any]] = []

    for raw in requests:
        state = process_request(raw, knowledge, index=index, client=client)
        results.append(state.to_audit_record())

    with open(DEFAULT_RESULTS_PATH, "w", encoding="utf-8") as fh:
        for rec in results:
            fh.write(json.dumps(rec) + "\n")

    print(f"processed {len(results)} requests -> {DEFAULT_RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
