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
    index = _index_with_chunks([chunk])
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
