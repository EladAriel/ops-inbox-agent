"""Tests for starter/labels.json — seam: the answer-key artifact only."""
from __future__ import annotations

import json
from pathlib import Path

from starter.state import Action, Intent

_PKG_ROOT = Path(__file__).resolve().parents[1]
_LABELS_PATH = _PKG_ROOT / "starter" / "labels.json"
_REQUESTS_PATH = _PKG_ROOT / "requests.jsonl"

VALID_INTENTS = {i.value for i in Intent if i != Intent.UNKNOWN}
VALID_ACTIONS = {
    Action.AUTO_RESOLVE.value,
    Action.ROUTE.value,
    Action.ESCALATE.value,
    Action.REJECT.value,
}


def _load_labeled_ids() -> set[str]:
    ids: set[str] = set()
    with _REQUESTS_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("label_status") == "labeled":
                ids.add(row["id"])
    return ids


def _load_labels() -> dict:
    with _LABELS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def test_labels_file_exists():
    assert _LABELS_PATH.is_file(), f"missing answer key: {_LABELS_PATH}"


def test_labels_cover_all_and_only_labeled_ids():
    labeled = _load_labeled_ids()
    labels = _load_labels()
    assert set(labels.keys()) == labeled
    assert len(labels) == len(labeled)


def test_labels_schema_intent_and_action():
    labels = _load_labels()
    for req_id, entry in labels.items():
        assert set(entry.keys()) >= {"intent", "action"}, req_id
        assert entry["intent"] in VALID_INTENTS, (req_id, entry["intent"])
        assert entry["action"] in VALID_ACTIONS, (req_id, entry["action"])


def test_spot_check_tier1_access_auto_resolve():
    labels = _load_labels()
    assert labels["REQ-001"] == {
        "intent": "access_request",
        "action": "auto_resolve",
    }


def test_spot_check_tier3_prod_db_escalate():
    labels = _load_labels()
    assert labels["REQ-002"] == {
        "intent": "access_request",
        "action": "escalate",
    }


def test_spot_check_pii_data_pull_escalate():
    labels = _load_labels()
    assert labels["REQ-008"] == {
        "intent": "data_pull",
        "action": "escalate",
    }


def test_spot_check_figma_purchase_route():
    labels = _load_labels()
    assert labels["REQ-025"] == {
        "intent": "purchase_approval",
        "action": "route",
    }


def test_spot_check_call_recording_policy():
    labels = _load_labels()
    assert labels["REQ-018"] == {
        "intent": "policy_question",
        "action": "auto_resolve",
    }


def test_adversarial_unlabeled_excluded():
    """Labeled key must not include injection/social-eng rows (REQ-036+)."""
    labels = _load_labels()
    assert "REQ-036" not in labels
    assert "REQ-037" not in labels
