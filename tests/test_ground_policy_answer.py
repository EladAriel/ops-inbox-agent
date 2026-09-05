"""Tests for ground_policy_answer — seam: ground_policy_answer(state, index=, client=)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from starter.knowledge_index import Chunk, KnowledgeIndex
from starter.pipeline import (
    Action,
    GroundedPolicyAnswer,
    Intent,
    RequestState,
    ground_policy_answer,
)


def _index_with_chunks(chunks: list[Chunk]) -> KnowledgeIndex:
    return KnowledgeIndex(chunks)


def _mock_client(parsed: GroundedPolicyAnswer | None) -> MagicMock:
    client = MagicMock()
    message = SimpleNamespace(parsed=parsed, refusal=None if parsed else "refused")
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(total_tokens=40),
    )
    client.chat.completions.parse.return_value = completion
    # retrieve still calls embeddings — stub a unit vector
    emb = SimpleNamespace(data=[SimpleNamespace(embedding=[1.0, 0.0], index=0)])
    client.embeddings.create.return_value = emb
    return client


def test_ground_non_policy_noop():
    state = RequestState(
        id="REQ-001",
        raw_text="access please",
        intent=Intent.ACCESS_REQUEST,
        action=Action.AUTO_RESOLVE,
    )
    client = _mock_client(None)
    index = _index_with_chunks([])
    result = ground_policy_answer(state, index=index, client=client)
    assert result.answer is None
    assert result.citations == []
    client.chat.completions.parse.assert_not_called()


def test_ground_covered_sets_answer_and_citations():
    chunk = Chunk(
        citation="purchase_limits.md#Approval bands (annualized spend)",
        filename="purchase_limits.md",
        heading="Approval bands (annualized spend)",
        text="Under $500/yr may be auto-approved.",
        embedding=[1.0, 0.0],
    )
    other = Chunk(
        citation="access_tiers.md#Tier 1 — Internal (low risk)",
        filename="access_tiers.md",
        heading="Tier 1 — Internal (low risk)",
        text="Tier 1 may be auto-granted.",
        embedding=[0.9, 0.1],
    )
    index = _index_with_chunks([chunk, other])
    client = _mock_client(
        GroundedPolicyAnswer(
            covered=True,
            answer="Purchases under $500/yr can be auto-approved.",
            citations=[chunk.citation],
        )
    )
    state = RequestState(
        id="REQ-013",
        raw_text="what's the approval threshold for a software purchase?",
        intent=Intent.POLICY_QUESTION,
        action=Action.AUTO_RESOLVE,
        fields={"topic": "approval threshold for software purchase"},
    )

    result = ground_policy_answer(state, index=index, client=client)

    assert result.action == Action.AUTO_RESOLVE
    assert "500" in (result.answer or "")
    assert chunk.citation in result.citations
    client.chat.completions.parse.assert_called_once()
    client.embeddings.create.assert_called()
    # Retrieval must embed raw_text, not only the short topic paraphrase.
    emb_input = client.embeddings.create.call_args.kwargs.get("input")
    if emb_input is None and client.embeddings.create.call_args.args:
        emb_input = client.embeddings.create.call_args.args[0]
    assert state.raw_text in (emb_input if isinstance(emb_input, str) else emb_input[0])


def test_ground_retrieve_prefers_raw_text_over_vague_topic():
    """REQ-015 regression: vague topic must not replace the real question."""
    chunk = Chunk(
        citation="pii_handling.md#Handling rules",
        filename="pii_handling.md",
        heading="Handling rules",
        text="PII must not be emailed to external parties without Data Governance + Legal.",
        embedding=[1.0, 0.0],
    )
    index = _index_with_chunks([chunk])
    client = _mock_client(
        GroundedPolicyAnswer(
            covered=True,
            answer="No — external sharing of customer phones needs Data Governance + Legal.",
            citations=[chunk.citation],
        )
    )
    raw = (
        "Am I allowed to email a spreadsheet of customer phone numbers "
        "to an external vendor?"
    )
    state = RequestState(
        id="REQ-015",
        raw_text=raw,
        intent=Intent.POLICY_QUESTION,
        action=Action.AUTO_RESOLVE,
        fields={"topic": "customer data sharing policy"},
    )

    result = ground_policy_answer(state, index=index, client=client)

    assert result.action == Action.AUTO_RESOLVE
    emb_input = client.embeddings.create.call_args.kwargs.get("input")
    if emb_input is None and client.embeddings.create.call_args.args:
        emb_input = client.embeddings.create.call_args.args[0]
    query = emb_input if isinstance(emb_input, str) else emb_input[0]
    assert raw in query
    assert query != "customer data sharing policy"


def test_ground_uncovered_escalates():
    chunk = Chunk(
        citation="pii_handling.md#What counts as PII",
        filename="pii_handling.md",
        heading="What counts as PII",
        text="SSN and personal emails are PII.",
        embedding=[1.0, 0.0],
    )
    index = _index_with_chunks([chunk])
    client = _mock_client(
        GroundedPolicyAnswer(
            covered=False,
            answer="Docs do not cover pet insurance reimbursement.",
            citations=[],
        )
    )
    state = RequestState(
        id="REQ-X",
        raw_text="What is our pet insurance reimbursement policy?",
        intent=Intent.POLICY_QUESTION,
        action=Action.AUTO_RESOLVE,
        fields={"topic": "pet insurance reimbursement"},
    )

    result = ground_policy_answer(state, index=index, client=client)

    assert result.action == Action.ESCALATE
    assert result.answer
    assert "not cover" in result.answer.lower() or "do not" in result.answer.lower()
    assert result.citations == []


def test_ground_no_hits_escalates_without_llm():
    """Empty retrieval must escalate — do not call the grounding model with (none)."""
    index = _index_with_chunks([])
    client = _mock_client(
        GroundedPolicyAnswer(
            covered=True,
            answer="Should never be used",
            citations=["fake.md#Nope"],
        )
    )
    state = RequestState(
        id="REQ-EMPTY",
        raw_text="What is our pet insurance reimbursement policy?",
        intent=Intent.POLICY_QUESTION,
        action=Action.AUTO_RESOLVE,
        fields={"topic": "pet insurance"},
    )

    result = ground_policy_answer(state, index=index, client=client)

    assert result.action == Action.ESCALATE
    assert result.citations == []
    assert "ground_no_hits" in result.flags
    assert "not cover" in (result.answer or "").lower() or "do not" in (
        result.answer or ""
    ).lower()
    client.chat.completions.parse.assert_not_called()
    client.embeddings.create.assert_not_called()
