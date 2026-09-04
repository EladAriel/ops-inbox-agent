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
import sys
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# Make the sibling `tools` package importable whether run as a module or a script.
_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG_ROOT = os.path.dirname(_HERE)  # candidate-package/
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

from tools import create_ticket, grant_access, lookup_user  # noqa: E402

from starter.config import get_openai_client, settings  # noqa: E402
from starter.knowledge_index import KnowledgeIndex  # noqa: E402
from starter.prompts import (  # noqa: E402
    CLASSIFY_SYSTEM_PROMPT,
    EXTRACT_SYSTEM_PROMPT,
    GROUND_SYSTEM_PROMPT,
)

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
REQUESTS_PATH = os.path.join(_PKG_ROOT, "requests.jsonl")
KNOWLEDGE_DIR = os.path.join(_PKG_ROOT, "knowledge")
DEFAULT_RESULTS_PATH = os.path.join(_PKG_ROOT, "results.jsonl")


# --------------------------------------------------------------------------- #
# Enums / schema. Typed state passed between stages. Extend as needed.
# --------------------------------------------------------------------------- #
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
    item: Optional[str] = None
    amount_yearly: Optional[float] = None
    data_description: Optional[str] = None
    purpose: Optional[str] = None
    summary: Optional[str] = None
    topic: Optional[str] = None


class GroundedPolicyAnswer(BaseModel):
    """Structured LLM output for policy grounding."""

    covered: bool
    answer: str
    citations: List[str] = Field(default_factory=list)


# Keys kept on the audit record per intent (others forced to null).
_FIELDS_BY_INTENT: Dict[Intent, frozenset[str]] = {
    Intent.ACCESS_REQUEST: frozenset({"user_id", "resource", "tier"}),
    Intent.PURCHASE_APPROVAL: frozenset({"user_id", "item", "amount_yearly"}),
    Intent.DATA_PULL: frozenset({"user_id", "data_description", "purpose"}),
    Intent.BUG_REPORT: frozenset({"summary", "resource"}),
    Intent.POLICY_QUESTION: frozenset({"topic"}),
    Intent.OUT_OF_SCOPE: frozenset(),
}


@dataclass
class ToolCall:
    """Record of a single tool invocation for the audit trail."""
    tool: str
    args: Dict[str, Any]
    result: Dict[str, Any] = field(default_factory=dict)
    approved_by: Optional[str] = None  # who cleared the approval gate, if applicable


@dataclass
class RequestState:
    """State object threaded through every pipeline stage.

    This is the audit record. Keep it machine-readable and complete: it is how
    the eval harness scores you and how a human reconstructs what happened.
    """
    id: str
    raw_text: str
    label_status: str = "unlabeled"

    intent: Intent = Intent.UNKNOWN
    fields: Dict[str, Any] = field(default_factory=dict)
    action: Action = Action.UNDECIDED
    route_to: Optional[str] = None  # named team queue when action is route

    # Grounding: the answer to a policy question + the doc(s) it is grounded in.
    answer: Optional[str] = None
    citations: List[str] = field(default_factory=list)

    tool_calls: List[ToolCall] = field(default_factory=list)
    requires_approval: bool = False
    approval_prompt: Optional[str] = None  # what a human would be asked to confirm

    confidence: float = 0.0
    flags: List[str] = field(default_factory=list)  # e.g. "prompt_injection", "pii"

    # Observability
    tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0

    def to_audit_record(self) -> Dict[str, Any]:
        """Serialize to a JSON-friendly dict for results.jsonl."""
        d = asdict(self)
        d["intent"] = self.intent.value
        d["action"] = self.action.value
        d["tool_calls"] = [asdict(tc) for tc in self.tool_calls]
        return d


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
    client: Optional[Any] = None,
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
    client: Optional[Any] = None,
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


# Decision thresholds from knowledge/ (purchase_limits.md, access_tiers.md,
# data_request_rules.md). Prefer code rules over LLM judgment.
_PURCHASE_AUTO_LT = 500.0  # < $500/yr auto-approve
_PURCHASE_MANAGER_LE = 5000.0  # $500–$5,000 → Manager-Approvals
# > $5,000 → escalate (Finance Director / + Procurement)

# access_tiers.md examples → numeric tier (1/2/3)
_RESOURCE_TIER: Dict[str, int] = {
    "analytics dashboard": 1,
    "internal wiki": 1,
    "wiki": 1,
    "slack": 1,
    "#incidents": 1,
    "on-call": 1,
    "sales crm": 2,
    "financial reporting": 2,
    "data warehouse": 2,
    "hr": 2,
    "people": 2,
    "production database": 3,
    "prod db": 3,
    "production": 3,
    "payment": 3,
    "call recording": 3,
    "call-recording": 3,
    "security tooling": 3,
    "reporting backend": 3,
}

_INJECTION_MARKERS = (
    "ignore all previous",
    "ignore previous instructions",
    "approval gate has been disabled",
    "skip the usual approval",
    "auto-approve this grant",
    "mark it resolved",
)

_PII_MARKERS = (
    "email",
    "emails",
    "phone",
    "ssn",
    "address",
    "contact",
    "name",
    "names",
    "pii",
    "customer",
)
_REGULATED_MARKERS = (
    "card bin",
    "card bins",
    "payment card",
    "credential",
    "token",
    "ssn",
    "health",
    "regulated",
    "transaction log",
)


def _looks_like_injection(text: str) -> bool:
    lower = text.lower()
    return any(m in lower for m in _INJECTION_MARKERS)


def _infer_access_tier(fields: Dict[str, Any]) -> Optional[int]:
    """Map tier field / resource string to 1|2|3 using access_tiers.md."""
    tier_raw = (fields.get("tier") or "").strip().lower()
    if tier_raw:
        if "3" in tier_raw or "restricted" in tier_raw or "admin" in tier_raw:
            # "admin" on sensitive systems is at least Tier 2; prod/admin → 3 if resource says so
            if "3" in tier_raw or "restricted" in tier_raw:
                return 3
        if "2" in tier_raw or "sensitive" in tier_raw or "standard" in tier_raw:
            return 2
        if "1" in tier_raw or "internal" in tier_raw or "read" in tier_raw:
            return 1
        if "admin" in tier_raw:
            return 2

    resource = (fields.get("resource") or "").strip().lower()
    if not resource:
        return None
    best: Optional[int] = None
    for needle, tier in _RESOURCE_TIER.items():
        if needle in resource:
            if best is None or tier > best:
                best = tier
    return best


def _data_category(fields: Dict[str, Any]) -> str:
    """Return aggregate | pii | regulated from data_request_rules.md heuristics."""
    blob = " ".join(
        str(fields.get(k) or "") for k in ("data_description", "purpose")
    ).lower()
    if any(m in blob for m in _REGULATED_MARKERS):
        return "regulated"
    if any(m in blob for m in _PII_MARKERS) and "aggregate" not in blob:
        return "pii"
    if "aggregate" in blob or "rollup" in blob or "counts" in blob or "dau" in blob:
        return "aggregate"
    # Default: if clearly non-person metrics, aggregate; else escalate as unclear
    if any(
        w in blob
        for w in ("signups", "revenue", "volume", "funnel", "by region", "by product")
    ):
        return "aggregate"
    return "unclear"


def decide_action(state: RequestState) -> RequestState:
    """Decide ``auto_resolve`` | ``route`` | ``escalate`` | ``reject`` via policy rules.

    Thresholds from knowledge/*.md (see module constants). Sets ``requires_approval``
    for Tier 2/3 grants. Injection / OOS never ``auto_resolve``.
    """
    if _looks_like_injection(state.raw_text):
        if "prompt_injection" not in state.flags:
            state.flags.append("prompt_injection")

    if state.intent == Intent.OUT_OF_SCOPE:
        state.action = Action.REJECT
        return _finalize_decide(state)

    if state.intent == Intent.POLICY_QUESTION:
        state.action = Action.AUTO_RESOLVE
        return _finalize_decide(state)

    if state.intent == Intent.BUG_REPORT:
        state.action = Action.ROUTE
        state.route_to = "Engineering"
        return _finalize_decide(state)

    if state.intent == Intent.PURCHASE_APPROVAL:
        amount = state.fields.get("amount_yearly")
        if amount is None:
            state.action = Action.ESCALATE
        else:
            amount_f = float(amount)
            if amount_f < _PURCHASE_AUTO_LT:
                state.action = Action.AUTO_RESOLVE
            elif amount_f <= _PURCHASE_MANAGER_LE:
                state.action = Action.ROUTE
                state.route_to = "Manager-Approvals"
            else:
                state.action = Action.ESCALATE
        return _finalize_decide(state)

    if state.intent == Intent.DATA_PULL:
        cat = _data_category(state.fields)
        if cat == "aggregate":
            state.action = Action.ROUTE
            state.route_to = "Data-Analytics"
        else:
            state.action = Action.ESCALATE
        return _finalize_decide(state)

    if state.intent == Intent.ACCESS_REQUEST:
        tier = _infer_access_tier(state.fields)
        if tier is None:
            state.action = Action.ESCALATE
        elif tier >= 2:
            state.action = Action.ESCALATE
            state.requires_approval = True
            resource = state.fields.get("resource") or "requested resource"
            state.approval_prompt = (
                f"Approve Tier {tier} grant_access for {resource}? "
                "Policy requires human approval; do not auto-grant."
            )
        else:
            state.action = Action.AUTO_RESOLVE
        return _finalize_decide(state)

    state.action = Action.ESCALATE
    return _finalize_decide(state)


def _finalize_decide(state: RequestState) -> RequestState:
    """Block auto_resolve when prompt injection was flagged."""
    if "prompt_injection" in state.flags and state.action == Action.AUTO_RESOLVE:
        state.action = Action.ESCALATE
        state.requires_approval = True
        state.approval_prompt = (
            state.approval_prompt
            or "Adversarial language detected; confirm before resolving."
        )
    return state


def ground_policy_answer(
    state: RequestState,
    *,
    index: Optional[KnowledgeIndex] = None,
    client: Optional[Any] = None,
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

    query = (state.fields.get("topic") or state.raw_text or "").strip()
    hits = index.retrieve(query, openai_client, emb_model, top_k=4)
    allowed_citations = {c.citation for c in hits}
    context = "\n\n".join(f"[{c.citation}]\n{c.heading}\n{c.text}" for c in hits)

    completion = openai_client.chat.completions.parse(
        model=chat_model,
        messages=[
            {"role": "system", "content": GROUND_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Knowledge excerpts:\n"
                    f"{context or '(none)'}\n\n"
                    "Answer the policy question using only those excerpts.\n\n"
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


def human_approval_gate(state: RequestState, approver: str = "MOCK_APPROVER") -> bool:
    """TODO: Implement the approval gate for mutating actions above threshold.

    Must be a real stop in the pipeline — not a comment or a print. In a batch/
    eval run this can be a mock approver (e.g. read from a decision map, env var,
    or always-deny), but the CONTROL FLOW must genuinely prevent ``grant_access``
    from firing unless approval is granted. Return True iff approved.
    """
    # Placeholder: deny by default so nothing mutating fires from the scaffold.
    return False


def execute_tools(state: RequestState) -> RequestState:
    """TODO: Perform the decided action via the stub tools.

    - ``route``  -> ``create_ticket(team, payload)`` (no raw PII in payload!).
    - ``auto_resolve`` for access -> ``grant_access(...)`` ONLY for below-threshold
      grants; anything gated must pass ``human_approval_gate`` first.
    - Handle ``grant_access`` failures gracefully (it fails ~15% of the time):
      retry / backoff / escalate — your call, and justify it in the write-up.
    - Append every attempt to ``state.tool_calls``.
    """
    return state


def redact_pii(state: RequestState) -> RequestState:
    """TODO (recommended): ensure no raw sensitive PII lands in the audit record.

    e.g. mask SSNs to last 4, redact personal emails/phones/addresses. See
    knowledge/pii_handling.md. Flag PII presence in ``state.flags``.
    """
    return state


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def process_request(
    raw: Dict[str, Any],
    knowledge: Dict[str, str],
    *,
    index: Optional[KnowledgeIndex] = None,
    client: Optional[Any] = None,
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
