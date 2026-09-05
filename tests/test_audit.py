"""Tests for audit finalize / emission / failure records."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from starter.audit import (
    REQUIRED_AUDIT_KEYS,
    emit_results_jsonl,
    failure_audit_record,
    finalize_audit,
    validate_audit_record,
)
from starter.config import settings
from starter.pipeline import Action, Intent, RequestState, human_approval_gate, main
from starter.usage import (
    chat_cost_usd,
    embedding_cost_usd,
    record_chat_usage,
    record_embedding_usage,
)


def test_finalize_audit_rounds_accumulated_cost():
    state = RequestState(id="REQ-X", raw_text="hi", tokens=100, cost_usd=0.000123456789)
    finalize_audit(state)
    assert state.cost_usd == round(0.000123456789, 8)


def test_record_chat_usage_splits_in_out_cost():
    state = RequestState(id="R", raw_text="x")
    completion = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
    )
    record_chat_usage(state, completion)
    assert state.tokens == 1500
    assert state.cost_usd == chat_cost_usd(1000, 500)
    # $0.15/M in + $0.60/M out
    assert state.cost_usd == round(
        1000 * settings.PRICE_PER_M_CHAT_INPUT / 1e6
        + 500 * settings.PRICE_PER_M_CHAT_OUTPUT / 1e6,
        12,
    )


def test_record_embedding_usage_uses_embed_rate():
    state = RequestState(id="R", raw_text="x")
    resp = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=2000, total_tokens=2000))
    record_embedding_usage(state, resp)
    assert state.tokens == 2000
    assert state.cost_usd == embedding_cost_usd(2000)
    assert state.cost_usd == round(2000 * settings.PRICE_PER_M_EMBEDDING / 1e6, 12)


def test_failure_audit_record_has_required_keys():
    rec = failure_audit_record(
        {"id": "REQ-FAIL", "raw_text": "boom", "label_status": "labeled"},
        RuntimeError("explode"),
        latency_ms=12.5,
    )
    missing = validate_audit_record(rec)
    assert missing == []
    assert set(REQUIRED_AUDIT_KEYS).issubset(rec.keys())
    assert rec["id"] == "REQ-FAIL"
    assert rec["intent"] == Intent.UNKNOWN.value
    assert rec["action"] == Action.ESCALATE.value
    assert "pipeline_error" in rec["flags"]
    assert rec["latency_ms"] == 12.5


def test_emit_results_jsonl_round_trip(tmp_path: Path):
    state = RequestState(
        id="REQ-001",
        raw_text="access please",
        intent=Intent.ACCESS_REQUEST,
        action=Action.AUTO_RESOLVE,
        confidence=0.9,
        tokens=100,
        cost_usd=0.0001,
    )
    finalize_audit(state)
    path = tmp_path / "results.jsonl"
    emit_results_jsonl(path, [state.to_audit_record()])
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    loaded = json.loads(lines[0])
    assert validate_audit_record(loaded) == []
    assert loaded["id"] == "REQ-001"
    assert loaded["cost_usd"] > 0


def test_human_approval_gate_env_ids_case_insensitive(monkeypatch):
    state = RequestState(id="REQ-003", raw_text="x")
    monkeypatch.setenv("TRIAGE_MOCK_APPROVE", "req-003")
    assert human_approval_gate(state) is True


def test_main_continues_after_one_request_failure(tmp_path: Path, monkeypatch):
    req_path = tmp_path / "requests.jsonl"
    req_path.write_text(
        json.dumps({"id": "A", "raw_text": "one", "label_status": "labeled"})
        + "\n"
        + json.dumps({"id": "B", "raw_text": "two", "label_status": "labeled"})
        + "\n",
        encoding="utf-8",
    )
    out_path = tmp_path / "results.jsonl"
    monkeypatch.setattr("starter.pipeline.REQUESTS_PATH", str(req_path))
    monkeypatch.setattr("starter.pipeline.DEFAULT_RESULTS_PATH", str(out_path))
    monkeypatch.setattr("starter.pipeline.load_knowledge", lambda: {})
    monkeypatch.setattr("starter.pipeline.get_openai_client", lambda: object())

    class _FakeIndex:
        @classmethod
        def load_or_build(cls, *args, **kwargs):
            return cls()

    monkeypatch.setattr("starter.pipeline.KnowledgeIndex", _FakeIndex)

    calls = {"n": 0}

    def _process(raw, knowledge, *, index=None, client=None):
        calls["n"] += 1
        if raw["id"] == "A":
            raise RuntimeError("boom")
        state = RequestState(
            id=raw["id"],
            raw_text=raw["raw_text"],
            intent=Intent.OUT_OF_SCOPE,
            action=Action.REJECT,
            tokens=5,
            cost_usd=0.00001,
        )
        return finalize_audit(state)

    monkeypatch.setattr("starter.pipeline.process_request", _process)
    assert main([]) == 0
    assert calls["n"] == 2
    lines = out_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert "pipeline_error" in first["flags"]
    assert second["id"] == "B"
    assert second["action"] == Action.REJECT.value
